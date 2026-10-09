from app.retriever import Retriever
from app.keyword_retriever import KeywordRetriever


class HybridRetriever:

    def __init__(self):
        self.vector_retriever = Retriever()
        self.keyword_retriever = KeywordRetriever()

    def retrieve(self, query, top_k=3):

        # ==========================================
        # Vector Retrieval
        # ==========================================

        vector_results = self.vector_retriever.retrieve(
            query,
            top_k=top_k
        )

        # ==========================================
        # Keyword Retrieval
        # ==========================================

        keyword_results = self.keyword_retriever.retrieve(
            query,
            top_k=top_k
        )

        # ==========================================
        # Combine Results
        # ==========================================

        combined = {}

        # ------------------------------------------
        # Add Vector Results
        # ------------------------------------------

        for result in vector_results:

            source = result["source"]

            combined[source] = {
                "source": source,
                "content": result["content"],
                "vector_score": 1 / (1 + result["distance"]),
                "keyword_score": 0
            }

        # ------------------------------------------
        # Add Keyword Results
        # ------------------------------------------

        for result in keyword_results:

            source = result["source"]

            if source not in combined:

                combined[source] = {
                    "source": source,
                    "content": result["content"],
                    "vector_score": 0,
                    "keyword_score": result["keyword_score"]
                }

            else:

                combined[source]["keyword_score"] = (
                    result["keyword_score"]
                )

        # ==========================================
        # Normalize Keyword Scores
        # ==========================================

        max_keyword_score = max(
            [
                result["keyword_score"]
                for result in combined.values()
            ],
            default=0
        )

        for result in combined.values():

            if max_keyword_score > 0:

                normalized_keyword_score = (
                    result["keyword_score"]
                    / max_keyword_score
                )

            else:

                normalized_keyword_score = 0

            result["normalized_keyword_score"] = (
                normalized_keyword_score
            )

        # ==========================================
        # Calculate Hybrid Score
        # ==========================================

        for result in combined.values():

            result["hybrid_score"] = (
                0.5 * result["vector_score"]
                +
                0.5 * result["normalized_keyword_score"]
            )

        # ==========================================
        # Rank Results
        # ==========================================

        ranked_results = sorted(
            combined.values(),
            key=lambda result: result["hybrid_score"],
            reverse=True
        )

        return ranked_results[:top_k]