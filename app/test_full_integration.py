from app.candidate import Candidate
from app.evaluator import AIEvaluator
from app.hybrid_retriever import HybridRetriever
from app.graph_retriever import GraphRetriever
from langsmith import tracing_context


def main():
    candidate = Candidate(
        candidate_id="INT001",
        name="Integration Test Candidate",
        role="Software Engineer",
        task="Two Sum",
        code="""
def two_sum(nums, target):
    seen = {}

    for i, num in enumerate(nums):
        complement = target - num

        if complement in seen:
            return [seen[complement], i]

        seen[num] = i

    return []
""",
        test_results="10/10 tests passed.",
        explanation=(
            "Uses a hash map to find the complement in O(n) "
            "average time and O(n) space."
        ),
    )

    print("Candidate created:", candidate.candidate_id)

    # Hybrid Search
    print("\nRunning Hybrid Search...")

    hybrid_retriever = HybridRetriever()

    query = """
    Evaluate the Two Sum solution for a Software Engineer.
    Consider correctness, problem solving, code quality,
    efficiency, and explanation.
    """

    hybrid_context = hybrid_retriever.retrieve(
        query,
        top_k=3
    )

    print(f"Hybrid results: {len(hybrid_context)}")

    for item in hybrid_context:
        print(f"- {item['source']}")

    # GraphRAG
    print("\nRunning GraphRAG...")

    graph_retriever = GraphRetriever()

    graph_context = graph_retriever.retrieve_for_candidate(
        role_name=candidate.role,
        task_name=candidate.task
    )

    print(
        "Role skills retrieved:",
        len(graph_context["role_skills"])
    )

    print(
        "Task knowledge retrieved:",
        len(graph_context["task_knowledge"])
    )

        # Full AI Evaluation
    print("\nRunning Full AI Evaluation...")

    evaluator = AIEvaluator()

    with tracing_context(
        metadata={
            "component": "full_integration_test",
            "candidate_id": candidate.candidate_id,
            "candidate_name": candidate.name,
            "role": candidate.role,
            "retrieval_type": "hybrid_plus_graph",
        }
    ):
        evaluation = evaluator.evaluate(
            candidate,
            hybrid_context,
            graph_context=graph_context,
        )

    print("\n" + "=" * 50)
    print("FULL INTEGRATION EVALUATION RESULT")
    print("=" * 50)

    print(f"Candidate: {candidate.name}")
    print(f"Overall Score: {evaluation['overall_score']}/10")
    print(f"Verdict: {evaluation['final_verdict']}")

    print("\nCriteria Scores:")
    for criterion, result in evaluation["criteria"].items():
        print(f"- {criterion}: {result['score']}/10")

    print("\nStrengths:")
    for item in evaluation["strengths"]:
        print(f"- {item}")

    print("\nWeaknesses:")
    for item in evaluation["weaknesses"]:
        print(f"- {item}")


if __name__ == "__main__":
    main()