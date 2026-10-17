import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from talentforge.ai import evaluate_submission
from talentforge.config import get_settings
from talentforge.database import get_db
from talentforge.models import (
    Assessment,
    Attempt,
    AuditEvent,
    EvaluationReport,
    Invitation,
    Organization,
    Question,
    Submission,
    TestCase,
    User,
    utcnow,
)
from talentforge.sandbox import CaseResult, RemoteSandbox, Sandbox, SandboxUnavailable
from talentforge.schemas import (
    AcceptInvitationRequest,
    AssessmentCreate,
    AssessmentUpdate,
    AssessmentView,
    AuthResponse,
    EvaluationReportView,
    InvitationCreate,
    InvitationView,
    LoginRequest,
    QuestionCreate,
    QuestionUpdate,
    RegisterRequest,
    RunRequest,
    SubmissionRequest,
    SubmissionView,
    UserView,
)
from talentforge.security import (
    create_invitation_token,
    decode_token,
    hash_password,
    hash_token,
    issue_token,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter()
bearer = HTTPBearer(auto_error=False)
Db = Annotated[Session, Depends(get_db)]


def get_sandbox() -> Sandbox:
    return RemoteSandbox()


SandboxDependency = Annotated[Sandbox, Depends(get_sandbox)]


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Db,
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        claims = decode_token(credentials.credentials)
        user_id = claims.get("sub")
        version = claims.get("ver")
        user = db.get(User, user_id) if isinstance(user_id, str) else None
        if user is None or version != user.token_version:
            raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
        return user
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.") from None


UserDependency = Annotated[User, Depends(current_user)]


def require_role(*roles: str) -> Callable[..., User]:
    def dependency(user: UserDependency) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="This account is not permitted to perform this action.")
        return user

    return dependency


def _audit(db: Session, actor: User | None, action: str, entity_type: str, entity_id: str) -> None:
    db.add(AuditEvent(
        organization_id=actor.organization_id if actor else None,
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    ))


def _org_assessment(db: Session, assessment_id: str, recruiter: User) -> Assessment:
    assessment = db.scalar(select(Assessment).where(
        Assessment.id == assessment_id,
        Assessment.organization_id == recruiter.organization_id,
    ).options(joinedload(Assessment.questions).joinedload(Question.test_cases)))
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return assessment


def _question_view(question: Question, show_hidden: bool) -> dict[str, Any]:
    return {
        "id": question.id,
        "position": question.position,
        "title": question.title,
        "prompt": question.prompt,
        "function_name": question.function_name,
        "starter_code": question.starter_code,
        "test_cases": [
            {
                "input_args": case.input_args,
                "expected_output": case.expected_output if show_hidden or not case.is_hidden else None,
                "is_hidden": case.is_hidden if show_hidden else False,
            }
            for case in question.test_cases
            if show_hidden or not case.is_hidden
        ],
    }


def _assessment_view(assessment: Assessment, show_hidden: bool = False) -> dict[str, Any]:
    return {
        "id": assessment.id,
        "title": assessment.title,
        "role": assessment.role,
        "instructions": assessment.instructions,
        "time_limit_minutes": assessment.time_limit_minutes,
        "allow_multiple_attempts": assessment.allow_multiple_attempts,
        "is_published": assessment.is_published,
        "created_at": assessment.created_at,
        "published_at": assessment.published_at,
        "questions": [_question_view(question, show_hidden) for question in assessment.questions],
    }


def _load_question(db: Session, assessment_id: str, question_id: str) -> Question:
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.assessment_id == assessment_id)
        .options(joinedload(Question.test_cases))
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    return question


def _set_test_cases(question: Question, case_inputs: list[Any]) -> None:
    question.test_cases.clear()
    for index, case in enumerate(case_inputs):
        question.test_cases.append(TestCase(
            position=index,
            input_args=case.input_args,
            expected_output=case.expected_output,
            is_hidden=case.is_hidden,
        ))


