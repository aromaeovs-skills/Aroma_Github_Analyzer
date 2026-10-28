from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.database.db import get_db

FREE_REPOSITORY_ANALYSES_PER_MONTH = 3
_DATABASE_UNSET = object()


class UsageStorageUnavailable(RuntimeError):
    pass


class MonthlyLimitExceeded(RuntimeError):
    def __init__(self, used: int, limit: int, period: str) -> None:
        self.used = used
        self.limit = limit
        self.period = period
        super().__init__("Monthly repository analysis limit reached.")


class UsageRepository:
    def __init__(self, database=_DATABASE_UNSET) -> None:
        self._default_database = database is _DATABASE_UNSET
        self._collection = (
            database["analysis_usage"]
            if database is not _DATABASE_UNSET and database is not None
            else None
        )
        self._index_ready = False

    @property
    def collection(self):
        if self._default_database and self._collection is None:
            database = get_db()
            if database is not None:
                self._collection = database["analysis_usage"]
        return self._collection

    @staticmethod
    def current_period() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def consume_repository_analysis(
        self,
        user_id: str,
        limit: int = FREE_REPOSITORY_ANALYSES_PER_MONTH,
    ) -> dict:
        if self.collection is None:
            raise UsageStorageUnavailable("MongoDB is required to enforce monthly analysis limits.")

        period = self.current_period()
        try:
            if not self._index_ready:
                self.collection.create_index(
                    [("user_id", 1), ("period", 1)],
                    unique=True,
                    name="unique_user_month",
                )
                self._index_ready = True
            try:
                self.collection.update_one(
                    {"user_id": user_id, "period": period},
                    {"$setOnInsert": {"count": 0}},
                    upsert=True,
                )
            except DuplicateKeyError:
                pass

            record = self.collection.find_one_and_update(
                {
                    "user_id": user_id,
                    "period": period,
                    "count": {"$lt": limit},
                },
                {"$inc": {"count": 1}},
                return_document=ReturnDocument.AFTER,
            )
            if record is None:
                record = self.collection.find_one({"user_id": user_id, "period": period})
                raise MonthlyLimitExceeded(record["count"], limit, period)
            return {"used": record["count"], "limit": limit, "period": period}
        except MonthlyLimitExceeded:
            raise
        except PyMongoError as exc:
            raise UsageStorageUnavailable("Could not enforce the monthly analysis limit.") from exc

    def get_repository_usage(self, user_id: str) -> dict:
        if self.collection is None:
            raise UsageStorageUnavailable("MongoDB is required to retrieve monthly analysis usage.")
        period = self.current_period()
        try:
            record = self.collection.find_one({"user_id": user_id, "period": period})
        except PyMongoError as exc:
            raise UsageStorageUnavailable("Could not retrieve monthly analysis usage.") from exc
        return {
            "used": record["count"] if record else 0,
            "limit": FREE_REPOSITORY_ANALYSES_PER_MONTH,
            "period": period,
        }
