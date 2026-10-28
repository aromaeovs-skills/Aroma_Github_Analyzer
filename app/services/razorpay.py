import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from app.database.billing_repository import BillingRepository, BillingStorageUnavailable

logger = logging.getLogger(__name__)
RAZORPAY_API_URL = "https://api.razorpay.com/v1"


class BillingConfigurationError(RuntimeError):
    pass


class BillingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RazorpaySettings:
    key_id: str
    key_secret: str
    plan_id: str
    webhook_secret: str
    total_count: int

    @classmethod
    def from_environment(
        cls,
        *,
        require_api: bool = True,
        require_plan: bool = True,
        require_webhook: bool = False,
    ) -> "RazorpaySettings":
        key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        plan_id = os.getenv("RAZORPAY_PLAN_ID", "").strip()
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
        total_count_value = os.getenv("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", "").strip()
        if require_api and (not key_id or not key_secret):
            raise BillingConfigurationError(
                "Configure RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."
            )
        if require_plan and not plan_id:
            raise BillingConfigurationError("Configure RAZORPAY_PLAN_ID.")
        if require_webhook and not webhook_secret:
            raise BillingConfigurationError("Configure RAZORPAY_WEBHOOK_SECRET.")
        total_count = 0
        if require_plan:
            try:
                total_count = int(total_count_value)
            except ValueError as exc:
                raise BillingConfigurationError(
                    "Set RAZORPAY_SUBSCRIPTION_TOTAL_COUNT to a value from 1 to 100."
                ) from exc
            if not 1 <= total_count <= 100:
                raise BillingConfigurationError(
                    "RAZORPAY_SUBSCRIPTION_TOTAL_COUNT must be from 1 to 100."
                )
        return cls(key_id, key_secret, plan_id, webhook_secret, total_count)


