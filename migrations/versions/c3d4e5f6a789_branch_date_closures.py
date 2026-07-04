"""branch date closures

Revision ID: c3d4e5f6a789
Revises: b7c2d91f0a24
Create Date: 2026-07-03 02:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a789"
down_revision = "b7c2d91f0a24"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "branch_date_closures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "date", name="uq_branch_date_closure"),
    )
    with op.batch_alter_table("branch_date_closures") as batch:
        batch.create_index(batch.f("ix_branch_date_closures_date"), ["date"], unique=False)


def downgrade():
    with op.batch_alter_table("branch_date_closures") as batch:
        batch.drop_index(batch.f("ix_branch_date_closures_date"))
    op.drop_table("branch_date_closures")
