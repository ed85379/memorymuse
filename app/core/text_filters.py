# text_filters.py

from __future__ import annotations
import re
from typing import Iterable, Literal
from dataclasses import dataclass, field
from enum import Enum

## CONFIGS
# Tags whose *entire blocks* we want to nuke (tag + inner content)
BLOCK_XML_TAGS = [
    "command-response",
    "internal-data",
]

# Tags where we only strip the tags, *keep* inner text
#    Right now this list is intentionally empty, but we wire it for later.
TAG_ONLY_STRIP_XML_TAGS: list[str] = [
    "remove-this-tag"
    # e.g. "some-future-wrapper",
]

JSON_BLOCK_PATTERN = re.compile(
    r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}",
    re.DOTALL,
)

BLOCK_XML_PATTERN = re.compile(
    r"<\s*(?P<tag>" + "|".join(re.escape(tag) for tag in BLOCK_XML_TAGS) + r")\b[^>]*>"
    r"(?:(?!<\s*(?P=tag)\b).)*?"
    r"</\s*(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Regex to capture ```lang?\n ... \n``` blocks, non-greedy
_CODE_BLOCK_RE = re.compile(
    r"```([^\n`]*)\n(.*?)```",
    re.DOTALL
)

JsonMode = Literal["remove", "replace", "disabled"]

class XmlBlockMode(str, Enum):
    REMOVE = "remove"   # strip entire block + contents
    KEEP   = "keep"     # leave as-is

class XmlTagStripMode(str, Enum):
    STRIP = "strip"     # remove tags, keep inner text
    KEEP  = "keep"      # leave as-is


def build_block_xml_pattern(tags: Iterable[str]) -> re.Pattern | None:
    tags = [t.strip() for t in tags if t.strip()]
    if not tags:
        return None

    # Named group so we can match the same tag in open/close
    # e.g. <command-response[example]> ... </command-response[example]>
    tag_alternation = "|".join(re.escape(tag) for tag in tags)
    pattern = re.compile(
        rf"<\s*(?P<tag>{tag_alternation})\b[^>]*>.*?</\s*(?P=tag)\s*>",
        re.DOTALL | re.IGNORECASE,
    )
    return pattern

def build_tag_only_pattern() -> re.Pattern | None:
    tags = [t.strip() for t in TAG_ONLY_STRIP_XML_TAGS if t.strip()]
    if not tags:
        return None

    inner = "|".join(re.escape(tag) for tag in tags)
    pattern = re.compile(
        rf"</?\s*(?:{inner})\b[^>]*>",
        re.IGNORECASE,
    )
    return pattern

def strip_block_xml(text: str, tags: Iterable[str]) -> str:
    """
    Remove entire blocks like:
      <command-response> ... </command-response[example]>
      <internal-data> ... </internal-data>
    including their contents.
    """
    pattern = build_block_xml_pattern(tags)
    if not pattern:
        return text
    return pattern.sub("", text)


def strip_tag_only_xml(text: str) -> str:
    pattern = build_tag_only_pattern()
    if not pattern:
        return text
    return pattern.sub("", text)

def strip_json(text: str, mode: JsonMode, marker: str) -> str:
    if mode == "disabled":
        return text
    if mode == "replace":
        return JSON_BLOCK_PATTERN.sub(marker, text)
    # mode == "remove"
    return JSON_BLOCK_PATTERN.sub("", text)

# This one has limited usefulness, so it isn't used.
def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class CodeBlockFilterMode(str, Enum):
    REMOVE = "remove"      # remove entire block
    REPLACE = "replace"    # replace with marker
    TRUNCATE = "truncate"  # keep first N lines, then marker

@dataclass
class TextFilterConfig:
    """
    Single config object controlling all text filters:
      - JSON
      - block XML
      - tag-only XML
      - code blocks
    """
    # --- JSON ---
    json_mode: JsonMode = "remove"
    json_replace_marker: str = "/// JSON BLOCK REMOVED FOR BREVITY ///"

    # --- Block XML (e.g. <command-response>, <internal-data>) ---
    xml_block_mode: XmlBlockMode = XmlBlockMode.KEEP
    # Tags whose entire blocks should be removed when xml_block_mode=REMOVE
    xml_block_tags: tuple[str, ...] = (
        "command-response",
        "command-response[example]",
        "internal-data",
    )

    # --- Tag-only XML (strip wrappers, keep content) ---
    xml_tag_strip_mode: XmlTagStripMode = XmlTagStripMode.KEEP
    # Tags whose *tags* should be stripped when xml_tag_strip_mode=STRIP
    xml_tag_strip_tags: tuple[str, ...] = field(default_factory=tuple)

    # --- Code blocks ---
    code_enabled: bool = False
    code_mode: CodeBlockFilterMode = CodeBlockFilterMode.TRUNCATE
    code_min_lines_for_filter: int = 6
    code_max_lines: int = 40
    code_marker_text: str = "/// Code block shortened for brevity ///"



def filter_code_blocks_by_lines(
    text: str,
    config: TextFilterConfig,
) -> str:
    """
    Apply line-count based filtering to ``` ``` blocks, based on TextFilterConfig.
    """
    if not config.code_enabled:
        return text

    def _replace(match: re.Match) -> str:
        lang = match.group(1) or ""
        body = match.group(2)

        body_stripped = body.strip()
        # If body is empty or whitespace-only, just remove the whole block
        if not body_stripped:
            return ""

        lines = body_stripped.splitlines()
        line_count = len(lines)

        if line_count <= config.code_min_lines_for_filter:
            return match.group(0)

        if line_count <= config.code_max_lines:
            return match.group(0)

        mode = config.code_mode

        if mode == CodeBlockFilterMode.REMOVE:
            return ""

        if mode == CodeBlockFilterMode.REPLACE:
            if not config.code_marker_text:
                # Embedding mode: drop the whole block, no marker
                return ""
            marker = f"{config.code_marker_text}"
            return f"```{lang}\n{marker}\n```"

        if mode == CodeBlockFilterMode.TRUNCATE:
            kept = lines[: config.code_max_lines]
            remaining = line_count - config.code_max_lines

            if not config.code_marker_text:
                # Embedding mode: keep only the first N lines, no marker
                new_body = "\n".join(kept)
                return f"```{lang}\n{new_body}\n```"

            marker = (
                f"{config.code_marker_text} "
                f"(remaining {remaining} lines omitted)"
            )
            new_body = "\n".join(kept + [marker])
            return f"```{lang}\n{new_body}\n```"

        return match.group(0)

    return _CODE_BLOCK_RE.sub(_replace, text)


class TextFilterPurpose(str, Enum):
    MNEMOSYNE_EMBEDDING = "mnemosyne_embedding"
    MNEMOSYNE_PROMPT = "mnemosyne_prompt"
    RECENT_CONTEXT = "recent_context"
    RELEVANT_MEMORIES = "relevant_memories"

# --- Call/Import these ---

def filter_text(raw_text: str, config: TextFilterConfig) -> str:
    """
    Apply all text filters (JSON, XML, code) according to a single config.
    """

    text = raw_text

    # 1. Block XML
    if config.xml_block_mode == XmlBlockMode.REMOVE:
        text = strip_block_xml(text, tags=config.xml_block_tags)

    # 2. Tag-only XML
    if config.xml_tag_strip_mode == XmlTagStripMode.STRIP:
        text = strip_tag_only_xml(text)

    # 3. JSON
    text = strip_json(
        text,
        mode=config.json_mode,
        marker=config.json_replace_marker,
    )

    # 4. Code blocks
    text = filter_code_blocks_by_lines(text, config)

    return text


def get_text_filter_config(system: str, purpose: str, detail: str) -> TextFilterConfig:
    key = f"{system}_{purpose}_{detail}_CFG"
    return globals().get(key, TextFilterConfig())

# --- Presets ---


# Relational Memory uses this to determine episodic boundaries
MNEMOSYNE_EMBEDDING_DEFAULT_CFG = TextFilterConfig(
    json_mode="remove",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.REMOVE,
    code_min_lines_for_filter=0,
    code_max_lines=0,
)

# Relational memory uses this to filter for the prompt
MNEMOSYNE_PROMPT_DEFAULT_CFG = TextFilterConfig(
    json_mode="replace",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=6,
    code_max_lines=3,
)

# (FUTURE USE) Used to filter full messages going into Qdrant
MEMORY_EMBEDDING_DEFAULT_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=False,
)

