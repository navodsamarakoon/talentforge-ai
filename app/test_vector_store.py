from app.document_loader import load_all_documents
from app.chunker import chunk_all_documents
from app.embeddings import EmbeddingGenerator
from app.vector_store import VectorStore


def main():

    print("\n")
    print("=" * 60)
    print("TALENTFORGE VECTOR DATABASE")
    print("=" * 60)

    # --------------------------------
    # Load documents
    # --------------------------------

    documents = load_all_documents()

    print(
        f"Documents loaded: {len(documents)}"
    )

    # --------------------------------
    # Create chunks
    # --------------------------------

    chunks = chunk_all_documents(documents)

    print(
        f"Chunks created: {len(chunks)}"
    )

    # --------------------------------
    # Generate embeddings
    # --------------------------------

    generator = EmbeddingGenerator()

    embeddings = generator.generate_embeddings(
        chunks
    )

    print(
        f"Embeddings generated: {len(embeddings)}"
    )

    # --------------------------------
    # Create vector store
    # --------------------------------

    vector_store = VectorStore()

    # --------------------------------
    # Store embeddings
    # --------------------------------

    vector_store.add_documents(
        chunks,
        embeddings
    )

    # --------------------------------
    # Verify storage
    # --------------------------------

    count = vector_store.count()

    print(
        f"Documents stored in ChromaDB: {count}"
    )

    print("\nVector database setup successful! 🚀")


if __name__ == "__main__":
    main()