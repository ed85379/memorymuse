# app/core/games/game_commands.py
# This file contains the commands that are specific to the games subsystem

import asyncio
from app.config import muse_settings
from app.core.games.game_service import take_game_turn_command_handler, build_turn_action_metadata

# Commands + intent triggers
COMMANDS = {
    "take_game_turn": {
        "triggers": [],
        "description": (
            "Commit your authoritative turn in the active game. Use an exact move or transition "
            "from the legal choices supplied in current game context. Every turn must explicitly "
            "replace, revise, reaffirm, or clear muse_plan; do not silently retain a stale plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "move": {
                    "type": "string",
                    "description": (
                        "An exact legal move or transition from the active game's supplied legal choices."
                    ),
                },
                "muse_plan": {
                    "type": ["string", "null"],
                    "description": (
                        "Iris's new, revised, or explicitly reaffirmed strategic plan for the next "
                        "game context; use null when no coherent plan remains."
                    ),
                },
            },
            "required": ["move", "muse_plan"],
            "additionalProperties": False,
        },
        "format": (
            '<command name="take_game_turn"> '
            '{"move": "<exact move from Legal moves>", '
            '"muse_plan": "<new, revised, reaffirmed plan, or null>"} '
            '</command>'
        ),
        "handler": lambda payload, **kwargs: take_game_turn_command_handler(
            payload,
            **kwargs,
        ),
        "filter": lambda result: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} took their turn.",
            "hidden": ""
        },
        "message_metadata": lambda result: {
            "turn_actions": [
                #build_turn_action_metadata(result)
                result.get("message_metadata")
            ]
        },
    },
}


def register_game_commands(registry):
    for name, handler in COMMANDS.items():
        print(f"Registering Games Command: {name}")
        registry.register(name, handler)