from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import muse_settings
from app.core import utils
from app.services.llm.contracts import (
    ExecutedToolResult,
    ModelTurn,
    NormalizedToolCall,
)

# Transitional imports.
#
# The first goal is preserving the known-good OpenAI Responses behavior while
# extracting the provider boundary. Once this path is live and tested, move
# these pure helpers out of openai_client.py into this package.
from app.services.openai_client import (
    PROMPT_CACHE_KEYS,
    TOOL_OUTPUT_TYPES,
    build_dev_content,
    build_openai_input_messages,
    build_payload_for_model,
    developer_pre_prompt_verbose,
    dump_openai_obj,
    extract_text_from_response_output,
)


@dataclass
class OpenAIResponsesContinuation:
    """
    Adapter-private continuation state.

    The orchestrator must treat this as opaque. For the Responses API,
    continuation means preserving the prior input plus the provider's response
    output, then appending function_call_output items after local tools run.
    """

    model: str
    input_items: list[Any]
    base_request_kwargs: dict[str, Any]


class OpenAIResponsesAdapter:
    """
    MemoryMuse adapter for OpenAI's Responses API.

    This class knows OpenAI Responses wire shapes. It does not execute
    MemoryMuse tools, broadcast UI status, persist messages, or decide
    application-level tool-loop policy.
    """

    def __init__(self, client: Any):
        self.client = client

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
        compiled_messages = build_openai_input_messages(messages or [])

        dev_content = build_dev_content(
            dev_prompt,
            muse_settings.get_section("muse_config").get("MUSE_NAME"),
        )

        prompt_cache_key = PROMPT_CACHE_KEYS.get(
            prompt_type,
            PROMPT_CACHE_KEYS["default"],
        )

        bundle = build_payload_for_model(
            model=model,
            developer_pre_prompt_verbose=developer_pre_prompt_verbose,
            dev_content=dev_content,
            compiled_messages=compiled_messages,
            prompt_cache_key=prompt_cache_key,
        )

        return await self._create_turn(
            model=model,
            input_items=bundle["input"],
            base_request_kwargs=bundle["kwargs"],
            tools=tools,
            tool_choice=tool_choice,
        )

    async def continue_turn(
        self,
        *,
        continuation: OpenAIResponsesContinuation,
        tool_results: list[ExecutedToolResult],
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
    ) -> ModelTurn:
        next_input = list(continuation.input_items)

        for result in tool_results:
            next_input.append(
                {
                    "type": "function_call_output",
                    "call_id": result.call_id,
                    "output": self._serialize_tool_result(result),
                }
            )

        return await self._create_turn(
            model=continuation.model,
            input_items=next_input,
            base_request_kwargs=continuation.base_request_kwargs,
            tools=tools,
            tool_choice=tool_choice,
        )

    async def _create_turn(
        self,
        *,
        model: str,
        input_items: list[Any],
        base_request_kwargs: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
    ) -> ModelTurn:
        request_kwargs = dict(base_request_kwargs)

        if tools:
            request_kwargs["tools"] = tools

        if tools and tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice

        response = await self.client.responses.create(
            model=model,
            input=input_items,
            store=True,
            **request_kwargs,
        )

        usage = self._collect_usage(
            response=response,
            model=model,
            request_kwargs=request_kwargs,
        )

        output_items = list(getattr(response, "output", []) or [])

        provider_tool_events = [
            dump_openai_obj(item)
            for item in output_items
            if getattr(item, "type", None) in TOOL_OUTPUT_TYPES
        ]

        function_calls = [
            self._normalize_function_call(item)
            for item in output_items
            if getattr(item, "type", None) == "function_call"
        ]

        continuation = OpenAIResponsesContinuation(
            model=model,
            # Preserve the provider's function-call item(s) in the conversation
            # before appending our function_call_output items next turn.
            input_items=[*input_items, *output_items],
            base_request_kwargs=base_request_kwargs,
        )

        return ModelTurn(
            text=extract_text_from_response_output(response),
            function_calls=function_calls,
            provider_tool_events=provider_tool_events,
            usage=usage,
            continuation=continuation,
        )

    @staticmethod
    def _normalize_function_call(item: Any) -> NormalizedToolCall:
        raw_arguments = getattr(item, "arguments", None) or "{}"

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            function_name = getattr(item, "name", "<unknown>")
            raise ValueError(
                f"OpenAI returned invalid JSON arguments for "
                f"function '{function_name}': {raw_arguments!r}"
            ) from exc

        if not isinstance(arguments, dict):
            function_name = getattr(item, "name", "<unknown>")
            raise ValueError(
                f"OpenAI returned non-object arguments for "
                f"function '{function_name}': {arguments!r}"
            )

        return NormalizedToolCall(
            call_id=getattr(item, "call_id", ""),
            name=getattr(item, "name", ""),
            arguments=arguments,
            raw=dump_openai_obj(item),
        )

    @staticmethod
    def _serialize_tool_result(result: ExecutedToolResult) -> str | list[dict[str, Any]]:
        """
        Preserve current Responses behavior:

        - ordinary tool results become JSON strings;
        - input-image attachments become Responses input_image objects;
        - if a tool has usable input images, they are passed as the output
          payload just as the current get_openai_response() path does.
        """

        image_items: list[dict[str, Any]] = []

        for attachment in result.attachments or []:
            if (
                attachment.get("kind") != "image"
                or attachment.get("role") != "input"
            ):
                continue

            image_item: dict[str, Any] = {
                "type": "input_image",
            }

            if attachment.get("image_url"):
                image_item["image_url"] = attachment["image_url"]
            elif attachment.get("file_id"):
                image_item["file_id"] = attachment["file_id"]
            else:
                continue

            if attachment.get("detail"):
                image_item["detail"] = attachment["detail"]

            image_items.append(image_item)

        if image_items:
            return image_items

        return json.dumps(result.tool_output)

    @staticmethod
    def _collect_usage(
        *,
        response: Any,
        model: str,
        request_kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        response_usage = getattr(response, "usage", None)

        if not response_usage:
            return None

        usage = dump_openai_obj(response_usage)

        input_details = getattr(response_usage, "input_tokens_details", None)
        output_details = getattr(response_usage, "output_tokens_details", None)

        input_tokens = getattr(response_usage, "input_tokens", None)
        cached_tokens = getattr(input_details, "cached_tokens", None)
        output_tokens = getattr(response_usage, "output_tokens", None)
        reasoning_tokens = getattr(output_details, "reasoning_tokens", None)

        print(
            f"Model: {model},\n"
            f"Reasoning: {request_kwargs.get('reasoning')},\n"
            f"Temp: {request_kwargs.get('temperature')},\n"
            f"Tokens — input: {input_tokens},\n"
            f"cached: {cached_tokens},\n"
            f"Tokens - output: {output_tokens},\n"
        )

        if reasoning_tokens is not None:
            print(f"Reasoning tokens: {reasoning_tokens}\n")

        utils.write_system_log(
            level="debug",
            module="core",
            component="openai_responses_adapter",
            function="_collect_usage",
            action="token_usage",
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
        )

        return usage