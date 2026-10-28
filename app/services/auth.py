import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError

from app.database.billing_repository import BillingRepository, BillingStorageUnavailable

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)
billing_repository = BillingRepository()
ACCESS_TOKEN_TTL_MINUTES = 60


@dataclass(frozen=True)
class Member:
    user_id: str
    plan: str


def get_access_token_settings() -> tuple[str, str, str]:
    secret = os.getenv("AUTH_TOKEN_SECRET", "").strip()
    issuer = os.getenv("AUTH_TOKEN_ISSUER", "github-analyzer").strip()
    audience = os.getenv("AUTH_TOKEN_AUDIENCE", "github-analyzer-api").strip()
    if len(secret.encode("utf-8")) < 32 or not issuer or not audience:
        raise ValueError(
            "Set AUTH_TOKEN_SECRET to at least 32 characters and configure "
            "AUTH_TOKEN_ISSUER and AUTH_TOKEN_AUDIENCE."
        )
    return secret, issuer, audience


def create_access_token(user_id: str) -> str:
    secret, issuer, audience = get_access_token_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
        },
        secret,
        algorithm="HS256",
    )


def get_current_member(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Member:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        secret, issuer, audience = get_access_token_settings()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        claims = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The bearer token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id.startswith("github:") or not user_id[7:]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The bearer token does not identify a GitHub member.",
        )

    try:
        is_premium = billing_repository.is_premium_member(user_id)
    except BillingStorageUnavailable as exc:
        logger.error("Could not load the member billing entitlement: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Membership status is temporarily unavailable.",
        ) from exc
    return Member(user_id=user_id, plan="premium" if is_premium else "free")


def require_premium_member(member: Member = Depends(get_current_member)) -> Member:
    if not is_premium_member(member):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full GitHub account analysis is available to premium members only.",
        )
    return member


def is_premium_member(member: Member) -> bool:
    return member.plan == "premium"
