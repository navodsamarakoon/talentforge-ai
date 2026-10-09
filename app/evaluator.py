import json

from ollama import chat
from sympy import content

from app.candidate import Candidate


class AIEvaluator:

    def __init__(self):
        self.model = "gemma3:4b"

    def evaluate(
    self,
    candidate: Candidate,
    retrieved_context=None,
    graph_context=None
):
        
        if retrieved_context is None:
            retrieved_context = []

        # ==========================================
        # Build Retrieved Knowledge Context
        # ==========================================

        
        if retrieved_context is None:
            retrieved_context = []

        if graph_context is None:
            graph_context = {}

        # Build existing RAG context
        rag_knowledge = "\n\n".join(
            f"Source: {item['source']}\n{item['content']}"
            for item in retrieved_context
        )

        # Build Neo4j graph context
        graph_sections = []

        for item in graph_context.get("role_skills", []):
            graph_sections.append(
                f"Role skill: {item['skill']}\n"
                f"Description: {item['description']}\n"
                f"Relationship: {item['relationship']}"
            )

        for item in graph_context.get("task_knowledge", []):
            graph_sections.append(
                f"Task: {item.get('task', '')}\n"
                f"Description: {item.get('description', '')}"
            )

            for related in item.get("related_knowledge", []):
                if related.get("related_skill"):
                    graph_sections.append(
                        f"Related skill: {related['related_skill']}\n"
                        f"Relationship: {related.get('relationship', '')}\n"
                        f"Description: "
                        f"{related.get('related_description') or ''}"
                    )

        graph_knowledge = "\n\n".join(graph_sections)

        knowledge_parts = []

        if rag_knowledge:
            knowledge_parts.append(
                "VECTOR / HYBRID RAG KNOWLEDGE:\n" + rag_knowledge
            )

        if graph_knowledge:
            knowledge_parts.append(
                "NEO4J GRAPH KNOWLEDGE:\n" + graph_knowledge
            )

        knowledge_context = "\n\n".join(knowledge_parts)

        if not knowledge_context:
            knowledge_context = (
                "No external TalentForge knowledge was retrieved."
            )


        # ==========================================
        # Evaluation Prompt
        # ==========================================

        prompt = f"""
You are TalentForge AI, a technical candidate evaluation system.

Your task is to evaluate a candidate for the given technical role
using only the evidence provided.

========================
CANDIDATE INFORMATION
========================

Role:
{candidate.role}

Task:
{candidate.task}

Candidate Code:
{candidate.code}

Test Results:
{candidate.test_results}

Candidate Explanation:
{candidate.explanation}


========================
RETRIEVED TALENTFORGE KNOWLEDGE
========================

The following information was retrieved from the TalentForge
technical knowledge base.

Use this knowledge as evaluation guidance.

IMPORTANT:

- Retrieved knowledge is evaluation guidance.
- Retrieved knowledge is NOT candidate evidence.
- Do not give the candidate credit merely because the knowledge
  describes a good practice or algorithm.
- Determine whether the candidate actually demonstrated
  the relevant knowledge in their submission.

{knowledge_context}


========================
EVALUATION CRITERIA
========================

Evaluate the candidate using these five criteria:

1. Correctness

Determine whether the submitted solution correctly solves the task.

Consider:
- Test results
- Expected behavior
- Logical correctness
- Handling of valid inputs
- Important edge cases


2. Problem Solving

Evaluate the candidate's ability to understand the problem
and develop an appropriate algorithmic solution.

Consider:
- Understanding of the problem
- Algorithm selection
- Data structure selection
- Logical reasoning
- Ability to identify constraints
- Ability to improve inefficient approaches


3. Code Quality

Evaluate how clearly and maintainably the candidate
implemented the solution.

Consider:
- Readability
- Code structure
- Meaningful variable names
- Maintainability
- Appropriate programming constructs
- Avoidance of unnecessary complexity
- Consistent coding practices


4. Efficiency

Evaluate the computational performance of the solution.

Consider:
- Time complexity
- Space complexity
- Algorithm selection
- Data structure selection
- Scalability


5. Explanation

Evaluate how clearly the candidate communicates
their technical reasoning.

Consider:
- Understanding of the solution
- Algorithm explanation
- Important implementation decisions
- Time complexity explanation
- Space complexity explanation
- Awareness of limitations and edge cases


========================
SCORING
========================

For each criterion:

- Give a score from 0 to 10.
- Provide evidence supporting the score.
- Base the score only on demonstrated candidate evidence.

Score meaning:

0-2   = Very Poor
3-4   = Poor
5-6   = Average
7-8   = Good
9-10  = Excellent


========================
EVALUATION RULES
========================

1. Evaluate only the evidence provided by the candidate.
2. Do not invent candidate information.
3. Do not assume skills that are not demonstrated.
4. Consider test results when evaluating correctness.
5. Consider time and space complexity when evaluating efficiency.
6. Use the retrieved TalentForge knowledge as technical evaluation guidance.
7. Do not treat retrieved knowledge as candidate evidence.
8. Identify important weaknesses or limitations.
9. Keep the evaluation technically accurate and objective.
10. A candidate should receive credit only when their submission
    demonstrates the relevant competency.
11. Do not assign scores based on claims that are not supported
    by the candidate's code, test results, or explanation.


========================
OUTPUT
========================

Return the evaluation using exactly the required JSON structure.

Do not include Markdown.
Do not include explanations outside the JSON object.
"""

        # ==========================================
        # JSON Schema
        # ==========================================

        evaluation_schema = {
            "type": "object",
            "properties": {

                "criteria": {
                    "type": "object",
                    "properties": {

                        "correctness": {
                            "type": "object",
                            "properties": {
                                "score": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 10
                                },
                                "evidence": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "score",
                                "evidence"
                            ],
                            "additionalProperties": False
                        },

                        "problem_solving": {
                            "type": "object",
                            "properties": {
                                "score": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 10
                                },
                                "evidence": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "score",
                                "evidence"
                            ],
                            "additionalProperties": False
                        },

                        "code_quality": {
                            "type": "object",
                            "properties": {
                                "score": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 10
                                },
                                "evidence": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "score",
                                "evidence"
                            ],
                            "additionalProperties": False
                        },

                        "efficiency": {
                            "type": "object",
                            "properties": {
                                "score": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 10
                                },
                                "evidence": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "score",
                                "evidence"
                            ],
                            "additionalProperties": False
                        },

                        "explanation": {
                            "type": "object",
                            "properties": {
                                "score": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 10
                                },
                                "evidence": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "score",
                                "evidence"
                            ],
                            "additionalProperties": False
                        }
                    },

                    "required": [
                        "correctness",
                        "problem_solving",
                        "code_quality",
                        "efficiency",
                        "explanation"
                    ],

                    "additionalProperties": False
                },

                "overall_score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 10
                },

                "strengths": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                },

                "weaknesses": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                },

                "final_verdict": {
                    "type": "string"
                }
            },

            "required": [
                "criteria",
                "overall_score",
                "strengths",
                "weaknesses",
                "final_verdict"
            ],

            "additionalProperties": False
        }

        # ==========================================
        # Call Local Ollama LLM
        # ==========================================

        response = chat(
            model=self.model,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            format=evaluation_schema,

            options={
                "temperature": 0
            }
        )

        # ==========================================
        # Extract LLM Response
        # ==========================================

        content = response.message.content

        # ==========================================
        # Parse JSON
        # ==========================================

        try:
            evaluation = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Ollama returned invalid JSON:\n{content}"
            ) from error

        # Calculate the final verdict using the overall score
        overall_score = float(evaluation["overall_score"])

        if overall_score >= 9.0:
            evaluation["final_verdict"] = "Excellent"
        elif overall_score >= 7.0:
            evaluation["final_verdict"] = "Good"
        elif overall_score >= 5.0:
            evaluation["final_verdict"] = "Average"
        else:
            evaluation["final_verdict"] = "Poor"

        return evaluation
