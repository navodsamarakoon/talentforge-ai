from app.document_loader import load_all_documents
from app.chunker import chunk_all_documents


def main():

    documents = load_all_documents()

    chunks = chunk_all_documents(documents)

    print("\n")
    print("=" * 60)
    print("TALENTFORGE DOCUMENT CHUNKING")
    print("=" * 60)

    print(
        f"Documents loaded: {len(documents)}"
    )

    print(
        f"Total chunks created: {len(chunks)}"
    )

    print("\n")

    for index, chunk in enumerate(chunks[:5], start=1):

        print("=" * 60)

        print(f"Chunk {index}")

        print("Source:")
        print(chunk["source"])

        print("\nContent:")

        print(chunk["content"])

        print()


if __name__ == "__main__":
    main()