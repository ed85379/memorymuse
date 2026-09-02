# muse_responder.py
# This module handles all model response routing and command execution
import httpx, time
import re, json
import humanize
from html import unescape
from typing import Any, Dict, List, Iterator, NamedTuple, Optional, TypedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from app.core.utils import write_system_log
from app.core.context_formatting import build_command_response_block
from app.core.time_location_utils import parse_iso_datetime
from app.services.openai_client import get_openai_response
from app.config import API_URL, muse_settings
from app.core.commands.registry import command_registry



#CMD_OPEN = re.compile(r"\[COMMAND:\s*([^\]]+)\]\s*", re.DOTALL)
#CMD_CLOSE = "[/COMMAND]"
CMD_OPEN = re.compile(
    r'<command\b[^>]*\bname\s*=\s*(?:"([^"]+)"|\'([^\']+)\')[^>]*>',
    re.IGNORECASE,
)
CMD_CLOSE = re.compile(r'</command\s*>', re.IGNORECASE)

@dataclass
class CommandResult:
    name: str
    payload: Dict[str, Any]
    status: str          # "ok" | "error" | "unknown" | "parse_error" | "no_handler"
    error: Optional[str] = None
    visible: str = ""    # what the filter says is visible
    hidden: Dict[str, Any] = None  # what the filter marks as hidden
    message_metadata: Optional[Dict[str, Any]] = None # Object that will go into the message metadata

def project_command_result(result: dict, schema: dict, now=None) -> dict:
    if not isinstance(result, dict):
        return {"Message": str(result)}

    include = set(schema.get("include", []))
    exclude = set(schema.get("exclude", []))
    humanize_fields = set(schema.get("humanize", []))
    rename = schema.get("rename", {})

    def _project(obj, prefix=""):
        if not isinstance(obj, dict):
            return obj

        projected = {}
        for key, value in obj.items():
            full_key = f"{prefix}{key}" if prefix else key

            # include/exclude logic (flat keys only in this simple version)
            if include and full_key not in include:
                continue
            if full_key in exclude:
                continue

            label = rename.get(full_key, key)

            if full_key in humanize_fields and value:
                dt = parse_iso_datetime(value)
                if dt:
                    projected[label] = humanize.naturaltime(now - dt)
                else:
                    projected[label] = value  # fallback to raw string if parse fails
            elif isinstance(value, dict):
                projected[label] = _project(value, prefix=full_key + ".")
            else:
                projected[label] = value

        return projected

    return _project(result)


def format_system_note(cmd_name: str, result: dict, schema: dict | None = None) -> str:
    lines = [f"(System note)", f"- Command: `{cmd_name}`"]
    now = datetime.now(timezone.utc)
    if schema:
        projected = project_command_result(result, schema, now=now)
        for label, value in projected.items():
            # Skip label if it's just the cmd name repeated
            if label.lower() == "cmd":
                lines.append(f"- {value}")
            else:
                lines.append(f"- {label}: {value}")
        child_cmds = schema.get("child_commands")
        if child_cmds:
            lines.append("")
            lines.append("Available related commands:")

            for child_name in child_cmds:
                cmd_def = command_registry.get(child_name)
                triggers = cmd_def.get("triggers")
                fmt = cmd_def.get("format")


                lines.append("")
                lines.append(f"- Command: `{child_name}`")
                if triggers:
                    joined_triggers = ", ".join(f'    - "{t}"\n' for t in triggers)
                    lines.append(f"  Listen for phrases like:\n{joined_triggers}")
                if fmt:
                    lines.append("  Format:")
                    lines.append(f"    {fmt}")
    else:
        # Fallback: just show a generic success line
        msg = result.get("text") or result.get("message") if isinstance(result, dict) else None
        if msg:
            lines.append(f"- Message: {msg}")

    return "\n".join(lines)

