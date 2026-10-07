from app.document_loader import load_all_documents


def main():

    documents = load_all_documents()

    print("\n")
    print("=" * 60)
    print("TALENTFORGE KNOWLEDGE BASE")
    print("=" * 60)

    print(
        f"Documents loaded: {len(documents)}"
    )

    for document in documents:

        print("\nSource:")
        print(document["source"])

        print(
            "Characters:",
            len(document["content"])
        )

        print("\nPreview:")

        print(
            document["content"][:200]
        )

        print("-" * 60)


if __name__ == "__main__":
    main()