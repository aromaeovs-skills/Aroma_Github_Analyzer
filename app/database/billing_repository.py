from datetime import datetime, timezone
import time

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.database.db import get_db


class BillingStorageUnavailable(RuntimeError):
    pass


class BillingRepository:
    def __init__(self) -> None:
        self._subscriptions = None
        self._events = None
        self._indexes_ready = False

    def _collections(self):
        if self._subscriptions is None:
            database = get_db()
            if database is None:
                raise BillingStorageUnavailable("MongoDB is required for subscription state.")
            self._subscriptions = database["billing_subscriptions"]
            self._events = database["billing_webhook_events"]

        if not self._indexes_ready:
            try:
                self._subscriptions.create_index(
                    [("subscription_id", 1)],
                    unique=True,
                    name="unique_razorpay_subscription",
                )
                self._subscriptions.create_index(
                    [("user_id", 1), ("updated_at", DESCENDING)],
                    name="member_subscription_history",
                )
                self._events.create_index(
                    [("event_id", 1)],
                    unique=True,
                    name="unique_razorpay_event",
                )
            except PyMongoError as exc:
                raise BillingStorageUnavailable(
                    "Could not initialize billing indexes."
                ) from exc
            self._indexes_ready = True
        return self._subscriptions, self._events

    def is_premium_member(self, user_id: str) -> bool:
        subscriptions, _ = self._collections()
        try:
            return subscriptions.find_one(
                {
                    "user_id": user_id,
                    "status": "active",
                    "$or": [
                        {"current_end": {"$gt": int(time.time())}},
                        {"current_end": {"$exists": False}},
                        {"current_end": None},
                    ],
                },
                {"_id": 1},
            ) is not None
        except PyMongoError as exc:
            raise BillingStorageUnavailable(
                "Could not verify the member subscription."
            ) from exc

    def get_latest_subscription(self, user_id: str) -> dict | None:
        subscriptions, _ = self._collections()
        try:
            record = subscriptions.find_one(
                {"user_id": user_id},
                sort=[("updated_at", DESCENDING)],
            )
        except PyMongoError as exc:
            raise BillingStorageUnavailable(
                "Could not retrieve the member subscription."
            ) from exc
        return self._public_subscription(record) if record else None

    @staticmethod
    def _public_subscription(record: dict) -> dict:
        return {
            "subscription_id": record["subscription_id"],
            "status": record.get("status", "created"),
            "cancel_at_cycle_end": record.get("cancel_at_cycle_end", False),
            "current_end": record.get("current_end"),
            "updated_at": record.get("updated_at"),
        }

    def save_created_subscription(
        self,
        *,
        user_id: str,
        subscription_id: str,
        plan_id: str,
        status: str,
        short_url: str | None,
    ) -> None:
        subscriptions, _ = self._collections()
        now = datetime.now(timezone.utc)
        try:
            subscriptions.update_one(
                {"subscription_id": subscription_id},
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "subscription_id": subscription_id,
                        "plan_id": plan_id,
                        "status": status,
                        "short_url": short_url,
                        "cancel_at_cycle_end": False,
                        "created_at": now,
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
        except PyMongoError as exc:
            raise BillingStorageUnavailable(
                "Could not persist the new subscription."
            ) from exc

    def request_cancellation(self, user_id: str, cancel_at_cycle_end: bool) -> dict | None:
        subscriptions, _ = self._collections()
        try:
            record = subscriptions.find_one_and_update(
                {
                    "user_id": user_id,
                    "status": "active",
                },
                {
                    "$set": {
                        "cancel_at_cycle_end": cancel_at_cycle_end,
                        "cancellation_requested_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                sort=[("updated_at", DESCENDING)],
                return_document=False,
            )
        except PyMongoError as exc:
            raise BillingStorageUnavailable(
                "Could not update the member subscription."
            ) from exc
        return self._public_subscription(record) if record else None

    def apply_webhook(
        self,
        *,
        event_id: str,
        subscription_id: str,
        user_id: str,
        plan_id: str,
        status: str,
        current_end: int | None,
        event_created_at: int | None,
    ) -> bool:
        subscriptions, events = self._collections()
        now = datetime.now(timezone.utc)
        try:
            existing = events.find_one({"event_id": event_id}, {"_id": 1})
            if existing:
                return False

            current = subscriptions.find_one(
                {"subscription_id": subscription_id},
                {"user_id": 1, "last_event_created_at": 1},
            )
            if current and current.get("user_id") != user_id:
                raise ValueError("The webhook subscription owner does not match.")
            if (
                current
                and event_created_at is not None
                and current.get("last_event_created_at", 0) > event_created_at
            ):
                events.insert_one({"event_id": event_id, "received_at": now})
                return False

            update = {
                "user_id": user_id,
                "subscription_id": subscription_id,
                "plan_id": plan_id,
                "status": status,
                "current_end": current_end,
                "updated_at": now,
            }
            if event_created_at is not None:
                update["last_event_created_at"] = event_created_at
            subscriptions.update_one(
                {"subscription_id": subscription_id},
                {
                    "$set": update,
                    "$setOnInsert": {"created_at": now, "cancel_at_cycle_end": False},
                },
                upsert=True,
            )
            events.insert_one({"event_id": event_id, "received_at": now})
            return True
        except DuplicateKeyError:
            return False
        except ValueError:
            raise
        except PyMongoError as exc:
            raise BillingStorageUnavailable(
                "Could not apply the subscription webhook."
            ) from exc
