from pathlib import Path
import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient


# Determine project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Secrets from .env
PROFILE_DIR = os.getenv("PROFILE_DIR")
VOICE_OUTPUT_DIR = os.getenv("VOICE_OUTPUT_DIR")
AUDIO_OUTPUT_PATH = os.getenv("AUDIO_OUTPUT_PATH")
ASSET_STORAGE_ROOT = os.getenv("ASSET_STORAGE_ROOT", "storage/assets")

API_URL = os.getenv("API_URL")
WEBSOCKET_URL = os.getenv("WEBSOCKET_URL")

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_SYSTEM_DB = os.getenv("MONGO_SYSTEM_DB")
# memory collections
MONGO_CONVERSATION_COLLECTION = os.getenv("MONGO_CONVERSATION_COLLECTION")
MONGO_FILES_COLLECTION = os.getenv("MONGO_FILES_COLLECTION")
MONGO_MEMORY_COLLECTION = os.getenv("MONGO_MEMORY_COLLECTION")
MONGO_PROJECTS_COLLECTION = os.getenv("MONGO_PROJECTS_COLLECTION")
MONGO_PROFILE_COLLECTION = os.getenv("MONGO_PROFILE_COLLECTION")
MONGO_THREADS_COLLECTION = os.getenv("MONGO_THREADS_COLLECTION")
MONGO_JOURNAL_COLLECTION = os.getenv("MONGO_JOURNAL_COLLECTION")
MONGO_ASSETS_COLLECTION = os.getenv("MONGO_ASSETS_COLLECTION")
# system collections
MONGO_STATES_COLLECTION = os.getenv("MONGO_STATES_COLLECTION")
MONGO_LOGS_COLLECTION = os.getenv("MONGO_LOGS_COLLECTION")
MONGO_USER_SETTINGS_COLLECTION = os.getenv("MONGO_USER_SETTINGS_COLLECTION")

ADMIN_MONGO_URI = os.getenv("ADMIN_MONGO_URI")
ADMIN_MONGO_DB = os.getenv("ADMIN_MONGO_DB")
ADMIN_MONGO_COLLECTION = os.getenv("ADMIN_MONGO_COLLECTION")

QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = os.getenv("QDRANT_PORT")
QDRANT_CONVERSATION_COLLECTION = os.getenv("QDRANT_CONVERSATION_COLLECTION")
QDRANT_MEMORY_COLLECTION = os.getenv("QDRANT_MEMORY_COLLECTION")
QDRANT_ENTITY_COLLECTION = os.getenv("QDRANT_ENTITY_COLLECTION")
QDRANT_JOURNAL_COLLECTION = os.getenv("QDRANT_JOURNAL_COLLECTION")

GRAPHDB_HOST = os.getenv("GRAPHDB_HOST")
GRAPHDB_PORT = os.getenv("GRAPHDB_PORT")

SENTENCE_TRANSFORMER_ENTITY_MODEL = os.getenv("SENTENCE_TRANSFORMER_ENTITY_MODEL")
SENTENCE_TRANSFORMER_MODEL = os.getenv("SENTENCE_TRANSFORMER_MODEL")
# Temporary until journal overhaul
JOURNAL_CATALOG_PATH = os.getenv("JOURNAL_CATALOG_PATH")
JOURNAL_DIR = os.getenv("JOURNAL_DIR")

