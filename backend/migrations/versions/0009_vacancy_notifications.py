"""Add opt-in vacancy notification events and delivery state."""
import sqlalchemy as sa
from alembic import op

revision = "0009_vacancy_notifications"
down_revision = "0008_recruiter_summaries"
branch_labels = None
depends_on = None


def upgrade():
    # Revision 0001 builds its tables from live metadata, so fresh PostgreSQL
    # installs may already have this column. Existing databases still need it.
    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vacancy_notifications BOOLEAN DEFAULT false NOT NULL")
    elif op.get_context().as_sql or not any(
        column["name"] == "vacancy_notifications" for column in sa.inspect(op.get_bind()).get_columns("users")
    ):
        op.add_column("users", sa.Column("vacancy_notifications", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        "vacancy_notification_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vacancy_id", sa.String(36), sa.ForeignKey("job_openings.id"), unique=True, nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "vacancy_notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("vacancy_notification_events.id"), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("outcome", sa.String(24)),
        sa.UniqueConstraint("event_id", "candidate_id", name="uq_vacancy_notification_candidate"),
        sa.CheckConstraint("state IN ('pending','claimed','sent','failed','skipped','delivery_unknown')",
                           name="ck_vacancy_notification_state"),
    )
    op.create_index("ix_vacancy_notification_due", "vacancy_notification_deliveries", ["state", "available_at"])
    op.create_index("ix_vacancy_notification_attempt", "vacancy_notification_deliveries", ["last_attempt_at"])


def downgrade():
    raise RuntimeError("Vacancy notification history cannot be removed by downgrade.")