# For the main Context of the current conversation
CONTEXT_RECENT_MIXED_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.KEEP,
    xml_tag_strip_mode=XmlTagStripMode.KEEP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=12,
    code_max_lines=12,
)

# For the Context of semantically recalled messages
CONTEXT_RELEVANT_MIXED_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=6,
    code_max_lines=3,
)

# For the episodic matching for Qdrant recalling
SEARCH_EMBEDDING_MIXED_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.KEEP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=6,
    code_max_lines=3,
    code_marker_text="",
)

# For the main Context of the current conversation
CONTEXT_RECENT_HEAVYCODE_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.KEEP,
    xml_tag_strip_mode=XmlTagStripMode.KEEP,
    code_enabled=False,
)

# For the Context of semantically recalled messages
CONTEXT_RELEVANT_HEAVYCODE_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=24,
    code_max_lines=24,
)

# For the episodic matching for Qdrant recalling
SEARCH_EMBEDDING_HEAVYCODE_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.TRUNCATE,
    code_min_lines_for_filter=6,
    code_max_lines=3,
    code_marker_text="",
)

# For the main Context of the current conversation
CONTEXT_RECENT_NOCODE_CFG = TextFilterConfig(
    json_mode="disabled",
    xml_block_mode=XmlBlockMode.KEEP,
    xml_tag_strip_mode=XmlTagStripMode.KEEP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.REPLACE,
    code_min_lines_for_filter=0,
    code_max_lines=0,  # Not relevant for REPLACE, but required
)

# For the Context of semantically recalled messages
CONTEXT_RELEVANT_NOCODE_CFG = TextFilterConfig(
    json_mode="remove",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.REPLACE,
    code_min_lines_for_filter=0,
    code_max_lines=0,  # Not relevant for REPLACE, but required
)

# For the episodic matching for Qdrant recalling
SEARCH_EMBEDDING_NOCODE_CFG = TextFilterConfig(
    json_mode="remove",
    xml_block_mode=XmlBlockMode.REMOVE,
    xml_tag_strip_mode=XmlTagStripMode.STRIP,
    code_enabled=True,
    code_mode=CodeBlockFilterMode.REPLACE,
    code_min_lines_for_filter=0,
    code_max_lines=0, # Not relevant for REPLACE, but required
    code_marker_text="",
)