class MuseConfig:
    def __init__(self, mongo_uri, db_name, live_collection, default_collection):
        self.client = MongoClient(mongo_uri)
        self.live = self.client[db_name][live_collection]
        self.defaults = self.client[db_name][default_collection]

    def get(self, key, default=None):
        # 1. Try live/dynamic setting
        doc = self.live.find_one({"_id": key})
        if doc and "value" in doc:
            return doc["value"]
        # 2. Fallback to default_config collection
        doc = self.defaults.find_one({"_id": key})
        if doc and "value" in doc:
            return doc["value"]
        # 3. Final fallback
        return default

    def set(self, key, value):
        self.live.update_one(
            {"_id": key}, {"$set": {"value": value}}, upsert=True
        )

    def as_dict(self, include_meta=True, pollable_only=False):
        # 1) Load defaults, optionally filtered by pollable
        default_query = {}
        if pollable_only:
            default_query["pollable"] = True

        default_docs = {doc["_id"]: doc for doc in self.defaults.find(default_query)}

        # 2) Load live docs only for the keys we care about
        if default_docs:
            live_query = {"_id": {"$in": list(default_docs.keys())}}
            live_docs = {doc["_id"]: doc for doc in self.live.find(live_query)}
        else:
            live_docs = {}

        # 3) If not pollable_only, we also want any purely-live keys
        if not pollable_only:
            # Grab all live docs, then merge with defaults
            extra_live_docs = {
                doc["_id"]: doc
                for doc in self.live.find({})
                if doc["_id"] not in default_docs
            }
            live_docs.update(extra_live_docs)

        # 4) Union of keys
        all_keys = set(default_docs) | set(live_docs)

        result = {}
        for key in all_keys:
            live_doc = live_docs.get(key)
            default_doc = default_docs.get(key)

            # Value: live > default > None
            if live_doc and "value" in live_doc:
                value = live_doc["value"]
            elif default_doc and "value" in default_doc:
                value = default_doc["value"]
            else:
                value = None

            entry = {"value": value}

            if include_meta:
                # description
                if (live_doc and "description" in live_doc) or (default_doc and "description" in default_doc):
                    entry["description"] = (
                        live_doc.get("description")
                        if live_doc and "description" in live_doc
                        else default_doc.get("description", "")
                    )
                else:
                    entry["description"] = ""

                # category
                if (live_doc and "category" in live_doc) or (default_doc and "category" in default_doc):
                    entry["category"] = (
                        live_doc.get("category")
                        if live_doc and "category" in live_doc
                        else default_doc.get("category", "uncategorized")
                    )
                else:
                    entry["category"] = "uncategorized"


            result[key] = entry

        return result

    def as_grouped(self, include_meta=True):
        """
        Return config as {category: [entries...]} for grouping in the UI.
        Each entry: {"key": ..., "value": ..., "description": ..., "category": ...}
        """
        live_docs = {doc["_id"]: doc for doc in self.live.find({})}
        default_docs = {doc["_id"]: doc for doc in self.defaults.find({})}
        all_keys = set(live_docs) | set(default_docs)

        grouped = {}
        for key in all_keys:
            live_doc = live_docs.get(key)
            default_doc = default_docs.get(key)
            # Value: live > default > None
            if live_doc and "value" in live_doc:
                value = live_doc["value"]
            elif default_doc and "value" in default_doc:
                value = default_doc["value"]
            else:
                value = None

            # Prefer meta fields from live, else fallback to default
            if include_meta:
                if (live_doc and "description" in live_doc) or (default_doc and "description" in default_doc):
                    description = (live_doc.get("description") if live_doc and "description" in live_doc
                                   else default_doc.get("description", ""))
                else:
                    description = ""
                if (live_doc and "category" in live_doc) or (default_doc and "category" in default_doc):
                    category = (live_doc.get("category") if live_doc and "category" in live_doc
                                else default_doc.get("category", "uncategorized"))
                else:
                    category = "uncategorized"
            else:
                description = ""
                category = "uncategorized"

            entry = {
                "key": key,
                "value": value,
                "description": description,
                "category": category
            }
            grouped.setdefault(category, []).append(entry)
        return grouped

muse_config = MuseConfig(
    mongo_uri=MONGO_URI,
    db_name=MONGO_SYSTEM_DB,
    live_collection="muse_config",
    default_collection="default_config"
)

class AdminConfig:
    def __init__(self, mongo_uri, db_name, collection, doc_id="instance_configs"):
        client = MongoClient(mongo_uri)
        self.collection = client[db_name][collection]
        self.doc_id = doc_id

    def get_all(self):
        doc = self.collection.find_one({"_id": self.doc_id}) or {}
        return doc

    def get_section(self, section, default=None):
        doc = self.get_all()
        return doc.get(section, default or {})

    def get(self, section, key, default=None):
        data = self.get_section(section)
        return data.get(key, default)

    def set(self, section, key, value):
        self.collection.update_one(
            {"_id": self.doc_id},
            {"$set": {f"{section}.{key}": value}},
            upsert=True,
        )

admin_config = AdminConfig(
    mongo_uri=ADMIN_MONGO_URI,
    db_name=ADMIN_MONGO_DB,
    collection=ADMIN_MONGO_COLLECTION,
)

class MuseSettings:
    def __init__(self, mongo_uri, db_name, collection, doc_id="user_settings"):
        client = MongoClient(mongo_uri)
        self.collection = client[db_name][collection]
        self.doc_id = doc_id

    def get_all(self):
        doc = self.collection.find_one({"_id": self.doc_id}) or {}
        return doc

    def get_section(self, section, default=None):
        doc = self.get_all()
        return doc.get(section, default or {})

    def update_section(self, section, data):
        self.collection.update_one(
            {"_id": self.doc_id},
            {"$set": {section: data}},
            upsert=True,
        )

muse_settings = MuseSettings(
    mongo_uri=MONGO_URI,
    db_name=MONGO_SYSTEM_DB,
    collection=MONGO_USER_SETTINGS_COLLECTION,
)