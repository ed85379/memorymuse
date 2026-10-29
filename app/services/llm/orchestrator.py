from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import muse_settings
from app.core.tools.core_tools import run_tool
from app.services.llm.contracts import (
    ExecutedToolResult,
    LLMAdapter,
    ModelTurn,
)


StatusCallback = Callable[
    [str, str | None, dict[str, Any] | None],
    Awaitable[None],
]


def _collect_assets_from_tool_result(tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    tool_assets = tool_result.get("assets") or []

    if isinstance(tool_assets, list):
        return tool_assets

    if isinstance(tool_assets, dict):
        return [tool_assets]

    return []

def _collect_tool_results_from_tool_result(
    tool_result: dict[str, Any],
    *,
    tool_name: str,
) -> list[dict[str, Any]]:
    receipts = tool_result.get("tool_results") or []

    if not isinstance(receipts, list):
        return []

    return [
        {
            **receipt,
            "tool_name": tool_name,
        }
        for receipt in receipts
        if isinstance(receipt, dict)
    ]

async def _emit_status(
    status_callback: StatusCallback | None,
    event: str,
    function_name: str | None = None,
    ui_meta: dict[str, Any] | None = None,
) -> None:
    """
    Status delivery must never be able to kill a model response.

    The caller owns modality behavior:
    - WebUI may broadcast a status message;
    - Smart Speaker may update a light ring;
    - Discord may send typing;
    - background jobs may intentionally do nothing.
    """

    if status_callback is None:
        return

    try:
        await status_callback(event, function_name, ui_meta)
    except Exception as status_error:
        print(
            f"Status callback error "
            f"({event}, {function_name or 'no function'}): "
            f"{status_error!r}"
        )


def _tool_choice_for_turn(
    *,
    tools: list[dict[str, Any]] | None,
    configured_tool_choice: Any,
    completed_tool_turns: int,
    max_tool_turns: int,
) -> Any:
    """
    Match the existing behavior exactly:

    If a caller supplied an explicit tool_choice and the maximum number of
    local-tool turns has been reached, force OpenAI to stop asking for tools.

    If tool_choice is None, preserve the legacy behavior rather than quietly
    changing the policy during this extraction.
    """

    if (
        tools
        and configured_tool_choice is not None
        and completed_tool_turns >= max_tool_turns
    ):
        return "none"

    return configured_tool_choice


async def _execute_tool_call(
    *,
    function_name: str,
    arguments: dict[str, Any],
    handlers: dict[str, Any],
    ui_meta: dict[str, Any] | None,
    status_callback: StatusCallback | None,
) -> dict[str, Any]:
    await _emit_status(
        status_callback,
        "tool_start",
        function_name,
        ui_meta,
    )

    try:
        tool_result = run_tool(
            function_name,
            arguments,
            handlers,
        )

        # Existing run_tool() is synchronous, but this costs us nothing and
        # lets a future handler path become async without rewriting the loop.
        if inspect.isawaitable(tool_result):
            tool_result = await tool_result

        if not isinstance(tool_result, dict):
            raise TypeError(
                f"Tool '{function_name}' returned "
                f"{type(tool_result).__name__}, expected dict."
            )

        if "tool_output" not in tool_result:
            raise ValueError(
                f"Tool '{function_name}' returned no 'tool_output'."
            )

        return tool_result

    except Exception as tool_error:
        await _emit_status(
            status_callback,
            "tool_error",
            function_name,
            ui_meta,
        )

        return {
            "tool_output": {
                "error": str(tool_error),
            }
        }


async def get_model_response(
    *,
    adapter: LLMAdapter,
    dev_prompt: str,
    user_assistant_messages: list[dict[str, Any]] | None = None,
    prompt_type: str = "default",
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    handlers: dict[str, Any] | None = None,
    tool_choice: Any = None,
    ui_meta: dict[str, Any] | None = None,
    max_tool_turns: int = 4,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    """
    Provider-neutral MemoryMuse model/tool orchestration.

    Responsibilities here:
      - invoke the selected adapter;
      - enforce tool-loop policy;
      - execute MemoryMuse-owned tools;
      - gather assets, usage, and provider tool-event metadata;
      - return the legacy-compatible result shape.

    Responsibilities deliberately NOT here:
      - OpenAI/Anthropic/local-server payload formatting;
      - provider-specific continuation serialization;
      - WebUI/Discord/speaker behavior;
      - message persistence.
    """

    resolved_model = (
        model
        or muse_settings.get_section("llm_config").get("OPENAI_MODEL")
    )

    if not resolved_model:
        return {
            "text": "",
            "tool_calls": [],
            "tool_results": [],
            "usage": [],
            "assets": [],
            "error": "No model was supplied or configured.",
        }

    handlers = handlers or {}

    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    usage_records: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    completed_tool_turns = 0

    try:
        initial_tool_choice = _tool_choice_for_turn(
            tools=tools,
            configured_tool_choice=tool_choice,
            completed_tool_turns=completed_tool_turns,
            max_tool_turns=max_tool_turns,
        )

        await _emit_status(
            status_callback,
            "thinking",
            None,
            ui_meta,
        )

        turn: ModelTurn = await adapter.start_turn(
            dev_prompt=dev_prompt,
            messages=user_assistant_messages or [],
            model=resolved_model,
            prompt_type=prompt_type,
            tools=tools,
            tool_choice=initial_tool_choice,
        )

        while True:
            if turn.usage:
                usage_records.append(turn.usage)

            tool_calls.extend(turn.provider_tool_events or [])

            # A normal final response, native-provider tool-only event, or
            # anything not requesting a MemoryMuse function ends here.
            if not turn.function_calls:
                return {
                    "text": turn.text,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "usage": usage_records,
                    "assets": assets,
                }

            # Defensive stop. In the ordinary path, the next request will have
            # received tool_choice="none" when an explicit choice was supplied.
            if completed_tool_turns >= max_tool_turns:
                return {
                    "text": turn.text,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "usage": usage_records,
                    "assets": assets,
                }

            executed_results: list[ExecutedToolResult] = []

            for function_call in turn.function_calls:
                function_name = function_call.name
                arguments = function_call.arguments

                print(
                    f"Function Call: {function_name},\n"
                    f"Function Arguments: {arguments},\n"
                )
                print("calling function")

                tool_result = await _execute_tool_call(
                    function_name=function_name,
                    arguments=arguments,
                    handlers=handlers,
                    ui_meta=ui_meta,
                    status_callback=status_callback,
                )

                print(f"tool_result: {tool_result}")

                displayed_tool_results = _collect_tool_results_from_tool_result(
                    tool_result,
                    tool_name=function_name
                )
                if displayed_tool_results:
                    tool_results.extend(displayed_tool_results)

                tool_assets = _collect_assets_from_tool_result(tool_result)
                if tool_assets:
                    assets.extend(tool_assets)

                executed_results.append(
                    ExecutedToolResult(
                        call_id=function_call.call_id,
                        name=function_name,
                        tool_output=tool_result["tool_output"],
                        attachments=tool_result.get("attachments", []) or [],
                    )
                )

            completed_tool_turns += 1

            next_tool_choice = _tool_choice_for_turn(
                tools=tools,
                configured_tool_choice=tool_choice,
                completed_tool_turns=completed_tool_turns,
                max_tool_turns=max_tool_turns,
            )

            await _emit_status(
                status_callback,
                "thinking",
                None,
                ui_meta,
            )

            turn = await adapter.continue_turn(
                continuation=turn.continuation,
                tool_results=executed_results,
                tools=tools,
                tool_choice=next_tool_choice,
            )

    except Exception as error:
        print("Error communicating with model:", error)

        return {
            "text": "",
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "usage": usage_records,
            "assets": assets,
            "error": str(error),
        }
