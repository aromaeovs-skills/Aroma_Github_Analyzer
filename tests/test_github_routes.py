import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import github as github_routes
from app.services.auth import Member, get_current_member


class FakeAnalysis:
    def model_dump(self):
        return {"summary": "Repository reviewed"}


def test_free_member_cannot_run_account_analysis(monkeypatch):
    app.dependency_overrides[get_current_member] = lambda: Member("free-user", "free")
    monkeypatch.setattr(
        github_routes.github_service,
        "analyze",
        lambda _username: pytest.fail("Free account analysis must be rejected before execution."),
    )
    try:
        response = TestClient(app).post(
            "/github/account/analyze",
            json={"username": "octocat"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_free_member_can_analyze_one_repository(monkeypatch):
    app.dependency_overrides[get_current_member] = lambda: Member("free-user", "free")
    monkeypatch.setattr(
        github_routes.usage_repository,
        "consume_repository_analysis",
        lambda _user_id: {"used": 1, "limit": 3, "period": "2026-10"},
    )
    monkeypatch.setattr(
        github_routes.github_service,
        "analyze_repository",
        lambda _owner, _repository: FakeAnalysis(),
    )
    monkeypatch.setattr(
        github_routes.github_repository,
        "save",
        lambda _document: "analysis-123",
    )
    try:
        response = TestClient(app).post(
            "/github/repository/analyze",
            json={"owner": "octocat", "repository": "hello-world"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["analysis_id"] == "analysis-123"
    assert response.json()["usage"]["limit"] == 3


def test_premium_member_can_run_account_analysis(monkeypatch):
    app.dependency_overrides[get_current_member] = lambda: Member("premium-user", "premium")
    monkeypatch.setattr(
        github_routes.github_service,
        "analyze",
        lambda _username: FakeAnalysis(),
    )
    monkeypatch.setattr(
        github_routes.github_repository,
        "save",
        lambda _document: "analysis-456",
    )
    try:
        response = TestClient(app).post(
            "/github/account/analyze",
            json={"username": "octocat"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["analysis_id"] == "analysis-456"


def test_subscription_checkout_requires_authenticated_member(monkeypatch):
    from app.routes import billing as billing_routes

    app.dependency_overrides[get_current_member] = lambda: Member("free-user", "free")
    monkeypatch.setattr(
        billing_routes.razorpay_service,
        "create_subscription",
        lambda user_id: {
            "subscription_id": "sub_123",
            "status": "created",
            "checkout_url": "https://rzp.io/i/example",
        },
    )
    try:
        response = TestClient(app).post("/billing/subscription")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["data"]["checkout_url"] == "https://rzp.io/i/example"


def test_razorpay_webhook_is_rejected_without_valid_signature(monkeypatch):
    from app.routes import billing as billing_routes

    def invalid_webhook(body, signature, event_id):
        raise ValueError("Invalid Razorpay webhook signature.")

    monkeypatch.setattr(billing_routes.razorpay_service, "process_webhook", invalid_webhook)
    response = TestClient(app).post(
        "/webhooks/razorpay",
        content=b'{"event":"subscription.activated"}',
        headers={"X-Razorpay-Signature": "bad"},
    )

    assert response.status_code == 400
