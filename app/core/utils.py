# core/utils.py
from datetime import datetime, timedelta, timezone
import re, json, humanize
from typing import List, Optional
from bson import ObjectId
from charset_normalizer import from_bytes
from cryptography.fernet import Fernet
from zoneinfo import ZoneInfo
from typing import Union
from nanoid import generate
from app.config import muse_settings, admin_config, MONGO_CONVERSATION_COLLECTION, MONGO_THREADS_COLLECTION, MONGO_PROJECTS_COLLECTION
from app.core.text_filters import get_text_filter_config, filter_text
from app.databases.mongo_connector import mongo, mongo_system
from app.core.time_location_utils import get_formatted_datetime, _load_user_location

ProjectIdLike = Union[str, ObjectId, None]

LOG_LEVELS = {
    "debug": 10,
    "info": 20,
    "warn": 30,
    "error": 40,
}

LOCATIONS = {
    "frontend": "UI / Frontend",
    "webui": "WebUI / Frontend",
    "discord": "Discord",
    "smartspeaker": "Smart-Speaker",
    "asset_text_chunk": "Uploaded Asset",
}

SOURCES_ALL = ["frontend", "webui", "discord", "chatgpt", "reminder", "system", "debug", "internal", "thoughts", "file", "asset_text_chunk"]
SOURCES_CHAT = ["frontend", "webui", "discord", "chatgpt"]
SOURCES_CONTEXT = ["frontend", "webui", "discord", "chatgpt", "reminder", "system", "internal", "thoughts"]



def write_system_log(level, module=None, component=None, function=None, **fields):
    # Lookup global level (from config or db)
    if LOG_LEVELS[level] < LOG_LEVELS[admin_config.get_section('controls').get('LOG_VERBOSITY')]:
        return  # Quietly drop logs under the threshold
    log_entry = {
        "timestamp": datetime.now(timezone.utc),
        "level": level,
        "module": module,
        "component": component,
        "function": function,
        **fields
    }
    try:
        mongo_system.insert_log("system_logs", log_entry)
    except Exception as e:
        with open("logs/systemlog_backup.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")


def slugify(text):
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')

def get_encryption_key():
    from app.core import memory_core
    entries = memory_core.cortex.get_entries_by_type("encryption_key")
    for e in entries:
        if e.get("type") == "encryption_key":
            return e.get("key_data")
    key = Fernet.generate_key().decode()
    memory_core.cortex.add_entry({
        "type": "encryption_key",
        "source": "journal_core",
        "created": get_formatted_datetime(),
        "key_data": key
    })
    return key

def encrypt_text(text: str) -> str:
    key = get_encryption_key()
    fernet = Fernet(key.encode())
    return fernet.encrypt(text.encode()).decode()

def decrypt_text(token: str) -> str:
    key = get_encryption_key()
    fernet = Fernet(key.encode())
    return fernet.decrypt(token.encode()).decode()

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

def format_journal_entry(t):
    ts = t.get("timestamp")
    if ts:
        try:
            if isinstance(ts, datetime):
                dt = ts
            else:
                dt = datetime.fromisoformat(ts)
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = str(ts)
    else:
        date_str = "Unknown date"

    body = t.get("text", "")
    return f"Date: {date_str}\n{body}"


def is_conversation_active():
    """
    Return True if there has been frontend chat activity within the last `minutes`.
    Used by Initiative to decide whether 'mention' should be offered.
    """
    collection = MONGO_CONVERSATION_COLLECTION
    docs = mongo.find_logs(
        collection_name=collection,
        query={"source": {"$in": ["frontend", "webui"]}},
        limit=1,
        sort_field="timestamp",
        ascending=False,  # newest first
    )
    if not docs:
        return False
    last_ts = docs[0]["timestamp"]
    now = datetime.utcnow()
    minutes = 10
    return (now - last_ts) <= timedelta(minutes=minutes)

def build_thread_lookup():
    threads = mongo.find_documents(
        MONGO_THREADS_COLLECTION,
        query={},
        projection={"_id": 0, "thread_id": 1, "title": 1}
    )
    return {t["thread_id"]: t.get("title", "Unnamed Thread") for t in threads}

def build_project_lookup():
    projects = mongo.find_documents(
        MONGO_PROJECTS_COLLECTION,
        query={},
        projection={"_id": 1, "name": 1}
    )
    return {p["_id"]: p.get("name", "Unnamed Project") for p in projects}

def build_project_filter_lookup():
    projects = mongo.find_documents(
        MONGO_PROJECTS_COLLECTION,
        query={},
        projection={ "_id": 1, "code_intensity": 1}
    )
    return { p["_id"]: p.get("code_intensity", "mixed") for p in projects}