class RazorpayService:
    def __init__(self, repository: BillingRepository | None = None) -> None:
        self.repository = repository or BillingRepository()

    @staticmethod
    def _request(method: str, path: str, settings: RazorpaySettings, **kwargs) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{RAZORPAY_API_URL}{path}",
                auth=(settings.key_id, settings.key_secret),
                timeout=(5, 20),
                **kwargs,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.warning("Razorpay API request failed: %s", type(exc).__name__)
            raise BillingProviderError("The payment provider request failed.") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise BillingProviderError("The payment provider returned an invalid response.") from exc
        if not isinstance(data, dict):
            raise BillingProviderError("The payment provider returned an invalid response.")
        return data

    def create_subscription(self, user_id: str) -> dict[str, Any]:
        settings = RazorpaySettings.from_environment()
        latest = self.repository.get_latest_subscription(user_id)
        if latest and latest["status"] in {"created", "authenticated", "pending"}:
            raise ValueError("A subscription is already awaiting payment.")
        if self.repository.is_premium_member(user_id):
            raise ValueError("The member already has an active premium subscription.")

        data = self._request(
            "POST",
            "/subscriptions",
            settings,
            json={
                "plan_id": settings.plan_id,
                "total_count": settings.total_count,
                "customer_notify": 1,
                "notes": {"user_id": user_id},
            },
        )
        subscription_id = data.get("id")
        if not isinstance(subscription_id, str) or not subscription_id:
            raise BillingProviderError("The payment provider omitted the subscription ID.")
        checkout_url = data.get("short_url")
        parsed_checkout_url = urlsplit(checkout_url) if isinstance(checkout_url, str) else None
        if (
            parsed_checkout_url is None
            or parsed_checkout_url.scheme != "https"
            or not parsed_checkout_url.hostname
            or not (
                parsed_checkout_url.hostname == "rzp.io"
                or parsed_checkout_url.hostname.endswith(".razorpay.com")
            )
        ):
            try:
                self._request(
                    "POST",
                    f"/subscriptions/{quote(subscription_id, safe='')}/cancel",
                    settings,
                    json={"cancel_at_cycle_end": 0},
                )
            except BillingProviderError:
                logger.exception("Could not cancel a subscription with an invalid checkout URL.")
            raise BillingProviderError("The payment provider returned an invalid checkout URL.")

        try:
            self.repository.save_created_subscription(
                user_id=user_id,
                subscription_id=subscription_id,
                plan_id=settings.plan_id,
                status=str(data.get("status", "created")),
                short_url=checkout_url,
            )
        except BillingStorageUnavailable:
            logger.exception("Could not save a newly created Razorpay subscription.")
            try:
                self._request(
                    "POST",
                    f"/subscriptions/{quote(subscription_id, safe='')}/cancel",
                    settings,
                    json={"cancel_at_cycle_end": 0},
                )
            except BillingProviderError:
                logger.exception("Could not cancel an unpersisted Razorpay subscription.")
            raise
        return {
            "subscription_id": subscription_id,
            "status": data.get("status", "created"),
            "checkout_url": checkout_url,
        }

    def cancel_subscription(self, user_id: str, cancel_at_cycle_end: bool) -> dict[str, Any]:
        settings = RazorpaySettings.from_environment(require_plan=False)
        current = self.repository.get_latest_subscription(user_id)
        if not current or current["status"] != "active":
            raise ValueError("No active subscription is available to cancel.")

        self._request(
            "POST",
            f"/subscriptions/{quote(current['subscription_id'], safe='')}/cancel",
            settings,
            json={"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0},
        )
        self.repository.request_cancellation(user_id, cancel_at_cycle_end)
        return {
            "subscription_id": current["subscription_id"],
            "status": "cancellation_requested",
            "cancel_at_cycle_end": cancel_at_cycle_end,
        }

    @staticmethod
    def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def process_webhook(self, body: bytes, signature: str, event_id: str | None) -> bool:
        settings = RazorpaySettings.from_environment(
            require_api=False,
            require_plan=False,
            require_webhook=True,
        )
        if not self.verify_webhook_signature(body, signature, settings.webhook_secret):
            raise ValueError("Invalid Razorpay webhook signature.")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid Razorpay webhook JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Invalid Razorpay webhook payload.")

        event = payload.get("event")
        if event not in {
            "subscription.activated",
            "subscription.charged",
            "subscription.cancelled",
            "subscription.completed",
            "subscription.halted",
            "subscription.paused",
            "subscription.pending",
            "subscription.resumed",
            "subscription.updated",
        }:
            return False

        event_payload = payload.get("payload")
        subscription_payload = (
            event_payload.get("subscription")
            if isinstance(event_payload, dict)
            else None
        )
        entity = (
            subscription_payload.get("entity")
            if isinstance(subscription_payload, dict)
            else None
        )
        if not isinstance(entity, dict):
            raise ValueError("Webhook does not contain a subscription entity.")
        subscription_id = entity.get("id")
        notes = entity.get("notes") or {}
        user_id = notes.get("user_id") if isinstance(notes, dict) else None
        if not isinstance(subscription_id, str) or not isinstance(user_id, str) or not user_id:
            raise ValueError("Webhook subscription is missing its member mapping.")

        incoming_event_id = event_id or hashlib.sha256(body).hexdigest()
        if not isinstance(incoming_event_id, str) or not incoming_event_id.strip():
            raise ValueError("Invalid Razorpay webhook event ID.")

        status = entity.get("status")
        if not isinstance(status, str):
            status = "active" if event in {"subscription.activated", "subscription.charged"} else "unknown"

        current_end = entity.get("current_end")
        if not isinstance(current_end, int):
            current_end = None
        event_created_at = payload.get("created_at")
        if not isinstance(event_created_at, int):
            event_created_at = None

        return self.repository.apply_webhook(
            event_id=incoming_event_id,
            subscription_id=subscription_id,
            user_id=user_id,
            plan_id=str(entity.get("plan_id", "")),
            status=status,
            current_end=current_end,
            event_created_at=event_created_at,
        )
