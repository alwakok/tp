# tickets.py
import csv
import io
import os
import uuid
from datetime import datetime, timezone

import magic

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, current_app, send_file, abort)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from models import db, Ticket, Category, Comment, Attachment, AuditLog, User
from forms import TicketForm, CommentForm
from auth import role_required

tickets_bp = Blueprint('tickets', __name__, url_prefix='/tickets')


# ---------------------------------------------------------------------------
# MIME-типы, которые считаются безопасными
# ---------------------------------------------------------------------------
ALLOWED_MIMES = {
    'application/pdf',
    'image/png',
    'image/jpeg',
    'image/gif',
    'text/plain',
    'application/zip',
    'application/x-zip',  # некоторые версии libmagic
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # docx
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',        # xlsx
}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _get_file_size(file_storage):
    """
    Возвращает размер файла в байтах, не загружая его в память целиком.
    Перемещает указатель в начало — после вызова можно сохранять файл.
    """
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    return size


def _format_size(num_bytes):
    """Человекочитаемый размер: 5.2 МБ, 512 КБ и т. п."""
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if num_bytes < 1024:
            return f'{num_bytes:.1f} {unit}'
        num_bytes /= 1024
    return f'{num_bytes:.1f} ТБ'


def _get_file_size_from_path(filepath):
    """Размер уже сохранённого файла на диске."""
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


def _check_upload_limits(ticket, new_file_size):
    """
    Проверяет все лимиты до сохранения файла.
    Возвращает (ok: bool, error_message: str | None).
    """
    # 1. Отдельный файл
    if new_file_size > current_app.config['MAX_FILE_SIZE']:
        limit = _format_size(current_app.config['MAX_FILE_SIZE'])
        return False, f'Размер файла превышает {limit}'

    # 2. Количество файлов на заявке
    existing_count = ticket.attachments.count()
    if existing_count >= current_app.config['MAX_FILES_PER_TICKET']:
        limit = current_app.config['MAX_FILES_PER_TICKET']
        return False, f'К заявке уже прикреплено {limit} файлов — максимум'

    # 3. Общий объём вложений заявки
    existing_total = sum(
        _get_file_size_from_path(a.filepath)
        for a in ticket.attachments.all()
    )
    total = existing_total + new_file_size
    if total > current_app.config['MAX_TOTAL_SIZE_PER_TICKET']:
        limit = _format_size(current_app.config['MAX_TOTAL_SIZE_PER_TICKET'])
        return False, f'Суммарный размер вложений превысит {limit}'

    return True, None


def _can_view_ticket(ticket):
    """Проверка права на просмотр карточки заявки."""
    if current_user.role in ('operator', 'manager', 'admin'):
        return True
    if current_user.role == 'requester':
        return ticket.requester_id == current_user.id
    if current_user.role == 'executor':
        return ticket.assignee_id == current_user.id
    return False


def _can_modify_ticket(ticket):
    """
    Проверка права на изменение содержимого заявки
    (комментарии, вложения, статус).

    Руководитель (manager) может ТОЛЬКО смотреть — ТЗ п. 4.2.2.
    """
    if current_user.role in ('admin', 'operator'):
        return True
    if current_user.role == 'executor':
        return ticket.assignee_id == current_user.id
    if current_user.role == 'requester':
        return ticket.requester_id == current_user.id
    return False


def generate_ticket_number():
    """Генерирует уникальный номер заявки (ТЗ п. 4.2.1, п. 2)."""
    year = datetime.now(timezone.utc).year
    last = (Ticket.query
            .filter(Ticket.ticket_number.like(f'TS-{year}-%'))
            .order_by(Ticket.id.desc())
            .first())
    if last:
        try:
            seq = int(last.ticket_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'TS-{year}-{seq:04d}'


def log_action(action, ticket_id=None, details=None):
    """Запись в журнал действий с фиксацией IP (ТЗ п. 4.1.5)."""
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        ticket_id=ticket_id,
        action=action,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:255],
    )
    db.session.add(log)


