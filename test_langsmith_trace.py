
import os
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()

print("Tracing enabled:", os.getenv("LANGSMITH_TRACING"))
print("API key configured:", bool(os.getenv("LANGSMITH_API_KEY")))
print("Project:", os.getenv("LANGSMITH_PROJECT"))


@traceable(name="TalentForge tracing test")
def test_trace():
    return "TalentForge LangSmith tracing is working!"


if __name__ == "__main__":
    print(test_trace())
