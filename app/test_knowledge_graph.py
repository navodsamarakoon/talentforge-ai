
from neo4j_graph import connect_to_neo4j


def test_knowledge_graph():
    graph = connect_to_neo4j()

    result = graph.query("""
        MATCH (n)
        RETURN labels(n) AS labels, count(n) AS total
        ORDER BY labels
    """)

    print("\nKnowledge Graph Node Summary")
    print("-" * 35)

    for row in result:
        print(f"{row['labels']}: {row['total']}")

    relationship_result = graph.query("""
        MATCH ()-[r]->()
        RETURN type(r) AS relationship, count(r) AS total
        ORDER BY relationship
    """)

    print("\nKnowledge Graph Relationships")
    print("-" * 35)

    for row in relationship_result:
        print(f"{row['relationship']}: {row['total']}")


if __name__ == "__main__":
    test_knowledge_graph()
