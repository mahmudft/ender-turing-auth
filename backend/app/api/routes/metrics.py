from fastapi import APIRouter, Depends
from sqlmodel import col, func, select

from app.api.deps import SessionDep, get_current_user_viewer
from app.models import Item, MetricsPublic, User, UserRole

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(get_current_user_viewer)],
)


@router.get("/", response_model=MetricsPublic)
def read_metrics(session: SessionDep) -> MetricsPublic:
    """
    Basic user and item metrics. Available to admins and managers.
    """
    total_users = session.exec(select(func.count()).select_from(User)).one()
    active_users = session.exec(
        select(func.count()).select_from(User).where(col(User.is_active))
    ).one()
    counts = dict(
        session.exec(select(User.role, func.count()).group_by(User.role)).all()
    )
    users_by_role = {role: counts.get(role, 0) for role in UserRole}
    total_items = session.exec(select(func.count()).select_from(Item)).one()
    return MetricsPublic(
        total_users=total_users,
        active_users=active_users,
        users_by_role=users_by_role,
        total_items=total_items,
    )
