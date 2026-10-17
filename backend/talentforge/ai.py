import asyncio
import logging
from typing import Any

from talentforge.config import get_settings
from talentforge.schemas import EvaluationOutput

logger = logging.getLogger(__name__)


async def evaluate_submission(
    role: str,
    task: str,
    code: str,
    explanation: str,
    execution_results: list[dict[str, Any]],
) -> tuple[EvaluationOutput | None, str]:
    settings = get_settings()
    if not settings.ai_enabled:
        return None, "AI evaluation is disabled; enable AI_ENABLED and configure Ollama to evaluate."

    passed = sum(bool(result.get("passed")) for result in execution_results)
    total = len(execution_results)
    evidence = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "execution_status": "completed",
    }
    retrieval_limitations: list[str] = []

    def run_existing_evaluator() -> tuple[object, list[str]]:
        from app.candidate import Candidate
        from app.evaluator import AIEvaluator

        retrieval_context: list[dict[str, Any]] = []
        graph_context: dict[str, Any] = {}
        if settings.retrieval_enabled:
            try:
                from app.hybrid_retriever import HybridRetriever

                retrieval_context = HybridRetriever().retrieve(
                    f"Assess this {role} solution for {task}; correctness, code quality, and algorithm efficiency.",
                    top_k=3,
                )
            except Exception as error:
                logger.warning("Hybrid retrieval unavailable for submission evaluation (%s).", type(error).__name__)
                retrieval_limitations.append("Hybrid retrieval context was unavailable.")
            try:
                from app.graph_retriever import GraphRetriever

                graph_context = GraphRetriever().retrieve_for_candidate(role, task)
            except Exception as error:
                logger.warning("Graph retrieval unavailable for submission evaluation (%s).", type(error).__name__)
                retrieval_limitations.append("Graph retrieval context was unavailable.")
        else:
            retrieval_limitations.append("Hybrid and graph retrieval were disabled.")

        candidate = Candidate(
            candidate_id="submission",
            name="Candidate",
            role=role,
            task=task,
            code=code[:20_000],
            test_results=evidence,
            explanation=explanation[:20_000],
        )
        return (
            AIEvaluator().evaluate(
                candidate,
                retrieved_context=retrieval_context,
                graph_context=graph_context,
            ),
            retrieval_limitations,
        )

    try:
        raw, retrieval_limitations = await asyncio.wait_for(
            asyncio.to_thread(run_existing_evaluator),
            timeout=settings.ai_timeout_seconds,
        )
        report = EvaluationOutput.model_validate(raw)
        report.criteria["correctness"].score = round((passed / total) * 10) if total else 0
        report.criteria["correctness"].evidence = (
            f"Server-verified automated tests: {passed}/{total} passed. "
            "This result is authoritative; AI-generated assertions do not replace it."
        )
        report.overall_score = round(sum(item.score for item in report.criteria.values()) / 5, 2)
        return report, "; ".join(retrieval_limitations)
    except (TimeoutError, ValueError, TypeError) as error:
        logger.warning("AI evaluation did not produce a valid report: %s", type(error).__name__)
        return None, f"AI evaluation failed validation or timed out ({type(error).__name__})."
    except ModuleNotFoundError as error:
        missing_module = error.name or "unknown"
        logger.warning(
            "AI evaluation service is unavailable: missing Python module %s",
            missing_module,
        )
        return None, f"AI evaluation unavailable (missing Python module: {missing_module})."
    except Exception as error:
        logger.warning("AI evaluation service is unavailable: %s", type(error).__name__)
        return None, f"AI evaluation unavailable ({type(error).__name__})."
