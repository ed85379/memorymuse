# app/databases/mongo_connector.py
from typing import Optional, Dict, Any
from pymongo import MongoClient, ASCENDING, ReturnDocument
from pymongo.database import Database
from pymongo.collection import Collection
from datetime import datetime
from app.config import MONGO_URI, MONGO_DB, MONGO_SYSTEM_DB



class MongoConnector:
    def __init__(self, uri, db_name=MONGO_DB):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        # Example: self.db['muse_log']

    def ensure_mongo_collection(self,
            collection_name: str,
            *,
            create_options: Optional[Dict[str, Any]] = None,
    ) -> Collection:
        """
        Ensure a MongoDB collection exists and return a handle to it.

        - If the collection already exists, just return db[name].
        - If it doesn't, create it (optionally with options) and return it.

        `create_options` can include things like:
          - capped: bool
          - size: int
          - max: int
          - validator: dict
          - validationLevel: str
          - validationAction: str
          - etc.
        """
        if collection_name in self.db.list_collection_names():
            return self.db[collection_name]

        create_options = create_options or {}

        # This will create the collection if it doesn't exist.
        self.db.create_collection(collection_name, **create_options)
        return self.db[collection_name]

    def get_collection(self, collection_name):
        return self.db[collection_name]

    def ensure_index(self, collection_name, field):
        self.db[collection_name].create_index([(field, ASCENDING)])

    def count_matching_documents(self, collection_name, query):
        count = self.db[collection_name].count_documents(query)
        return count

    def run_aggregate(self, collection_name, pipeline):
        return self.db[collection_name].aggregate(pipeline)

    def insert_log(self, collection_name, log_entry):
        self.db[collection_name].insert_one(log_entry)

    def insert_logs_bulk(self, collection_name, log_entries):
        self.db[collection_name].insert_many(log_entries)

    def find_documents(self, collection_name, query=None, projection=None, sort=None, sort_field=None, limit=None, skip=None):
        cursor = self.db[collection_name].find(query or {}, projection)
        if sort_field:
            cursor = cursor.sort(sort_field, sort if sort is not None else 1)  # 1=ASC, -1=DESC
        if limit:
            cursor = cursor.limit(limit)
        if skip:
            cursor = cursor.skip(skip)
        return list(cursor)

    def find_one_document(self, collection_name, query=None, projection=None):
        return self.db[collection_name].find_one(query or {}, projection)

    def insert_one_document(self, collection_name, doc):
        self.db[collection_name].insert_one(doc)

    def update_one_document(self, collection_name, filter_query, update_data):
        # Returns the updated document after the change
        return self.db[collection_name].find_one_and_update(
            filter_query,
            {"$set": update_data},
            return_document=ReturnDocument.AFTER
        )

    def update_one_document_array(self, collection_name, filter_query, update_data):
        # Returns the updated document after the change
        return self.db[collection_name].find_one_and_update(
            filter_query,
            update_data,
            return_document=ReturnDocument.AFTER
        )

    def update_many_documents(self, collection_name, filter_query, update_data):
        """
        Apply a Mongo update document to every matching document.

        Returns PyMongo's UpdateResult, including matched_count and modified_count.
        """
        return self.db[collection_name].update_many(
            filter_query,
            update_data,
        )

    def delete_one_document(self, collection_name, query):
        return self.db[collection_name].delete_one(query)

    def find_logs(self, collection_name, query=None, limit=100, sort_field="timestamp", ascending=True):
        cursor = self.db[collection_name].find(query or {})
        if ascending:
            cursor = cursor.sort(sort_field, ASCENDING)
        else:
            cursor = cursor.sort(sort_field, -1)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)

    def update_logs(self, collection_name, filter_query, update_data):
        return self.db[collection_name].update_many(filter_query, {"$set": update_data})

    def move_logs(self, from_collection, to_collection, filter_query):
        docs = list(self.db[from_collection].find(filter_query))
        if docs:
            self.db[to_collection].insert_many(docs)
            self.db[from_collection].delete_many(filter_query)
        return len(docs)

    def count_logs(self, collection_name, filter_query=None):
        return self.db[collection_name].count_documents(filter_query or {})

    def delete_mongo_message(self, collection_name, message_id: str) -> bool:
        mongo_result = self.db[collection_name].delete_one({"message_id": message_id})
        if mongo_result.deleted_count == 1:
            print(f"MongoDB: Deleted {message_id}.")
            return True

        print(f"MongoDB: Could NOT delete {message_id} (not found?).")
        return False

    # Add more as needed


mongo = MongoConnector(uri=MONGO_URI, db_name=MONGO_DB)
mongo_system = MongoConnector(uri=MONGO_URI, db_name=MONGO_SYSTEM_DB)
