from embeddings import EmbeddingGenerator
from vector_store import VectorStore


class Retriever:

    def __init__(self):

        self.embedding_generator = EmbeddingGenerator()
        self.vector_store = VectorStore()

    def retrieve(self, query, top_k=3):
        """
        Retrieve relevant knowledge for a query.
        """

        query_embedding = (
            self.embedding_generator.generate_embedding(
                query
            )
        )

        results = self.vector_store.search(
            query_embedding,
            top_k
        )

        return results