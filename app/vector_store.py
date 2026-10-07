import chromadb


CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "talentforge_knowledge"


class VectorStore:

    def __init__(self):

        self.client = chromadb.PersistentClient(
            path=CHROMA_PATH
        )

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME
        )

    def add_documents(self, chunks, embeddings):

        ids = [
            f"chunk_{index}"
            for index in range(len(chunks))
        ]

        documents = [
            chunk["content"]
            for chunk in chunks
        ]

        metadatas = [
            {
                "source": chunk["source"]
            }
            for chunk in chunks
        ]

        self.collection.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas
        )

        print(
            f"Stored {len(chunks)} chunks in ChromaDB."
        )

    def count(self):

        return self.collection.count()

    def search(self, query_embedding, top_k=3):
        """
        Retrieve the most relevant knowledge chunks.
        """

        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k
        )

        retrieved_chunks = []

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        for document, metadata, distance in zip(
            documents,
            metadatas,
            distances
        ):
            retrieved_chunks.append({
                "content": document,
                "source": metadata["source"],
                "distance": distance
            })

        return retrieved_chunks    