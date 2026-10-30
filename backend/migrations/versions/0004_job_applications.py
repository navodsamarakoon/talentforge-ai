"""Add candidate job applications and private CV references.

Revision ID: 0004_job_applications
Revises: 0003_job_openings
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_job_applications"
down_revision = "0003_job_openings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_opening_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_user_id", sa.String(length=36), nullable=False),
        sa.Column("original_cv_filename", sa.String(length=255), nullable=False),
        sa.Column("cv_mime_type", sa.String(length=100), nullable=False),
        sa.Column("cv_sha256", sa.String(length=64), nullable=False),
        sa.Column("cv_storage_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="submitted", nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('submitted', 'screening', 'rejected', 'selected')",
            name="ck_job_application_status",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_opening_id"],
            ["job_openings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cv_storage_ref", name="uq_job_applications_cv_storage_ref"),
        sa.UniqueConstraint(
            "job_opening_id",
            "candidate_user_id",
            name="uq_job_application_job_candidate",
        ),
    )
    op.create_index(
        "ix_job_applications_candidate_submitted",
        "job_applications",
        ["candidate_user_id", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_applications_candidate_submitted",
        table_name="job_applications",
    )
    op.drop_table("job_applications")
