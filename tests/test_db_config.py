import importlib

import pytest

from app.database import db as db_module
from app.database.db import build_mongo_client_kwargs
from app.services.github.github_client import GitHubClient


def test_build_mongo_client_kwargs_for_local_mongo_does_not_force_tls():
    kwargs = build_mongo_client_kwargs("mongodb://localhost:27017")
    assert "tls" not in kwargs
    assert kwargs["serverSelectionTimeoutMS"] == 10000
    assert kwargs["retryWrites"] is False


def test_build_mongo_client_kwargs_for_atlas_uses_tls():
    kwargs = build_mongo_client_kwargs("mongodb+srv://cluster.example.mongodb.net")
    assert kwargs["tls"] is True


def test_database_uses_env_names(monkeypatch):
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DATABASE_NAME", "github_analyzer_test")

    import app.database.db as db_file
    importlib.reload(db_file)

    assert db_file.MONGODB_URL == "mongodb://localhost:27017"
    assert db_file.DATABASE_NAME == "github_analyzer_test"

    importlib.reload(db_module)


def test_github_client_raises_clear_error_for_invalid_token(monkeypatch):
    class FakeResponse:
        status_code = 401
        headers = {}

        def raise_for_status(self):
            raise Exception("401 Client Error: Unauthorized")

    def fake_get(url, headers=None, timeout=None, params=None):
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)
    client = GitHubClient(token="ghp_invalid_token")

    with pytest.raises(RuntimeError, match="GitHub authentication failed|invalid or expired"):
        client.get_user("octocat")


def test_placeholder_api_keys_are_ignored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_key_here")
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_key_here")
    monkeypatch.setenv("GITHUB_TOKEN", "your_github_token_here")

    import app.services.ai.config as config_module
    import app.services.ai.manager as manager_module

    importlib.reload(config_module)
    importlib.reload(manager_module)

    assert config_module.GEMINI_API_KEY is None
    assert config_module.OPENAI_API_KEY is None
    assert config_module.GITHUB_TOKEN is None
    assert len(manager_module.AIManager().providers) == 0
