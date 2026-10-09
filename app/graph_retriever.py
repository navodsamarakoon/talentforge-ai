
from app.neo4j_graph import connect_to_neo4j


class GraphRetriever:
    def __init__(self):
        self.graph = connect_to_neo4j()

    def retrieve_role_skills(self, role_name="Software Engineer"):
        query = """
        MATCH (role:Role {name: $role_name})-[r:REQUIRES]->(skill)
        RETURN role.name AS role,
               type(r) AS relationship,
               skill.name AS skill,
               skill.description AS description
        ORDER BY skill.name
        """

        return self.graph.query(
            query,
            params={"role_name": role_name},
        )

    def retrieve_task_knowledge(self, task_name):
        query = """
        MATCH (task:SkillEntity {name: $task_name})
        OPTIONAL MATCH (task)-[r]-(related)
        RETURN task.name AS task,
               task.description AS description,
               collect({
                   relationship: type(r),
                   related_skill: related.name,
                   related_description: related.description
               }) AS related_knowledge
        """

        return self.graph.query(
            query,
            params={"task_name": task_name},
        )

    def retrieve_for_candidate(self, role_name, task_name):
        role_skills = self.retrieve_role_skills(role_name)
        task_knowledge = self.retrieve_task_knowledge(task_name)

        return {
            "role_skills": role_skills,
            "task_knowledge": task_knowledge,
        }


if __name__ == "__main__":
    retriever = GraphRetriever()

    context = retriever.retrieve_for_candidate(
        role_name="Software Engineer",
        task_name="Two Sum",
    )

    print("\nRole Skills:")
    for item in context["role_skills"]:
        print(f"- {item['skill']}: {item['description']}")

    print("\nTask Knowledge:")
    for item in context["task_knowledge"]:
        print(item)
