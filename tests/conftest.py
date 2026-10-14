"""
Общие фикстуры для тестов.

Запуск: pytest (из корня проекта, после pip install -r requirements-dev.txt).
"""
import os
import tempfile

import pytest

from app import create_app
from config import Config
from models import db, User, Category


@pytest.fixture()
def app():
    # Файловая, а не in-memory SQLite: с ':memory:' каждое новое соединение
    # из пула видит пустую базу, что ломает фикстуры между запросами теста.
    db_fd, db_path = tempfile.mkstemp(suffix='.db')

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        WTF_CSRF_ENABLED = False      # тесты шлют данные формы без CSRF-токена
        RATELIMIT_ENABLED = False     # иначе тесты логина мешают друг другу
        SEED_DEMO_DATA = False        # пользователей создаём сами, в фикстурах
        SECRET_KEY = 'test-secret-key'

    application = create_app(TestConfig)
    yield application

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def category(app):
    with app.app_context():
        c = Category(name='Оборудование')
        db.session.add(c)
        db.session.commit()
        return c.id


def make_user(username, role, password='Password123', is_active=True,
              email=None):
    """Создаёт пользователя заданной роли и возвращает его id."""
    user = User(
        username=username,
        email=email or f'{username}@example.com',
        role=role,
        is_active=is_active,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user.id


@pytest.fixture()
def users(app):
    """Создаёт по одному пользователю на каждую роль, возвращает словарь id."""
    with app.app_context():
        ids = {
            'requester': make_user('requester1', 'requester'),
            'requester2': make_user('requester2', 'requester'),
            'operator': make_user('operator1', 'operator'),
            'executor': make_user('executor1', 'executor'),
            'manager': make_user('manager1', 'manager'),
            'admin': make_user('admin1', 'admin'),
            'blocked': make_user('blocked1', 'requester', is_active=False),
        }
        return ids


def login(client, username, password='Password123'):
    return client.post('/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)
