"""Persist organization summary snapshots and delivery outcomes."""
import sqlalchemy as sa
from alembic import op

revision = "0008_recruiter_summaries"
down_revision = "0007_cv_match_result"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recruiter_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("run_date", sa.String(10), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "run_date", name="uq_recruiter_summary_org_date"),
        sa.CheckConstraint("state IN ('pending','claimed','sent','failed','unknown')", name="ck_recruiter_summary_state"),
    )
    op.add_column("cv_screenings", sa.Column("summary_id", sa.String(36), sa.ForeignKey("recruiter_summaries.id", ondelete="RESTRICT")))
    op.create_index("ix_cv_screenings_summary_id", "cv_screenings", ["summary_id"])


def downgrade():
    raise RuntimeError("Retain summary delivery evidence and roll back code instead.")
