
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re, json, humanize
from app.core.time_location_utils import get_formatted_datetime, _load_user_location
from app.config import (
    muse_settings,
)
from app.core.text_filters import get_text_filter_config, filter_text
from app.core.games.game_service import format_game_metadata_for_history, format_turn_actions_for_history

LOCATIONS = {
    "frontend": "UI / Frontend",
    "webui": "WebUI / Frontend",
    "discord": "Discord",
    "smartspeaker": "Smart-Speaker",
    "asset_text_chunk": "Uploaded Asset",
}

def strip_command_blocks(text):
    def summarize(match):
        block = match.group(0)

        # Extract internal-data
        internal_match = re.search(
            r"<internal-data>(.*?)</internal-data>",
            block,
            flags=re.DOTALL,
        )
        internal_text = internal_match.group(1).strip() if internal_match else ""

        # Extract visible as: everything inside <command-response> but
        # *outside* <internal-data> — i.e., the text before/after it.
        # Easiest is to remove the internal-data chunk and tags, then strip tags.
        without_internal = re.sub(
            r"<internal-data>.*?</internal-data>",
            "",
            block,
            flags=re.DOTALL,
        )
        # Now strip any remaining tags (<command-response>, etc.)
        visible = re.sub(r"<.*?>", "", without_internal).strip()

        if visible and internal_text:
            return f"{visible}\n\n{internal_text}"
        if internal_text:
            return internal_text
        return visible

    return re.sub(
        r"<command-response>.*?</command-response>",
        summarize,
        text,
        flags=re.DOTALL,
    )

