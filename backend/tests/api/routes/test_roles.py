"""Security-critical behaviour of the admin / manager / member access model."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, UserRole, UserUpdate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

USERS = f"{settings.API_V1_STR}/users"
METRICS = f"{settings.API_V1_STR}/metrics/"


def _user_with_headers(
    client: TestClient, db: Session, role: UserRole
) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password, role=role)
    )
    headers = user_authentication_headers(client=client, email=email, password=password)
    return user, headers


def test_manager_can_view_users_and_metrics(client: TestClient, db: Session) -> None:
    _, headers = _user_with_headers(client, db, UserRole.MANAGER)
    other, _ = _user_with_headers(client, db, UserRole.MEMBER)

    assert client.get(f"{USERS}/", headers=headers).status_code == 200
    assert client.get(f"{USERS}/{other.id}", headers=headers).status_code == 200
    r = client.get(METRICS, headers=headers)
    assert r.status_code == 200
    assert set(r.json()["users_by_role"]) == {"admin", "manager", "member"}


def test_manager_cannot_change_access(client: TestClient, db: Session) -> None:
    manager, headers = _user_with_headers(client, db, UserRole.MANAGER)
    other, _ = _user_with_headers(client, db, UserRole.MEMBER)

    for target in (other, manager):  # neither other users nor themselves
        r = client.patch(
            f"{USERS}/{target.id}", headers=headers, json={"role": "admin"}
        )
        assert r.status_code == 403
    r = client.patch(f"{USERS}/{other.id}", headers=headers, json={"is_active": False})
    assert r.status_code == 403
    r = client.post(
        f"{USERS}/",
        headers=headers,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert r.status_code == 403
    assert client.delete(f"{USERS}/{other.id}", headers=headers).status_code == 403

    db.refresh(other)
    assert other.role == UserRole.MEMBER and other.is_active


def test_member_cannot_view_users_or_metrics(client: TestClient, db: Session) -> None:
    _, headers = _user_with_headers(client, db, UserRole.MEMBER)
    other, _ = _user_with_headers(client, db, UserRole.MEMBER)

    assert client.get(f"{USERS}/", headers=headers).status_code == 403
    assert client.get(f"{USERS}/{other.id}", headers=headers).status_code == 403
    assert client.get(METRICS, headers=headers).status_code == 403


def test_member_can_update_own_profile_but_not_escalate(
    client: TestClient, db: Session
) -> None:
    member, headers = _user_with_headers(client, db, UserRole.MEMBER)

    r = client.patch(
        f"{USERS}/me", headers=headers, json={"full_name": "New Name", "role": "admin"}
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "New Name"
    assert r.json()["role"] == "member"  # role is not part of the self-update

    r = client.patch(f"{USERS}/{member.id}", headers=headers, json={"role": "admin"})
    assert r.status_code == 403
    db.refresh(member)
    assert member.role == UserRole.MEMBER


def test_signup_always_creates_member(client: TestClient) -> None:
    email = random_email()
    r = client.post(
        f"{USERS}/signup",
        json={"email": email, "password": random_lower_string(), "role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "member"


def test_admin_manages_access(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    other, _ = _user_with_headers(client, db, UserRole.MEMBER)
    r = client.patch(
        f"{USERS}/{other.id}", headers=superuser_token_headers, json={"role": "manager"}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"

    r = client.patch(
        f"{USERS}/{other.id}", headers=superuser_token_headers, json={"role": "owner"}
    )
    assert r.status_code == 422  # unknown roles are rejected


def test_role_change_applies_to_existing_session(
    client: TestClient, db: Session
) -> None:
    member, headers = _user_with_headers(client, db, UserRole.MEMBER)
    assert client.get(f"{USERS}/", headers=headers).status_code == 403

    crud.update_user(
        session=db, db_user=member, user_in=UserUpdate(role=UserRole.MANAGER)
    )
    assert client.get(f"{USERS}/", headers=headers).status_code == 200

    crud.update_user(
        session=db, db_user=member, user_in=UserUpdate(role=UserRole.MEMBER)
    )
    assert client.get(f"{USERS}/", headers=headers).status_code == 403


def test_deactivation_applies_to_existing_session(
    client: TestClient, db: Session
) -> None:
    manager, headers = _user_with_headers(client, db, UserRole.MANAGER)
    assert client.get(f"{USERS}/me", headers=headers).status_code == 200

    crud.update_user(session=db, db_user=manager, user_in=UserUpdate(is_active=False))
    assert client.get(f"{USERS}/me", headers=headers).status_code == 400
    assert client.get(METRICS, headers=headers).status_code == 400


def test_admin_cannot_remove_own_admin_access(client: TestClient, db: Session) -> None:
    admin, headers = _user_with_headers(client, db, UserRole.ADMIN)

    for change in ({"role": "manager"}, {"role": "member"}, {"is_active": False}):
        r = client.patch(f"{USERS}/{admin.id}", headers=headers, json=change)
        assert r.status_code == 403
    db.refresh(admin)
    assert admin.role == UserRole.ADMIN and admin.is_active
