import os
import json

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

from candidate import Candidate


# Load environment variables from .env
load_dotenv()


class AIEvaluator:

    def __init__(self):

        # Get Hugging Face API token
        token = os.getenv("HF_TOKEN")

        if not token:
            raise ValueError(
                "HF_TOKEN is not set in the .env file."
            )

        # Create Hugging Face client
        self.client = InferenceClient(
            api_key=token
        )

    def evaluate(self, candidate: Candidate):

        # ==========================================
        # TALENTFORGE AI EVALUATION PROMPT
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
EVALUATION CRITERIA
========================

Evaluate the candidate using these five criteria:

1. Correctness
   Determine whether the submitted solution correctly solves the task.

2. Problem Solving
   Evaluate the candidate's algorithmic thinking and approach.

3. Code Quality
   Evaluate readability, structure, maintainability,
   and coding practices.

4. Efficiency
   Evaluate time complexity, space complexity,
   and whether the solution uses an appropriate algorithm.

5. Explanation
   Evaluate how clearly the candidate explains
   the solution and reasoning.


========================
SCORING
========================

For each criterion:

- Give a score from 0 to 10.
- Provide evidence supporting the score.
- Base the score only on the provided candidate evidence.

Score meaning:

0-2   = Very Poor
3-4   = Poor
5-6   = Average
7-8   = Good
9-10  = Excellent


========================
EVALUATION RULES
========================

1. Evaluate only the evidence provided.
2. Do not invent candidate information.
3. Do not assume skills that are not demonstrated.
4. Consider test results when evaluating correctness.
5. Consider time and space complexity when evaluating efficiency.
6. Identify important weaknesses or limitations.
7. Keep the evaluation technically accurate and objective.


========================
OUTPUT
========================

Return the evaluation using exactly the required JSON schema.

Do not include Markdown.
Do not include explanations outside the JSON object.
"""

        # ==========================================
        # JSON SCHEMA
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
        # STRUCTURED RESPONSE FORMAT
        # ==========================================

        response_format = {
            "type": "json_schema",

            "json_schema": {
                "name": "TalentForgeEvaluation",

                "schema": evaluation_schema,

                "strict": True
            }
        }

        # ==========================================
        # CALL LLM
        # ==========================================

        response = self.client.chat.completions.create(

            model="Qwen/Qwen3-4B-Instruct-2507",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            response_format=response_format,

            max_tokens=1500
        )

        # ==========================================
        # GET RESPONSE
        # ==========================================

        content = response.choices[0].message.content

        # ==========================================
        # PARSE JSON
        # ==========================================

        try:

            evaluation = json.loads(content)

        except json.JSONDecodeError as error:

            raise ValueError(
                f"LLM returned invalid JSON:\n{content}"
            ) from error

        return evaluation