from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user
from models import db, User, Category
from forms import UserForm, CategoryForm
from auth import role_required

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/users')
@role_required('admin')
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@role_required('admin')
def create_user():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('Имя пользователя уже занято', 'danger')
            return render_template('admin/user_form.html', form=form)

        user = User(username=form.username.data, email=form.email.data, role=form.role.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'Пользователь {user.username} создан', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', form=form)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@role_required('admin')
def toggle_user(user_id):
    """Блокировка/разблокировка (ТЗ п. 4.2.1, п. 11)."""
    user = User.query.get_or_404(user_id)

    # 1. Нельзя заблокировать себя
    if user.id == current_user.id:
        flash('Нельзя заблокировать собственную учётную запись', 'danger')
        return redirect(url_for('admin.users'))

    # 2. Нельзя заблокировать последнего активного администратора
    if user.role == 'admin' and user.is_active:
        active_admins = User.query.filter_by(role='admin', is_active=True).count()
        if active_admins <= 1:
            flash('Нельзя заблокировать последнего активного администратора', 'danger')
            return redirect(url_for('admin.users'))

    # Блокировка/разблокировка
    user.is_active = not user.is_active
    db.session.commit()

    action = 'разблокирован' if user.is_active else 'заблокирован'
    flash(f'Пользователь {user.username} {action}', 'success')

    return redirect(url_for('admin.users'))

@admin_bp.route('/categories', methods=['GET', 'POST'])
@role_required('admin')
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        db.session.add(Category(name=form.name.data))
        db.session.commit()
        flash('Категория добавлена', 'success')
        return redirect(url_for('admin.categories'))

    all_categories = Category.query.all()
    return render_template('admin/categories.html', categories=all_categories, form=form)