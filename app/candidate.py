class Candidate:
    def __init__(
        self,
        candidate_id,
        name,
        role,
        task,
        code,
        test_results,
        explanation
    ):
        self.candidate_id = candidate_id
        self.name = name
        self.role = role
        self.task = task
        self.code = code
        self.test_results = test_results
        self.explanation = explanation