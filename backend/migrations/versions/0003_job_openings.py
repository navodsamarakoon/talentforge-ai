"""Add recruiter job openings.

Revision ID: 0003_job_openings
Revises: 0002_assessment_archive
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_job_openings"
down_revision = "0002_assessment_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    if "job_openings" not in existing_tables:
        op.create_table(
            "job_openings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("employment_type", sa.String(length=20), nullable=False),
            sa.Column("location", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "employment_type IN ('internship', 'full-time', 'part-time')",
                name="ck_job_openings_employment_type",
            ),
            sa.CheckConstraint(
                "status IN ('draft', 'published', 'closed')",
                name="ck_job_openings_status",
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"],
                ["organizations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("job_openings")
    }
    if "ix_job_openings_org_created" not in existing_indexes:
        op.create_index(
            "ix_job_openings_org_created",
            "job_openings",
            ["organization_id", "created_at"],
        )
    if "ix_job_openings_status_created" not in existing_indexes:
        op.create_index(
            "ix_job_openings_status_created",
            "job_openings",
            ["status", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "job_openings" in inspector.get_table_names():
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("job_openings")
        }
        if "ix_job_openings_status_created" in existing_indexes:
            op.drop_index("ix_job_openings_status_created", table_name="job_openings")
        if "ix_job_openings_org_created" in existing_indexes:
            op.drop_index("ix_job_openings_org_created", table_name="job_openings")
        op.drop_table("job_openings")