def process_commands_in_response(
    response: str,
    *,
    source: Optional[str] = None,
    apply_filters: bool = True,
    strip_on_error: bool = True,
    command_context=None,
) -> (str, List[CommandResult]):
    """
    Unified command-processing core.

    - Parses all <command name="cmd">{}</command> blocks from `response`
    - Executes handlers from command_registry command definitions
    - Optionally applies command_def["filter"] to handler results
    - Returns:
        cleaned_response: original text with command blocks removed or replaced
        results: list of CommandResult objects (for logging / summaries)
    """
    cleaned_parts: List[str] = []
    cursor = 0
    results: List[CommandResult] = []

    commands = list(extract_commands(response))
    if not commands:
        # No commands at all — return original text untouched
        return response, results

    for cm in commands:
        start, end = cm.span
        command_name = cm.name.strip()
        raw_payload = cm.json_text.strip()

        # Append any text before this command
        if start > cursor:
            cleaned_parts.append(response[cursor:start])

        # Default replacement if we end up stripping
        replacement = "\n"

        # Try to parse payload
        try:
            payload = json.loads(raw_payload)
        except Exception as e:
            write_system_log(
                level="error",
                module="core",
                component="command_core",
                function="process_commands_in_response",
                action="parse_payload_error",
                command=command_name,
                payload=raw_payload,
                error=str(e),
            )
            results.append(CommandResult(
                name=command_name,
                payload={},
                status="parse_error",
                error=str(e),
            ))
            if not strip_on_error:
                # keep the original block if you ever want that behavior
                cleaned_parts.append(response[start:end])
            else:
                cleaned_parts.append(replacement)
            cursor = end
            continue

        command_def = command_registry.get(command_name)
        if not command_def:
            write_system_log(
                level="warn",
                module="core",
                component="command_core",
                function="process_commands_in_response",
                action="unknown_command",
                command=command_name,
                payload=raw_payload,
            )
            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="no_handler",
            ))
            if not strip_on_error:
                cleaned_parts.append(response[start:end])
            else:
                cleaned_parts.append(replacement)
            cursor = end
            continue

        handler = command_def.get("handler")
        if not handler:
            write_system_log(
                level="error",
                module="core",
                component="command_core",
                function="process_commands_in_response",
                action="missing_handler",
                command=command_name,
                payload=raw_payload,
            )
            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="no_handler",
                error="Command definition has no handler",
            ))
        # Execute handler
        try:
            extra_kwargs = command_context or {}
            if source is not None:
                extra_kwargs = {**extra_kwargs, "source": source}

            handler_result = handler(payload, **extra_kwargs) \
                if extra_kwargs else handler(payload)

            # If handler returns nothing → we still consider it ok, just no visible text
            visible = ""
            hidden = {}

            if apply_filters and handler_result is not None:
                filter_fn = command_def.get("filter")
                if filter_fn:
                    filtered = filter_fn(handler_result)
                    if filtered is None:
                        filtered = {}
                    elif not isinstance(filtered, dict):
                        raise TypeError(
                            f"Command filter for {command_name} returned {type(filtered).__name__}, expected dict"
                        )
                    visible = filtered.get("visible", "") or ""
                    hidden = filtered.get("hidden", {}) or {}

            message_metadata = None
            metadata_builder = command_def.get("message_metadata")
            if metadata_builder is not None:
                message_metadata = metadata_builder(handler_result)

            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="ok",
                visible=visible,
                hidden=hidden,
                message_metadata=message_metadata,
            ))
            print(f"DEBUG command payload: {payload}")
            # Turn hidden dict into formatted string
            note_schema = command_def.get("note_schema")
            hidden_str = format_system_note(cmd_name=command_name, result=hidden, schema=note_schema)


            # Decide what to inject into cleaned text
            if apply_filters and (visible or hidden):
                replacement = build_command_response_block(
                    visible=visible,
                    hidden=hidden_str,
                )
                cleaned_parts.append(replacement)
            else:
                cleaned_parts.append("\n")

        except Exception as e:
            write_system_log(
                level="error",
                module="core",
                component="command_core",
                function="process_commands_in_response",
                action="command_error",
                command=command_name,
                payload=payload,
                error=str(e),
            )
            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="error",
                error=str(e),
            ))
            if not strip_on_error:
                cleaned_parts.append(response[start:end])
            else:
                cleaned_parts.append("\n")

        cursor = end

    # Append trailing text
    if cursor < len(response):
        cleaned_parts.append(response[cursor:])

    cleaned_response = "".join(cleaned_parts)
    return cleaned_response, results

