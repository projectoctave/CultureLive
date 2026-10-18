import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-only-32b!!")
os.environ.setdefault("DASHBOARD_API_KEY", "test-admin-api-key-123")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "test-token-encryption-key-xx")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live"
)


def run_in_thread(fn, *args):
    """Exécute fn dans un thread (Alembic utilise asyncio.run, interdit dans une boucle active)."""
    error: list[BaseException] = []

    def target():
        try:
            fn(*args)
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]


@pytest.fixture(scope="session")
def migrated_db():
    """Applique les migrations Alembic sur la base de test (valide aussi les migrations)."""
    from backend.db.migrate import upgrade_head

    run_in_thread(upgrade_head)
