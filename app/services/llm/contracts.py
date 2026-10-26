from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class NormalizedToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    raw: dict[str, Any] | None = None


@dataclass
class ExecutedToolResult:
    call_id: str
    name: str
    tool_output: Any
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelTurn:
    text: str
    function_calls: list[NormalizedToolCall]
    provider_tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    continuation: Any


class LLMAdapter(Protocol):
    async def start_turn(
        self,
        *,
        dev_prompt: str,
        messages: list[dict[str, Any]] | None,
        model: str,
        prompt_type: str,
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
    ) -> ModelTurn:
        ...

    async def continue_turn(
        self,
        *,
        continuation: Any,
        tool_results: list[ExecutedToolResult],
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
    ) -> ModelTurn:
        ...