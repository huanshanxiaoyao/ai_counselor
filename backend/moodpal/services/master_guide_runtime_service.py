from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..hint_generator import generate_hint
from ..master_guide.routing_signal_extractor import extract_master_guide_routing_signals
from ..master_guide.state import build_master_guide_state_from_session
from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MasterGuideRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_master_guide_turn(*, session, history_messages: list) -> MasterGuideRuntimeTurnResult:
    metadata = dict(session.metadata or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    state['cbt_state'] = {}
    state['humanistic_state'] = {}
    state['psychoanalysis_state'] = {}

    conv_state = dict(metadata.get('conversation_state') or {})
    last_hint_turn_index = int(conv_state.get('last_hint_turn_index') or -99)

    signals = extract_master_guide_routing_signals(state)
    turn_index = int(state.get('turn_index') or 0)
    hint_text = generate_hint(signals, turn_index=turn_index, last_hint_turn_index=last_hint_turn_index)

    logger.info(
        'MoodPal conversation turn session=%s subject=%s persona=%s turn=%s hint=%s alliance=%s distress=%s',
        session.id,
        session.usage_subject,
        session.persona_id,
        turn_index,
        bool(hint_text),
        signals.get('alliance_status'),
        signals.get('distress_level'),
    )

    result = execute_conversation_turn(
        persona_id=session.persona_id,
        hint_text=hint_text,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )

    next_last_hint = turn_index if hint_text else last_hint_turn_index
    persist_patch = {
        'conversation_state': {
            'last_hint_turn_index': next_last_hint,
            'alliance_status': signals.get('alliance_status', 'medium'),
        }
    }

    reply_metadata = {
        'engine': 'conversation',
        'track': 'free_chat',
        'technique_id': '',
        'hint_injected': bool(hint_text),
        'fallback_used': result.used_fallback,
        'fallback_kind': 'llm_local_rule' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'usage': result.usage,
        'alliance_status': signals.get('alliance_status'),
        'distress_level': signals.get('distress_level'),
        'json_mode_degraded': False,
        'completion_mode': 'chat' if not result.used_fallback else 'rule_fallback',
        'llm_error_type': '',
        'debug_system_prompt': result.system_prompt,
        'debug_user_prompt': next(
            (m.get('content', '') for m in reversed(history_messages) if m.get('role') == 'user'),
            '',
        ),
    }

    return MasterGuideRuntimeTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=persist_patch,
        used_fallback=result.used_fallback,
    )


def merge_master_guide_state_metadata(metadata, state_patch) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata
    if state_patch.get('conversation_state'):
        merged = dict(next_metadata.get('conversation_state') or {})
        merged.update(state_patch['conversation_state'])
        next_metadata['conversation_state'] = merged
    return next_metadata
