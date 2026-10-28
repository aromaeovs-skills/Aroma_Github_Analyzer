import hashlib
import hmac
import json

import pytest

from app.services.razorpay import (
    BillingConfigurationError,
    RazorpayService,
    RazorpaySettings,
)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeBillingRepository:
    def __init__(self):
        self.saved = None
        self.webhook = None

    def get_latest_subscription(self, user_id):
        return None

    def is_premium_member(self, user_id):
        return False

    def save_created_subscription(self, **kwargs):
        self.saved = kwargs

    def apply_webhook(self, **kwargs):
        self.webhook = kwargs
        return True


def configure_razorpay(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test_secret_not_real")
    monkeypatch.setenv("RAZORPAY_PLAN_ID", "plan_test_monthly")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
    monkeypatch.setenv("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", "12")


def test_razorpay_requires_a_configured_plan_and_finite_term(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test_secret_not_real")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
    monkeypatch.delenv("RAZORPAY_PLAN_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", raising=False)

    with pytest.raises(BillingConfigurationError, match="RAZORPAY_PLAN_ID"):
        RazorpaySettings.from_environment()

    monkeypatch.setenv("RAZORPAY_PLAN_ID", "plan_test_monthly")
    monkeypatch.setenv("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", "101")
    with pytest.raises(BillingConfigurationError, match="from 1 to 100"):
        RazorpaySettings.from_environment()


def test_create_subscription_uses_server_configured_plan(monkeypatch):
    configure_razorpay(monkeypatch)
    repository = FakeBillingRepository()
    requests = []

    def fake_request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return FakeResponse(
            {
                "id": "sub_test_123",
                "status": "created",
                "short_url": "https://rzp.io/i/test",
            }
        )

    monkeypatch.setattr("app.services.razorpay.requests.request", fake_request)
    result = RazorpayService(repository).create_subscription("member-123")

    assert result == {
        "subscription_id": "sub_test_123",
        "status": "created",
        "checkout_url": "https://rzp.io/i/test",
    }
    assert requests[0][2]["json"]["plan_id"] == "plan_test_monthly"
    assert requests[0][2]["json"]["total_count"] == 12
    assert requests[0][2]["json"]["notes"] == {"user_id": "member-123"}
    assert repository.saved["user_id"] == "member-123"


def test_webhook_requires_valid_signature_and_is_idempotency_aware(monkeypatch):
    configure_razorpay(monkeypatch)
    repository = FakeBillingRepository()
    service = RazorpayService(repository)
    body = json.dumps(
        {
            "event": "subscription.activated",
            "created_at": 1790000000,
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_test_123",
                        "plan_id": "plan_test_monthly",
                        "status": "active",
                        "current_end": 1792592000,
                        "notes": {"user_id": "member-123"},
                    }
                }
            },
        }
    ).encode()
    signature = hmac.new(
        b"test_webhook_secret",
        body,
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(ValueError, match="Invalid Razorpay webhook signature"):
        service.process_webhook(body, "not-valid", "event-1")

    assert service.process_webhook(body, signature, "event-1")
    assert repository.webhook["user_id"] == "member-123"
    assert repository.webhook["status"] == "active"
    assert repository.webhook["event_id"] == "event-1"


def test_unrelated_signed_webhook_event_is_ignored(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
    service = RazorpayService(FakeBillingRepository())
    body = b'{"event":"payment.captured","payload":{}}'
    signature = hmac.new(
        b"test_webhook_secret",
        body,
        hashlib.sha256,
    ).hexdigest()

    assert service.process_webhook(body, signature, "payment-event") is False
