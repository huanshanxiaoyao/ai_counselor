from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage
from ..persona_specs import get_persona_spec
from ..services.model_option_service import normalize_selected_model


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationTurnResult:
    reply_text: str
    provider: str
    model: str
    usage: dict
    system_prompt: str = ''
    used_fallback: bool = False


def execute_conversation_turn(
    *,
    persona_id: str,
    hint_text: Optional[str],
    history_messages: list,
    selected_model: str,
    subject_key: str = '',
) -> ConversationTurnResult:
    system_prompt = _build_system_prompt(persona_id, hint_text)
    provider_name, model_name = _resolve_provider_and_model(selected_model)
    try:
        client = LLMClient(provider_name=provider_name)
        result = client.complete_with_history(
            messages=history_messages,
            system_prompt=system_prompt,
            model=model_name,
        )
        reply_text = result.text.strip()
        if not reply_text:
            raise ValueError('empty_reply')
        if result.usage.total_tokens > 0 and subject_key:
            record_token_usage(
                subject=parse_subject_key(subject_key),
                source='moodpal.conversation.turn',
                total_tokens=result.usage.total_tokens,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                provider=provider_name,
                model=result.model,
            )
        return ConversationTurnResult(
            reply_text=reply_text,
            provider=provider_name,
            model=result.model,
            usage={
                'prompt_tokens': result.usage.prompt_tokens,
                'completion_tokens': result.usage.completion_tokens,
                'total_tokens': result.usage.total_tokens,
            },
            system_prompt=system_prompt,
        )
    except Exception:
        logger.exception(
            'ConversationExecutor failed persona=%s provider=%s',
            persona_id,
            provider_name,
        )
        return ConversationTurnResult(
            reply_text='我在，可以继续说。',
            provider=provider_name,
            model=model_name or '',
            usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
            system_prompt=system_prompt,
            used_fallback=True,
        )


def _build_system_prompt(persona_id: str, hint_text: Optional[str]) -> str:
    parts = [get_persona_spec(persona_id)]
    if hint_text:
        parts.append(f'【背景觉察】\n{hint_text}')
    return '\n\n'.join(parts)


def _resolve_provider_and_model(selected_model: str):
    value = normalize_selected_model(selected_model)
    if ':' in value:
        provider_name, model_name = value.split(':', 1)
        provider_name = provider_name.strip() or getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
        return provider_name, model_name.strip() or None
    provider_name = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    return provider_name, value or None
