# app/core/conversation/status_sinks.py

from datetime import datetime, timezone
from typing import Any

def make_webui_status_sink(
    *,
    muse_name: str,
    broadcast_message,
):
    async def webui_status_sink(
        event: str,
        function_name: str | None,
        status_ui_meta: dict[str, Any] | None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()

        if event == "thinking":
            message = f"{muse_name} is thinking..."

        elif event == "tool_start":
            message = (
                (status_ui_meta or {})
                .get(function_name or "", {})
                .get("start", f"Running {function_name}...")
            )

        elif event == "tool_error":
            message = (
                (status_ui_meta or {})
                .get(function_name or "", {})
                .get("error", f"Error running {function_name}")
            )

        else:
            return

        await broadcast_message(
            message=message,
            timestamp=timestamp,
            role="muse",
            to_modality="webui",
            payload_type="status_message",
        )

    return webui_status_sink


def resolve_status_sink(
    *,
    prompt_type: str,
    muse_name: str,
    broadcast_message,
):
    if prompt_type == "webui":
        return make_webui_status_sink(
            muse_name=muse_name,
            broadcast_message=broadcast_message,
        )

    return None