def prompt_projects_helper(project_id=None):
    project_lookup = build_project_lookup()
    project_filter_lookup = build_project_filter_lookup()
    project_meta = ""
    project_id_raw = project_id  # may be None or ""
    project_id = None
    project_name = ""
    project_code_intensity = ""
    if project_id_raw:
        try:
            project_id = ObjectId(project_id_raw)
        except Exception:
            project_id = None  # bad ID, just treat as no project
    if project_id and project_lookup:
        project_name = project_lookup.get(project_id)
        if project_name:
            project_meta = f"[Project: {project_name}] "
    if project_id and project_filter_lookup:
        project_code_intensity = project_filter_lookup.get(project_id)

    return project_name, project_meta, project_code_intensity

def prompt_threads_helper(thread_id=None):
    thread_lookup = build_thread_lookup()
    thread_meta = ""
    thread_title = ""
    if thread_id and thread_lookup:
        thread_title = thread_lookup.get(thread_id)
        if thread_title:
            thread_meta = f"[Thread: {thread_title}] "

    return thread_title, thread_meta

def get_objectids_for_message_ids(message_ids):
    if not message_ids:
        return {}

    docs = mongo.find_documents(
        collection_name=MONGO_CONVERSATION_COLLECTION,
        query={"message_id": {"$in": message_ids}},
        projection={"_id": 1, "message_id": 1},
    )

    return {
        doc["message_id"]: str(doc["_id"])
        for doc in docs
        if doc.get("message_id") and doc.get("_id")
    }

def normalize_role(role: str) -> str:
    """
    Map roles from Mongo to the role for sending to the model.
    Sending `muse` as `assistant` tends to flatten responses, therefore, both sides should be sent as `user`
    """
    return {
        "muse": "user",
        "user": "user",
        "system": "system",
    }.get(role, "user")

def format_context_entry(
        e,
        project_lookup=None,
        proj_code_intensity="MIXED",
        purpose=None,
        search_memory_id=None,
):
    loc = _load_user_location()
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

    # --- Build lines ---
    # Line 1: "5 minutes ago - Ed said:"  (or just "Ed said:" if no htime)
    if chtime:
        header_line = f"{chtime} - {name} said:"
    else:
        header_line = f"{name} said:"

    # Line 2: the message itself
    body_line = msg

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

def serialize_doc(doc):
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, ObjectId):
        return str(doc)
    else:
        return doc

