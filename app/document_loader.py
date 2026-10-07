from pathlib import Path


# ==========================================
# KNOWLEDGE BASE DIRECTORY
# ==========================================

KNOWLEDGE_BASE_DIR = Path("knowledge_base")


# ==========================================
# LOAD SINGLE DOCUMENT
# ==========================================

def load_document(file_path):
    """
    Load a single knowledge-base document.
    """

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        content = file.read()

    return {
        "source": file_path.name,
        "content": content
    }


# ==========================================
# LOAD ALL DOCUMENTS
# ==========================================

def load_all_documents():
    """
    Load all Markdown documents from the
    TalentForge knowledge base.
    """

    documents = []

    # Find all .md files
    for file_path in KNOWLEDGE_BASE_DIR.glob("*.md"):

        document = load_document(file_path)

        documents.append(document)

    return documents