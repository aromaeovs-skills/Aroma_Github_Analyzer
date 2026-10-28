import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.services.auth import (
    ACCESS_TOKEN_TTL_MINUTES,
    create_access_token,
    get_access_token_settings,
)

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/auth")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
OAUTH_STATE_COOKIE = "github_oauth_state"
OAUTH_STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class GitHubOAuthSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_callback_url: str


def _is_allowed_callback_url(value: str) -> bool:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        return False
    return parts.scheme == "https" or parts.hostname.lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def _oauth_settings() -> GitHubOAuthSettings:
    client_id = os.getenv("GITHUB_CLIENT_ID", "").strip()
    client_secret = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GITHUB_OAUTH_REDIRECT_URI", "").strip()
    frontend_callback_url = os.getenv(
        "FRONTEND_AUTH_CALLBACK_URL",
        "http://localhost:3000/auth/callback",
    ).strip()
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError(
            "Set GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, and GITHUB_OAUTH_REDIRECT_URI."
        )
    if not _is_allowed_callback_url(redirect_uri):
        raise ValueError(
            "GITHUB_OAUTH_REDIRECT_URI must use HTTPS (HTTP is allowed only for localhost) "
            "and must not contain credentials, query parameters, or a fragment."
        )
    if not _is_allowed_callback_url(frontend_callback_url):
        raise ValueError(
            "FRONTEND_AUTH_CALLBACK_URL must use HTTPS (HTTP is allowed only for localhost) "
            "and must not contain credentials, query parameters, or a fragment."
        )
    get_access_token_settings()
    return GitHubOAuthSettings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        frontend_callback_url=frontend_callback_url,
    )


def _configured_settings() -> GitHubOAuthSettings:
    try:
        return _oauth_settings()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"GitHub authentication is not configured. {exc}",
        ) from exc


def _frontend_redirect(settings: GitHubOAuthSettings, values: dict[str, str]) -> str:
    return f"{settings.frontend_callback_url}#{urlencode(values)}"


def _clear_state_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(
        OAUTH_STATE_COOKIE,
        path="/auth/github/callback",
        secure=os.getenv("GITHUB_OAUTH_REDIRECT_URI", "").startswith("https://"),
        httponly=True,
        samesite="lax",
    )


@auth_router.get("/github/login")
def github_login() -> RedirectResponse:
    settings = _configured_settings()
    state = secrets.token_urlsafe(32)
    authorization_url = f"{GITHUB_AUTHORIZE_URL}?{urlencode({
        'client_id': settings.client_id,
        'redirect_uri': settings.redirect_uri,
        'state': state,
        'allow_signup': 'true',
    })}"
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path="/auth/github/callback",
        secure=settings.redirect_uri.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return response


@auth_router.get("/github/callback")
def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = _configured_settings()
    stored_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The GitHub authorization state is missing or invalid.",
        )

    if error:
        response = RedirectResponse(
            _frontend_redirect(settings, {"auth_error": "github_login_cancelled"}),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_state_cookie(response)
        return response
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub did not return an authorization code.",
        )

    try:
        token_response = requests.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("GitHub did not return an access token.")

        user_response = requests.get(
            GITHUB_USER_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "GitHub-Analyzer",
            },
            timeout=10,
        )
        user_response.raise_for_status()
        user_data = user_response.json()
        github_id = user_data.get("id") if isinstance(user_data, dict) else None
        login = user_data.get("login") if isinstance(user_data, dict) else None
        if (
            isinstance(github_id, bool)
            or not isinstance(github_id, int)
            or github_id <= 0
            or not isinstance(login, str)
            or not login
        ):
            raise ValueError("GitHub returned an invalid user profile.")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("GitHub OAuth exchange failed: %s", type(exc).__name__)
        response = RedirectResponse(
            _frontend_redirect(settings, {"auth_error": "github_login_failed"}),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_state_cookie(response)
        return response

    token = create_access_token(f"github:{github_id}")
    response = RedirectResponse(
        _frontend_redirect(
            settings,
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": str(ACCESS_TOKEN_TTL_MINUTES * 60),
                "login": login,
            },
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _clear_state_cookie(response)
    return response
