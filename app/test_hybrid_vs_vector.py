from retriever import Retriever
from hybrid_retriever import HybridRetriever


def print_results(title, results):

    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    for index, result in enumerate(results, start=1):

        print("\n" + "-" * 60)
        print(f"Rank: {index}")
        print(f"Source: {result['source']}")

        if "distance" in result:
            print(f"Vector Distance: {result['distance']:.4f}")

        if "vector_score" in result:
            print(f"Vector Score: {result['vector_score']:.4f}")

        if "keyword_score" in result:
            print(f"Keyword Score: {result['keyword_score']}")

        if "hybrid_score" in result:
            print(f"Hybrid Score: {result['hybrid_score']:.4f}")


def main():

    print("=" * 60)
    print("TALENTFORGE SEARCH COMPARISON")
    print("=" * 60)

    query = """
    What is the most efficient approach for solving
    the Two Sum problem using a hash map?
    """

    print("\nQuery:")
    print(query)

    # ==========================================
    # Vector-only Search
    # ==========================================

    print("\nRunning vector-only search...")

    vector_retriever = Retriever()

    vector_results = vector_retriever.retrieve(
        query,
        top_k=3
    )

    print_results(
        "VECTOR-ONLY SEARCH",
        vector_results
    )

    # ==========================================
    # Hybrid Search
    # ==========================================

    print("\nRunning hybrid search...")

    hybrid_retriever = HybridRetriever()

    hybrid_results = hybrid_retriever.retrieve(
        query,
        top_k=3
    )

    print_results(
        "HYBRID SEARCH",
        hybrid_results
    )

    # ==========================================
    # Compare Top Results
    # ==========================================

    print("\n" + "=" * 60)
    print("TOP RESULT COMPARISON")
    print("=" * 60)

    vector_top = vector_results[0]["source"]
    hybrid_top = hybrid_results[0]["source"]

    print(
        f"\nVector-only top result: "
        f"{vector_top}"
    )

    print(
        f"Hybrid search top result: "
        f"{hybrid_top}"
    )

    # ==========================================
    # Check whether algorithms.md is retrieved
    # ==========================================

    target_document = "algorithms.md"

    vector_sources = [
        result["source"]
        for result in vector_results
    ]

    hybrid_sources = [
        result["source"]
        for result in hybrid_results
    ]

    print("\n" + "=" * 60)
    print("RELEVANCE CHECK")
    print("=" * 60)

    print(
        f"\n'{target_document}' in vector results: "
        f"{target_document in vector_sources}"
    )

    print(
        f"'{target_document}' in hybrid results: "
        f"{target_document in hybrid_sources}"
    )

    print("\n" + "=" * 60)
    print("HYBRID VS VECTOR TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()