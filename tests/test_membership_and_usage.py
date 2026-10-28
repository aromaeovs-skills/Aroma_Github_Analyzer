from copy import deepcopy
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from app.services.auth import (
    Member,
    get_current_member,
    is_premium_member,
    require_premium_member,
)
from app.services.usage import (
    MonthlyLimitExceeded,
    UsageRepository,
    UsageStorageUnavailable,
)


class FakeCollection:
    def __init__(self):
        self.records = {}

    def create_index(self, *args, **kwargs):
        return "unique_user_month"

    def update_one(self, query, update, upsert=False):
        key = (query["user_id"], query["period"])
        self.records.setdefault(key, {"user_id": key[0], "period": key[1], "count": 0})

    def find_one_and_update(self, query, update, return_document=None):
        key = (query["user_id"], query["period"])
        record = self.records.get(key)
        if record is None or record["count"] >= query["count"]["$lt"]:
            return None
        record["count"] += update["$inc"]["count"]
        return deepcopy(record)

    def find_one(self, query):
        record = self.records.get((query["user_id"], query["period"]))
        return deepcopy(record) if record else None


class FakeDatabase:
    def __init__(self):
        self.collection = FakeCollection()

    def __getitem__(self, name):
        assert name == "analysis_usage"
        return self.collection


def test_only_active_premium_subscription_grants_premium_access():
    assert is_premium_member(Member(user_id="member-1", plan="premium"))
    assert not is_premium_member(Member(user_id="member-3", plan="free"))
    assert require_premium_member(Member(user_id="member-1", plan="premium")).user_id == "member-1"

    with pytest.raises(HTTPException) as exc:
        require_premium_member(Member(user_id="member-3", plan="free"))
    assert exc.value.status_code == 403


def test_authentication_requires_bearer_token_and_token_configuration(monkeypatch):
    with pytest.raises(HTTPException) as missing_token:
        get_current_member(None)
    assert missing_token.value.status_code == 401

    from fastapi.security import HTTPAuthorizationCredentials

    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-token")
    with pytest.raises(HTTPException) as unconfigured:
        get_current_member(credentials)
    assert unconfigured.value.status_code == 503


def test_authentication_verifies_app_token_and_loads_subscription_plan(monkeypatch):
    from fastapi.security import HTTPAuthorizationCredentials

    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    monkeypatch.setattr(
        "app.services.auth.billing_repository.is_premium_member",
        lambda user_id: user_id == "github:123",
    )

    token = jwt.encode(
        {
            "sub": "github:123",
            "iss": "github-analyzer",
            "aud": "github-analyzer-api",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "test-signing-secret-that-is-at-least-32-bytes",
        algorithm="HS256",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    member = get_current_member(credentials)

    assert member == Member(user_id="github:123", plan="premium")


def test_free_monthly_usage_is_enforced_per_member():
    usage = UsageRepository(FakeDatabase())

    for expected in (1, 2, 3):
        result = usage.consume_repository_analysis("member-1")
        assert result["used"] == expected
        assert result["limit"] == 3

    with pytest.raises(MonthlyLimitExceeded) as exc:
        usage.consume_repository_analysis("member-1")
    assert exc.value.used == 3

    other_member = usage.consume_repository_analysis("member-2")
    assert other_member["used"] == 1


def test_usage_fails_closed_without_persistent_database():
    with pytest.raises(UsageStorageUnavailable, match="MongoDB is required"):
        UsageRepository(database=None).consume_repository_analysis("member-1")