def format_context_entry(
        e,
        project_lookup=None,
        asset_lookup=None,
        proj_code_intensity="MIXED",
        purpose=None,
        search_memory_id=None,
        game_panel_open=False,
):
    loc = _load_user_location()
    source = e.get("source", "")
    role = e.get("role", "")
    if role == "user":
        name = muse_settings.get_section('user_config').get('USER_NAME') or "User"
    elif role == "muse":
        name = muse_settings.get_section('muse_config').get('MUSE_NAME') or "Muse"
    elif role == "system":
        name = "System"
    else:
        name = role.capitalize() if role else "Unknown"

    # --- Timestamp handling ---
    ts = e.get("timestamp")
    dt = None
    time_str = ""
    htime = ""
    chtime = ""

    if ts:
        try:
            if isinstance(ts, datetime):
                dt = ts
            else:
                dt = datetime.fromisoformat(ts)

            # Assume UTC if naive, then convert to user TZ
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            dt = dt.astimezone(ZoneInfo(loc.timezone))

            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            htime = humanize.naturaltime(dt)
            chtime = htime.capitalize()
        except Exception:
            # Fallback: keep raw
            time_str = str(ts)
            htime = ""
    # If no timestamp, both stay empty

    # --- Project label (keyed by ObjectId) ---
    project_meta = ""
    project_id = e.get("project_id")
    if project_id and project_lookup:
        proj_name = project_lookup.get(project_id)
        if proj_name:
            project_meta = f"[Project: {proj_name}]"

    # --- Asset excerpt provenance ---
    asset_meta = ""
    if source == "asset_text_chunk":
        metadata = e.get("metadata") or {}
        asset_id = metadata.get("asset_id")
        chunk_index = metadata.get("chunk_index")

        asset_doc = asset_lookup.get(asset_id) if asset_id else None

        if not asset_doc:
            lines = ["Asset Excerpt — Linked Asset Unavailable"]

            if asset_id:
                lines.append(f"Asset ID: {asset_id}")

            if search_memory_id:
                lines.append(f"Recall Message ID: {search_memory_id}")

            lines.append(
                "Possible issue: this indexed excerpt is still recallable, but its "
                "source asset could not be found or is no longer living. Its indexed "
                "message may need cleanup."
            )

            asset_meta = "\n".join(lines)
        else:
            metadata = e.get("metadata") or {}
            asset_id = metadata.get("asset_id")
            chunk_index = metadata.get("chunk_index")

            asset_doc = asset_lookup.get(asset_id) if asset_id and asset_lookup else None
            asset_name = (
                asset_doc.get("display_name")
                or asset_doc.get("filename")
                or asset_id
            ) if asset_doc else asset_id

            indexing = (asset_doc or {}).get("indexing") or {}
            chunk_message_ids = indexing.get("chunk_message_ids") or []
            total_chunks = len(chunk_message_ids)

            lines = ["Asset Excerpt"]

            if asset_name:
                lines.append(f"Asset: {asset_name}")
            if asset_id:
                lines.append(f"Asset ID: {asset_id}")

            if chunk_index is not None:
                try:
                    chunk_number = int(chunk_index) + 1
                    if total_chunks:
                        lines.append(f"Excerpt: chunk {chunk_number} of {total_chunks}")
                    else:
                        lines.append(f"Excerpt: chunk {chunk_number}")
                except (TypeError, ValueError):
                    pass

            description = (asset_doc or {}).get("description")
            if description:
                lines.append(f"Description: {description}")

            # Leave this out until the command actually exists.
            # lines.append(
            #     "Use `read_asset` with this asset ID if the complete file is needed."
            # )

            asset_meta = "\n".join(lines)

    # --- Source ---
    source_name = ""
    source = e.get("source") or ""
    if source:
        source_name = f"[Source: {LOCATIONS.get(source)}]"

    # --- Tags ---
    tags = e.get("user_tags") or []
    tag_meta = ""
    if tags:
        tag_list = ", ".join(tags)
        tag_meta = f"[Tags: {tag_list}]"

    # --- Remembered ---
    remembered = e.get("remembered") or ""
    rem_note = ""
    if remembered:
        rem_note = f"[Highlighted memory]"

    # --- Message text ---
    msg = e.get("message", "")
    if purpose:
        filter_cfg = get_text_filter_config("CONTEXT", purpose, proj_code_intensity)
        msg = filter_text(msg, filter_cfg)

    msg = strip_command_blocks(msg)

    # --- Recent game-turn history ---
    if purpose == "RECENT":
        metadata = e.get("metadata") or {}
        turn_actions = metadata.get("turn_actions") or []
        if turn_actions:
            print(f"GAME_PANEL_OPEN: {game_panel_open}")
            turn_history = format_turn_actions_for_history(
                turn_actions,
                game_panel_open=game_panel_open,
            )

            if turn_history:
                msg = f"{msg}\n\n{turn_history}" if msg else turn_history

    # --- Build lines ---
    # Line 1: "5 minutes ago - Ed said:"  (or just "Ed said:" if no htime)
    if chtime:
        header_line = f"{chtime} - {name} said:"
    else:
        header_line = f"{name} said:"

    # Line 2: the message itself
    body_line = msg

    if asset_meta:
        body_line = f"{asset_meta}\n\n{body_line}"

    # Line 3: "[2025-12-14 15:30:12] [Project: MemoryMuse]"
    # If we have neither timestamp nor project, we can omit the line entirely
    meta_parts = []
    if time_str:
        meta_parts.append(f"[{time_str}]")
    if project_meta:
        meta_parts.append(project_meta)
    if source_name:
        meta_parts.append(source_name)
    if tag_meta:
        meta_parts.append(tag_meta)
    if remembered:
        meta_parts.append(rem_note)
    if search_memory_id:
        meta_parts.append(f"[search_memory ID: {search_memory_id}]")

    if role != "system":
        if meta_parts:
            footer_line = " ".join(meta_parts)
            return f"{header_line}\n{body_line}\n{footer_line}"
        else:
            # No timestamp / project — just header + body
            return f"{header_line}\n{body_line}"
    else:
        if time_str:
            system_header = f"[System message @ {time_str}]"
        else:
            system_header = "[System message]"
        return f"{system_header}\n{body_line}"

def build_command_response_block(
    *,
    visible: str = "",
    hidden: str | None = None,
    #prefix: str = "(System note) "
) -> str:
    """
    Build a standardized <command-response> block with optional <internal-data>.

    - `visible`: user-facing text (outside <internal-data>)
    - `hidden`: dict serialized into <internal-data> as JSON

    Returns a string like:
      <command-response><internal-data>{...}</internal-data>...</command-response>
    or, if no hidden:
      <command-response>...</command-response>
    or, if no visible:
      <command-response><internal-data>{...}</internal-data></command-response>
    """
    hidden = hidden or ""
    parts: list[str] = ["<command-response>"]

    if hidden:
        parts.append("<internal-data>")
        parts.append(hidden)
        parts.append("</internal-data>")

    if visible:
        parts.append(visible)

    parts.append("</command-response>")
    return "".join(parts)