"""Тесты аутентификации: логин, блокировка, logout, open redirect."""
from conftest import login


def test_login_success(client, users):
    resp = login(client, 'requester1')
    assert resp.status_code == 200
    assert 'Заявки' in resp.get_data(as_text=True)


def test_login_wrong_password(client, users):
    resp = login(client, 'requester1', password='неверный-пароль')
    assert 'Неверное имя пользователя или пароль' in resp.get_data(as_text=True)


def test_login_unknown_username(client):
    resp = login(client, 'нет-такого-пользователя')
    assert 'Неверное имя пользователя или пароль' in resp.get_data(as_text=True)


def test_login_blocked_account(client, users):
    resp = login(client, 'blocked1')
    assert 'заблокирован' in resp.get_data(as_text=True).lower()


def test_logout_requires_login_after(client, users):
    login(client, 'requester1')
    client.get('/logout')
    # после логаута страница заявок должна требовать логина
    resp = client.get('/tickets/', follow_redirects=True)
    assert 'Вход в систему' in resp.get_data(as_text=True)


def test_open_redirect_is_blocked(client, users):
    """?next=https://evil.example не должен уводить на внешний домен."""
    resp = client.post(
        '/login?next=https://evil.example/phishing',
        data={'username': 'requester1', 'password': 'Password123'},
    )
    assert resp.status_code == 302
    assert resp.headers['Location'].startswith('/') or 'evil.example' not in resp.headers['Location']


def test_register_creates_requester_role(client, app):
    resp = client.post('/register', data={
        'username': 'newuser',
        'email': 'newuser@example.com',
        'password': 'Password123',
        'password2': 'Password123',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from models import User
        user = User.query.filter_by(username='newuser').first()
        assert user is not None
        # Роль всегда 'requester', даже если бы кто-то попытался её подменить
        assert user.role == 'requester'
