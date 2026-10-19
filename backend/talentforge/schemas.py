from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=128)


class UserView(ORMModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    organization_id: str | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserView


class TestCaseInput(BaseModel):
    input_args: list[Any]
    expected_output: Any
    is_hidden: bool = False


class QuestionInput(BaseModel):
    position: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20_000)
    function_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100)
    starter_code: str = Field(default="", max_length=20_000)
    test_cases: list[TestCaseInput] = Field(min_length=1, max_length=200)


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    role: Literal["Software Engineer", "Software Engineering Intern"]
    instructions: str = Field(default="", max_length=20_000)
    time_limit_minutes: int = Field(ge=5, le=480)
    allow_multiple_attempts: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Title must contain at least one non-whitespace character.")
        return normalized


class AssessmentUpdate(AssessmentCreate):
    pass


class QuestionCreate(QuestionInput):
    pass


class QuestionUpdate(BaseModel):
    position: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    function_name: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100)
    starter_code: str | None = Field(default=None, max_length=20_000)
    test_cases: list[TestCaseInput] | None = Field(default=None, min_length=1, max_length=200)


class TestCaseView(BaseModel):
    input_args: list[Any]
    expected_output: Any | None = None
    is_hidden: bool = False


class QuestionView(BaseModel):
    id: str
    position: int
    title: str
    prompt: str
    function_name: str
    starter_code: str
    test_cases: list[TestCaseView] = Field(default_factory=list)


class AssessmentView(BaseModel):
    id: str
    title: str
    role: str
    instructions: str
    time_limit_minutes: int
    allow_multiple_attempts: bool
    is_published: bool
    is_archived: bool
    has_candidate_records: bool = False
    created_at: datetime
    published_at: datetime | None
    questions: list[QuestionView] = Field(default_factory=list)


class InvitationCreate(BaseModel):
    email: EmailStr


class InvitationView(ORMModel):
    id: str
    assessment_id: str
    email: EmailStr
    expires_at: datetime
    revoked_at: datetime | None
    accepted_at: datetime | None
    invitation_url: str | None = None


class AttemptView(BaseModel):
    id: str
    assessment_id: str
    started_at: datetime
    deadline_at: datetime
    completed_at: datetime | None
    assessment: AssessmentView


class RunRequest(BaseModel):
    question_id: str
    code: str = Field(min_length=1, max_length=100_000)


class SubmissionRequest(RunRequest):
    explanation: str = Field(default="", max_length=20_000)


class TestResultView(BaseModel):
    passed: bool
    status: str
    message: str = ""
    duration_ms: int | None = None


class SubmissionView(BaseModel):
    id: str
    attempt_id: str
    question_id: str
    submitted_at: datetime
    execution_status: str
    execution_results: list[dict[str, Any]]
    evaluation_status: str


class EvaluationReportView(BaseModel):
    submission_id: str
    candidate_id: str
    candidate_email: EmailStr
    candidate_name: str
    assessment_id: str
    overall_score: float | None
    criteria: dict[str, Any] | None
    strengths: list[str] | None
    weaknesses: list[str] | None
    final_summary: str | None
    execution_status: str
    execution_results: list[dict[str, Any]]
    evaluation_status: str
    limitations: str
    question_title: str | None = None


class EvaluationCriteria(BaseModel):
    score: int = Field(ge=0, le=10)
    evidence: str = Field(max_length=4_000)


class EvaluationOutput(BaseModel):
    criteria: dict[str, EvaluationCriteria]
    overall_score: float = Field(ge=0, le=10)
    strengths: list[str]
    weaknesses: list[str]
    final_summary: str = Field(min_length=1, max_length=4_000)
    final_verdict: str

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, value: dict[str, EvaluationCriteria]) -> dict[str, EvaluationCriteria]:
        required = {"correctness", "problem_solving", "code_quality", "efficiency", "explanation"}
        if set(value) != required:
            raise ValueError("Evaluation must include all five rubric criteria.")
        return value
