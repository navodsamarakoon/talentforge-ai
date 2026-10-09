import json

from app.candidate import Candidate
from app.evaluator import AIEvaluator
from app.storage import save_evaluation, load_evaluation
from app.document_loader import load_all_documents
from app.graph_retriever import GraphRetriever
from app.hybrid_retriever import HybridRetriever

documents = load_all_documents()

print("\n")
print("=" * 60)
print("TALENTFORGE KNOWLEDGE BASE")
print("=" * 60)

print(f"Documents loaded: {len(documents)}")

for document in documents:

    print("\nSource:", document["source"])

    print(
        "Characters:",
        len(document["content"])
    )


def main():

    # ==========================================
    # SAMPLE CANDIDATE 1 — STRONG
    # ==========================================

    candidate_1 = Candidate(
        candidate_id="C001",
        name="Alice",
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

        test_results={
            "total": 10,
            "passed": 10,
            "failed": 0
        },

        explanation=(
            "I use a hash map to store previously seen numbers and "
            "their indices. For each number, I calculate the complement "
            "as target minus the current number. If the complement is "
            "already in the hash map, I return the two indices. "
            "This gives O(n) time complexity and O(n) space complexity."
        )
    )


    # ==========================================
    # SAMPLE CANDIDATE 2 — AVERAGE
    # ==========================================

    candidate_2 = Candidate(
        candidate_id="C002",
        name="Bob",
        role="Software Engineer",
        task="Two Sum",

        code="""
def two_sum(nums, target):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]

    return []
""",

        test_results={
            "total": 10,
            "passed": 10,
            "failed": 0
        },

        explanation=(
            "I compare every pair of numbers in the array. "
            "If two numbers add up to the target, I return their indices. "
            "This solution uses nested loops and has O(n^2) time complexity."
        )
    )


    # ==========================================
    # SAMPLE CANDIDATE 3 — WEAK
    # ==========================================

    candidate_3 = Candidate(
        candidate_id="C003",
        name="Charlie",
        role="Software Engineer",
        task="Two Sum",

        code="""
def two_sum(nums, target):
    if len(nums) < 2:
        return []

    if nums[0] + nums[1] == target:
        return [0, 1]

    return []
""",

        test_results={
            "total": 10,
            "passed": 3,
            "failed": 7
        },

        explanation=(
            "I check the first two numbers and return their indices "
            "if they add up to the target."
        )
    )


    # ==========================================
    # CREATE EVALUATOR
    # ==========================================

    evaluator = AIEvaluator()
    graph_retriever = GraphRetriever()
    hybrid_retriever = HybridRetriever()

    # ==========================================
    # TEST ALL CANDIDATES
    # ==========================================

    candidates = [
        candidate_1,
        candidate_2,
        candidate_3
    ]


    for candidate in candidates:

        print("\n")
        print("=" * 60)
        print(f"Evaluating Candidate: {candidate.candidate_id}")
        print(f"Name: {candidate.name}")
        print("=" * 60)

        retrieved_context = hybrid_retriever.retrieve(
            query=(
                f"Evaluate a {candidate.role} candidate "
                f"for the {candidate.task} task. "
                f"Assess correctness, problem solving, code quality, "
                f"efficiency, and explanation."
            ),
            top_k=3,
        )

        graph_context = graph_retriever.retrieve_for_candidate(
            role_name=candidate.role,
            task_name=candidate.task,
        )

        evaluation = evaluator.evaluate(
            candidate,
            retrieved_context=retrieved_context,
            graph_context=graph_context
        )

        print("\nAI Evaluation:\n")

        print(
            json.dumps(
                evaluation,
                indent=4
            )
        )

        print("\nGraphRAG Context:")
        print(json.dumps(graph_context, indent=4))


        # ==========================================
        # SAVE EVALUATION
        # ==========================================

        file_path = save_evaluation(
            candidate,
            evaluation
        )

        print(f"\nEvaluation saved to: {file_path}")


if __name__ == "__main__":
    main()