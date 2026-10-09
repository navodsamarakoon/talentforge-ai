import os

from dotenv import load_dotenv
from neo4j import GraphDatabase


load_dotenv()


URI = os.getenv("NEO4J_URI")
USERNAME = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")


if not URI or not USERNAME or not PASSWORD:
    raise ValueError("Neo4j environment variables are not configured.")


driver = GraphDatabase.driver(
    URI,
    auth=(USERNAME, PASSWORD)
)


try:
    driver.verify_connectivity()
    print("Neo4j AuraDB connection successful! 🎉")

except Exception as error:
    print("Neo4j connection failed.")
    print(error)

finally:
    driver.close()