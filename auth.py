from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from audit import log_action
from forms import LoginForm, RegisterForm
from models import db, User


auth_bp = Blueprint('auth', __name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=['500 per day', '100 per hour'],
)

# Хэш для «фиктивной» проверки пароля, когда пользователь с таким именем
# не найден. Нужен, чтобы check_password_hash всегда выполнялась и ответ
# для несуществующего и существующего (с неверным паролем) логина занимал
# одинаковое время — иначе по задержке можно угадывать существующие логины.
_DUMMY_PASSWORD_HASH = generate_password_hash('dummy-password-for-timing-safety')


def _is_safe_redirect_url(target):
    """
    Разрешает редирект только на относительный путь в рамках этого же сайта.
    Защита от open redirect через параметр ?next=.
    """
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return (
        test_url.scheme in ('', 'http', 'https')
        and test_url.netloc in ('', ref_url.netloc)
        and not target.startswith('//')  # protocol-relative URL — тоже внешний
    )


def role_required(*roles):
    """Декоратор проверки роли (ТЗ п. 4.2.2)"""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
@limiter.limit('20 per hour')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('tickets.list_tickets'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        if user is None:
            # Пользователя нет — всё равно выполняем проверку хэша, чтобы
            # время ответа не отличалось от случая «неверный пароль»
            # (защита от user enumeration по таймингу).
            check_password_hash(_DUMMY_PASSWORD_HASH, form.password.data)
            log_action('login_failed', details=f'Неизвестный логин: {form.username.data}')
            db.session.commit()
            flash('Неверное имя пользователя или пароль', 'danger')
            return redirect(url_for('auth.login'))

        if not user.check_password(form.password.data):
            log_action('login_failed', user_id=user.id, details='Неверный пароль')
            db.session.commit()
            flash('Неверное имя пользователя или пароль', 'danger')
            return redirect(url_for('auth.login'))

        if not user.is_active:
            log_action('login_blocked', user_id=user.id, details='Попытка входа в заблокированную учётную запись')
            db.session.commit()
            flash('Учётная запись заблокирована', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=form.remember_me.data)
        log_action('login', user_id=user.id)
        db.session.commit()

        next_page = request.args.get('next')
        if not _is_safe_redirect_url(next_page):
            next_page = None
        return redirect(next_page or url_for('tickets.list_tickets'))

    return render_template('login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def register():
    """Публичная регистрация — только для заявителей. В проде отключить."""
    if current_user.is_authenticated:
        return redirect(url_for('tickets.list_tickets'))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data, role='requester')
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # получаем user.id для аудит-лога
        log_action('register', user_id=user.id, details=f'Зарегистрирован: {user.username}')
        db.session.commit()
        flash('Регистрация успешна. Теперь вы можете войти.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    log_action('logout', user_id=current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))
