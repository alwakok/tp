# audit.py
"""
Журнал действий (ТЗ п. 4.1.5, п. 4).

Вынесен в отдельный модуль, а не в tickets.py, по двум причинам:
  1. Логирование нужно и в auth.py (login/logout/register), и в
     admin.py (создание/блокировка пользователей, категории) — если бы
     функция осталась в tickets.py, auth.py не мог бы её импортировать
     без циклического импорта (tickets.py и так импортирует role_required
     из auth.py).
  2. Один источник правды для формата записи аудита.
"""
from flask import request
from flask_login import current_user

from models import db, AuditLog


def log_action(action, ticket_id=None, details=None, user_id=None):
    """
    Записывает действие в audit_logs.

    user_id можно передать явно (например, для событий, где current_user
    ещё не аутентифицирован на момент записи — неудачная попытка логина
    по известному пользователю). По умолчанию берётся current_user.
    """
    if user_id is None:
        user_id = current_user.id if current_user.is_authenticated else None

    log = AuditLog(
        user_id=user_id,
        ticket_id=ticket_id,
        action=action,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:255],
    )
    db.session.add(log)
