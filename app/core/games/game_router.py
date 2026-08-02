# app/core/games/game_router.py

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field

from app.core.games import game_service
from app.core.games.game_registry import (
    GameValidationError,
    list_game_definitions,
)
from app.core.utils import serialize_doc


router = APIRouter(
    prefix="/api/games",
    tags=["games"],
)


class GameCreateRequest(BaseModel):
    # React creates this with nanoid so the frontend can optimistically
    # insert the game before the backend responds.
    game_id: str = Field(min_length=1, max_length=128)

    game_type: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=200)
    create_data: dict[str, Any] | None = None


class GameUpdateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None


def _model_dump(model: BaseModel, **kwargs) -> dict[str, Any]:
    """
    Small Pydantic v1/v2 compatibility seam.
    """
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)

    return model.dict(**kwargs)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, game_service.GameNotFoundError):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if isinstance(exc, game_service.GameSessionCreateError):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if isinstance(exc, GameValidationError):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    raise exc


@router.get("/types")
def get_game_types():
    """
    Registry-backed list for the Game Manager's create panel.
    """
    return {
        "game_types": list_game_definitions(),
    }


@router.get("/")
def get_games(
    game_type: str | None = None,
    status: Literal["active", "archived", "all"] = "active",
    limit: int = Query(default=100, ge=1, le=200),
):
    """
    Lightweight Game Manager listing.

    Games are global/co-equal durable entities. There is deliberately no
    project_id or thread_id filter here.
    """
    try:
        status_filter = None if status == "all" else status

        games = game_service.list_game_sessions(
            game_type=game_type,
            status=status_filter,
            limit=limit,
        )

        return {
            "games": serialize_doc(games),
        }
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/", status_code=http_status.HTTP_201_CREATED)
def create_game(payload: GameCreateRequest):
    try:
        game = game_service.create_game_session(
            payload.game_id,
            game_type=payload.game_type,
            label=payload.label,
            create_data=payload.create_data,
        )

        return {
            "game": serialize_doc(game),
        }
    except Exception as exc:
        _raise_service_error(exc)


@router.get("/{game_id}")
def get_game(game_id: str):
    """
    Full canonical game context for opening/reloading a board.
    """
    try:
        game = game_service.get_game_context(game_id)

        return {
            "game": serialize_doc(game),
        }
    except Exception as exc:
        _raise_service_error(exc)


@router.patch("/{game_id}")
def update_game(
    game_id: str,
    payload: GameUpdateRequest,
):
    patch = _model_dump(payload, exclude_unset=True)

    if not patch:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one game field must be supplied.",
        )

    try:
        game = game_service.update_game_session(
            game_id=game_id,
            label=patch.get("label"),
            status=patch.get("status"),
        )

        return {
            "game": serialize_doc(game),
        }
    except Exception as exc:
        _raise_service_error(exc)