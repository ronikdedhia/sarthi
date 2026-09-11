"""
Settings module used ONLY for test runs (pytest.ini points DJANGO_SETTINGS_MODULE here,
not at sarthi_backend.settings directly).

2026-09-10: settings.py now actually calls load_dotenv(), so backend/.env's real
TURSO_DATABASE_URL/TURSO_AUTH_TOKEN reach Django for real (previously python-dotenv was a
dependency nothing invoked). That's necessary for production, but it means tests importing
sarthi_backend.settings directly would run the ENTIRE suite against the real hosted
production Turso database, polluting it with test rows.

An env-var-based guard (e.g. setting DJANGO_DB_ENGINE in a conftest.py) does NOT work here:
pytest-django resolves Django settings inside its own pytest_load_initial_conftests hook,
which runs BEFORE a rootdir conftest.py's own module-level code executes -- confirmed by
tracing an actual failed run that reached out to 'libsql.db.backends.sqlite3' despite a
conftest.py trying to set DJANGO_DB_ENGINE first. A dedicated settings module Django
resolves directly (no hook-ordering race possible) is the standard, robust fix.
"""
from sarthi_backend.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(BASE_DIR / 'db.sqlite3'),
    }
}