# This allows referencing handlers directly by name
COMMAND_HANDLERS = {
    name: cfg["handler"] for name, cfg in command_registry.all().items()
}


def process_initiative_json_actions(
    raw_response: str,
    *,
    source: Optional[str] = None,
    initiative_data: Optional[Dict[str, Any]] = None,
    apply_filters: bool = True,
) -> List[CommandResult]:
    """
    Process a JSON-only Initiative response.

    Expected shape:
    {
      "should_act": true|false,
      "actions": [
        {"type": "mention", "subject": "..."},
        {"type": "set_motd", "text": "..."}
      ]
    }

    Returns:
        list[CommandResult]
    """
    try:
        data = json.loads(raw_response)
    except Exception as e:
        write_system_log(
            level="error",
            module="core",
            component="command_core",
            function="process_initiative_json_actions",
            action="parse_json_error",
            payload=raw_response,
            error=str(e),
        )
        return [
            CommandResult(
                name="initiative_json",
                payload={},
                status="parse_error",
                error=str(e),
            )
        ]

    if not isinstance(data, dict):
        return [
            CommandResult(
                name="initiative_json",
                payload={},
                status="parse_error",
                error="Top-level JSON must be an object",
            )
        ]

    if not data.get("should_act"):
        return [
            CommandResult(
                name="initiative_json",
                payload={},
                status="silence",
            )
        ]

    actions = data.get("actions", [])
    if not isinstance(actions, list):
        return [
            CommandResult(
                name="initiative_json",
                payload=data,
                status="parse_error",
                error="'actions' must be a list",
            )
        ]

    results: List[CommandResult] = []

    for action in actions:
        if not isinstance(action, dict):
            results.append(CommandResult(
                name="initiative_action",
                payload={},
                status="parse_error",
                error="Each action must be an object",
            ))
            continue

        command_name = action.get("type")
        if not isinstance(command_name, str) or not command_name.strip():
            results.append(CommandResult(
                name="unknown",
                payload=action,
                status="parse_error",
                error="Action missing valid 'type'",
            ))
            continue

        command_name = command_name.strip()
        payload = {k: v for k, v in action.items() if k != "type"}
        command_def = command_registry.get(command_name)
        handler = command_def.get("handler")
        #handler = COMMAND_HANDLERS.get(command_name)
        if not handler:
            write_system_log(
                level="warn",
                module="core",
                component="command_core",
                function="process_initiative_json_actions",
                action="unknown_command",
                command=command_name,
                payload=action,
            )
            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="no_handler",
            ))
            continue

        try:
            extra_kwargs = initiative_data or {}
            if source is not None:
                extra_kwargs = {**extra_kwargs, "source": source}

            handler_result = handler(payload, **extra_kwargs) if extra_kwargs else handler(payload)

            visible = ""
            hidden = {}

            if apply_filters and handler_result is not None:
                command_def = command_registry.get(command_name)
                filter_fn = command_def.get("filter")
                if filter_fn:
                    filtered = filter_fn(handler_result) or {}
                    visible = filtered.get("visible", "") or ""
                    hidden = filtered.get("hidden", {}) or {}

            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="ok",
                visible=visible,
                hidden=hidden,
            ))

        except Exception as e:
            write_system_log(
                level="error",
                module="core",
                component="command_core",
                function="process_initiative_json_actions",
                action="command_error",
                command=command_name,
                payload=payload,
                error=str(e),
            )
            results.append(CommandResult(
                name=command_name,
                payload=payload,
                status="error",
                error=str(e),
            ))

    return results

class CommandMatch(NamedTuple):
    name: str
    json_text: str
    span: tuple[int, int]     # (start, end) in the original text
    had_close: bool

