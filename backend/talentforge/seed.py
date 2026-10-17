from sqlalchemy import select

from talentforge.database import SessionLocal
from talentforge.models import Assessment, Question, TestCase, User


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Assessment.id).limit(1)) is not None:
            print("Seed skipped: an assessment already exists.")
            return
        owner = db.scalar(select(User).where(User.role == "recruiter").order_by(User.created_at).limit(1))
        if owner is None or owner.organization_id is None:
            print("Seed skipped: register a recruiter account before seeding.")
            return
        assessment = Assessment(
            organization_id=owner.organization_id,
            created_by_id=owner.id,
            title="Python Fundamentals Sample",
            role="Software Engineer",
            instructions="Complete the Python function before the time limit.",
            time_limit_minutes=30,
        )
        question = Question(
            position=0,
            title="Pair Sum",
            prompt="Return the indices of two values that sum to the target.",
            function_name="pair_sum",
            starter_code="def pair_sum(values, target):\n    pass\n",
        )
        question.test_cases.extend([
            TestCase(position=0, input_args=[[2, 7, 11, 15], 9], expected_output=[0, 1], is_hidden=False),
            TestCase(position=1, input_args=[[3, 2, 4], 6], expected_output=[1, 2], is_hidden=True),
        ])
        assessment.questions.append(question)
        db.add(assessment)
        db.commit()
        print("Created a sample draft assessment (not published).")


if __name__ == "__main__":
    seed()
