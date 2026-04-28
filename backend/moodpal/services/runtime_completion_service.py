from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from django.conf import settings

from backend.llm import CompletionResult, LLMClient, complete_json_with_strategy, parse_json_payload


DEFAULT_RUNTIME_MAX_TOKENS = 700


@dataclass(frozen=True)
class RuntimeStructuredCompletion:
    payload: dict
    completion: CompletionResult
    completion_mode: str = 'json_mode'
    json_mode_degraded: bool = False
    json_mode_attempted: bool = False
    structured_output_policy: str = ''
    max_tokens: int = DEFAULT_RUNTIME_MAX_TOKENS


def get_runtime_max_tokens() -> int:
    value = int(getattr(settings, 'MOODPAL_RUNTIME_MAX_TOKENS', DEFAULT_RUNTIME_MAX_TOKENS) or DEFAULT_RUNTIME_MAX_TOKENS)
    return max(128, value)


def complete_runtime_structured_turn(
    *,
    provider_name: str,
    model_name: str | None,
    prompt: str,
    system_prompt: str,
    client_factory: Type[LLMClient] = LLMClient,
) -> RuntimeStructuredCompletion:
    client = client_factory(provider_name=provider_name)
    max_tokens = get_runtime_max_tokens()
    structured_result = complete_json_with_strategy(
        client,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model_name or None,
        max_tokens=max_tokens,
    )
    payload = parse_json_payload(structured_result.completion.text)
    if not isinstance(payload, dict):
        raise ValueError('invalid_structured_turn_payload')
    return RuntimeStructuredCompletion(
        payload=payload,
        completion=structured_result.completion,
        completion_mode=structured_result.completion_mode,
        json_mode_degraded=bool(structured_result.json_mode_degraded),
        json_mode_attempted=bool(structured_result.json_mode_attempted),
        structured_output_policy=structured_result.policy,
        max_tokens=max_tokens,
    )
