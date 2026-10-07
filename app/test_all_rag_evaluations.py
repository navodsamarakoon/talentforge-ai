from candidate import Candidate
from evaluator import AIEvaluator
from retriever import Retriever


def main():

    print("=" * 60)
    print("TALENTFORGE - RAG EVALUATION TEST")
    print("=" * 60)

    # ==========================================
    # Candidates
    # ==========================================

    candidates = [

        Candidate(
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

            test_results="""
10/10 tests passed
""",

            explanation="""
I use a hash map to store numbers that I have already seen.

For each number, I calculate the complement using:

target - current_number

If the complement already exists in the hash map,
I return the two indices.

The average time complexity is O(n) and the space
complexity is O(n).
"""
        ),

        Candidate(
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

            test_results="""
10/10 tests passed
""",

            explanation="""
I compare every pair of numbers until I find two
numbers whose sum equals the target.

The solution is simple and passes all tests.

The time complexity is O(n^2).
"""
        ),

        Candidate(
            candidate_id="C003",
            name="Charlie",
            role="Software Engineer",
            task="Two Sum",

            code="""
def two_sum(nums, target):
    if len(nums) >= 2:
        if nums[0] + nums[1] == target:
            return [0, 1]

    return []
""",

            test_results="""
3/10 tests passed
""",

            explanation="""
I check whether the first two numbers add up to
the target and return their indices.
"""
        )
    ]

    # ==========================================
    # Initialize RAG components
    # ==========================================

    print("\nInitializing RAG system...")

    retriever = Retriever()
    evaluator = AIEvaluator()

    print("RAG system ready.")

    # ==========================================
    # Evaluate all candidates
    # ==========================================

    results = []

    for candidate in candidates:

        print("\n" + "=" * 60)
        print(f"EVALUATING {candidate.candidate_id} - {candidate.name}")
        print("=" * 60)

        # --------------------------------------
        # Retrieve relevant knowledge
        # --------------------------------------

        query = f"""
Evaluate a {candidate.role} candidate's solution
for the {candidate.task} problem.

Focus on:
- correctness
- problem solving
- code quality
- efficiency
- explanation
- algorithm selection
- time complexity
- space complexity
"""

        print("\nRetrieving knowledge...")

        retrieved_context = retriever.retrieve(
            query,
            top_k=3
        )

        print(f"Retrieved {len(retrieved_context)} knowledge chunks.")

        for index, item in enumerate(retrieved_context, start=1):
            print(f"{index}. {item['source']}")

        # --------------------------------------
        # RAG Evaluation
        # --------------------------------------

        print("\nRunning Gemma 3 4B evaluation...")

        evaluation = evaluator.evaluate(
            candidate,
            retrieved_context
        )

        results.append({
            "candidate": candidate,
            "evaluation": evaluation
        })

        # --------------------------------------
        # Display result
        # --------------------------------------

        print("\nRESULT")
        print("-" * 40)

        print(
            f"Overall Score: "
            f"{evaluation['overall_score']}/10"
        )

        print(
            f"Final Verdict: "
            f"{evaluation['final_verdict']}"
        )

        print("\nCriteria:")

        criteria = evaluation["criteria"]

        print(
            f"Correctness: "
            f"{criteria['correctness']['score']}/10"
        )

        print(
            f"Problem Solving: "
            f"{criteria['problem_solving']['score']}/10"
        )

        print(
            f"Code Quality: "
            f"{criteria['code_quality']['score']}/10"
        )

        print(
            f"Efficiency: "
            f"{criteria['efficiency']['score']}/10"
        )

        print(
            f"Explanation: "
            f"{criteria['explanation']['score']}/10"
        )

    # ==========================================
    # Final Comparison
    # ==========================================

    print("\n\n")
    print("=" * 60)
    print("FINAL RAG EVALUATION COMPARISON")
    print("=" * 60)

    for result in results:

        candidate = result["candidate"]
        evaluation = result["evaluation"]

        print(
            f"{candidate.candidate_id} - "
            f"{candidate.name}: "
            f"{evaluation['overall_score']}/10 "
            f"({evaluation['final_verdict']})"
        )

    print("\n" + "=" * 60)
    print("RAG VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()