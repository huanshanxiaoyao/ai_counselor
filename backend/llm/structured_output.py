from __future__ import annotations

import json
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .client import CompletionResult, LLMClient
from .exceptions import LLMAPIError


JSON_MODE_UNSUPPORTED_HINTS = (
    'response_format.type',
    'json_object',
    'not supported by this model',
)

COMPLETION_MODE_JSON_MODE = 'json_mode'
COMPLETION_MODE_PROMPT_JSON = 'prompt_json'

STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE = 'native_json_mode'
STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY = 'prompt_json_only'
STRUCTURED_OUTPUT_POLICY_AUTO_PROBE_ONCE = 'auto_probe_once'

# These entries are backed by official provider docs or direct provider 400 responses.
MODEL_STRUCTURED_OUTPUT_POLICIES = {
    ('qwen', 'qwen-plus'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('qwen', 'qwen-max'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('qwen', 'qwen3.5-plus'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('deepseek', 'deepseek-chat'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('deepseek', 'deepseek-reasoner'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('doubao', 'doubao-seed-2-0-lite-260215'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('doubao', 'doubao-seed-2-0-mini-260215'): STRUCTURED_OUTPUT_POLICY_NATIVE_JSON_MODE,
    ('doubao', 'doubao-seed-2-0-pro-260215'): STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY,
    ('minimax', 'minimax-m2.5'): STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY,
    ('minimax', 'minimax-m2.7'): STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY,
}

_PROMPT_JSON_ONLY_CACHE: set[tuple[str, str]] = set()
_PROMPT_JSON_ONLY_CACHE_LOCK = Lock()


@dataclass(frozen=True)
class StructuredOutputResult:
    completion: CompletionResult
    json_mode_degraded: bool = False
    completion_mode: str = COMPLETION_MODE_JSON_MODE
    json_mode_attempted: bool = False
    policy: str = STRUCTURED_OUTPUT_POLICY_AUTO_PROBE_ONCE


def complete_json_with_strategy(client: LLMClient, **kwargs) -> StructuredOutputResult:
    provider = getattr(client, 'provider', None)
    provider_name = str(
        getattr(provider, 'name', '') or getattr(client, 'provider_name', '') or ''
    ).strip()
    model_name = str(kwargs.get('model') or getattr(provider, 'default_model', '') or '').strip()
    policy = resolve_structured_output_policy(client=client, provider_name=provider_name, model_name=model_name)

    if policy == STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY:
        completion = client.complete_with_metadata(json_mode=False, **kwargs)
        return StructuredOutputResult(
            completion=completion,
            json_mode_degraded=False,
            completion_mode=COMPLETION_MODE_PROMPT_JSON,
            json_mode_attempted=False,
            policy=policy,
        )

    try:
        completion = client.complete_with_metadata(json_mode=True, **kwargs)
        return StructuredOutputResult(
            completion=completion,
            json_mode_degraded=False,
            completion_mode=COMPLETION_MODE_JSON_MODE,
            json_mode_attempted=True,
            policy=policy,
        )
    except LLMAPIError as exc:
        if not is_json_mode_unsupported_error(exc):
            raise
        _remember_prompt_json_only(provider_name=provider_name, model_name=model_name)
        completion = client.complete_with_metadata(json_mode=False, **kwargs)
        return StructuredOutputResult(
            completion=completion,
            json_mode_degraded=True,
            completion_mode=COMPLETION_MODE_PROMPT_JSON,
            json_mode_attempted=True,
            policy=policy,
        )


def complete_json_with_fallback(client: LLMClient, **kwargs) -> tuple[CompletionResult, bool]:
    result = complete_json_with_strategy(client, **kwargs)
    return result.completion, result.json_mode_degraded


def resolve_structured_output_policy(*, client: LLMClient, provider_name: str, model_name: str) -> str:
    provider = getattr(client, 'provider', None)
    sdk_type = str(getattr(provider, 'sdk_type', 'openai') or 'openai').strip().lower()
    if sdk_type != 'openai':
        return STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY

    key = _structured_output_model_key(provider_name=provider_name, model_name=model_name)
    if key in MODEL_STRUCTURED_OUTPUT_POLICIES:
        return MODEL_STRUCTURED_OUTPUT_POLICIES[key]
    if key in _PROMPT_JSON_ONLY_CACHE:
        return STRUCTURED_OUTPUT_POLICY_PROMPT_JSON_ONLY
    return STRUCTURED_OUTPUT_POLICY_AUTO_PROBE_ONCE


def reset_structured_output_policy_cache() -> None:
    with _PROMPT_JSON_ONLY_CACHE_LOCK:
        _PROMPT_JSON_ONLY_CACHE.clear()


def _remember_prompt_json_only(*, provider_name: str, model_name: str) -> None:
    with _PROMPT_JSON_ONLY_CACHE_LOCK:
        _PROMPT_JSON_ONLY_CACHE.add(_structured_output_model_key(provider_name=provider_name, model_name=model_name))


def _structured_output_model_key(*, provider_name: str, model_name: str) -> tuple[str, str]:
    return (
        str(provider_name or '').strip().lower(),
        str(model_name or '').strip().lower(),
    )


def is_json_mode_unsupported_error(exc: LLMAPIError) -> bool:
    if getattr(exc, 'status_code', None) != 400:
        return False
    message = str(exc).lower()
    return all(hint in message for hint in ['response_format.type', 'json_object']) or any(
        hint in message for hint in JSON_MODE_UNSUPPORTED_HINTS
    )


def parse_json_payload(raw_text: str) -> Any:
    text = (raw_text or '').strip()
    if not text:
        return None

    candidates = [text]
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
