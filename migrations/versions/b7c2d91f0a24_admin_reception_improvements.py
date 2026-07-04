"""admin reception improvements

Revision ID: b7c2d91f0a24
Revises: a45eda52c22b
Create Date: 2026-07-02 20:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c2d91f0a24"
down_revision = "a45eda52c22b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("profile_image_url", sa.String(length=500), nullable=True))
        batch.create_foreign_key("fk_users_branch_id_branches", "branches", ["branch_id"], ["id"])

    with op.batch_alter_table("barbers") as batch:
        batch.add_column(sa.Column("address", sa.String(length=255), nullable=True))

    with op.batch_alter_table("salary_payments") as batch:
        batch.add_column(sa.Column("recipient_type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.alter_column("barber_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key("fk_salary_payments_user_id_users", "users", ["user_id"], ["id"])

    op.execute("UPDATE salary_payments SET recipient_type = 'barbero' WHERE recipient_type IS NULL")

    with op.batch_alter_table("salary_payments") as batch:
        batch.alter_column("recipient_type", existing_type=sa.String(length=30), nullable=False)


def downgrade():
    with op.batch_alter_table("salary_payments") as batch:
        batch.drop_constraint("fk_salary_payments_user_id_users", type_="foreignkey")
        batch.alter_column("barber_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("user_id")
        batch.drop_column("recipient_type")

    with op.batch_alter_table("barbers") as batch:
        batch.drop_column("address")

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_branch_id_branches", type_="foreignkey")
        batch.drop_column("profile_image_url")
        batch.drop_column("branch_id")
