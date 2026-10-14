"""Тесты ролевой модели доступа (RBAC)."""
from conftest import login


def test_requester_cannot_access_admin_users(client, users):
    login(client, 'requester1')
    resp = client.get('/admin/users')
    assert resp.status_code == 403


def test_admin_can_access_admin_users(client, users):
    login(client, 'admin1')
    resp = client.get('/admin/users')
    assert resp.status_code == 200


def test_operator_cannot_access_admin_users(client, users):
    login(client, 'operator1')
    resp = client.get('/admin/users')
    assert resp.status_code == 403


def test_requester_cannot_access_reports(client, users):
    login(client, 'requester1')
    resp = client.get('/tickets/reports')
    assert resp.status_code == 403


def test_manager_can_access_reports(client, users):
    login(client, 'manager1')
    resp = client.get('/tickets/reports')
    assert resp.status_code == 200


def test_anonymous_redirected_to_login(client):
    resp = client.get('/tickets/', follow_redirects=True)
    assert 'Вход в систему' in resp.get_data(as_text=True)
