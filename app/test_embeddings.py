from app.document_loader import load_all_documents
from app.chunker import chunk_all_documents
from app.embeddings import EmbeddingGenerator


def main():

    # Load documents
    documents = load_all_documents()

    # Create chunks
    chunks = chunk_all_documents(documents)

    print("\n")
    print("=" * 60)
    print("TALENTFORGE EMBEDDING GENERATION")
    print("=" * 60)

    print(f"Documents: {len(documents)}")
    print(f"Chunks: {len(chunks)}")

    # Create embedding generator
    generator = EmbeddingGenerator()

    # Generate embeddings
    embeddings = generator.generate_embeddings(chunks)

    print("\nEmbeddings generated successfully!")

    print(
        f"Number of embeddings: {len(embeddings)}"
    )

    print(
        f"Embedding dimension: {embeddings.shape[1]}"
    )

    print("\nFirst embedding preview:")

    print(
        embeddings[0][:10]
    )

    print("\nFirst chunk:")

    print(
        chunks[0]["content"][:300]
    )


if __name__ == "__main__":
    main()