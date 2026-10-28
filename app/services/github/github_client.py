from typing import Any, Dict, List, Optional

import requests


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Aroma-GitHub-Analyzer",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _handle_response(self, response: requests.Response, *, operation: str) -> None:
        if response.status_code == 401:
            raise RuntimeError(
                "GitHub authentication failed. Check GITHUB_TOKEN in .env; the token may be missing, invalid, expired, or not authorized for GitHub API access."
            )
        if response.status_code == 404:
            if operation == "user":
                raise ValueError("GitHub user not found.")
            return
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                reset_time = response.headers.get("X-RateLimit-Reset")
                raise RuntimeError(f"GitHub API rate limit exceeded. Reset timestamp: {reset_time}")
            raise RuntimeError("GitHub API access was forbidden. Check the token and GitHub permissions.")
        self._handle_rate_limit(response)
        response.raise_for_status()

    def get_user(self, username: str) -> Dict[str, Any]:
        response = requests.get(
            f"{self.BASE_URL}/users/{username}",
            headers=self._headers(),
            timeout=10,
        )

        self._handle_response(response, operation="user")
        return response.json()

    def get_repositories(
        self,
        username: str,
        max_repositories: int | None = 30,
    ) -> List[Dict[str, Any]]:
        repositories = []
        page = 1
        per_page = 100 if max_repositories is None else min(max_repositories, 100)
        while max_repositories is None or len(repositories) < max_repositories:
            response = requests.get(
                f"{self.BASE_URL}/users/{username}/repos",
                headers=self._headers(),
                params={
                    "sort": "updated",
                    "direction": "desc",
                    "type": "public",
                    "per_page": per_page,
                    "page": page,
                },
                timeout=10,
            )
            if response.status_code == 404:
                raise ValueError("GitHub user not found.")
            self._handle_rate_limit(response)
            response.raise_for_status()
            batch = response.json()
            repositories.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        if max_repositories is not None:
            return repositories[:max_repositories]
        return repositories

    def has_readme(self, owner: str, repository: str) -> bool:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/readme",
            headers=self._headers(),
            timeout=10,
        )

        if response.status_code == 404:
            return False
        self._handle_response(response, operation="repository")
        return True

    def get_languages(self, owner: str, repository: str) -> Dict[str, int]:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/languages",
            headers=self._headers(),
            timeout=10,
        )

        if response.status_code == 404:
            return {}
        self._handle_response(response, operation="repository")
        return response.json()

    def get_repository_tree(self, owner: str, repository: str, branch: Optional[str] = None) -> List[Dict[str, Any]]:
        if branch is None:
            repo_response = requests.get(
                f"{self.BASE_URL}/repos/{owner}/{repository}",
                headers=self._headers(),
                timeout=10,
            )
            if repo_response.status_code == 404:
                return []
            repo_response.raise_for_status()
            branch = repo_response.json().get("default_branch")
            if not branch:
                return []

        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/git/trees/{branch}",
            headers=self._headers(),
            params={"recursive": "1"},
            timeout=15,
        )

        if response.status_code in (404, 409):
            return []
        self._handle_response(response, operation="repository")
        data = response.json()
        return data.get("tree", [])

    def get_file_content(self, owner: str, repository: str, path: str, max_chars: int = 20000) -> str:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/contents/{path}",
            headers=self._headers(),
            timeout=10,
        )

        if response.status_code == 404:
            return ""
        self._handle_response(response, operation="repository")

        data = response.json()
        if not isinstance(data, dict):
            return ""

        download_url = data.get("download_url")
        if not download_url:
            return ""

        file_response = requests.get(download_url, headers={"User-Agent": "Aroma-GitHub-Analyzer"}, timeout=10)
        if file_response.status_code == 404:
            return ""
        file_response.raise_for_status()

        content_type = file_response.headers.get("Content-Type", "").lower()
        binary_signals = (
            "image/",
            "audio/",
            "video/",
            "application/zip",
            "application/octet-stream",
            "application/pdf",
        )
        if any(signal in content_type for signal in binary_signals):
            return ""

        return file_response.text[:max_chars]

    def get_readme_content(self, owner: str, repository: str, max_chars: int = 20000) -> str:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/readme",
            headers=self._headers(),
            timeout=10,
        )
        if response.status_code == 404:
            return ""
        self._handle_rate_limit(response)
        response.raise_for_status()

        data = response.json()
        download_url = data.get("download_url")
        if not download_url:
            return ""

        readme_response = requests.get(download_url, headers={"User-Agent": "Aroma-GitHub-Analyzer"}, timeout=10)
        if readme_response.status_code == 404:
            return ""
        readme_response.raise_for_status()
        return readme_response.text[:max_chars]

    def get_repository_topics(self, owner: str, repository: str) -> List[str]:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}/topics",
            headers=self._headers(),
            timeout=10,
        )
        if response.status_code == 404:
            return []
        self._handle_response(response, operation="repository")
        return response.json().get("names", [])

    def get_repository_details(self, owner: str, repository: str) -> Dict[str, Any]:
        response = requests.get(
            f"{self.BASE_URL}/repos/{owner}/{repository}",
            headers=self._headers(),
            timeout=10,
        )
        if response.status_code == 404:
            return {}
        self._handle_response(response, operation="repository")
        return response.json()

    def _handle_rate_limit(self, response: requests.Response) -> None:
        if response.status_code != 403:
            return
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset_time = response.headers.get("X-RateLimit-Reset")
            raise RuntimeError(f"GitHub API rate limit exceeded. Reset timestamp: {reset_time}")
