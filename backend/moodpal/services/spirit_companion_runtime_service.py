from __future__ import annotations

import logging
from dataclasses import dataclass

from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpiritCompanionTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict | None = None


def run_spirit_companion_turn(
    *,
    session,
    history_messages: list[dict],
) -> SpiritCompanionTurnResult:
    logger.info(
        'MoodPal spirit_companion conversation turn session=%s subject=%s',
        session.id, session.usage_subject,
    )
    result = execute_conversation_turn(
        persona_id=session.persona_id,
        hint_text=None,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )
    reply_metadata = {
        'engine': 'spirit_companion',
        'track': '',
        'technique_id': '',
        'fallback_used': result.used_fallback,
        'fallback_kind': 'system_fallback' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'json_mode_degraded': False,
        'completion_mode': 'chat',
    }
    return SpiritCompanionTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=None,
    )
