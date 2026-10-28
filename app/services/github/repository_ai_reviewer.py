import json

from pydantic import ValidationError

from app.models.github_repository_analysis import RepositoryCodeAnalysis
from app.services.ai.manager import AIManager
from app.services.ai.models import AIRequest
from app.services.ai.prompts import SYSTEM_PROMPTS


class RepositoryAIReviewer:
    def __init__(self):
        self.ai = AIManager()

    def review(self, repository_name: str, metrics: dict, readme: str, code_samples: list[dict]) -> RepositoryCodeAnalysis:
        prompt = f"""
Repository:

{repository_name}

Repository Metrics:

{metrics}

README:

{readme}

Important Source Files:

{code_samples}
"""

        request = AIRequest(
            system_prompt=SYSTEM_PROMPTS["repository_code_reviewer"],
            prompt=prompt,
            temperature=0.2,
        )

        response = self.ai.generate(request)

        try:
            data = json.loads(response.content)
            data["repository_name"] = repository_name
            data["metrics"] = metrics
            return RepositoryCodeAnalysis.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise Exception(f"Repository Review Failed\n\n{exc}\n\n{response.content}") from exc
