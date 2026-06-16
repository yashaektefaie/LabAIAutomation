"""
Core agent: multi-turn conversation with Claude for Opentrons protocol generation.

Uses prompt caching for the knowledge base, streaming with extended thinking,
and structured data injection for upstream experiment data.
"""

from __future__ import annotations

import json
import re
from typing import Any, Generator

from anthropic import Anthropic, AnthropicVertex
from anthropic.types import (
    ContentBlockParam,
    Message,
    MessageParam,
    TextBlockParam,
    ThinkingBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

from .data_ingestion import FileAttachment, build_data_context
from .knowledge import load_knowledge_docs
from .profile import load_profile, profile_to_prompt
from .prompts import LABWARE_REFERENCE, SYSTEM_PROMPT, build_instruction_prompt
from .settings import Settings

# Stream event types
StreamEvent = tuple[str, str]  # ("thinking" | "text" | "tool_start" | "tool_result", content)


class OpentronAgent:
    """
    Multi-turn conversational agent for generating Opentrons protocols.

    Architecture mirrors the official Opentrons AI server but simplified
    for local / CLI use:
      - System prompt + labware reference as system messages
      - Knowledge docs injected as a cached user message at the start
      - Per-turn: user prompt + any data attachments -> assistant response
      - Extended thinking: live reasoning trace streamed to the UI
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.use_vertex:
            self.client = AnthropicVertex(
                project_id=settings.vertex_project,
                region=settings.vertex_region,
            )
        else:
            self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.model

        # Load machine profile (persisted across sessions)
        self._profile_text = profile_to_prompt(load_profile())

        # Load knowledge docs once (will be sent as a cached prefix)
        self._knowledge_text = load_knowledge_docs(settings)

        # Conversation history (beyond the cached prefix)
        self._history: list[MessageParam] = []

        # File attachments for the current session
        self._attachments: list[FileAttachment] = []

        # Tools available to the model
        self._tools: list[ToolParam] = []

    @property
    def system_content(self) -> list[TextBlockParam]:
        """System prompt blocks with caching on the labware reference."""
        blocks = [
            TextBlockParam(type="text", text=SYSTEM_PROMPT),
        ]
        if self._profile_text:
            blocks.append(TextBlockParam(type="text", text=self._profile_text))
        blocks.append(
            TextBlockParam(
                type="text",
                text=LABWARE_REFERENCE,
                cache_control={"type": "ephemeral"},
            ),
        )
        return blocks

    @property
    def knowledge_messages(self) -> list[MessageParam]:
        """The cached knowledge docs as the first user/assistant exchange."""
        return [
            {
                "role": "user",
                "content": [
                    TextBlockParam(
                        type="text",
                        text=self._knowledge_text,
                        cache_control={"type": "ephemeral"},
                    ),
                ],
            },
            {
                "role": "assistant",
                "content": "Understood. I have the Opentrons documentation loaded and ready to help generate protocols.",
            },
        ]

    @property
    def _thinking_params(self) -> dict:
        """Parameters for extended thinking, when enabled."""
        if not self.settings.thinking_budget:
            return {}
        return {
            "thinking": {
                "type": "adaptive",
            },
            "temperature": 1,  # required when thinking is enabled
        }

    def reload_profile(self) -> None:
        """Reload the machine profile from disk (e.g. after /profile set)."""
        self._profile_text = profile_to_prompt(load_profile())

    def add_attachment(self, attachment: FileAttachment) -> str:
        """Add a file attachment for context. Returns a confirmation message."""
        self._attachments.append(attachment)
        return f"Loaded '{attachment.name}' ({attachment.file_type}, {len(attachment.content)} chars)"

    def reset(self) -> None:
        """Clear conversation history and attachments."""
        self._history.clear()
        self._attachments.clear()

    # ------------------------------------------------------------------
    # Non-streaming chat (kept for backwards compatibility)
    # ------------------------------------------------------------------

    def chat(self, user_input: str) -> str:
        """Send a message and get a response. Handles tool use automatically."""
        thinking_text = ""
        result_text = ""
        for event_type, chunk in self.chat_stream(user_input):
            if event_type == "thinking":
                thinking_text += chunk
            elif event_type == "text":
                result_text += chunk
        return result_text

    # ------------------------------------------------------------------
    # Streaming chat with extended thinking
    # ------------------------------------------------------------------

    def chat_stream(self, user_input: str) -> Generator[StreamEvent, None, None]:
        """
        Stream a response. Yields (event_type, chunk) tuples:
          - ("thinking", text)   — reasoning trace chunks
          - ("text", text)       — response text chunks
          - ("tool_start", name) — tool call starting
          - ("tool_result", text)— tool call result
        """
        data_context = build_data_context(self._attachments)
        prompt_text = build_instruction_prompt(user_input, data_context)

        messages: list[MessageParam] = [
            *self.knowledge_messages,
            *self._history,
            {"role": "user", "content": prompt_text},
        ]

        # Stream the first response
        result_text, messages = yield from self._stream_and_handle_tools(messages)

        # Update conversation history
        self._history.append({"role": "user", "content": prompt_text})
        self._history.append({"role": "assistant", "content": result_text})

    def _stream_and_handle_tools(
        self, messages: list[MessageParam]
    ) -> Generator[StreamEvent, None, tuple[str, list[MessageParam]]]:
        """Stream a response, handling tool use loops. Returns (final_text, messages)."""
        while True:
            collected_text = ""
            collected_thinking = ""
            tool_uses: list[dict] = []
            current_block_type: str | None = None
            current_tool: dict = {}

            api_params = self._base_api_params(messages)

            with self.client.messages.stream(**api_params) as stream:
                for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "thinking":
                            current_block_type = "thinking"
                        elif block.type == "text":
                            current_block_type = "text"
                        elif block.type == "tool_use":
                            current_block_type = "tool_use"
                            current_tool = {"id": block.id, "name": block.name, "input_json": ""}
                            yield ("tool_start", block.name)

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "thinking_delta":
                            collected_thinking += delta.thinking
                            yield ("thinking", delta.thinking)
                        elif delta.type == "text_delta":
                            collected_text += delta.text
                            yield ("text", delta.text)
                        elif delta.type == "input_json_delta":
                            current_tool["input_json"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_block_type == "tool_use" and current_tool:
                            current_tool["input"] = json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                            tool_uses.append(current_tool)
                            current_tool = {}
                        current_block_type = None

                response = stream.get_final_message()

            # If no tool use, we're done
            if response.stop_reason != "tool_use":
                return collected_text, messages

            # Handle tool calls
            assistant_content: list[ContentBlockParam] = []
            tool_results: list[ContentBlockParam] = []

            for block in response.content:
                if block.type == "thinking":
                    assistant_content.append(
                        ThinkingBlockParam(type="thinking", thinking=block.thinking, signature=block.signature)
                    )
                elif block.type == "text":
                    assistant_content.append(TextBlockParam(type="text", text=block.text))
                elif block.type == "tool_use":
                    assistant_content.append(
                        ToolUseBlockParam(type="tool_use", id=block.id, name=block.name, input=block.input)
                    )
                    result = self._execute_tool(block.name, block.input)
                    yield ("tool_result", result)
                    tool_results.append(
                        ToolResultBlockParam(type="tool_result", tool_use_id=block.id, content=result)
                    )

            messages = [
                *messages,
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": tool_results},
            ]

    def _base_api_params(self, messages: list[MessageParam]) -> dict:
        """Build the base kwargs for a messages API call."""
        params = {
            "model": self.model,
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
            "system": self.system_content,
            "messages": messages,
        }
        if self._tools:
            params["tools"] = self._tools
        # Extended thinking overrides
        thinking = self._thinking_params
        if thinking:
            params.update(thinking)
        return params

    def _execute_tool(self, name: str, params: Any) -> str:
        """Execute a tool call synchronously."""
        return f"Unknown tool: {name}"
