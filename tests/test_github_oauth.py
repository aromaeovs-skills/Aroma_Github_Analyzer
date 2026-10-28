from urllib.parse import parse_qs, urlparse

import jwt
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials

from app.main import app
from app.routes import auth as auth_routes
from app.services.auth import get_current_member


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def configure_github_oauth(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GITHUB_OAUTH_REDIRECT_URI",
        "http://localhost:8000/auth/github/callback",
    )
    monkeypatch.setenv(
        "FRONTEND_AUTH_CALLBACK_URL",
        "http://localhost:3000/auth/callback",
    )
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-signing-secret-that-is-at-least-32-bytes")


def test_github_login_redirects_with_state_cookie(monkeypatch):
    configure_github_oauth(monkeypatch)

    response = TestClient(app).get("/auth/github/login", follow_redirects=False)
    authorize_url = urlparse(response.headers["location"])
    query = parse_qs(authorize_url.query)

    assert response.status_code == 302
    assert authorize_url.netloc == "github.com"
    assert authorize_url.path == "/login/oauth/authorize"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/github/callback"]
    assert response.cookies[auth_routes.OAUTH_STATE_COOKIE] == query["state"][0]
    assert "httponly" in response.headers["set-cookie"].lower()


def test_callback_urls_require_https_outside_localhost():
    assert auth_routes._is_allowed_callback_url("http://localhost:3000/auth/callback")
    assert auth_routes._is_allowed_callback_url("https://app.example/auth/callback")
    assert not auth_routes._is_allowed_callback_url("http://app.example/auth/callback")
    assert not auth_routes._is_allowed_callback_url(
        "https://app.example/auth/callback?token=unsafe"
    )


def test_github_callback_issues_api_token_for_verified_github_user(monkeypatch):
    configure_github_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_routes.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"access_token": "github-oauth-token"}),
    )

    def get_user(*args, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer github-oauth-token"
        return FakeResponse({"id": 12345, "login": "octocat"})

    monkeypatch.setattr(auth_routes.requests, "get", get_user)
    monkeypatch.setattr(
        "app.services.auth.billing_repository.is_premium_member",
        lambda _user_id: False,
    )
    client = TestClient(app)
    login_response = client.get("/auth/github/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        "/auth/github/callback",
        params={"code": "authorization-code", "state": state},
        follow_redirects=False,
    )
    fragment = parse_qs(urlparse(callback_response.headers["location"]).fragment)
    token = fragment["access_token"][0]
    claims = jwt.decode(
        token,
        "test-signing-secret-that-is-at-least-32-bytes",
        algorithms=["HS256"],
        audience="github-analyzer-api",
        issuer="github-analyzer",
    )

    assert callback_response.status_code == 303
    assert fragment["token_type"] == ["Bearer"]
    assert fragment["expires_in"] == ["3600"]
    assert fragment["login"] == ["octocat"]
    assert claims["sub"] == "github:12345"
    assert "github-oauth-token" not in callback_response.headers["location"]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert get_current_member(credentials).user_id == "github:12345"


def test_github_callback_rejects_missing_or_mismatched_state(monkeypatch):
    configure_github_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_routes.requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OAuth exchange must not run for invalid state.")
        ),
    )
    client = TestClient(app)
    client.get("/auth/github/login", follow_redirects=False)

    response = client.get(
        "/auth/github/callback",
        params={"code": "authorization-code", "state": "not-the-cookie-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The GitHub authorization state is missing or invalid."
