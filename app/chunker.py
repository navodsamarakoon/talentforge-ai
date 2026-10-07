from app.document_loader import load_all_documents


def chunk_document(document, chunk_size=500, chunk_overlap=100):
    """
    Split a document into overlapping text chunks.
    """

    text = document["content"]
    source = document["source"]

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunk_text = text[start:end]

        chunks.append({
            "source": source,
            "content": chunk_text
        })

        start += chunk_size - chunk_overlap

    return chunks


def chunk_all_documents(documents):
    """
    Chunk all loaded knowledge-base documents.
    """

    all_chunks = []

    for document in documents:

        chunks = chunk_document(document)

        all_chunks.extend(chunks)

    return all_chunks