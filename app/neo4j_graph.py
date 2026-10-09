
import os

from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

load_dotenv()


def connect_to_neo4j():
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not username or not password:
        raise ValueError(
            "Neo4j environment variables are missing. "
            "Please check your .env file."
        )

    graph = Neo4jGraph(
        url=uri,
        username=username,
        password=password,
    )

    # Verify that Neo4j can execute a query.
    result = graph.query(
        "RETURN 'TalentForge AI connected!' AS message"
    )

    print(result[0]["message"])
    return graph


if __name__ == "__main__":
    try:
        graph = connect_to_neo4j()
        print("LangChain Neo4j connection successful! 🎉")
    except Exception as error:
        print("Neo4j connection failed.")
        print(f"Error type: {type(error).__name__}")
        print(f"Error: {error}")
