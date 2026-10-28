from app.models.github_request import GitHubAnalysisRequest, GitHubRepositoryAnalysisRequest
from app.models.github_repository_analysis import RepositoryCodeAnalysis
from app.services.github.github_client import GitHubClient
from app.services.github.github_service import GitHubService


def test_request_models_reject_path_injection():
    assert GitHubAnalysisRequest(username="octocat").username == "octocat"
    assert GitHubRepositoryAnalysisRequest(
        owner="octocat",
        repository="hello-world.py",
    ).repository == "hello-world.py"

    for invalid_owner in ("../octocat", "octocat/repo"):
        try:
            GitHubRepositoryAnalysisRequest(owner=invalid_owner, repository="repo")
        except ValueError:
            continue
        raise AssertionError("Invalid GitHub owner was accepted.")


def test_get_repositories_fetches_all_public_pages(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def __init__(self, repositories):
            self.repositories = repositories

        def json(self):
            return self.repositories

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=None, params=None):
        calls.append(params)
        if params["page"] == 1:
            return FakeResponse([{"name": f"repo-{index}"} for index in range(100)])
        return FakeResponse([{"name": "repo-100"}])

    monkeypatch.setattr("requests.get", fake_get)
    repositories = GitHubClient().get_repositories("octocat", max_repositories=None)

    assert len(repositories) == 101
    assert [call["page"] for call in calls] == [1, 2]
    assert all(call["type"] == "public" for call in calls)


def test_repository_analysis_rejects_private_repositories():
    class FakeClient:
        def get_repository_details(self, owner, repository):
            return {"private": True}

    service = GitHubService.__new__(GitHubService)
    service.client = FakeClient()

    try:
        service.analyze_repository("octocat", "private-repo")
    except ValueError as exc:
        assert str(exc) == "Only public repositories can be analyzed."
    else:
        raise AssertionError("Private repository analysis was allowed.")


def test_repository_analysis_reviews_only_requested_public_repository():
    class FakeClient:
        def get_repository_details(self, owner, repository):
            assert (owner, repository) == ("octocat", "hello-world")
            return {"private": False, "default_branch": "main"}

        def has_readme(self, owner, repository):
            return True

        def get_repository_tree(self, owner, repository, branch):
            return [{"path": "src/main.py", "type": "blob"}]

        def get_file_content(self, owner, repository, path):
            return "print('hello')"

        def get_readme_content(self, owner, repository):
            return "# Hello"

    class FakeCodeAnalyzer:
        def analyze_tree(self, tree):
            return {
                "source_paths": ["src/main.py"],
                "dependency_files": [],
                "detected_frameworks": [],
                "total_files": 1,
                "source_files": 1,
                "sampled_lines": 0,
                "has_readme": False,
                "has_tests": False,
                "has_docker": False,
                "has_ci": False,
                "has_license": False,
                "important_files": [],
            }

        def detect_technologies_from_dependencies(self, contents):
            return []

        def select_source_files(self, source_paths, max_files):
            return source_paths

    class FakeReviewer:
        def review(self, repository_name, metrics, readme, code_samples):
            assert repository_name == "hello-world"
            assert metrics["has_readme"] is True
            assert code_samples[0]["path"] == "src/main.py"
            return RepositoryCodeAnalysis(
                repository_name=repository_name,
                code_quality_score=80,
                architecture_score=80,
                readability_score=80,
                maintainability_score=80,
                testing_score=50,
                documentation_score=80,
                complexity_score=20,
                developer_level="Intermediate",
                project_difficulty="Beginner",
                summary="Reviewed repository",
                metrics=metrics,
            )

    service = GitHubService.__new__(GitHubService)
    service.client = FakeClient()
    service.code_analyzer = FakeCodeAnalyzer()
    service.repository_reviewer = FakeReviewer()

    result = service.analyze_repository("octocat", "hello-world")

    assert result.repository_name == "hello-world"
    assert result.metrics.sampled_lines == 1


def test_account_analysis_returns_all_repositories_but_deep_checks_three():
    class FakeClient:
        def __init__(self):
            self.deep_checks = []

        def get_user(self, username):
            return {"login": username, "public_repos": 4}

        def get_repositories(self, username, max_repositories):
            assert max_repositories is None
            return [
                {"name": f"repo-{index}", "language": "Python"}
                for index in range(4)
            ]

        def has_readme(self, owner, repository):
            self.deep_checks.append(repository)
            return True

        def get_languages(self, owner, repository):
            return {"Python": 100}

        def get_repository_tree(self, owner, repository, branch=None):
            return []

    class FakeAI:
        def generate(self, request):
            class Response:
                content = (
                    '{"overall_score":70,"repository_score":70,'
                    '"documentation_score":70,"activity_score":70,'
                    '"diversity_score":70,"summary":"Good portfolio"}'
                )

            return Response()

    service = GitHubService.__new__(GitHubService)
    service.client = FakeClient()
    service.ai = FakeAI()
    response = service.analyze("octocat")

    assert len(response.repositories) == 4
    assert service.client.deep_checks == ["repo-0", "repo-1", "repo-2"]
    assert response.repositories[3].has_readme is None
