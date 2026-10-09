
from neo4j_graph import connect_to_neo4j
from skill_entities import SKILL_ENTITIES
from skill_relationships import SKILL_RELATIONSHIPS


def populate_knowledge_graph():
    graph = connect_to_neo4j()

    # Create all skill and problem nodes.
    for entity in SKILL_ENTITIES:
        graph.query(
            """
            MERGE (n:SkillEntity {name: $name})
            SET n.type = $type,
                n.description = $description
            """,
            params=entity,
        )

    # Create the Software Engineer role.
    graph.query(
        """
        MERGE (:Role {name: 'Software Engineer'})
        """
    )

    # Create relationships using the APOC plugin.
    for item in SKILL_RELATIONSHIPS:
        graph.query(
            """
            MATCH (source {name: $source})
            MATCH (target {name: $target})
            CALL apoc.merge.relationship(
                source,
                $relationship,
                {},
                {},
                target
            ) YIELD rel
            RETURN type(rel) AS relationship_type
            """,
            params=item,
        )

    print(f"Stored {len(SKILL_ENTITIES)} entities.")
    print(f"Processed {len(SKILL_RELATIONSHIPS)} relationships.")
    print("TalentForge AI knowledge graph populated! 🎉")


if __name__ == "__main__":
    populate_knowledge_graph()
