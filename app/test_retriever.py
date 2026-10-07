from retriever import Retriever


def main():

    print("\n")
    print("=" * 60)
    print("TALENTFORGE RAG RETRIEVAL")
    print("=" * 60)

    retriever = Retriever()

    query = (
        "What is the most efficient approach "
        "for solving the Two Sum problem?"
    )

    print("\nQuery:")
    print(query)

    print("\nSearching knowledge base...\n")

    results = retriever.retrieve(
        query,
        top_k=3
    )

    print(
        f"Retrieved chunks: {len(results)}"
    )

    for index, result in enumerate(
        results,
        start=1
    ):

        print("\n")
        print("=" * 60)
        print(f"Result {index}")

        print("\nSource:")
        print(result["source"])

        print("\nDistance:")
        print(result["distance"])

        print("\nContent:")
        print(result["content"])


if __name__ == "__main__":
    main()