def _serialize_results(results: list[CaseResult]) -> list[dict[str, object]]:
    return [
        {"passed": result.passed, "status": result.status, "message": result.message, "duration_ms": result.duration_ms}
        for result in results
    ]


def _candidate_submission_view(db: Session, submission: Submission) -> dict[str, Any]:
    question = db.get(Question, submission.question_id)
    visible_count = sum(1 for case in question.test_cases if not case.is_hidden) if question else 0
    return {
        "id": submission.id,
        "attempt_id": submission.attempt_id,
        "question_id": submission.question_id,
        "submitted_at": submission.submitted_at,
        "execution_status": submission.execution_status,
        "execution_results": submission.execution_results[:visible_count],
        "evaluation_status": submission.evaluation_status,
    }


def _run_cases(sandbox: Sandbox, code: str, question: Question, cases: list[TestCase]) -> list[dict[str, object]]:
    if len(code) > get_settings().sandbox_max_code_chars:
        raise HTTPException(status_code=413, detail="Submitted code exceeds the configured size limit.")
    try:
        return _serialize_results(sandbox.run(code, question.function_name, [
            {"input_args": case.input_args, "expected_output": case.expected_output}
            for case in cases
        ]))
    except SandboxUnavailable as error:
        raise HTTPException(status_code=503, detail={"code": "sandbox_unavailable", "message": str(error)}) from error


def _complete_attempt_if_ready(db: Session, attempt: Attempt, assessment: Assessment) -> None:
    all_questions_submitted = all(
        db.scalar(select(Submission.id).where(
            Submission.attempt_id == attempt.id,
            Submission.question_id == question.id,
        )) is not None
        for question in assessment.questions
    )
    if all_questions_submitted:
        attempt.completed_at = utcnow()


async def _evaluate_saved_submission(
    db: Session,
    submission: Submission,
    attempt: Attempt,
    assessment: Assessment,
    question: Question,
) -> None:
    submission.evaluation_status = "running"
    db.commit()
    evaluation, limitation = await evaluate_submission(
        assessment.role,
        question.title + "\n" + question.prompt,
        submission.code,
        submission.explanation,
        submission.execution_results,
    )
    report = submission.report
    if report is None:
        report = EvaluationReport(submission_id=submission.id)
        db.add(report)
    report.status = (
        "completed" if evaluation is not None
        else "skipped" if limitation.startswith("AI evaluation is disabled")
        else "failed"
    )
    report.limitations = limitation
    report.overall_score = evaluation.overall_score if evaluation else None
    report.criteria = {key: value.model_dump() for key, value in evaluation.criteria.items()} if evaluation else None
    report.strengths = evaluation.strengths if evaluation else None
    report.weaknesses = evaluation.weaknesses if evaluation else None
    report.final_summary = evaluation.final_summary if evaluation else None
    submission.evaluation_status = report.status
    _complete_attempt_if_ready(db, attempt, assessment)
    db.commit()


def _ensure_open_attempt(attempt: Attempt) -> None:
    now = utcnow()
    deadline = attempt.deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if attempt.completed_at is not None or now > deadline:
        raise HTTPException(status_code=409, detail="Assessment deadline has passed or attempt is already completed.")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Db) -> AuthResponse:
    organization = Organization(name=payload.organization_name.strip())
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="recruiter",
        organization=organization,
    )
    db.add(user)
    try:
        db.flush()
        _audit(db, user, "recruiter.registered", "user", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account or organization with those details already exists.") from None
    db.refresh(user)
    return AuthResponse(access_token=issue_token(user.id, user.token_version), user=UserView.model_validate(user))


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Db) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return AuthResponse(access_token=issue_token(user.id, user.token_version), user=UserView.model_validate(user))


@router.post("/auth/logout", status_code=204)
def logout(user: UserDependency, db: Db) -> None:
    user.token_version += 1
    _audit(db, user, "user.logged_out", "user", user.id)
    db.commit()


@router.get("/auth/me", response_model=UserView)
def me(user: UserDependency) -> User:
    return user


