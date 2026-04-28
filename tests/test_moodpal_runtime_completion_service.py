import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from backend.llm import LLMAPIError, LLMClient, complete_json_with_strategy, reset_structured_output_policy_cache
from backend.moodpal.services.runtime_completion_service import complete_runtime_structured_turn


def _fake_completion(text: str, *, provider: str = 'qwen', model: str = 'qwen-plus', total_tokens: int = 24):
    return SimpleNamespace(
        text=text,
        provider_name=provider,
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - (total_tokens // 2),
            total_tokens=total_tokens,
        ),
    )


@pytest.mark.django_db
@override_settings(MOODPAL_RUNTIME_MAX_TOKENS=321)
def test_runtime_structured_turn_skips_known_prompt_json_only_models():
    payload = {
        'reply': '我们先把现在最难受的那一块放在这里。',
        'state_patch': {'agenda_topic': '工作压力'},
    }
    with patch(
        'backend.moodpal.services.runtime_completion_service.LLMClient.complete_with_metadata',
        return_value=_fake_completion(json.dumps(payload, ensure_ascii=False)),
    ) as mocked_complete:
        result = complete_runtime_structured_turn(
            provider_name='doubao',
            model_name='doubao-seed-2-0-pro-260215',
            prompt='prompt',
            system_prompt='system',
        )

    assert result.payload == payload
    assert result.completion_mode == 'prompt_json'
    assert result.json_mode_degraded is False
    assert result.json_mode_attempted is False
    assert result.structured_output_policy == 'prompt_json_only'
    assert result.max_tokens == 321
    assert mocked_complete.call_count == 1
    first_call = mocked_complete.call_args_list[0]
    assert first_call.kwargs['json_mode'] is False
    assert first_call.kwargs['max_tokens'] == 321


@pytest.mark.django_db
def test_complete_json_with_strategy_probes_unknown_model_once_then_caches_prompt_json_only():
    payload = {
        'reply': '我们先不急着下结论。',
        'state_patch': {'focus': 'unknown-model'},
    }
    reset_structured_output_policy_cache()
    client = LLMClient(provider_name='qwen')

    with patch(
        'backend.llm.client.LLMClient.complete_with_metadata',
        side_effect=[
            LLMAPIError(
                'The parameter `response_format.type` specified in the request are not valid: `json_object` is not supported by this model.',
                status_code=400,
            ),
            _fake_completion(json.dumps(payload, ensure_ascii=False)),
            _fake_completion(json.dumps(payload, ensure_ascii=False)),
        ],
    ) as mocked_complete:
        first = complete_json_with_strategy(
            client,
            prompt='prompt',
            model='qwen-unknown-jsonless',
            temperature=0,
        )
        second = complete_json_with_strategy(
            client,
            prompt='prompt',
            model='qwen-unknown-jsonless',
            temperature=0,
        )

    assert first.completion_mode == 'prompt_json'
    assert first.json_mode_degraded is True
    assert first.json_mode_attempted is True
    assert first.policy == 'auto_probe_once'
    assert second.completion_mode == 'prompt_json'
    assert second.json_mode_degraded is False
    assert second.json_mode_attempted is False
    assert second.policy == 'prompt_json_only'
    assert mocked_complete.call_args_list[0].kwargs['json_mode'] is True
    assert mocked_complete.call_args_list[1].kwargs['json_mode'] is False
    assert mocked_complete.call_args_list[2].kwargs['json_mode'] is False