def allowed_by_extension(filename):
    """Проверка расширения по whitelist (без обращения к диску)."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_EXTENSIONS']


def allowed_by_mime(filepath):
    """
    Проверка реального MIME-типа сохранённого файла.
    Вызывается ТОЛЬКО после file.save().
    """
    try:
        mime = magic.from_file(filepath, mime=True)
    except Exception as e:
        current_app.logger.warning(f'MIME-проверка не удалась для {filepath}: {e}')
        return False
    return mime in ALLOWED_MIMES


# ---------------------------------------------------------------------------
# Список заявок
# ---------------------------------------------------------------------------

@tickets_bp.route('/')
@login_required
def list_tickets():
    """Список и фильтрация заявок (ТЗ п. 4.2.1, п. 7)."""
    page = request.args.get('page', 1, type=int)
    query = Ticket.query

    # Разграничение доступа (ТЗ п. 4.2.2)
    if current_user.role == 'requester':
        query = query.filter(Ticket.requester_id == current_user.id)
    elif current_user.role == 'executor':
        query = query.filter(Ticket.assignee_id == current_user.id)

    # Фильтры
    status = request.args.get('status')
    priority = request.args.get('priority')
    category_id = request.args.get('category_id', type=int)
    assignee_id = request.args.get('assignee_id', type=int)
    requester_id = request.args.get('requester_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category_id:
        query = query.filter(Ticket.category_id == category_id)
    if assignee_id:
        query = query.filter(Ticket.assignee_id == assignee_id)
    if requester_id:
        query = query.filter(Ticket.requester_id == requester_id)
    if date_from:
        query = query.filter(Ticket.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Ticket.created_at <= datetime.fromisoformat(date_to))

    tickets = query.order_by(Ticket.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    categories = Category.query.all()
    executors = User.query.filter_by(role='executor').all()
    requesters = User.query.filter_by(role='requester').all()

    return render_template(
        'tickets/list.html',
        tickets=tickets,
        categories=categories,
        executors=executors,
        requesters=requesters,
        current_filters=request.args,
    )


# ---------------------------------------------------------------------------
# Создание заявки
# ---------------------------------------------------------------------------

@tickets_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_ticket():
    """Создание заявки (ТЗ п. 4.2.1, п. 1)."""
    form = TicketForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]

    if form.validate_on_submit():
        ticket = Ticket(
            ticket_number=generate_ticket_number(),
            subject=form.subject.data,
            description=form.description.data,
            priority=form.priority.data,
            category_id=form.category_id.data,
            requester_id=current_user.id,
        )
        db.session.add(ticket)
        db.session.flush()  # получаем ticket.id

        log_action('create', ticket.id, f'Создана заявка {ticket.ticket_number}')
        db.session.commit()

        flash(f'Заявка {ticket.ticket_number} создана', 'success')
        return redirect(url_for('tickets.detail', ticket_id=ticket.id))

    return render_template('tickets/create.html', form=form)


# ---------------------------------------------------------------------------
# Карточка заявки
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>')
@login_required
def detail(ticket_id):
    """Просмотр карточки заявки (ТЗ п. 4.2.1, пп. 5, 6)."""
    ticket = Ticket.query.get_or_404(ticket_id)

    if not _can_view_ticket(ticket):
        abort(403)

    comment_form = CommentForm()
    assignees = User.query.filter_by(role='executor', is_active=True).all()

    return render_template(
        'tickets/detail.html',
        ticket=ticket,
        comment_form=comment_form,
        assignees=assignees,
    )


# ---------------------------------------------------------------------------
# Назначение исполнителя
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>/assign', methods=['POST'])
@role_required('operator', 'admin')
def assign(ticket_id):
    """Назначение исполнителя (ТЗ п. 4.2.1, п. 3)."""
    ticket = Ticket.query.get_or_404(ticket_id)
    assignee_id = request.form.get('assignee_id', type=int)

    if assignee_id:
        assignee = User.query.filter_by(id=assignee_id, role='executor').first()
        if not assignee:
            flash('Исполнитель не найден', 'danger')
            return redirect(url_for('tickets.detail', ticket_id=ticket_id))

        ticket.assignee_id = assignee.id
        if ticket.status == 'new':
            ticket.status = 'in_progress'

        log_action('assign', ticket.id, f'Назначен исполнитель: {assignee.username}')
        db.session.commit()
        flash(f'Заявка назначена {assignee.username}', 'success')

    return redirect(url_for('tickets.detail', ticket_id=ticket_id))


# ---------------------------------------------------------------------------
# Смена статуса
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>/status', methods=['POST'])
@role_required('operator', 'executor', 'admin')
def update_status(ticket_id):
    """Смена статуса заявки (ТЗ п. 4.2.1, п. 4)."""
    ticket = Ticket.query.get_or_404(ticket_id)

    if current_user.role == 'executor' and ticket.assignee_id != current_user.id:
        abort(403)

    new_status = request.form.get('status')
    valid_statuses = ['new', 'in_progress', 'review', 'done', 'rejected', 'closed']

    if new_status not in valid_statuses:
        flash('Недопустимый статус', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    old_status = ticket.status
    ticket.status = new_status
    log_action('update_status', ticket.id, f'Статус: {old_status} → {new_status}')
    db.session.commit()

    flash('Статус обновлён', 'success')
    return redirect(url_for('tickets.detail', ticket_id=ticket_id))


# ---------------------------------------------------------------------------
# Комментарии
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>/comment', methods=['POST'])
@login_required
def add_comment(ticket_id):
    """Добавление комментария (ТЗ п. 4.2.1, п. 5)."""
    ticket = Ticket.query.get_or_404(ticket_id)

    if not _can_modify_ticket(ticket):
        abort(403)

    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(
            content=form.content.data,
            ticket_id=ticket.id,
            author_id=current_user.id,
        )
        db.session.add(comment)
        log_action('comment', ticket.id, 'Добавлен комментарий')
        db.session.commit()
        flash('Комментарий добавлен', 'success')

    return redirect(url_for('tickets.detail', ticket_id=ticket_id))


# ---------------------------------------------------------------------------
# Вложения
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>/upload', methods=['POST'])
@login_required
def upload_attachment(ticket_id):
    """
    Загрузка вложения с двухфазной проверкой (ТЗ п. 4.2.1, п. 6):
      1. Расширение — до сохранения.
      2. MIME — после сохранения (magic.from_file требует файл на диске).
    """
    ticket = Ticket.query.get_or_404(ticket_id)

    if not _can_modify_ticket(ticket):
        abort(403)

    file = request.files.get('file')

    # 1. Файл выбран?
    if not file or not file.filename:
        flash('Файл не выбран', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 2. Расширение по whitelist
    if not allowed_by_extension(file.filename):
        allowed = ', '.join(sorted(current_app.config['ALLOWED_EXTENSIONS']))
        flash(f'Недопустимый тип файла. Разрешены: {allowed}', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 3. Размер
    size = _get_file_size(file)
    if size == 0:
        flash('Файл пустой', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 4. Лимиты (размер, количество, суммарный объём)
    ok, error = _check_upload_limits(ticket, size)
    if not ok:
        flash(error, 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 5. Сохранение на диск
    original_name = secure_filename(file.filename)
    unique_name = f'{uuid.uuid4().hex}_{original_name}'
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)

    try:
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(filepath)
    except OSError as e:
        current_app.logger.error(f'Ошибка сохранения файла: {e}')
        flash('Не удалось сохранить файл', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 6. MIME-проверка по содержимому (уже сохранённый файл)
    if not allowed_by_mime(filepath):
        # Файл не прошёл — удаляем и сообщаем
        try:
            os.remove(filepath)
        except OSError:
            pass
        flash('Содержимое файла не соответствует его расширению', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    # 7. Запись в БД
    attachment = Attachment(
        filename=original_name,
        filepath=filepath,
        ticket_id=ticket.id,
        uploaded_by=current_user.id,
    )
    db.session.add(attachment)
    log_action('upload', ticket.id,
               f'Загружен файл: {original_name} ({_format_size(size)})')
    db.session.commit()

    flash(f'Файл {original_name} загружен ({_format_size(size)})', 'success')
    return redirect(url_for('tickets.detail', ticket_id=ticket_id))


# ---------------------------------------------------------------------------
# Скачивание вложения
# ---------------------------------------------------------------------------

@tickets_bp.route('/<int:ticket_id>/attachment/<int:att_id>')
@login_required
def download_attachment(ticket_id, att_id):
    """Скачивание вложения с проверкой прав."""
    ticket = Ticket.query.get_or_404(ticket_id)

    if not _can_view_ticket(ticket):
        abort(403)

    attachment = Attachment.query.get_or_404(att_id)

    # Проверка, что вложение принадлежит этой заявке
    if attachment.ticket_id != ticket.id:
        abort(404)

    if not os.path.exists(attachment.filepath):
        flash('Файл не найден на сервере', 'danger')
        return redirect(url_for('tickets.detail', ticket_id=ticket_id))

    log_action('download', ticket.id, f'Скачан файл: {attachment.filename}')
    db.session.commit()

    return send_file(
        attachment.filepath,
        as_attachment=True,
        download_name=attachment.filename,
    )


# ---------------------------------------------------------------------------
# Отчёты
# ---------------------------------------------------------------------------

@tickets_bp.route('/reports')
@role_required('manager', 'admin')
def reports():
    """Страница отчётов (ТЗ п. 4.2.1, п. 8)."""
    return render_template('reports/index.html')


@tickets_bp.route('/reports/export')
@role_required('manager', 'admin')
def export_csv():
    """Экспорт отчёта в CSV."""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = Ticket.query
    if date_from:
        query = query.filter(Ticket.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Ticket.created_at <= datetime.fromisoformat(date_to))

    tickets = query.order_by(Ticket.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Номер', 'Тема', 'Статус', 'Приоритет',
        'Заявитель', 'Исполнитель', 'Дата создания',
    ])

    for t in tickets:
        writer.writerow([
            t.ticket_number,
            t.subject,
            t.status,
            t.priority,
            t.requester.username if t.requester else '',
            t.assignee.username if t.assignee else '',
            t.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'tickets_report_{datetime.now().strftime("%Y%m%d")}.csv',
    )