@router.post("/invitations/accept", response_model=AuthResponse, status_code=201)
def accept_invitation(payload: AcceptInvitationRequest, db: Db) -> AuthResponse:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(payload.token)))
    now = utcnow()
    if invitation is None or invitation.revoked_at or invitation.accepted_at:
        raise HTTPException(status_code=400, detail="Invitation is invalid, revoked, or already used.")
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="Invitation has expired.")
    existing_user = db.scalar(select(User).where(User.email == invitation.email))
    if existing_user is not None:
        if existing_user.role != "candidate" or not verify_password(payload.password, existing_user.password_hash):
            raise HTTPException(status_code=401, detail="An account already exists; sign in with that candidate account.")
        invitation.accepted_at = now
        invitation.candidate_id = existing_user.id
        organization_id = db.scalar(select(Assessment.organization_id).where(Assessment.id == invitation.assessment_id))
        db.add(AuditEvent(
            organization_id=organization_id,
            actor_id=existing_user.id,
            action="invitation.accepted",
            entity_type="invitation",
            entity_id=invitation.id,
        ))
        db.commit()
        return AuthResponse(
            access_token=issue_token(existing_user.id, existing_user.token_version),
            user=UserView.model_validate(existing_user),
        )
    user = User(
        email=invitation.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="candidate",
    )
    db.add(user)
    db.flush()
    invitation.accepted_at = now
    invitation.candidate_id = user.id
    organization_id = db.scalar(select(Assessment.organization_id).where(Assessment.id == invitation.assessment_id))
    db.add(AuditEvent(
        organization_id=organization_id,
        actor_id=user.id,
        action="invitation.accepted",
        entity_type="invitation",
        entity_id=invitation.id,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account already exists for this email.") from None
    db.refresh(user)
    return AuthResponse(access_token=issue_token(user.id, user.token_version), user=UserView.model_validate(user))


@router.post("/assessments", response_model=AssessmentView, status_code=201)
def create_assessment(
    payload: AssessmentCreate,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = Assessment(
        organization_id=recruiter.organization_id,
        created_by_id=recruiter.id,
        title=payload.title.strip(),
        role=payload.role,
        instructions=payload.instructions,
        time_limit_minutes=payload.time_limit_minutes,
        allow_multiple_attempts=payload.allow_multiple_attempts,
    )
    db.add(assessment)
    try:
        db.flush()
        _audit(db, recruiter, "assessment.created", "assessment", assessment.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Assessment could not be saved.") from None
    return _assessment_view(assessment, show_hidden=True)


@router.get("/assessments", response_model=list[AssessmentView])
def list_assessments(
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> list[dict[str, Any]]:
    rows = db.scalars(select(Assessment).where(Assessment.organization_id == recruiter.organization_id)
        .options(joinedload(Assessment.questions).joinedload(Question.test_cases))
        .order_by(Assessment.created_at.desc())).unique().all()
    return [_assessment_view(row, show_hidden=True) for row in rows]


@router.get("/assessments/{assessment_id}", response_model=AssessmentView)
def get_assessment(
    assessment_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    return _assessment_view(_org_assessment(db, assessment_id, recruiter), show_hidden=True)


@router.patch("/assessments/{assessment_id}", response_model=AssessmentView)
def update_assessment(
    assessment_id: str,
    payload: AssessmentUpdate,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = _org_assessment(db, assessment_id, recruiter)
    if assessment.is_published:
        raise HTTPException(status_code=409, detail="Published assessments cannot be edited.")
    for key, value in payload.model_dump().items():
        setattr(assessment, key, value)
    _audit(db, recruiter, "assessment.updated", "assessment", assessment.id)
    db.commit()
    return _assessment_view(assessment, show_hidden=True)


@router.post("/assessments/{assessment_id}/questions", response_model=AssessmentView, status_code=201)
def add_question(
    assessment_id: str,
    payload: QuestionCreate,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = _org_assessment(db, assessment_id, recruiter)
    if assessment.is_published:
        raise HTTPException(status_code=409, detail="Published assessments cannot be edited.")
    question = Question(
        position=payload.position, title=payload.title.strip(), prompt=payload.prompt,
        function_name=payload.function_name, starter_code=payload.starter_code,
    )
    _set_test_cases(question, payload.test_cases)
    assessment.questions.append(question)
    db.flush()
    _audit(db, recruiter, "question.created", "question", question.id)
    db.commit()
    return _assessment_view(_org_assessment(db, assessment_id, recruiter), show_hidden=True)


@router.patch("/assessments/{assessment_id}/questions/{question_id}", response_model=AssessmentView)
def update_question(
    assessment_id: str,
    question_id: str,
    payload: QuestionUpdate,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = _org_assessment(db, assessment_id, recruiter)
    if assessment.is_published:
        raise HTTPException(status_code=409, detail="Published assessments cannot be edited.")
    question = _load_question(db, assessment_id, question_id)
    values = payload.model_dump(exclude_unset=True)
    cases = values.pop("test_cases", None)
    for key, value in values.items():
        setattr(question, key, value)
    if cases is not None:
        _set_test_cases(question, cases)
    _audit(db, recruiter, "question.updated", "question", question.id)
    db.commit()
    return _assessment_view(_org_assessment(db, assessment_id, recruiter), show_hidden=True)


@router.post("/assessments/{assessment_id}/publish", response_model=AssessmentView)
def publish_assessment(
    assessment_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = _org_assessment(db, assessment_id, recruiter)
    if assessment.is_published:
        return _assessment_view(assessment, show_hidden=True)
    if not assessment.questions:
        raise HTTPException(status_code=422, detail="Add at least one coding question before publication.")
    if any(not question.test_cases or not any(not case.is_hidden for case in question.test_cases)
           or not any(case.is_hidden for case in question.test_cases) for question in assessment.questions):
        raise HTTPException(status_code=422, detail="Every question needs both visible and hidden test cases.")
    assessment.is_published = True
    assessment.published_at = utcnow()
    _audit(db, recruiter, "assessment.published", "assessment", assessment.id)
    db.commit()
    return _assessment_view(assessment, show_hidden=True)


@router.post("/assessments/{assessment_id}/invitations", response_model=InvitationView, status_code=201)
def create_invitation(
    assessment_id: str,
    payload: InvitationCreate,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> dict[str, Any]:
    assessment = _org_assessment(db, assessment_id, recruiter)
    if not assessment.is_published:
        raise HTTPException(status_code=409, detail="Publish the assessment before inviting candidates.")
    raw_token = create_invitation_token()
    invitation = Invitation(
        assessment_id=assessment.id,
        email=payload.email.lower(),
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(hours=get_settings().invitation_expiry_hours),
    )
    db.add(invitation)
    _audit(db, recruiter, "invitation.created", "assessment", assessment.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This email has already been invited to the assessment.") from None
    return {
        "id": invitation.id,
        "assessment_id": invitation.assessment_id,
        "email": invitation.email,
        "expires_at": invitation.expires_at,
        "revoked_at": None,
        "accepted_at": None,
        "invitation_url": f"/accept-invitation?token={raw_token}",
    }


@router.get("/assessments/{assessment_id}/invitations", response_model=list[InvitationView])
def list_invitations(
    assessment_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> list[dict[str, Any]]:
    _org_assessment(db, assessment_id, recruiter)
    rows = db.scalars(select(Invitation).where(Invitation.assessment_id == assessment_id)
        .order_by(Invitation.expires_at.desc())).all()
    return [InvitationView.model_validate(row).model_dump() for row in rows]


@router.post("/assessments/{assessment_id}/invitations/{invitation_id}/revoke", status_code=204)
def revoke_invitation(
    assessment_id: str,
    invitation_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
) -> None:
    _org_assessment(db, assessment_id, recruiter)
    invitation = db.scalar(select(Invitation).where(
        Invitation.id == invitation_id, Invitation.assessment_id == assessment_id))
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    invitation.revoked_at = utcnow()
    _audit(db, recruiter, "invitation.revoked", "invitation", invitation.id)
    db.commit()


@router.get("/candidate/assessments", response_model=list[AssessmentView])
def candidate_assessments(
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> list[dict[str, Any]]:
    invitations = db.scalars(select(Invitation).where(
        Invitation.candidate_id == candidate.id, Invitation.accepted_at.is_not(None),
        Invitation.revoked_at.is_(None),
    )).all()
    assessments = []
    for invite in invitations:
        assessment = db.scalar(select(Assessment).where(
            Assessment.id == invite.assessment_id, Assessment.is_published.is_(True),
        ).options(joinedload(Assessment.questions).joinedload(Question.test_cases)))
        if assessment is not None:
            assessments.append(_assessment_view(assessment, show_hidden=False))
    return assessments


@router.get("/candidate/attempts", response_model=list[dict])
def candidate_attempts(
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> list[dict[str, Any]]:
    attempts = db.scalars(select(Attempt).where(
        Attempt.candidate_id == candidate.id,
    ).order_by(Attempt.started_at.desc())).all()
    return [
        {
            "id": attempt.id,
            "assessment_id": attempt.assessment_id,
            "deadline_at": attempt.deadline_at,
            "completed_at": attempt.completed_at,
        }
        for attempt in attempts
    ]


@router.post("/candidate/assessments/{assessment_id}/attempts", response_model=dict, status_code=201)
def start_attempt(
    assessment_id: str,
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> dict[str, Any]:
    invitation = db.scalar(select(Invitation).where(
        Invitation.assessment_id == assessment_id, Invitation.candidate_id == candidate.id,
        Invitation.accepted_at.is_not(None), Invitation.revoked_at.is_(None),
    ))
    assessment = db.scalar(select(Assessment).where(
        Assessment.id == assessment_id, Assessment.is_published.is_(True),
    ).options(joinedload(Assessment.questions).joinedload(Question.test_cases)))
    if invitation is None or assessment is None:
        raise HTTPException(status_code=404, detail="Authorized assessment not found.")
    existing = db.scalars(select(Attempt).where(
        Attempt.assessment_id == assessment_id, Attempt.candidate_id == candidate.id,
    )).all()
    if existing:
        if not assessment.allow_multiple_attempts:
            raise HTTPException(status_code=409, detail="An attempt has already been started for this assessment.")
        if any(attempt.completed_at is None and _deadline_active(attempt.deadline_at) for attempt in existing):
            raise HTTPException(status_code=409, detail="An active attempt already exists.")
    attempt = Attempt(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        deadline_at=utcnow() + timedelta(minutes=assessment.time_limit_minutes),
    )
    db.add(attempt)
    db.flush()
    db.add(AuditEvent(
        organization_id=assessment.organization_id,
        actor_id=candidate.id,
        action="attempt.started",
        entity_type="attempt",
        entity_id=attempt.id,
    ))
    db.commit()
    return {
        "id": attempt.id,
        "assessment_id": attempt.assessment_id,
        "started_at": attempt.started_at,
        "deadline_at": attempt.deadline_at,
        "completed_at": attempt.completed_at,
        "server_time": utcnow(),
        "submissions": [],
        "assessment": _assessment_view(assessment, show_hidden=False),
    }


def _deadline_active(deadline: datetime) -> bool:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > utcnow()


def _candidate_attempt(db: Session, attempt_id: str, candidate: User) -> tuple[Attempt, Assessment]:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.candidate_id != candidate.id:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    assessment = db.scalar(select(Assessment).where(Assessment.id == attempt.assessment_id)
        .options(joinedload(Assessment.questions).joinedload(Question.test_cases)))
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return attempt, assessment


@router.get("/candidate/attempts/{attempt_id}", response_model=dict)
def get_attempt(
    attempt_id: str,
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> dict[str, Any]:
    attempt, assessment = _candidate_attempt(db, attempt_id, candidate)
    return {
        "id": attempt.id,
        "assessment_id": assessment.id,
        "started_at": attempt.started_at,
        "deadline_at": attempt.deadline_at,
        "completed_at": attempt.completed_at,
        "server_time": utcnow(),
        "submissions": [
            {
                "id": submission.id,
                "question_id": submission.question_id,
                "execution_status": submission.execution_status,
                "evaluation_status": submission.evaluation_status,
            }
            for submission in db.scalars(select(Submission).where(Submission.attempt_id == attempt.id)).all()
        ],
        "assessment": _assessment_view(assessment, show_hidden=False),
    }


@router.post("/candidate/attempts/{attempt_id}/run-samples", response_model=list[dict[str, Any]])
def run_samples(
    attempt_id: str,
    payload: RunRequest,
    db: Db,
    sandbox: SandboxDependency,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> list[dict[str, Any]]:
    attempt, _ = _candidate_attempt(db, attempt_id, candidate)
    _ensure_open_attempt(attempt)
    question = _load_question(db, attempt.assessment_id, payload.question_id)
    cases = [case for case in question.test_cases if not case.is_hidden]
    if not cases:
        raise HTTPException(status_code=422, detail="No visible sample cases are configured.")
    return _run_cases(sandbox, payload.code, question, cases)


@router.post("/candidate/attempts/{attempt_id}/submissions", response_model=SubmissionView, status_code=201)
async def submit_solution(
    attempt_id: str,
    payload: SubmissionRequest,
    db: Db,
    sandbox: SandboxDependency,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> Submission:
    attempt, assessment = _candidate_attempt(db, attempt_id, candidate)
    _ensure_open_attempt(attempt)
    question = _load_question(db, assessment.id, payload.question_id)
    previous = db.scalar(select(Submission).where(
        Submission.attempt_id == attempt.id, Submission.question_id == question.id))
    if previous is not None:
        raise HTTPException(status_code=409, detail="A final submission already exists for this question.")
    settings = get_settings()
    if len(payload.code) > settings.sandbox_max_code_chars:
        raise HTTPException(status_code=413, detail="Submitted code exceeds the configured size limit.")
    submission = Submission(
        attempt_id=attempt.id,
        question_id=question.id,
        code=payload.code,
        explanation=payload.explanation,
    )
    db.add(submission)
    try:
        db.flush()
        db.add(AuditEvent(
            organization_id=assessment.organization_id,
            actor_id=candidate.id,
            action="submission.created",
            entity_type="submission",
            entity_id=submission.id,
        ))
        _complete_attempt_if_ready(db, attempt, assessment)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A final submission already exists for this question.") from None
    db.refresh(submission)

    try:
        execution_results = _run_cases(sandbox, payload.code, question, question.test_cases)
        submission.execution_results = execution_results
        submission.execution_status = "completed"
    except HTTPException as error:
        if error.status_code != 503:
            raise
        submission.execution_status = "sandbox_unavailable"
        submission.execution_results = [{"passed": False, "status": "sandbox_unavailable", "message": error.detail}]
        submission.evaluation_status = "skipped"
        report = EvaluationReport(
            submission_id=submission.id,
            status="skipped",
            limitations="Execution did not run because the Docker sandbox was unavailable.",
        )
        db.add(report)
        db.commit()
        db.refresh(submission)
        return _candidate_submission_view(db, submission)

    submission.evaluation_status = "running"
    db.commit()
    await _evaluate_saved_submission(db, submission, attempt, assessment, question)
    db.refresh(submission)
    return _candidate_submission_view(db, submission)


@router.get("/candidate/submissions/{submission_id}", response_model=SubmissionView)
def get_candidate_submission(
    submission_id: str,
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> dict[str, Any]:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    attempt = db.get(Attempt, submission.attempt_id)
    if attempt is None or attempt.candidate_id != candidate.id:
        raise HTTPException(status_code=404, detail="Submission not found.")
    return _candidate_submission_view(db, submission)


@router.post("/candidate/submissions/{submission_id}/retry-execution", response_model=SubmissionView)
async def retry_submission_execution(
    submission_id: str,
    db: Db,
    sandbox: SandboxDependency,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> dict[str, Any]:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    attempt, assessment = _candidate_attempt(db, submission.attempt_id, candidate)
    if submission.execution_status not in {"pending", "sandbox_unavailable"}:
        raise HTTPException(status_code=409, detail="This submission does not need execution retry.")
    question = _load_question(db, assessment.id, submission.question_id)
    try:
        submission.execution_results = _run_cases(sandbox, submission.code, question, question.test_cases)
    except HTTPException as error:
        if error.status_code != 503:
            raise
        submission.execution_status = "sandbox_unavailable"
        if submission.report is not None:
            submission.report.limitations = "Execution retry failed because the Docker sandbox is unavailable."
        db.commit()
        raise
    submission.execution_status = "completed"
    db.commit()
    await _evaluate_saved_submission(db, submission, attempt, assessment, question)
    db.refresh(submission)
    return _candidate_submission_view(db, submission)


@router.post("/candidate/submissions/{submission_id}/retry-evaluation", response_model=SubmissionView)
async def retry_submission_evaluation(
    submission_id: str,
    db: Db,
    candidate: Annotated[User, Depends(require_role("candidate"))],
) -> dict[str, Any]:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    attempt, assessment = _candidate_attempt(db, submission.attempt_id, candidate)
    if submission.execution_status != "completed":
        raise HTTPException(status_code=409, detail="Evaluation requires completed sandbox execution.")
    if submission.evaluation_status == "completed":
        raise HTTPException(status_code=409, detail="This submission already has a completed evaluation.")
    question = _load_question(db, assessment.id, submission.question_id)
    await _evaluate_saved_submission(db, submission, attempt, assessment, question)
    db.refresh(submission)
    return _candidate_submission_view(db, submission)


def _report_dict(submission: Submission, attempt: Attempt, question: Question, candidate: User) -> dict[str, Any]:
    report = submission.report
    return {
        "submission_id": submission.id,
        "candidate_id": candidate.id,
        "candidate_email": candidate.email,
        "candidate_name": candidate.full_name,
        "assessment_id": attempt.assessment_id,
        "overall_score": report.overall_score if report else None,
        "criteria": report.criteria if report else None,
        "strengths": report.strengths if report else None,
        "weaknesses": report.weaknesses if report else None,
        "final_summary": report.final_summary if report else None,
        "execution_status": submission.execution_status,
        "execution_results": submission.execution_results,
        "evaluation_status": submission.evaluation_status,
        "limitations": report.limitations if report else "Evaluation report is not available.",
        "question_title": question.title,
    }


@router.get("/assessments/{assessment_id}/reports", response_model=list[EvaluationReportView])
def assessment_reports(
    assessment_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    _org_assessment(db, assessment_id, recruiter)
    rows = db.execute(
        select(Submission, Attempt, Question, User)
        .join(Attempt, Attempt.id == Submission.attempt_id)
        .join(Question, Question.id == Submission.question_id)
        .join(User, User.id == Attempt.candidate_id)
        .where(Attempt.assessment_id == assessment_id)
        .order_by(Submission.submitted_at.desc())
        .offset(offset).limit(limit)
    ).all()
    return [_report_dict(*row) for row in rows]


@router.get("/assessments/{assessment_id}/compare", response_model=list[EvaluationReportView])
def compare_candidates(
    assessment_id: str,
    db: Db,
    recruiter: Annotated[User, Depends(require_role("recruiter"))],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    _org_assessment(db, assessment_id, recruiter)
    rows = db.execute(
        select(Submission, Attempt, Question, User)
        .join(Attempt, Attempt.id == Submission.attempt_id)
        .join(Question, Question.id == Submission.question_id)
        .join(User, User.id == Attempt.candidate_id)
        .where(Attempt.assessment_id == assessment_id)
        .order_by(Submission.submitted_at.desc())
        .offset(offset).limit(limit)
    ).all()
    reports = [_report_dict(*row) for row in rows]
    return sorted(reports, key=lambda item: item["overall_score"] if item["overall_score"] is not None else -1, reverse=True)
