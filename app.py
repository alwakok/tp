# app.py
"""
АИС «Техподдержка» — точка входа приложения.

Стек (актуально на 17.09.2026):
    Python       3.14.5
    Flask        3.1.3
    SQLAlchemy   2.0.54
    Flask-Login  0.6.3
    Flask-WTF    1.2.2

Запуск для разработки:
    python app.py

Запуск для продакшена:
    gunicorn --workers 4 --bind unix:/run/tech_support.sock 'app:app'
"""

import os
from datetime import datetime, timezone

from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import generate_csrf, CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config
from models import db, User, Category
from auth import auth_bp
from tickets import tickets_bp
from admin import admin_bp


# ---------------------------------------------------------------------------
# Справочники для человекочитаемых подписей (используются в Jinja-фильтрах)
# ---------------------------------------------------------------------------
ROLE_LABELS = {
    'requester': 'Заявитель',
    'operator': 'Оператор',
    'executor': 'Исполнитель',
    'manager': 'Руководитель',
    'admin': 'Администратор',
}

STATUS_LABELS = {
    'new': 'Новая',
    'in_progress': 'В работе',
    'review': 'На проверке',
    'done': 'Выполнена',
    'rejected': 'Отклонена',
    'closed': 'Закрыта',
}

PRIORITY_LABELS = {
    'low': 'Низкий',
    'medium': 'Средний',
    'high': 'Высокий',
    'critical': 'Критический',
}


# ---------------------------------------------------------------------------
# Включаем поддержку внешних ключей в SQLite.
# По умолчанию SQLite не проверяет FK — это критично для целостности данных.
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, connection_record):
    # Работает только для SQLite-соединений
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        # Не SQLite — игнорируем
        pass
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Flask-Login
# ---------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Фабрика приложения
# ---------------------------------------------------------------------------
def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Инициализация расширений
    db.init_app(app)
    csrf = CSRFProtect()
    csrf.init_app(app)
    login_manager.init_app(app)

    # Регистрация Blueprint'ов
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(admin_bp)

    # -----------------------------------------------------------------------
    # Jinja-фильтры и глобальные переменные (используются в шаблонах)
    # -----------------------------------------------------------------------
    app.jinja_env.globals.update(
        role_label=lambda r: ROLE_LABELS.get(r, r),
        status_label=lambda s: STATUS_LABELS.get(s, s),
        priority_label=lambda p: PRIORITY_LABELS.get(p, p),
        csrf_token=generate_csrf,
    )

    @app.context_processor
    def inject_now():
        return {'now': datetime.now(timezone.utc)}

    # -----------------------------------------------------------------------
    # Корневой маршрут
    # -----------------------------------------------------------------------
    @app.route('/')
    def index():
        return render_template('base.html')

    # -----------------------------------------------------------------------
    # Обработчики ошибок (ТЗ п. 4.1.8)
    # -----------------------------------------------------------------------
    @app.errorhandler(403)
    def forbidden(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return render_template('errors/413.html'), 413

    # -----------------------------------------------------------------------
    # Инициализация БД и начальных данных
    # -----------------------------------------------------------------------
    with app.app_context():
        db.create_all()
        seed_data()

    return app


# ---------------------------------------------------------------------------
# Начальные данные (выполняется один раз при первом запуске)
# ---------------------------------------------------------------------------
def seed_data():
    """
    Создаёт пользователей всех ролей и базовые категории заявок,
    если база данных пуста. При повторных запусках ничего не меняет.
    """
    if User.query.count() > 0:
        return

    # -----------------------------------------------------------------------
    # Пользователи всех ролей (ТЗ п. 4.2.2)
    # -----------------------------------------------------------------------
    demo_users = [
        # (логин,      email,                     пароль,         роль)
        ('admin',     'admin@example.com',       '12345678',    'admin'),
        ('operator', 'operator1@example.com',   '12345678', 'operator'),
        ('executor', 'executor1@example.com',   '12345678', 'executor'),
        ('manager',  'manager1@example.com',    '12345678',  'manager'),
        ('user',     'user1@example.com',       '12345678',   'requester'),
    ]

    for username, email, password, role in demo_users:
        user = User(username=username, email=email, role=role, is_active=True)
        user.set_password(password)
        db.session.add(user)

    # -----------------------------------------------------------------------
    # Категории заявок (ТЗ п. 4.2.1, п. 10)
    # -----------------------------------------------------------------------
    default_categories = [
        'Оборудование',
        'Программное обеспечение',
        'Сеть',
        'Доступ и учётные записи',
        'Другое',
    ]
    for name in default_categories:
        db.session.add(Category(name=name))

    db.session.commit()

    # -----------------------------------------------------------------------
    # Вывод учётных данных в консоль
    # -----------------------------------------------------------------------
    print('=' * 70)
    print('✅ Начальные данные созданы')
    print('=' * 70)
    print(f'{"Логин":<12} {"Пароль":<15} {"Роль":<16} Кто это')
    print('-' * 70)

    role_names = {
        'admin':     'Администратор',
        'operator':  'Оператор',
        'executor':  'Исполнитель',
        'manager':   'Руководитель',
        'requester': 'Заявитель',
    }
    descriptions = {
        'admin':     'Полный доступ, управление пользователями',
        'operator':  'Регистрация и назначение всех заявок',
        'executor':  'Обработка только назначенных заявок',
        'manager':   'Просмотр всех заявок и отчёты',
        'requester': 'Создание и просмотр своих заявок',
    }

    for username, _, password, role in demo_users:
        print(f'{username:<12} {password:<15} {role_names[role]:<16} {descriptions[role]}')

    print('=' * 70)
    print('⚠️  Смените пароли перед использованием в реальной эксплуатации!')
    print('=' * 70)

# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
app = create_app()


if __name__ == '__main__':
    # ВНИМАНИЕ: dev-сервер Flask не предназначен для продакшена.
    # Для продакшена используйте Gunicorn/uWSGI + Nginx.
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5001, debug=debug_mode)


