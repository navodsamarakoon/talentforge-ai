import json
from pathlib import Path


# ==========================================
# EVALUATION STORAGE DIRECTORY
# ==========================================

STORAGE_DIR = Path("evaluations")


# ==========================================
# SAVE EVALUATION
# ==========================================

def save_evaluation(candidate, evaluation):
    """
    Save a candidate's AI evaluation as a JSON file.
    """

    # Create evaluations directory if it doesn't exist
    STORAGE_DIR.mkdir(exist_ok=True)

    # Create file path using candidate ID
    file_path = STORAGE_DIR / f"{candidate.candidate_id}.json"

    # Data to store
    data = {
        "candidate_id": candidate.candidate_id,
        "candidate_name": candidate.name,
        "role": candidate.role,
        "task": candidate.task,
        "evaluation": evaluation
    }

    # Save JSON file
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )

    return file_path


# ==========================================
# LOAD EVALUATION
# ==========================================

def load_evaluation(candidate_id):
    """
    Load a previously saved candidate evaluation.
    """

    file_path = STORAGE_DIR / f"{candidate_id}.json"

    # Check whether evaluation exists
    if not file_path.exists():
        raise FileNotFoundError(
            f"No saved evaluation found for candidate: {candidate_id}"
        )

    # Read JSON file
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    return data