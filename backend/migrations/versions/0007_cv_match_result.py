"""Persist backend-generated job matching evidence."""
import sqlalchemy as sa
from alembic import op

revision = "0007_cv_match_result"
down_revision = "0006_job_requirements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cv_screenings", sa.Column("match_result", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("cv_screenings", "match_result")
