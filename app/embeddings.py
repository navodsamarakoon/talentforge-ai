from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingGenerator:

    def __init__(self):
        print("Loading embedding model...")

        self.model = SentenceTransformer(MODEL_NAME)

        print("Embedding model loaded.")

    def generate_embedding(self, text):
        """
        Generate an embedding vector for a single text.
        """

        embedding = self.model.encode(
            text,
            convert_to_numpy=True
        )

        return embedding

    def generate_embeddings(self, chunks):
        """
        Generate embeddings for all document chunks.
        """

        texts = [
            chunk["content"]
            for chunk in chunks
        ]

        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True
        )

        return embeddings