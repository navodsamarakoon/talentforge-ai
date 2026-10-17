import asyncio
import logging
import sys
from types import ModuleType, SimpleNamespace

from talentforge.ai import evaluate_submission


def test_existing_evaluator_uses_execution_evidence_and_validates_output(monkeypatch):
    settings = SimpleNamespace(ai_enabled=True, retrieval_enabled=False, ai_timeout_seconds=2)
    monkeypatch.setattr("talentforge.ai.get_settings", lambda: settings)
    candidate_data = {}

    class Candidate:
        def __init__(self, **kwargs):
            candidate_data.update(kwargs)

    criteria_names = {"correctness", "problem_solving", "code_quality", "efficiency", "explanation"}
    valid_output = {
        "criteria": {name: {"score": 8, "evidence": "The submission shows this."} for name in criteria_names},
        "overall_score": 8,
        "strengths": ["Clear solution."],
        "weaknesses": [],
        "final_summary": "The candidate provides a clear, tested solution.",
        "final_verdict": "Good",
    }

    class Evaluator:
        def evaluate(self, candidate, retrieved_context, graph_context):
            return valid_output

    candidate_module = ModuleType("app.candidate")
    candidate_module.Candidate = Candidate
    evaluator_module = ModuleType("app.evaluator")
    evaluator_module.AIEvaluator = Evaluator
    monkeypatch.setitem(sys.modules, "app.candidate", candidate_module)
    monkeypatch.setitem(sys.modules, "app.evaluator", evaluator_module)

    report, limitation = asyncio.run(evaluate_submission(
        "Software Engineer",
        "Return a value",
        "def solve(): return 1",
        "A short explanation.",
        [
            {"passed": True, "status": "passed"},
            {"passed": False, "status": "failed"},
        ],
    ))

    assert report is not None
    assert report.criteria["correctness"].score == 5
    assert report.criteria["correctness"].evidence.startswith("Server-verified automated tests: 1/2 passed.")
    assert report.overall_score == 7.4
    assert report.final_summary == valid_output["final_summary"]
    assert candidate_data["test_results"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "execution_status": "completed",
    }
    assert limitation == "Hybrid and graph retrieval were disabled."

    class MalformedEvaluator:
        def evaluate(self, candidate, retrieved_context, graph_context):
            return {"overall_score": "not a number"}

    evaluator_module.AIEvaluator = MalformedEvaluator
    invalid, limitation = asyncio.run(evaluate_submission(
        "Software Engineer", "Task", "code", "", [{"passed": True}],
    ))
    assert invalid is None
    assert "failed validation" in limitation


def test_missing_ai_dependency_names_module_without_logging_exception_details(monkeypatch, caplog):
    settings = SimpleNamespace(ai_enabled=True, retrieval_enabled=False, ai_timeout_seconds=2)
    monkeypatch.setattr("talentforge.ai.get_settings", lambda: settings)

    class Candidate:
        def __init__(self, **kwargs):
            pass

    class Evaluator:
        def evaluate(self, candidate, retrieved_context, graph_context):
            raise ModuleNotFoundError("No module named 'ollama'", name="ollama")

    candidate_module = ModuleType("app.candidate")
    candidate_module.Candidate = Candidate
    evaluator_module = ModuleType("app.evaluator")
    evaluator_module.AIEvaluator = Evaluator
    monkeypatch.setitem(sys.modules, "app.candidate", candidate_module)
    monkeypatch.setitem(sys.modules, "app.evaluator", evaluator_module)

    with caplog.at_level(logging.WARNING, logger="talentforge.ai"):
        report, limitation = asyncio.run(evaluate_submission(
            "Software Engineer", "Task", "code", "", [{"passed": True}],
        ))

    assert report is None
    assert limitation == "AI evaluation unavailable (missing Python module: ollama)."
    assert "missing Python module ollama" in caplog.text
    assert "No module named" not in caplog.text


def test_ollama_client_uses_configured_host_and_request_timeout(monkeypatch):
    ollama_module = ModuleType("ollama")
    ollama_module.Client = object
    langsmith_module = ModuleType("langsmith")
    langsmith_module.traceable = lambda **_kwargs: lambda function: function
    monkeypatch.setitem(sys.modules, "ollama", ollama_module)
    monkeypatch.setitem(sys.modules, "langsmith", langsmith_module)

    from app import evaluator as existing_evaluator

    client_settings = {}
    sentinel = object()

    class FakeClient:
        def __init__(self, host, timeout):
            client_settings.update(host=host, timeout=timeout)

        def chat(self, **_kwargs):
            return sentinel

    monkeypatch.setattr(existing_evaluator, "Client", FakeClient)
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama-service:11434")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "240")

    result = existing_evaluator.traced_ollama_chat("gemma3:4b", [], {}, {})

    assert result is sentinel
    assert client_settings == {
        "host": "http://ollama-service:11434",
        "timeout": 240.0,
    }


def test_outer_ai_timeout_is_reported_without_exception_details(monkeypatch, caplog):
    settings = SimpleNamespace(ai_enabled=True, retrieval_enabled=False, ai_timeout_seconds=270)
    monkeypatch.setattr("talentforge.ai.get_settings", lambda: settings)

    async def timed_out_to_thread(_function):
        raise TimeoutError

    monkeypatch.setattr("talentforge.ai.asyncio.to_thread", timed_out_to_thread)

    with caplog.at_level(logging.WARNING, logger="talentforge.ai"):
        report, limitation = asyncio.run(evaluate_submission(
            "Software Engineer", "Task", "code", "", [{"passed": True}],
        ))

    assert report is None
    assert limitation == "AI evaluation failed validation or timed out (TimeoutError)."
    assert "AI evaluation did not produce a valid report: TimeoutError" in caplog.text
