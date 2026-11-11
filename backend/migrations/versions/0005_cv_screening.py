"""Add the CV automation ledger. No backfill or changes to existing records."""
from alembic import op
import sqlalchemy as sa

revision = "0005_cv_screening"
down_revision = "0004_job_applications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("cv_screenings",
        sa.Column("application_id", sa.String(36), sa.ForeignKey("job_applications.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("dispatch_id", sa.String(36), nullable=False, unique=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("extraction_attempts", sa.Integer(), nullable=False),
        sa.Column("generation_token", sa.String(36)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("profile", sa.JSON()), sa.Column("cv_text", sa.Text()), sa.Column("error_code", sa.String(64)),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True)), sa.Column("workflow_claimed_at", sa.DateTime(timezone=True)),
        sa.Column("decision", sa.String(16)), sa.Column("notification_state", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('queued','extracting','ready','dispatching','accepted','unknown','failed')", name="ck_cv_screening_state"),
        sa.CheckConstraint("extraction_attempts BETWEEN 0 AND 3", name="ck_cv_screening_attempts"),
        sa.CheckConstraint("notification_state IS NULL OR notification_state IN ('claimed','sent','failed','unknown')", name="ck_cv_notification_state"))


def downgrade():
    raise RuntimeError("Retain screening/notification evidence; roll back code and disable flags, not this ledger")
