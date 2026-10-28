import os
import logging
from threading import Lock

from dotenv import load_dotenv
from pymongo import MongoClient

logger = logging.getLogger(__name__)
load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URL") or os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "github_analyzer")
_client = None
_database = None
_connection_lock = Lock()


def build_mongo_client_kwargs(mongodb_url: str | None) -> dict:
    kwargs = {
        "serverSelectionTimeoutMS": 10000,
        "retryWrites": False,
    }

    if not mongodb_url:
        return kwargs

    url = mongodb_url.strip().lower()
    if url.startswith("mongodb+srv://") or ".mongodb.net" in url or ".mongodb.com" in url:
        kwargs["tls"] = True

    return kwargs


def get_database():
    if not MONGODB_URL or not DATABASE_NAME:
        return None

    global _client, _database
    if _database is not None:
        return _database

    with _connection_lock:
        if _database is not None:
            return _database
        client = MongoClient(MONGODB_URL, **build_mongo_client_kwargs(MONGODB_URL))
        try:
            client.admin.command("ping")
        except Exception:
            client.close()
            logger.exception("MongoDB connection failed; database-backed features are unavailable.")
            return None
        _client = client
        _database = client[DATABASE_NAME]
        return _database


def get_db():
    return get_database()
