"""Run the role migration against a separate, populated database."""

import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
BEFORE_ROLES = "fe56fa70289e"
ROLES = "4b7e2c1d9a10"


@pytest.fixture()
def migration_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine]:
    base_url = str(settings.DATABASE_URL)
    name = f"role_migration_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base_url.rsplit("/", 1)[0] + f"/{name}"
    # alembic/env.py reads the URL from settings
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin_engine.dispose()


def _alembic() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "alembic"))
    return cfg


def test_existing_users_keep_their_privileges(migration_db: Engine) -> None:
    cfg = _alembic()
    command.upgrade(cfg, BEFORE_ROLES)
    with migration_db.begin() as conn:
        for email, is_superuser, is_active in [
            ("root@example.com", True, True),
            ("staff@example.com", False, True),
            ("gone@example.com", False, False),
        ]:
            conn.execute(
                text(
                    'INSERT INTO "user" (id, email, hashed_password, is_superuser, '
                    "is_active) VALUES (:id, :email, 'x', :su, :active)"
                ),
                {
                    "id": uuid.uuid4(),
                    "email": email,
                    "su": is_superuser,
                    "active": is_active,
                },
            )

    command.upgrade(cfg, ROLES)
    with migration_db.connect() as conn:
        rows = dict(conn.execute(text('SELECT email, role FROM "user"')).all())
        active = dict(conn.execute(text('SELECT email, is_active FROM "user"')).all())
    assert rows == {
        "root@example.com": "admin",
        "staff@example.com": "member",
        "gone@example.com": "member",
    }
    assert active["gone@example.com"] is False  # active status is untouched

    # Managers must not become superusers when rolling back.
    with migration_db.begin() as conn:
        conn.execute(
            text(
                """UPDATE "user" SET role = 'manager' WHERE email = 'staff@example.com'"""
            )
        )
    command.downgrade(cfg, BEFORE_ROLES)
    with migration_db.connect() as conn:
        rows = dict(conn.execute(text('SELECT email, is_superuser FROM "user"')).all())
    assert rows == {
        "root@example.com": True,
        "staff@example.com": False,
        "gone@example.com": False,
    }
