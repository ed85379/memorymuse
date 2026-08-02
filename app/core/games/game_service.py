# app/core/games/game_service.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from app.config import MONGO_GAMES_COLLECTION

from app.databases.mongo_connector import mongo

from .game_registry import (
    GameValidationError,
    get_game_definition,
)


class GameNotFoundError(LookupError):
    """The requested durable game session does not exist."""


class GameRevisionConflictError(RuntimeError):
    """
    The game exists, but a different committed action advanced it between
    the caller reading it and attempting to save its next state.
    """


class GameSessionCreateError(RuntimeError):
    """A durable game session could not be created."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _normalize_game_id(game_id: Any) -> str:
    if not isinstance(game_id, str) or not game_id.strip():
        raise GameValidationError(
            "game_id must be a non-empty string."
        )

    return game_id.strip()

def _games_collection() -> Collection:
    return mongo.get_collection(MONGO_GAMES_COLLECTION)


def ensure_game_indexes(
    games_collection: Collection | None = None,
) -> None:
    """
    Call this once during addon startup, or manually during the first cut.

    `game_id` is our stable public/session identity. Mongo may retain its
    normal ObjectId `_id`; there is no need to overload it.
    """
    collection = games_collection or _games_collection()

    collection.create_index(
        [("game_id", ASCENDING)],
        unique=True,
        name="games_game_id_unique",
    )
    collection.create_index(
        [("status", ASCENDING), ("updated_at", DESCENDING)],
        name="games_status_updated_at",
    )
    collection.create_index(
        [("game_type", ASCENDING), ("updated_at", DESCENDING)],
        name="games_type_updated_at",
    )


def _public_game_projection(
    game_doc: dict[str, Any],
    *,
    include_state: bool = False,
) -> dict[str, Any]:
    """
    Convert Mongo's internal document into a stable API/service shape.

    We omit `_id` here. Consumers should use game_id, not leak ObjectIds
    through every game-facing layer.
    """
    result = {
        "game_id": game_doc["game_id"],
        "game_type": game_doc["game_type"],
        "label": game_doc.get("label"),
        "status": game_doc.get("status", "active"),
        "revision": game_doc["revision"],
        "created_at": game_doc["created_at"],
        "updated_at": game_doc["updated_at"],
        "last_turn": game_doc.get("last_turn"),
    }

    if include_state:
        result["state"] = game_doc["state"]

    return result


def create_game_session(
    game_id: str,
    *,
    game_type: str,
    label: str | None = None,
    create_data: dict[str, Any] | None = None,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    """
    Creates a new durable game world at revision 0.

    game_id is created in React with nanoid so optimistic frontend
    insertion can use the same final identity.
    """
    game_id = _normalize_game_id(game_id)

    collection = games_collection or _games_collection()
    definition = get_game_definition(game_type)
    initial_state = definition.create_initial_state(create_data)

    if label is not None and not isinstance(label, str):
        raise GameValidationError(
            "Game label must be a string or null."
        )

    normalized_label = (
        label.strip()
        if isinstance(label, str) and label.strip()
        else definition.label
    )

    now = _utcnow()

    game_doc = {
        "game_id": game_id,
        "game_type": definition.game_type,
        "label": normalized_label,
        "status": "active",
        "revision": 0,
        "state": initial_state,
        "pending_muse_turn": None,
        "last_turn": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        collection.insert_one(game_doc)
    except DuplicateKeyError as exc:
        raise GameSessionCreateError(
            f"Game '{game_id}' already exists."
        ) from exc

    return _public_game_projection(game_doc, include_state=True)


def get_game_session(
    game_id: str,
    *,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    """
    Full canonical session read. This is what the board loader should call.
    """
    collection = games_collection or _games_collection()

    game_doc = collection.find_one({"game_id": game_id})

    if game_doc is None:
        raise GameNotFoundError(f"Game '{game_id}' does not exist.")

    return _public_game_projection(game_doc, include_state=True)


def get_game_context(
    game_id: str,
    *,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    """
    Returns canonical session data plus the game-specific rich context
    projection needed for the board/prompt.

    This is a useful read for:
      - Game Manager opening a game
      - /talk prompt assembly when active_game_id is present
      - frontend reloadBoard()
    """
    collection = games_collection or _games_collection()

    game_doc = collection.find_one({"game_id": game_id})

    if game_doc is None:
        raise GameNotFoundError(f"Game '{game_id}' does not exist.")

    definition = get_game_definition(game_doc["game_type"])

    return {
        **_public_game_projection(game_doc, include_state=True),
        "context_display": definition.build_context_display(
            game_doc["state"],
            game_doc.get("pending_muse_turn"),
        ),
    }


def list_game_sessions(
    *,
    game_type: str | None = None,
    status: str | None = "active",
    limit: int = 50,
    games_collection: Collection | None = None,
) -> list[dict[str, Any]]:
    """
    Lightweight Game Manager listing.

    This intentionally does NOT hydrate full board state for every game.
    Open a selected game through get_game_context() instead.
    """
    collection = games_collection or _games_collection()

    limit = max(1, min(limit, 200))

    query: dict[str, Any] = {}

    if game_type is not None:
        query["game_type"] = game_type

    if status is not None:
        query["status"] = status

    cursor = (
        collection.find(
            query,
            {
                "_id": 0,
                "game_id": 1,
                "game_type": 1,
                "label": 1,
                "status": 1,
                "revision": 1,
                "created_at": 1,
                "updated_at": 1,
                "last_turn": 1,
            },
        )
        .sort("updated_at", DESCENDING)
        .limit(limit)
    )

    return list(cursor)


def apply_take_game_turn(
    *,
    game_id: str,
    expected_revision: int,
    action_data: dict[str, Any],
    actor_role: str,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    """
    Authoritative game mutation seam.

    Used by both:
      - User's submitted composer/turn action
      - Muse's take_game_turn command handler

    The caller is responsible for:
      - resolving/guarding active_game_id;
      - ensuring a model-supplied game_id does not conflict with active_game_id;
      - attaching this accepted result to message metadata;
      - broadcasting/reloading UI state afterward.

    This service is responsible for:
      - loading canonical session state;
      - revision guarding;
      - asking the registered game definition to apply the turn;
      - atomically saving the resulting state;
      - returning normalized accepted truth.
    """
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise GameValidationError(
            "expected_revision must be a non-negative integer."
        )

    if actor_role not in {"user", "muse"}:
        raise GameValidationError(
            "actor_role must be either 'user' or 'muse'."
        )

    if not isinstance(action_data, dict):
        raise GameValidationError(
            "take_game_turn action_data must be an object."
        )

    # The outer service argument and the action envelope must agree.
    # This is partly redundant, but redundancy is cheap here and ambiguity isn't.
    action_revision = action_data.get("expected_revision")

    if action_revision != expected_revision:
        raise GameValidationError(
            "action_data.expected_revision must match expected_revision."
        )

    collection = games_collection or _games_collection()

    current_game = collection.find_one({"game_id": game_id})

    if current_game is None:
        raise GameNotFoundError(
            f"Game '{game_id}' does not exist."
        )

    if current_game.get("status") != "active":
        raise GameValidationError(
            f"Game '{game_id}' is not active and cannot accept a turn."
        )

    actual_revision = current_game["revision"]

    # Friendly early failure. The Mongo update below still guards against a
    # different writer committing after this read.
    if actual_revision != expected_revision:
        raise GameRevisionConflictError(
            f"Game '{game_id}' is at revision {actual_revision}, "
            f"not expected revision {expected_revision}."
        )

    definition = get_game_definition(current_game["game_type"])

    # For chess:
    #
    # user turn:
    #   action_data contains next_state + prepare_muse_turn generated by chess.js.
    #
    # muse turn:
    #   action_data contains the selected move and muse_plan.
    #   The registry looks up the move in current_game["pending_muse_turn"].
    applied = definition.apply_turn(
        current_game["state"],
        current_game.get("pending_muse_turn"),
        action_data,
        actor_role,
    )

    next_state = applied["state"]
    next_pending_muse_turn = applied["pending_muse_turn"]
    turn_result = applied["turn_result"]

    now = _utcnow()
    next_revision = expected_revision + 1

    # This is only the latest transition snapshot for previews/debugging.
    # The durable per-conversation history belongs in message metadata.
    last_turn = {
        "revision": next_revision,
        "actor": actor_role,
        "operation": action_data.get("operation"),
        "result": turn_result,
        "at": now,
    }

    updated_game = collection.find_one_and_update(
        {
            "game_id": game_id,
            "status": "active",
            "revision": expected_revision,
        },
        {
            "$set": {
                "state": next_state,
                "pending_muse_turn": next_pending_muse_turn,
                "last_turn": last_turn,
                "updated_at": now,
            },
            "$inc": {
                "revision": 1,
            },
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated_game is None:
        # The game existed when we read it. A failed compare-and-set now
        # normally means another turn won the race and advanced the board.
        latest_game = collection.find_one(
            {"game_id": game_id},
            {
                "_id": 0,
                "revision": 1,
                "status": 1,
            },
        )

        if latest_game is None:
            raise GameNotFoundError(
                f"Game '{game_id}' disappeared while applying the turn."
            )

        raise GameRevisionConflictError(
            f"Game '{game_id}' changed before this turn could commit. "
            f"Current revision: {latest_game.get('revision')}."
        )

    # This is the normalized accepted result that the caller can place in
    # user-message or Muse-message metadata, and use for UI reconciliation.
    return {
        "action_type": "take_game_turn",
        "game_id": updated_game["game_id"],
        "game_type": updated_game["game_type"],
        "actor": actor_role,
        "previous_revision": expected_revision,
        "revision": updated_game["revision"],
        "operation": action_data.get("operation"),
        "turn_result": turn_result,
        "ui_display": {
            "notation": turn_result.get("notation"),
            "move": turn_result.get("move"),
            "actor": actor_role,
        },
        "context_display": definition.build_context_display(
            updated_game["state"],
            updated_game.get("pending_muse_turn"),
        ),
    }

def update_game_session(
    *,
    game_id: str,
    label: str | None = None,
    status: str | None = None,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    """
    Update manager-owned game metadata.

    This does not mutate canonical game state or revision. Revision remains
    the concurrency guard for actual gameplay transitions.
    """
    game_id = _normalize_game_id(game_id)

    updates: dict[str, Any] = {}

    if label is not None:
        if not isinstance(label, str) or not label.strip():
            raise GameValidationError(
                "Game label must be a non-empty string."
            )

        updates["label"] = label.strip()

    if status is not None:
        if status not in {"active", "archived"}:
            raise GameValidationError(
                "Game status must be 'active' or 'archived'."
            )

        updates["status"] = status

    if not updates:
        raise GameValidationError(
            "No supported game fields were supplied."
        )

    collection = games_collection or _games_collection()

    updates["updated_at"] = _utcnow()

    updated_game = collection.find_one_and_update(
        {"game_id": game_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )

    if updated_game is None:
        raise GameNotFoundError(
            f"Game '{game_id}' does not exist."
        )

    return _public_game_projection(
        updated_game,
        include_state=False,
    )

def archive_game_session(
    game_id: str,
    *,
    games_collection: Collection | None = None,
) -> dict[str, Any]:
    return update_game_session(
        game_id=game_id,
        status="archived",
        games_collection=games_collection,
    )