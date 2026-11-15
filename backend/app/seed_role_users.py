"""Create one demo user per role for local review. Development only.

    uv run python app/seed_role_users.py

Users (password: changethis123):
    admin   -> FIRST_SUPERUSER from .env (created by prestart)
    manager -> manager@example.com
    member  -> member@example.com
"""

import logging

from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.db import engine, init_db
from app.models import UserCreate, UserRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEMO_PASSWORD = "changethis123"
DEMO_USERS = {
    "manager@example.com": UserRole.MANAGER,
    "member@example.com": UserRole.MEMBER,
}


def main() -> None:
    if settings.FASTAPI_ENV != "development":
        raise SystemExit("Refusing to seed demo users outside development")
    with Session(engine) as session:
        init_db(session)
        for email, role in DEMO_USERS.items():
            if crud.get_user_by_email(session=session, email=email):
                logger.info("%s already exists, skipping", email)
                continue
            crud.create_user(
                session=session,
                user_create=UserCreate(
                    email=email,
                    password=DEMO_PASSWORD,
                    role=role,
                    full_name=role.title(),
                ),
            )
            logger.info("Created %s (%s)", email, role)


if __name__ == "__main__":
    main()
