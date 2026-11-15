from collections.abc import Callable, Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import USER_VIEWER_ROLES, TokenPayload, User, UserRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: allow only users whose current role is in `roles`.

    The role is read from the database on every request (see get_current_user),
    so role or active-status changes apply to sessions that already exist.
    """
    allowed = frozenset(roles)

    def checker(current_user: CurrentUser) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=403, detail="The user doesn't have enough privileges"
            )
        return current_user

    return checker


get_current_admin = require_roles(UserRole.ADMIN)
get_current_user_viewer = require_roles(*USER_VIEWER_ROLES)
