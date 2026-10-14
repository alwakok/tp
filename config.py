import os
import secrets
from datetime import timedelta


class Config:
    # ----------------------------------------------------------------------
    # SECRET_KEY — обязательная переменная окружения в продакшене.
    # В режиме разработки генерируется случайный ключ при каждом запуске
    # (это означает, что сессии сбрасываются при перезапуске — приемлемо
    # для разработки, но НЕ для продакшена).
    # ----------------------------------------------------------------------
    SECRET_KEY = os.environ.get('SECRET_KEY')

    if not SECRET_KEY:
        env = os.environ.get('FLASK_ENV', 'development')
        if env == 'production':
            raise RuntimeError(
                '❌ SECRET_KEY не установлен. '
                'Задайте переменную окружения SECRET_KEY перед запуском в продакшене.'
            )
        # Разработка: генерируем одноразовый ключ
        SECRET_KEY = secrets.token_hex(32)
        print('⚠️  SECRET_KEY не задан — сгенерирован временный ключ. '
              'Сессии будут сброшены при перезапуске.')

    # ----------------------------------------------------------------------
    # База данных
    # ----------------------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///tech_support.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ----------------------------------------------------------------------
    # Безопасность сессий (ТЗ п. 4.1.5)
    # ----------------------------------------------------------------------
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # В проде (FLASK_ENV=production) включаем Secure-флаг автоматически,
    # чтобы cookie сессии никогда не уходила по незашифрованному HTTP.
    # В разработке по умолчанию выключено — иначе localhost по HTTP
    # не сможет сохранить cookie. Переопределяется SESSION_COOKIE_SECURE=1/0.
    SESSION_COOKIE_SECURE = os.environ.get(
        'SESSION_COOKIE_SECURE',
        '1' if os.environ.get('FLASK_ENV', 'development') == 'production' else '0'
    ) == '1'

    # ----------------------------------------------------------------------
    # Демо-данные (seed_data в app.py). По умолчанию включены — удобно для
    # разработки и для первого запуска при защите диплома. На реальном проде
    # укажите SEED_DEMO_DATA=0, чтобы не создавать учётки с паролем 12345678.
    # ----------------------------------------------------------------------
    SEED_DEMO_DATA = os.environ.get('SEED_DEMO_DATA', '1') == '1'

    # ----------------------------------------------------------------------
    # Загрузка файлов (ТЗ п. 4.2.1, п. 6)
    # ----------------------------------------------------------------------
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # общий вес запроса: 16 МБ
    MAX_FILE_SIZE = 5 * 1024 * 1024  # отдельный файл: 5 МБ
    MAX_FILES_PER_TICKET = 10  # максимум файлов на заявку
    MAX_TOTAL_SIZE_PER_TICKET = 50 * 1024 * 1024  # суммарно на заявку: 50 МБ

    UPLOAD_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'uploads'
    )
    ALLOWED_EXTENSIONS = {
        'pdf', 'png', 'jpg', 'jpeg', 'gif',
        'txt', 'log', 'zip', 'docx', 'xlsx',
    }