import json

from pydantic import ValidationError

from app.models.github_response import GitHubAnalysisResponse, GitHubRepositoryInsight
from app.models.github_repository_analysis import RepositoryCodeAnalysis
from app.services.ai.config import GITHUB_TOKEN
from app.services.ai.manager import AIManager
from app.services.ai.models import AIRequest
from app.services.ai.prompts import SYSTEM_PROMPTS
from app.services.github.github_client import GitHubClient
from app.services.github.github_code_analyzer import GitHubCodeAnalyzer
from app.services.github.repository_ai_reviewer import RepositoryAIReviewer


class GitHubService:
    def __init__(self):
        self.client = GitHubClient(token=GITHUB_TOKEN)
        self.ai = AIManager()
        self.code_analyzer = GitHubCodeAnalyzer()
        self.repository_reviewer = RepositoryAIReviewer()

    def analyze_repository(
        self,
        owner: str,
        repository_name: str,
    ) -> RepositoryCodeAnalysis:
        repository = self.client.get_repository_details(owner, repository_name)
        if not repository:
            raise ValueError("GitHub repository not found.")
        if repository.get("private", False):
            raise ValueError("Only public repositories can be analyzed.")

        has_readme = self.client.has_readme(owner, repository_name)

        tree = self.client.get_repository_tree(
            owner,
            repository_name,
            repository.get("default_branch"),
        )
        if not tree:
            raise ValueError("Repository is empty or has no accessible source tree.")

        metrics = self.code_analyzer.analyze_tree(tree)
        source_paths = metrics.pop("source_paths", [])

        dependency_contents = {}
        for dependency_path in metrics.get("dependency_files", []):
            content = self.client.get_file_content(owner, repository_name, dependency_path)
            if content:
                dependency_contents[dependency_path] = content[:12000]

        frameworks = set(metrics.get("detected_frameworks", []))
        frameworks.update(
            self.code_analyzer.detect_technologies_from_dependencies(dependency_contents)
        )
        metrics["detected_frameworks"] = sorted(frameworks)

        code_samples = []
        sampled_lines = 0
        for path in self.code_analyzer.select_source_files(source_paths, max_files=12):
            content = self.client.get_file_content(owner, repository_name, path)
            if not content:
                continue
            line_count = len(content.splitlines())
            sampled_lines += line_count
            code_samples.append(
                {
                    "path": path,
                    "content": content[:12000],
                    "sampled_lines": line_count,
                }
            )

        metrics["sampled_lines"] = sampled_lines
        metrics["has_readme"] = has_readme
        readme = self.client.get_readme_content(owner, repository_name)
        return self.repository_reviewer.review(
            repository_name=repository_name,
            metrics=metrics,
            readme=readme[:15000],
            code_samples=code_samples,
        )

    def analyze(self, username: str) -> GitHubAnalysisResponse:
        user = self.client.get_user(username)
        repositories = self.client.get_repositories(username, max_repositories=None)

        repo_list = []
        repository_reviews = []
        detected_languages = set()
        detected_profile_skills = set()

        for repository_index, repo in enumerate(repositories):
            repository_name = repo["name"]
            if repository_index >= 3:
                if repo.get("language"):
                    detected_languages.add(repo["language"])
                repo_list.append(
                    GitHubRepositoryInsight(
                        name=repository_name,
                        description=repo.get("description"),
                        language=repo.get("language"),
                        stars=repo.get("stargazers_count", 0),
                        forks=repo.get("forks_count", 0),
                        has_readme=None,
                    )
                )
                continue

            try:
                has_readme = self.client.has_readme(username, repository_name)
            except Exception:
                has_readme = False

            try:
                languages = self.client.get_languages(username, repository_name)
            except Exception:
                languages = {}

            detected_languages.update(languages.keys())

            repo_list.append(
                GitHubRepositoryInsight(
                    name=repository_name,
                    description=repo.get("description"),
                    language=repo.get("language"),
                    stars=repo.get("stargazers_count", 0),
                    forks=repo.get("forks_count", 0),
                    has_readme=has_readme,
                )
            )

            try:
                tree = self.client.get_repository_tree(username, repository_name, repo.get("default_branch"))

                if not tree:
                    repository_reviews.append({
                        "repository_name": repository_name,
                        "code_quality_score": 0,
                        "architecture_score": 0,
                        "readability_score": 0,
                        "maintainability_score": 0,
                        "testing_score": 0,
                        "documentation_score": 0,
                        "complexity_score": 0,
                        "developer_level": "Not enough code to evaluate",
                        "project_difficulty": "Not applicable",
                        "summary": "Repository is empty or has no accessible source tree.",
                        "strengths": [],
                        "issues": ["No source files available for analysis."],
                        "detected_skills": [],
                        "engineering_practices": [],
                        "recommendations": [
                            "Add project source code and documentation before requesting code-quality analysis."
                        ],
                        "metrics": {
                            "total_files": 0,
                            "source_files": 0,
                            "sampled_lines": 0,
                            "has_readme": has_readme,
                            "has_tests": False,
                            "has_docker": False,
                            "has_ci": False,
                            "has_license": False,
                            "detected_frameworks": [],
                            "dependency_files": [],
                            "important_files": [],
                        },
                    })
                    continue

                tree_metrics = self.code_analyzer.analyze_tree(tree)
                source_paths = tree_metrics.pop("source_paths", [])

                dependency_contents = {}
                for dependency_path in tree_metrics.get("dependency_files", []):
                    try:
                        content = self.client.get_file_content(username, repository_name, dependency_path)
                        if content:
                            dependency_contents[dependency_path] = content[:12000]
                    except Exception:
                        continue

                detected_dependency_technologies = self.code_analyzer.detect_technologies_from_dependencies(dependency_contents)
                existing_frameworks = set(tree_metrics.get("detected_frameworks", []))
                existing_frameworks.update(detected_dependency_technologies)
                tree_metrics["detected_frameworks"] = sorted(existing_frameworks)
                detected_profile_skills.update(existing_frameworks)

                selected_files = self.code_analyzer.select_source_files(source_paths, max_files=12)
                code_samples = []
                sampled_lines = 0

                for path in selected_files:
                    try:
                        content = self.client.get_file_content(username, repository_name, path)
                        if not content:
                            continue

                        line_count = len(content.splitlines())
                        sampled_lines += line_count
                        code_samples.append({
                            "path": path,
                            "content": content[:12000],
                            "sampled_lines": line_count,
                        })
                    except Exception:
                        continue

                tree_metrics["sampled_lines"] = sampled_lines

                try:
                    readme = self.client.get_readme_content(username, repository_name)
                except Exception:
                    readme = ""

                review = self.repository_reviewer.review(
                    repository_name=repository_name,
                    metrics=tree_metrics,
                    readme=readme[:15000],
                    code_samples=code_samples,
                )
                review_data = review.model_dump()
                repository_reviews.append(review_data)
                detected_profile_skills.update(review_data.get("detected_skills", []))

            except Exception as exc:
                repository_reviews.append({
                    "repository_name": repository_name,
                    "analysis_error": str(exc),
                })

        prompt = f"""
GitHub User:

Username:
{user.get("login")}

Name:
{user.get("name")}

Bio:
{user.get("bio")}

Public Repositories:
{user.get("public_repos")}

All Public Repository Metadata (most recently updated first):
{[repository.model_dump() for repository in repo_list[:25]]}

All public repositories are included in the returned repository list. Detailed
source review is limited to the three most recently updated repositories.

Followers:
{user.get("followers")}

Following:
{user.get("following")}

Detected Languages:
{sorted(detected_languages)}

Detected Frameworks and Engineering Skills:
{sorted(detected_profile_skills)}

Detailed Repository Engineering Reviews:
{repository_reviews}
"""

        request = AIRequest(
            system_prompt=SYSTEM_PROMPTS["github_analyzer"],
            prompt=prompt,
            temperature=0.2,
        )

        response = self.ai.generate(request)

        try:
            data = json.loads(response.content)
            data["repositories"] = [repository.model_dump() for repository in repo_list]

            combined_skills = set(detected_languages)
            combined_skills.update(detected_profile_skills)
            data["detected_skills"] = sorted(combined_skills)

            successful_reviews = [review for review in repository_reviews if "code_quality_score" in review]
            successful_reviews.sort(
                key=lambda review: (
                    review.get("code_quality_score", 0)
                    + review.get("architecture_score", 0)
                    + review.get("maintainability_score", 0)
                    + review.get("testing_score", 0)
                ),
                reverse=True,
            )

            data["top_projects"] = [
                review["repository_name"] for review in successful_reviews[:5] if review.get("code_quality_score", 0) > 0
            ]
            data["repository_reviews"] = repository_reviews
            return GitHubAnalysisResponse.model_validate(data)

        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub AI response was not valid JSON.") from exc
        except ValidationError as exc:
            raise RuntimeError("GitHub AI response did not match the expected schema.") from exc
