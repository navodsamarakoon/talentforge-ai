from document_loader import load_all_documents


class KeywordRetriever:

    def __init__(self):
        self.documents = load_all_documents()

    def retrieve(self, query, top_k=3):

        query_words = self._tokenize(query)

        results = []

        for document in self.documents:

            content = document["content"].lower()

            score = 0

            for word in query_words:

                if word in content:
                    score += content.count(word)

            if score > 0:

                results.append({
                    "source": document["source"],
                    "content": document["content"],
                    "keyword_score": score
                })

        # Highest keyword score first
        results.sort(
            key=lambda item: item["keyword_score"],
            reverse=True
        )

        return results[:top_k]

    def _tokenize(self, text):

        # Convert text to lowercase
        text = text.lower()

        # Remove simple punctuation
        punctuation = ".,!?;:()[]{}\"'"

        for character in punctuation:
            text = text.replace(character, " ")

        words = text.split()

        # Remove very common words
        stop_words = {
            "the",
            "is",
            "a",
            "an",
            "of",
            "to",
            "and",
            "for",
            "in",
            "on",
            "with",
            "this",
            "that",
            "what",
            "how"
        }

        return [
            word
            for word in words
            if word not in stop_words
        ]