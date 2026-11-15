"""Replace is_superuser with role

Existing superusers become admins and everyone else becomes a member, so no
user gains privileges. Downgrade maps admin back to is_superuser and maps
manager to a regular user (the least-privileged equivalent).

Revision ID: 4b7e2c1d9a10
Revises: fe56fa70289e
Create Date: 2026-11-15 15:05:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4b7e2c1d9a10"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "role", sa.String(length=20), nullable=False, server_default="member"
        ),
    )
    op.execute("""UPDATE "user" SET role = 'admin' WHERE is_superuser IS TRUE""")
    op.create_check_constraint(
        "ck_user_role", "user", "role IN ('admin', 'manager', 'member')"
    )
    op.drop_column("user", "is_superuser")


def downgrade():
    op.add_column(
        "user",
        sa.Column(
            "is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute("""UPDATE "user" SET is_superuser = TRUE WHERE role = 'admin'""")
    op.drop_constraint("ck_user_role", "user", type_="check")
    op.drop_column("user", "role")
