"""
OpenAI-compatible LLM provider adapter.

This adapter works with any OpenAI-compatible API:
- OpenRouter
- NVIDIA (NGC)
- OpenCode Zen
- Local models via llama.cpp / vLLM / Ollama
- Any OpenAI-compatible API

Provider-specific behavior is configured through base URL and model name.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.intelligence.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMProviderConfig,
    LLMResponse,
    LLMToolCall,
)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    """Configuration for OpenAI-compatible provider."""

    provider_name: str
    model: str
    api_key: str
    base_url: str
    timeout_seconds: int = 60
    max_retries: int = 2
    retry_base_delay: float = 1.0


class OpenAICompatibleLLMProvider(LLMProvider):
    """
    OpenAI-compatible LLM provider.

    Works with any provider that implements the OpenAI Chat Completions API.
    """

    def __init__(self) -> None:
        self._config: OpenAICompatibleConfig | None = None
        self._client: httpx.AsyncClient | None = None
        self._initialized = False

    @property
    def provider_name(self) -> str:
        if self._config:
            return self._config.provider_name
        return "openai_compatible"

    @property
    def supported_models(self) -> tuple[str, ...]:
        return (self._config.model,) if self._config else ()

    async def initialize(self, config: "LLMProviderConfig") -> None:
        self._initialized = True

        # Parse provider-specific config from the generic config
        provider_name = getattr(config, "provider_name", None) or config.config.get(
            "provider_name", "openai_compatible"
        )
        model = getattr(config, "model", None) or config.config.get("model")
        api_key = config.config.get("api_key", "")
        base_url = config.config.get("base_url", "https://api.openai.com/v1")
        timeout_seconds = config.config.get("timeout_seconds", 60)
        max_retries = config.config.get("max_retries", 2)

        if not api_key:
            # Try to get from environment
            api_key = os.environ.get("LLM_API_KEY", "")

        if not model:
            raise ValueError("Model must be explicitly configured via LLM_MODEL")

        self._config = OpenAICompatibleConfig(
            provider_name=provider_name,
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=config.config.get("retry_base_delay", 1.0),
        )

        # Create HTTP client
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout_seconds),
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _convert_messages(
        self, messages: list[LLMMessage | dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert internal LLMMessage or raw dict to OpenAI format."""
        converted = []
        for msg in messages:
            if isinstance(msg, dict):
                msg_dict: dict[str, Any] = {
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                }
                if msg.get("tool_calls"):
                    msg_dict["tool_calls"] = msg["tool_calls"]
                if msg.get("tool_call_id"):
                    msg_dict["tool_call_id"] = msg["tool_call_id"]
                converted.append(msg_dict)
                continue

            msg_dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": (
                                json.dumps(tc.arguments)
                                if isinstance(tc.arguments, dict)
                                else str(tc.arguments)
                            ),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            converted.append(msg_dict)
        return converted

    def _convert_tools(
        self, tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        """Convert internal or OpenAI tool definitions to standard OpenAI format."""
        if not tools:
            return None
        converted = []
        for tool in tools:
            if "type" in tool and "function" in tool:
                converted.append(tool)
            elif "function" in tool:
                converted.append({"type": "function", "function": tool["function"]})
            else:
                converted.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.get("name", ""),
                            "description": tool.get("description", ""),
                            "parameters": tool.get(
                                "arguments_schema", tool.get("parameters", {})
                            ),
                        },
                    }
                )
        return converted

    def _convert_tool_choice(
        self, tool_choice: str | None
    ) -> str | dict[str, Any] | None:
        """Convert tool_choice to OpenAI format."""
        if tool_choice is None or tool_choice == "auto":
            return "auto"
        if tool_choice == "none":
            return "none"
        # Specific tool name
        return {"type": "function", "function": {"name": tool_choice}}

    async def _make_request(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> httpx.Response:
        """Make HTTP request to the provider API."""
        if not self._client:
            raise RuntimeError("Provider not initialized. Call initialize() first.")
        if not self._config:
            raise RuntimeError("Provider not configured. Call initialize() first.")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": self._convert_messages(messages),
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = self._convert_tool_choice(tool_choice)

        # Make request with retries
        last_error: BaseException | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._client.post("/chat/completions", json=payload)
                response.raise_for_status()
                return response
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_base_delay * (2**attempt))
                    continue
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 or e.response.status_code == 429:
                    last_error = e
                    if attempt < self._config.max_retries:
                        delay = self._config.retry_base_delay * (2**attempt)
                        # Check Retry-After header
                        retry_after = e.response.headers.get("retry-after")
                        if retry_after:
                            try:
                                delay = max(delay, float(retry_after))
                            except ValueError:
                                pass
                        elif e.response.status_code == 429:
                            # Groq 429 rate limits typically need at least 2.5s window
                            delay = max(delay, 2.5 * (attempt + 1))
                        logger.warning(
                            "HTTP %s from %s. Retrying in %.2fs (attempt %d/%d)...",
                            e.response.status_code,
                            self.provider_name,
                            delay,
                            attempt + 1,
                            self._config.max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                # Client errors (4xx except 429) - don't retry
                raise
            except httpx.RequestError as e:
                last_error = e
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_base_delay * (2**attempt))
                    continue

        raise RuntimeError(
            f"Failed after {self._config.max_retries + 1} attempts: {last_error}"
        )

    async def chat_completion(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a chat completion via OpenAI-compatible API."""

        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        response = await self._make_request(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        data = response.json()

        # Parse response
        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                raw_args = func.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        parsed_args = {}
                elif isinstance(raw_args, dict):
                    parsed_args = raw_args
                else:
                    parsed_args = {}

                tool_calls.append(
                    LLMToolCall(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=parsed_args,
                    )
                )

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tuple(tool_calls) if tool_calls else (),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage"),
        )

    async def structured_completion(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        response_schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate a structured completion using JSON schema."""
        # Use function calling with a single function that matches the schema
        schema_func = {
            "name": "structured_output",
            "description": "Generate structured output matching the schema",
            "parameters": response_schema,
        }

        response = await self.chat_completion(
            messages=messages,
            tools=[{"type": "function", "function": schema_func}],
            tool_choice="required",
            temperature=0.0,
        )

        if response.tool_calls:
            tool_call = response.tool_calls[0]
            return tool_call.arguments  # type: ignore[no-any-return]

        # Fallback: try to parse content as JSON
        if response.content:
            try:
                return json.loads(response.content)  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass

        return {}
