from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from talentforge.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_organization_role", "organization_id", "role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vacancy_notifications: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization | None] = relationship()


class JobOpening(Base):
    __tablename__ = "job_openings"
    __table_args__ = (
        CheckConstraint(
            "employment_type IN ('internship', 'full-time', 'part-time')",
            name="ck_job_openings_employment_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'closed')",
            name="ck_job_openings_status",
        ),
        Index("ix_job_openings_org_created", "organization_id", "created_at"),
        Index("ix_job_openings_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requirements: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = (
        UniqueConstraint(
            "job_opening_id",
            "candidate_user_id",
            name="uq_job_application_job_candidate",
        ),
        UniqueConstraint("cv_storage_ref", name="uq_job_applications_cv_storage_ref"),
        CheckConstraint(
            "status IN ('submitted', 'screening', 'rejected', 'selected')",
            name="ck_job_application_status",
        ),
        Index("ix_job_applications_candidate_submitted", "candidate_user_id", "submitted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_opening_id: Mapped[str] = mapped_column(
        ForeignKey("job_openings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    original_cv_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    cv_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    cv_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cv_storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted", server_default="submitted")
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class VacancyNotificationEvent(Base):
    __tablename__ = "vacancy_notification_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("job_openings.id"), unique=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VacancyNotificationDelivery(Base):
    __tablename__ = "vacancy_notification_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "candidate_id", name="uq_vacancy_notification_candidate"),
        CheckConstraint("state IN ('pending','claimed','sent','failed','skipped','delivery_unknown')",
                        name="ck_vacancy_notification_state"),
        Index("ix_vacancy_notification_due", "state", "available_at"),
        Index("ix_vacancy_notification_attempt", "last_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("vacancy_notification_events.id"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    recipient: Mapped[str] = mapped_column(String(320))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    outcome: Mapped[str | None] = mapped_column(String(24))


class VacancySmtpBudget(Base):
    __tablename__ = "vacancy_smtp_budget"
    __table_args__ = (
        CheckConstraint("id = 1 AND reservations >= 0", name="ck_vacancy_smtp_budget_singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_day: Mapped[date] = mapped_column(Date)
    reservations: Mapped[int] = mapped_column(default=0)
    auth_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecruiterSummary(Base):
    __tablename__ = "recruiter_summaries"
    __table_args__ = (
        UniqueConstraint("organization_id", "run_date", name="uq_recruiter_summary_org_date"),
        CheckConstraint("state IN ('pending','claimed','sent','failed','unknown')", name="ck_recruiter_summary_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    run_date: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    recipients: Mapped[list] = mapped_column(JSON, nullable=False)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CVScreening(Base):
    __tablename__ = "cv_screenings"
    __table_args__ = (
        CheckConstraint("state IN ('queued','extracting','ready','dispatching','accepted','unknown','failed')", name="ck_cv_screening_state"),
        CheckConstraint("extraction_attempts BETWEEN 0 AND 3", name="ck_cv_screening_attempts"),
        CheckConstraint("notification_state IS NULL OR notification_state IN ('claimed','sent','failed','unknown')", name="ck_cv_notification_state"),
    )
    application_id: Mapped[str] = mapped_column(ForeignKey("job_applications.id", ondelete="RESTRICT"), primary_key=True)
    dispatch_id: Mapped[str] = mapped_column(String(36), default=new_id, unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    extraction_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generation_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile: Mapped[dict | None] = mapped_column(JSON)
    match_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_id: Mapped[str | None] = mapped_column(ForeignKey("recruiter_summaries.id", ondelete="RESTRICT"), index=True)
    cv_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(16))
    notification_state: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (Index("ix_assessment_org_created", "organization_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_multiple_attempts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list["Question"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", order_by="Question.position"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    function_name: Mapped[str] = mapped_column(String(100), nullable=False)
    starter_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assessment: Mapped[Assessment] = relationship(back_populates="questions")
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="TestCase.position"
    )


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    input_args: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    expected_output: Mapped[object] = mapped_column(JSON, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    question: Mapped[Question] = relationship(back_populates="test_cases")


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("assessment_id", "email", name="uq_invitation_assessment_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (Index("ix_attempt_candidate_assessment", "candidate_id", "assessment_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_submission_attempt_question"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    execution_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    execution_results: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)

    report: Mapped["EvaluationReport | None"] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )


class EvaluationReport(Base):
    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), unique=True)
    overall_score: Mapped[float | None] = mapped_column(Float)
    criteria: Mapped[dict[str, object] | None] = mapped_column(JSON)
    strengths: Mapped[list[str] | None] = mapped_column(JSON)
    weaknesses: Mapped[list[str] | None] = mapped_column(JSON)
    final_summary: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submission: Mapped[Submission] = relationship(back_populates="report")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
