"""Initial TalentForge platform schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op

from talentforge.database import Base
from talentforge import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    original = {"organizations", "users", "assessments", "questions", "test_cases", "invitations", "attempts", "submissions", "evaluation_reports", "audit_events"}
    Base.metadata.create_all(bind=op.get_bind(), tables=[t for t in Base.metadata.sorted_tables if t.name in original])


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
