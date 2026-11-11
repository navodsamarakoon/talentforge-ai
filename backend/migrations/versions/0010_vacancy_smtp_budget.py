"""Track the daily vacancy SMTP budget and persistent authentication stop."""
import sqlalchemy as sa
from alembic import op

revision = "0010_vacancy_smtp_budget"
down_revision = "0009_vacancy_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vacancy_smtp_budget",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_day", sa.Date(), nullable=False),
        sa.Column("reservations", sa.Integer(), nullable=False),
        sa.Column("auth_blocked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1 AND reservations >= 0", name="ck_vacancy_smtp_budget_singleton"),
    )


def downgrade():
    raise RuntimeError("Keep the SMTP budget and authentication stop during application rollback.")