def _balanced_object_end(text: str, start: int) -> Optional[int]:
    """
    Given text and index at the first '{', return index just after
    the matching closing '}' that balances the object. Handles strings and escapes.
    Returns None if unbalanced.
    """
    n = len(text)
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1  # just after the closing brace
        i += 1
    return None

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

def _find_fence_spans(text: str) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) index pairs for all ```fenced``` code blocks
    in the given text. Spans are half-open: [start, end).
    """
    spans: list[tuple[int, int]] = []
    for m in FENCE_RE.finditer(text):
        spans.append((m.start(), m.end()))
    return spans

def _in_fence(pos: int, spans: list[tuple[int, int]]) -> bool:
    """
    True if the given character index `pos` lies inside any fenced span.
    """
    for start, end in spans:
        if start <= pos < end:
            return True
    return False

def extract_commands(text: str) -> Iterator[CommandMatch]:
    """
    Yields all command blocks in order. Each block:
      - <command name="name"> { ...balanced JSON... } </command>
    Multiple commands per response are handled safely.
    """
    fence_spans = _find_fence_spans(text)

    def is_in_fence(pos: int) -> bool:
        return _in_fence(pos, fence_spans)

    i, n = 0, len(text)
    while True:
        m = CMD_OPEN.search(text, i)
        if not m:
            break

        if is_in_fence(m.start()):
            i = m.end()
            continue

        name = (m.group(1) or m.group(2)).strip()
        pos = m.end()

        lbrace = text.find("{", pos)
        if lbrace == -1 or is_in_fence(lbrace):
            i = pos
            continue

        rbr_end = _balanced_object_end(text, lbrace)
        if rbr_end is None or is_in_fence(rbr_end - 1):
            i = pos
            continue

        k = rbr_end
        while k < n and text[k].isspace():
            k += 1

        close_match = CMD_CLOSE.match(text, k)
        if not close_match or is_in_fence(k):
            i = pos
            continue

        yield CommandMatch(
            name=name,
            json_text=text[lbrace:rbr_end],
            span=(m.start(), close_match.end()),
            had_close=True,
        )
        i = close_match.end()




FENCE_PATTERN = re.compile(
    r"(```.*?```|~~~.*?~~~)",
    re.DOTALL
)

FOLLOWUP_TAG_RE = re.compile(
    r"<followup-turn\b[^>]*?/>",
    re.IGNORECASE,
)

REASON_ATTR_RE = re.compile(
    r'\breason\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
    re.IGNORECASE,
)

INTENT_ATTR_RE = re.compile(
    r'\bintent\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
    re.IGNORECASE,
)

class FollowupParseResult(TypedDict):
    cleaned_text: str
    reason: Optional[str]
    intent: Optional[str]

def _first_group(match: re.Match | None) -> Optional[str]:
    if not match:
        return None
    return unescape((match.group(1) or match.group(2) or "").strip()) or None

def extract_followup_turn(text: str) -> FollowupParseResult:
    matches = list(FOLLOWUP_TAG_RE.finditer(text))

    if not matches:
        return {
            "cleaned_text": text,
            "reason": None,
            "intent": None,
        }

    if len(matches) > 1:
        write_system_log(
            level="debug",
            module="core",
            component="responder",
            function="route_user_input",
            action="followup_multiple_tags_found",
            count=len(matches),
        )

    first_tag = matches[0].group(0)

    reason = _first_group(REASON_ATTR_RE.search(first_tag))
    intent = _first_group(INTENT_ATTR_RE.search(first_tag))

    if not intent:
        write_system_log(
            level="error",
            module="core",
            component="responder",
            function="route_user_input",
            action="followup_missing_intent",
            matched_tag=first_tag,
            reason=reason,
        )
    else:
        write_system_log(
            level="info",
            module="core",
            component="responder",
            function="route_user_input",
            action="followup_processed",
            reason=reason,
            intent=intent,
        )

    cleaned_text = FOLLOWUP_TAG_RE.sub("", text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()

    return {
        "cleaned_text": cleaned_text,
        "reason": reason,
        "intent": intent,
    }

def normalize_muse_experience_tags(text: str) -> str:
    """
    Normalize <muse-experience> tags in non-fenced text only.

    - Skips anything inside ```...``` or ~~~...~~~ fences
    - Normalizes [] / () to <>
    - Appends missing </muse-experience> if there’s an opening tag
    """
    if not isinstance(text, str):
        return text

    # Split into segments: text and fenced blocks
    parts = []
    last_end = 0

    for m in FENCE_PATTERN.finditer(text):
        # non-fenced chunk before this fence
        if m.start() > last_end:
            parts.append(("plain", text[last_end:m.start()]))
        # the fenced chunk itself
        parts.append(("fence", m.group(0)))
        last_end = m.end()

    # trailing non-fenced chunk
    if last_end < len(text):
        parts.append(("plain", text[last_end:]))

    def _normalize_plain(chunk: str) -> str:
        # 1) Normalize bracket types for open/close tags
        chunk = re.sub(
            r'[\[\(]\s*muse-experience\s*[\]\)]',
            '<muse-experience>',
            chunk,
            flags=re.IGNORECASE,
        )
        chunk = re.sub(
            r'[\[\(]\s*/\s*muse-experience\s*[\]\)]',
            '</muse-experience>',
            chunk,
            flags=re.IGNORECASE,
        )

        # 2) Ensure closing tag if there’s an opening
        open_tag_pattern = re.compile(r'<\s*muse-experience\s*>', re.IGNORECASE)
        close_tag_pattern = re.compile(r'<\s*/\s*muse-experience\s*>', re.IGNORECASE)

        has_open = bool(open_tag_pattern.search(chunk))
        has_close = bool(close_tag_pattern.search(chunk))

        if has_open and not has_close:
            chunk = chunk.rstrip() + '\n</muse-experience>'

        return chunk

    normalized_parts = []
    for kind, chunk in parts:
        if kind == "plain":
            normalized_parts.append(_normalize_plain(chunk))
        else:
            # fence: leave exactly as-is
            normalized_parts.append(chunk)

    return "".join(normalized_parts)
# Main entry point for any response parsing after prompt

@dataclass
class RouteUserInputResult:
    response_text: str
    cmd_results: list = field(default_factory=list)
    usage: list = field(default_factory=list)
    followup_turn: str | None = None
    tool_calls: list = field(default_factory=list)
    assets: list = field(default_factory=list)

async def route_user_input(
        dev_prompt: str,
        user_assistant_messages: list = None,
        client=None,
        prompt_type="api",
        apply_cmd_filters=True,
        tool_bundle=None,
        command_context=None,
) -> RouteUserInputResult:

    result = await get_openai_response(
        dev_prompt,
        client=client,
        user_assistant_messages=user_assistant_messages,
        prompt_type=prompt_type,
        model=muse_settings.get_section("llm_config").get("OPENAI_MODEL"),
        tools=tool_bundle["tools"],
        tool_choice=tool_bundle["tool_choice"],
        handlers=tool_bundle["handlers"],
        ui_meta=tool_bundle["ui_meta"],
    )
    response = result.get("text", "")
    tool_calls = result.get("tool_calls", [])
    usage = result.get("usage", [])
    assets = result.get("assets", [])

    # Normalize muse-experience tags outside of fenced code blocks
    response = normalize_muse_experience_tags(response)

    write_system_log(
        level="debug",
        module="core",
        component="responder",
        function="route_user_input",
        action="raw_response",
        response=response
    )

    cleaned_response, cmd_results = process_commands_in_response(
        response,
        apply_filters=apply_cmd_filters,      # use COMMANDS[cmd]["filter"]
        strip_on_error=True,     # keep UI clean
        command_context=command_context,
    )

    # Optional: log a compact summary of what ran
    if cmd_results:
        summary = "; ".join(
            f"{r.name}:{r.status}" for r in cmd_results
        )
        write_system_log(
            level="info",
            module="core",
            component="responder",
            function="route_user_input",
            action="commands_processed",
            summary=summary,
        )

    followup_result = extract_followup_turn(cleaned_response)
    print(f"DEBUG: {followup_result['intent']}")

    return RouteUserInputResult(
        response_text=followup_result["cleaned_text"],
        cmd_results=cmd_results,
        usage=usage,
        followup_turn=followup_result["intent"],
        tool_calls=tool_calls,
        assets=assets,
    )

# Handles muse_initiator-specific responses
async def handle_muse_decision(
    dev_prompt,
    user_assistant_messages: list = None,
    client=None,
    model=muse_settings.get_section("llm_config").get("OPENAI_WHISPER_MODEL"),
    source=None,
    initiative_data=None,
    tool_bundle=None,
) -> str:
    """
    Processes Initiative (muse) backend decisions using the unified command extraction pipeline.
    Returns a terse summary string of processing results
    (e.g., 'Processed: speak; Error in remember_fact: ...').
    """
    result = await get_openai_response(
        dev_prompt,
        client=client,
        user_assistant_messages=user_assistant_messages,
        prompt_type="initiative",
        model=model,
        tools=tool_bundle["tools"],
        tool_choice=tool_bundle["tool_choice"],
        handlers=tool_bundle["handlers"],
        ui_meta=tool_bundle["ui_meta"],
    )
    response = result.get("text", "")
    tool_calls = result.get("tool_calls", [])
    usage = result.get("usage", [])
    print(f"INITIATIVE COMMAND: {response}")

    write_system_log(
        level="debug",
        module="core",
        component="responder",
        function="handle_muse_decision",
        action="raw_response",
        response=response
    )

    # Silence handling — returns early without attempting command parse.
    if "[CHOOSES SILENCE]" in response:
        write_system_log(
            level="debug",
            module="core",
            component="responder",
            function="handle_muse_decision",
            action="initiative_decision",
            result="silent"
        )
        return "Initiative chose silence."

    cmd_results = process_initiative_json_actions(
        response,
        source=source,
        initiative_data=initiative_data,
        apply_filters=False,     # no <command-response> wrapping needed
    )

    if not cmd_results:
        write_system_log(
            level="warn",
            module="core",
            component="responder",
            function="handle_muse_decision",
            action="initiative_decision",
            result="No command block found in Initiative response."
        )
        return "No command block found in Initiative response."

    # Log each command result
    for r in cmd_results:
        level = "info" if r.status == "ok" else "warn" if r.status in ("no_handler", "parse_error", "silence") else "error"
        write_system_log(
            level=level,
            module="core",
            component="responder",
            function="handle_muse_decision",
            action="command_processed",
            command=r.name,
            status=r.status,
            error=r.error,
            payload=r.payload,
        )

    # Build terse summary string
    summary_parts = []
    for r in cmd_results:
        if r.status == "ok":
            summary_parts.append(f"Processed: {r.name}")
        elif r.status == "silence":
            summary_parts.append(f"Initiative chose silence")
        elif r.status == "no_handler":
            summary_parts.append(f"Unknown command: {r.name}")
        elif r.status == "parse_error":
            summary_parts.append(f"Error in {r.name}: invalid JSON payload")
        else:  # "error"
            summary_parts.append(f"Error in {r.name}: {r.error}")

    return "; ".join(summary_parts)

def send_to_websocket(text: str, to="webui", timestamp=None, retries=3, delay=0.5):
    payload = {"message": text, "to": to, "timestamp": timestamp}
    for attempt in range(1, retries + 1):
        try:
            response = httpx.post(
                f"{API_URL}/api/muse/speak",
                json=payload,
                timeout=5
            )
            if response.status_code == 200:
                return True
            else:
                print(f"WebSocket send failed ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"WebSocket send attempt {attempt} error: {e}")
        if attempt < retries:
            time.sleep(delay * attempt)
    print("WebSocket send gave up after retries.")
    return False

