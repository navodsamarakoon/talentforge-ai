"""Add structured requirements to existing job openings."""
import sqlalchemy as sa
from alembic import op

revision = "0006_job_requirements"
down_revision = "0005_cv_screening"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_openings", sa.Column("requirements", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("job_openings", "requirements")
