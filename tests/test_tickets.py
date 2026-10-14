"""Тесты доступа к заявкам (IDOR) и утилит tickets.py."""
from conftest import login


def _create_ticket(client, category_id, subject='Тестовая заявка'):
    return client.post('/tickets/create', data={
        'subject': subject,
        'description': 'Описание проблемы',
        'priority': 'medium',
        'category_id': category_id,
    }, follow_redirects=True)


def test_requester_can_view_own_ticket(client, users, category):
    login(client, 'requester1')
    _create_ticket(client, category)

    resp = client.get('/tickets/1')
    assert resp.status_code == 200
    assert 'Тестовая заявка' in resp.get_data(as_text=True)


def test_other_requester_cannot_view_foreign_ticket(client, users, category):
    login(client, 'requester1')
    _create_ticket(client, category)
    client.get('/logout')

    login(client, 'requester2')
    resp = client.get('/tickets/1')
    assert resp.status_code == 403


def test_executor_cannot_view_unassigned_ticket(client, users, category):
    login(client, 'requester1')
    _create_ticket(client, category)
    client.get('/logout')

    login(client, 'executor1')
    resp = client.get('/tickets/1')
    assert resp.status_code == 403


def test_operator_can_view_any_ticket(client, users, category):
    login(client, 'requester1')
    _create_ticket(client, category)
    client.get('/logout')

    login(client, 'operator1')
    resp = client.get('/tickets/1')
    assert resp.status_code == 200


def test_requester_cannot_assign_ticket(client, users, category):
    login(client, 'requester1')
    _create_ticket(client, category)

    resp = client.post('/tickets/1/assign', data={'assignee_id': users['executor']})
    assert resp.status_code == 403


def test_csv_safe_neutralizes_formula_injection():
    from tickets import _csv_safe

    assert _csv_safe('=HYPERLINK("http://evil")').startswith("'=")
    assert _csv_safe('+1+1').startswith("'+")
    assert _csv_safe('Обычная тема') == 'Обычная тема'


def test_generate_ticket_number_is_unique_per_year(app, users, category):
    with app.app_context():
        from tickets import generate_ticket_number
        from models import db, Ticket
        from datetime import datetime, timezone

        first = generate_ticket_number()
        db.session.add(Ticket(
            ticket_number=first, subject='x', description='x',
            category_id=category, requester_id=users['requester'],
        ))
        db.session.commit()

        second = generate_ticket_number()
        assert first != second
