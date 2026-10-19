"""Add assessment archive state.

Revision ID: 0002_assessment_archive
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_assessment_archive"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessments")}
    if "is_archived" not in existing_columns:
        op.add_column(
            "assessments",
            sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        )


def downgrade() -> None:
    existing_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessments")}
    if "is_archived" in existing_columns:
        op.drop_column("assessments", "is_archived")
