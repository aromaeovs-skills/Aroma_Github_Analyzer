from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.errors import PyMongoError

from app.database.db import get_db


class AnalysisStorageUnavailable(RuntimeError):
    pass


class GitHubRepository:
    def __init__(self):
        self._collection = None
        self._indexes_ready = False

    @property
    def collection(self):
        if self._collection is None:
            database = get_db()
            if database is not None:
                self._collection = database["github_analyses"]
        if self._collection is not None and not self._indexes_ready:
            try:
                self._collection.create_index(
                    [("user_id", 1), ("created_at", DESCENDING)],
                    name="user_analysis_history",
                )
            except PyMongoError as exc:
                raise AnalysisStorageUnavailable(
                    "Could not initialize analysis history indexes."
                ) from exc
            self._indexes_ready = True
        return self._collection

    def save(self, data: dict) -> str:
        if self.collection is None:
            raise AnalysisStorageUnavailable("MongoDB is required to persist analysis results.")

        data["created_at"] = datetime.now(timezone.utc)
        try:
            result = self.collection.insert_one(data)
        except PyMongoError as exc:
            raise AnalysisStorageUnavailable("Could not persist the analysis result.") from exc
        return str(result.inserted_id)

    def get_by_id_for_user(self, analysis_id: str, user_id: str) -> Optional[dict]:
        if self.collection is None:
            raise AnalysisStorageUnavailable("MongoDB is required to retrieve analysis results.")

        if not ObjectId.is_valid(analysis_id):
            return None

        try:
            document = self.collection.find_one(
                {"_id": ObjectId(analysis_id), "user_id": user_id}
            )
        except PyMongoError as exc:
            raise AnalysisStorageUnavailable("Could not retrieve the analysis result.") from exc
        if document:
            document["_id"] = str(document["_id"])
        return document

    def get_latest_by_user(self, user_id: str) -> Optional[dict]:
        if self.collection is None:
            raise AnalysisStorageUnavailable("MongoDB is required to retrieve analysis results.")

        try:
            document = self.collection.find_one(
                {"user_id": user_id},
                sort=[("created_at", DESCENDING)],
            )
        except PyMongoError as exc:
            raise AnalysisStorageUnavailable("Could not retrieve the latest analysis.") from exc
        if document:
            document["_id"] = str(document["_id"])
        return document

    def get_history_by_user(self, user_id: str) -> List[dict]:
        if self.collection is None:
            raise AnalysisStorageUnavailable("MongoDB is required to retrieve analysis results.")

        try:
            documents = list(
                self.collection.find({"user_id": user_id}).sort("created_at", DESCENDING)
            )
        except PyMongoError as exc:
            raise AnalysisStorageUnavailable("Could not retrieve analysis history.") from exc
        for document in documents:
            document["_id"] = str(document["_id"])
        return documents