def stringify_datetimes(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: stringify_datetimes(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [stringify_datetimes(i) for i in obj]
    return obj

def ensure_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]

def smart_decode(file_bytes):
    result = from_bytes(file_bytes).best()
    if result is None:
        # As a last resort, decode as utf-8 with replacement
        return file_bytes.decode("utf-8", errors="replace")
    return str(result)

def split_by_word_boundary(text, max_chars):
    chunks = []
    start = 0
    while start < len(text):
        # Find the furthest space (word boundary) before max_chars
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Only look for a space if we didn't reach the end
            space = text.rfind(' ', start, end)
            newline = text.rfind('\n', start, end)
            # Prefer newlines as breakpoints, then spaces
            split_at = max(newline, space)
            if split_at > start:
                end = split_at
        chunk = text[start:end].strip()
        if chunk:  # Avoid empty
            chunks.append(chunk)
        start = end
    return chunks

def smart_paragraph_split(text):
    # Normalize all line endings to \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

def chunk_file(
    file_bytes,
    encoding="utf-8",
    max_chunk_chars=4000,
    min_chunk_chars=500,
    strategy="regex",
    break_marker="\u200b"  # Zero-width space, invisible in text
):
    """
    Splits a file into non-overlapping, semantically reasonable chunks.
    Inserts an invisible zero-width space at chunk boundaries if a split occurs mid-paragraph.
    """
    try:
        text = smart_decode(file_bytes)
    except UnicodeDecodeError:
        raise ValueError("File decoding failed—unsupported encoding or binary file.")
    # This will split on two or more *any* line endings (handles \n, \r\n, or \r)
    paragraphs = re.split(r"(?:\r\n|\r|\n){2,}", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current = []
    current_len = 0
    start_line = 0
    lines_so_far = 0
    byte_offset = 0
    para_index = 0

    while para_index < len(paragraphs):
        para = paragraphs[para_index]
        para_len = len(para)

        if para_len > max_chunk_chars:
            # Paragraph itself is too big: split it up, invisibly marking breaks
            start = 0
            fragments = split_by_word_boundary(para, max_chunk_chars)
            for i, frag in enumerate(fragments):
                chunk_text = frag
                # Optionally add break_marker logic here if you still want it
                chunk_bytes = chunk_text.encode(encoding)
                chunk_lines = chunk_text.count("\n")
                end_line = lines_so_far + chunk_lines
                chunks.append({
                    "content": chunk_text,
                    "index": len(chunks),
                    "start_line": start_line,
                    "end_line": end_line,
                    "start_byte": byte_offset,
                    "end_byte": byte_offset + len(chunk_bytes),
                })
                byte_offset += len(chunk_bytes)
                lines_so_far = end_line
                start_line = end_line + 1
            para_index += 1
            continue

        # If current chunk is empty or can fit this paragraph, add it
        if not current or (current_len + para_len + 2) <= max_chunk_chars:
            current.append(para)
            current_len += para_len + 2
            para_index += 1
        else:
            # Finish current chunk
            chunk_text = "\n\n".join(current)
            chunk_bytes = chunk_text.encode(encoding)
            chunk_lines = chunk_text.count("\n")
            end_line = lines_so_far + chunk_lines
            chunks.append({
                "content": chunk_text,
                "index": len(chunks),
                "start_line": start_line,
                "end_line": end_line,
                "start_byte": byte_offset,
                "end_byte": byte_offset + len(chunk_bytes),
            })
            byte_offset += len(chunk_bytes)
            lines_so_far = end_line
            start_line = end_line + 1
            current = []
            current_len = 0

    # Add any leftovers as the final chunk
    if current:
        chunk_text = "\n\n".join(current)
        chunk_bytes = chunk_text.encode(encoding)
        chunk_lines = chunk_text.count("\n")
        end_line = lines_so_far + chunk_lines
        chunks.append({
            "content": chunk_text,
            "index": len(chunks),
            "start_line": start_line,
            "end_line": end_line,
            "start_byte": byte_offset,
            "end_byte": byte_offset + len(chunk_bytes),
        })

    # Merge tiny last chunk if necessary (avoids fragments)
    if (
        len(chunks) > 1
        and len(chunks[-1]["content"]) < min_chunk_chars
    ):
        prev = chunks[-2]
        last = chunks[-1]
        merged_text = prev["content"] + "\n\n" + last["content"]
        merged_bytes = merged_text.encode(encoding)
        chunks[-2] = {
            "content": merged_text,
            "index": prev["index"],
            "start_line": prev["start_line"],
            "end_line": last["end_line"],
            "start_byte": prev["start_byte"],
            "end_byte": prev["start_byte"] + len(merged_bytes),
        }
        chunks.pop()
    return chunks

def get_adaptive_top_k(min_top_k, default_top_k, num_injected_chunks):
    # Subtract 1 for 1, but never go below MIN_TOP_K
    return max(min_top_k, default_top_k - num_injected_chunks)

def generate_new_id(size=8):
    # default alphabet: [A-Za-z0-9_-]
    return generate(size=size)

def build_message_match_filter(
    start_dt: datetime,
    end_dt: datetime,
    source: Optional[str] = None,
    tag: Optional[List[str]] = None,
    project_id: Optional[str] = None,
    thread_id: Optional[List[str]] = None,
    search_text: Optional[str] = None,
    include_hidden: bool = False,
    include_forgotten: bool = False,
    include_private: bool = False,
):
    match_filter: dict = {
        "timestamp": {"$gte": start_dt, "$lt": end_dt}
    }

    # Source
    if source:
        match_filter["source"] = source.lower()
    else:
        match_filter["source"] = {"$ne": "chatgpt"}

    # Tags
    if tag:
        match_filter["user_tags"] = {"$in": tag}

    # Project
    if project_id:
        try:
            match_filter["project_id"] = ObjectId(project_id)
        except Exception:
            pass

    # Threads
    if thread_id:
        match_filter["thread_ids"] = {"$in": thread_id}

    # Flags
    if not include_hidden:
        match_filter["is_hidden"] = {"$ne": True}
    if not include_forgotten:
        match_filter["is_forgotten"] = {"$ne": True}
    if not include_private:
        match_filter["is_private"] = {"$ne": True}

    # Text search (Mongo text index)
    if search_text:
        match_filter["$text"] = {"$search": search_text}

    return match_filter

DISABLEABLE_COMMANDS = {
    "set_motd": "ENABLE_MOTD",
    "write_public_journal": "ENABLE_JOURNAL",
    "write_private_journal": "ENABLE_PRIVATE_JOURNAL",
    "set_reminder": "ENABLE_REMINDERS",
    "search_reminders": "ENABLE_REMINDERS",
    "mention": "ENABLE_UNPROMPTED_MESSAGING",
}

def command_is_allowed(command: str) -> bool:
    """
    Return True if this command is allowed for the current muse/user config.
    Unknown commands default to allowed.
    """
    flag = DISABLEABLE_COMMANDS.get(command)
    if not flag:
        return True  # pass-through for everything not explicitly gated

    muse_features = muse_settings.get_section("muse_features") or {}
    return bool(muse_features.get(flag, True))  # default to enabled

def strip_muse_private_blocks(text: str) -> str:
    text = re.sub(r"<muse-experience>.*?</muse-experience>", "", text, flags=re.DOTALL)
    text = re.sub(r"<muse-interlude>.*?</muse-interlude>", "", text, flags=re.DOTALL)
    return text

def strip_gm_notes(text: str) -> str:
    text = re.sub(r"<gm-note>.*?</gm-note>", "", text, flags=re.DOTALL)
    return text