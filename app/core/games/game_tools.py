import secrets
from typing import Any
from app.config import muse_settings

MUSE_NAME = muse_settings.get_section('muse_config').get('MUSE_NAME')

ALLOWED_DIE_SIDES = frozenset({2, 4, 6, 8, 10, 12, 20, 100})
MAX_DICE_COUNT = 100
MAX_ABS_MODIFIER = 10_000
ALLOWED_ROLL_VISIBILITIES = frozenset({"shared", "hidden"})


def roll_dice_handler(
    *,
    sides: int,
    count: int,
    modifier: int,
    reason: str | None,
    visibility: str,
    **_runtime_kwargs: Any,
) -> dict[str, Any]:
    """
    Roll a constrained set of standard dice.

    The full result returns to Iris through the function-tool loop.
    Registry projection / UI rendering decides what Ed sees for
    shared versus hidden rolls.
    """

    # bool is technically an int in Python. It is not a die size,
    # die count, or modifier.
    for field_name, value in (
        ("sides", sides),
        ("count", count),
        ("modifier", modifier),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")

    if sides not in ALLOWED_DIE_SIDES:
        allowed = ", ".join(str(value) for value in sorted(ALLOWED_DIE_SIDES))
        raise ValueError(f"sides must be one of: {allowed}")

    if not 1 <= count <= MAX_DICE_COUNT:
        raise ValueError(
            f"count must be between 1 and {MAX_DICE_COUNT}"
        )

    if abs(modifier) > MAX_ABS_MODIFIER:
        raise ValueError(
            f"modifier must be between "
            f"{-MAX_ABS_MODIFIER} and {MAX_ABS_MODIFIER}"
        )

    if reason is not None and not isinstance(reason, str):
        raise ValueError("reason must be a string or null")

    if visibility not in ALLOWED_ROLL_VISIBILITIES:
        raise ValueError("visibility must be either 'shared' or 'hidden'")

    rolls = [
        secrets.randbelow(sides) + 1
        for _ in range(count)
    ]

    dice_total = sum(rolls)
    total = dice_total + modifier

    expression = f"{count}d{sides}"
    if modifier > 0:
        expression += f"+{modifier}"
    elif modifier < 0:
        expression += str(modifier)

    roll_result = {
        "expression": expression,
        "sides": sides,
        "count": count,
        "modifier": modifier,
        "rolls": rolls,
        "dice_total": dice_total,
        "total": total,
        "reason": reason,
        "visibility": visibility,
    }

    return {
        "tool_output": roll_result,
        "attachments": [],
        "tool_results": [
            {
                "kind": "dice_roll",
                "visibility": visibility,
                "expression": expression,
                "rolls": rolls,
                "dice_total": dice_total,
                "modifier": modifier,
                "total": total,
                "reason": reason,
            }
        ],
    }


def render_dice_roll_history(receipt: dict) -> str | None:
    if receipt.get("kind") != "dice_roll":
        return None

    rolls = receipt.get("rolls") or []
    expression = receipt.get("expression") or "dice"
    modifier = receipt.get("modifier", 0)
    total = receipt.get("total")
    visibility = receipt.get("visibility", "shared")
    reason = receipt.get("reason") or "unspecified"

    return (
        f"[Dice roll — {visibility}] "
        f"{expression} → {rolls} + {modifier} = {total}. "
        f"Reason: {reason}"
    )

TOOL_REGISTRY = {
    "roll_dice": {
        "schema": {
            "type": "function",
            "name": "roll_dice",
            "description": (
                "Roll dice before responding when a game or scene has meaningful "
                "uncertainty. Choose only standard die sizes. Use visibility='shared' "
                "when Ed should see the roll details, or visibility='hidden' when "
                "the roll should be recorded as having happened but its result and "
                "reason must not be shown in the UI."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "sides": {
                        "type": "integer",
                        "enum": [2, 4, 6, 8, 10, 12, 20, 100],
                        "description": "Sides per die. Use 2 for a coin-flip-style roll."
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Number of dice to roll."
                    },
                    "modifier": {
                        "type": "integer",
                        "minimum": -10000,
                        "maximum": 10000,
                        "description": "Flat modifier added to the dice total. Use 0 when none."
                    },
                    "reason": {
                        "type": ["string", "null"],
                        "description": "Brief reason for the roll, or null if none."
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["shared", "hidden"],
                        "description": "Whether roll details are visible to Ed in the UI."
                    }
                },
                "required": [
                    "sides",
                    "count",
                    "modifier",
                    "reason",
                    "visibility"
                ],
                "additionalProperties": False
            },
        },
        "ui": {
            "start": f"{MUSE_NAME} is rolling dice…",
            "error": "The dice are cocked."
        },
        "handler": roll_dice_handler,
        "render_history": render_dice_roll_history,
    },
}

def register_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Game Tools: {name}")
        registry.register(name, handler)

