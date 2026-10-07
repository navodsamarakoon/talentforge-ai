from candidate import Candidate
from evaluator import AIEvaluator
from retriever import Retriever


def main():

    print("\n")
    print("=" * 60)
    print("TALENTFORGE RAG-BASED EVALUATION")
    print("=" * 60)

    # --------------------------------
    # Create candidate
    # --------------------------------

    candidate = Candidate(
        candidate_id="RAG001",
        name="RAG Test Candidate",
        role="Software Engineer",
        task="""
Implement the Two Sum problem.

Given an array of integers and a target,
return the indices of the two numbers
that add up to the target.
""",
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
        test_results="""
10/10 tests passed.

All provided test cases passed successfully.
""",
        explanation="""
I use a hash map to store previously seen numbers
and their indices.

For each number, I calculate the complement
using target - current value.

If the complement is already in the hash map,
the two required indices are returned.

The average time complexity is O(n)
and the space complexity is O(n).
"""
    )

    # --------------------------------
    # Retrieve knowledge
    # --------------------------------

    retriever = Retriever()

    query = """
Evaluate this Software Engineer candidate's
Two Sum solution, especially correctness,
problem solving, code quality, efficiency,
and explanation.
"""

    print("\nRetrieving TalentForge knowledge...")

    retrieved_context = retriever.retrieve(
        query,
        top_k=3
    )

    print(
        f"Retrieved knowledge chunks: "
        f"{len(retrieved_context)}"
    )

    for index, item in enumerate(
        retrieved_context,
        start=1
    ):
        print(
            f"{index}. {item['source']}"
        )

    # --------------------------------
    # Evaluate candidate using RAG
    # --------------------------------

    evaluator = AIEvaluator()

    print("\nRunning RAG-based evaluation...")

    evaluation = evaluator.evaluate(
        candidate,
        retrieved_context
    )

    # --------------------------------
    # Display result
    # --------------------------------

    print("\n")
    print("=" * 60)
    print("RAG EVALUATION RESULT")
    print("=" * 60)

    print(
        f"\nOverall Score: "
        f"{evaluation['overall_score']}/10"
    )

    print(
        f"\nFinal Verdict:\n"
        f"{evaluation['final_verdict']}"
    )

    print("\nCriteria:")

    for criterion, result in evaluation[
        "criteria"
    ].items():

        print(
            f"\n{criterion}: "
            f"{result['score']}/10"
        )

        print(
            f"Evidence: "
            f"{result['evidence']}"
        )

    print("\nStrengths:")

    for strength in evaluation["strengths"]:
        print(f"- {strength}")

    print("\nWeaknesses:")

    for weakness in evaluation["weaknesses"]:
        print(f"- {weakness}")


if __name__ == "__main__":
    main()