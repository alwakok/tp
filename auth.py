from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import login_user, logout_user, login_required, current_user
from forms import LoginForm, RegisterForm
from models import db, User



auth_bp = Blueprint('auth', __name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=['500 per day', '100 per hour'],
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
        if user is None or not user.check_password(form.password.data):
            flash('Неверное имя пользователя или пароль', 'danger')
            return redirect(url_for('auth.login'))
        if not user.is_active:
            flash('Учётная запись заблокирована', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('tickets.list_tickets'))

    return render_template('login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Публичная регистрация — только для заявителей. В проде отключить."""
    if current_user.is_authenticated:
        return redirect(url_for('tickets.list_tickets'))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data, role='requester')
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация успешна. Теперь вы можете войти.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))