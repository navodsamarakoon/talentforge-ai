from keyword_retriever import KeywordRetriever


def main():

    print("=" * 60)
    print("TALENTFORGE KEYWORD RETRIEVAL TEST")
    print("=" * 60)

    retriever = KeywordRetriever()

    query = """
    What is the most efficient approach for solving
    the Two Sum problem using a hash map?
    """

    print("\nQuery:")
    print(query)

    print("\nSearching knowledge base...\n")

    results = retriever.retrieve(
        query,
        top_k=3
    )

    print(f"Retrieved {len(results)} documents.\n")

    for index, result in enumerate(results, start=1):

        print("-" * 60)

        print(f"Rank: {index}")
        print(f"Source: {result['source']}")
        print(f"Keyword Score: {result['keyword_score']}")

        preview = result["content"][:300]

        print("\nContent Preview:")
        print(preview)

    print("\n" + "=" * 60)
    print("KEYWORD RETRIEVAL TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()