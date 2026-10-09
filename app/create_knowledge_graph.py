
from neo4j_graph import connect_to_neo4j


def create_knowledge_graph():
    graph = connect_to_neo4j()

    # Create the base node for the Software Engineer role.
    graph.query("""
        MERGE (role:Role {name: 'Software Engineer'})
        RETURN role.name AS role
    """)

    print("TalentForge AI knowledge graph initialized! 🎉")


if __name__ == "__main__":
    create_knowledge_graph()
