"""Failover provider chain.

Tries each configured provider in priority order. Each provider uses its own
model (models are not portable between providers). If every provider fails,
:class:`AllProvidersFailed` is raised so the caller can fall back to the
offline engine.
"""

from __future__ import annotations

from typing import Any
import logging

from config import get_settings
from llm.base import AllProvidersFailed, ProviderError
from llm.clients import AnthropicProvider, GeminiProvider, OpenAIProvider


def build_providers(settings=None) -> list[Any]:
    settings = settings or get_settings()
    providers: list[Any] = []

    def _is_real(key: str) -> bool:
        return settings._is_real_key(key)

    # User-configured priority, then sensible defaults.
    order = [settings.llm_provider.lower(), "gemini", "openai", "anthropic"]
    built: dict[str, Any] = {}
    if _is_real(settings.gemini_api_key):
        built["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if _is_real(settings.openai_api_key):
        built["openai"] = OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.openai_base_url)
    if _is_real(settings.anthropic_api_key):
        built["anthropic"] = AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)

    for name in order:
        if name in built and name not in [p.name for p in providers]:
            providers.append(built[name])
    # Append any remaining configured providers not in the order list.
    for name, provider in built.items():
        if name not in [p.name for p in providers]:
            providers.append(provider)
    return providers


def has_any_provider(settings=None) -> bool:
    return len(build_providers(settings)) > 0


def first_provider(settings=None) -> Any | None:
    providers = build_providers(settings)
    return providers[0] if providers else None


class FailoverProvider:
    """Wraps a list of providers; tries them in order per streamed turn."""

    def __init__(self, providers: list[Any]):
        self.providers = providers
        self.name = "failover"

    def stream_tool_calls(self, messages, tools, system_prompt):
        errors: list[str] = []
        for provider in self.providers:
            try:
                yield from provider.stream_tool_calls(messages, tools, system_prompt)
                return
            except ProviderError as exc:
                logging.error(f"Provider {provider.name} failed: {exc.message}", exc_info=True)
                errors.append(f"{provider.name}: {exc.message}")
                continue
        raise AllProvidersFailed("; ".join(errors))

    def as_events(self, messages, tools, system_prompt) -> dict[str, Any]:
        """Convenience: collect the stream into a plain dict result."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for event in self.stream_tool_calls(messages, tools, system_prompt):
            if event["type"] == "text":
                text_parts.append(event["text"])
            elif event["type"] == "tool_call":
                tool_calls.append(event)
        return {"text": "".join(text_parts), "tool_calls": tool_calls}