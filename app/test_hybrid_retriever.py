from hybrid_retriever import HybridRetriever


def main():

    print("=" * 60)
    print("TALENTFORGE HYBRID SEARCH - RANKING TEST")
    print("=" * 60)

    retriever = HybridRetriever()

    query = """
    What is the most efficient approach for solving
    the Two Sum problem using a hash map?
    """

    print("\nQuery:")
    print(query)

    print("\nRunning hybrid retrieval...\n")

    results = retriever.retrieve(
        query,
        top_k=3
    )

    print(f"Ranked results: {len(results)}")

    for index, result in enumerate(results, start=1):

        print("\n" + "-" * 60)

        print(f"Rank: {index}")
        print(f"Source: {result['source']}")

        print(
            f"Vector Score: "
            f"{result['vector_score']:.4f}"
        )

        print(
            f"Keyword Score: "
            f"{result['keyword_score']}"
        )

        print(
            f"Normalized Keyword Score: "
            f"{result['normalized_keyword_score']:.4f}"
        )

        print(
            f"Hybrid Score: "
            f"{result['hybrid_score']:.4f}"
        )

    print("\n" + "=" * 60)
    print("HYBRID RANKING TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()