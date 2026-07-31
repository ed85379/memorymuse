# app/core/games/games_router.py

from fastapi import APIRouter, HTTPException
from app.core.games import game_service
from app.core.utils import serialize_doc

router = APIRouter(prefix="/api/games", tags=["games"])

@router.get("/")
def get_games():
    games = game_service.list_game_sessions()
    games_clean = serialize_doc(games)
    return {"games": games_clean}

