from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.moodpal.models import MoodPalSession
from backend.moodpal.runtime.turn_driver import execute_assistant_turn

from .token_ledger_service import EvalUsageRecord, build_usage_record


@dataclass
class EvalTargetSessionContext:
    persona_id: str
    usage_subject: str
    selected_model: str = ''
    status: str = MoodPalSession.Status.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class EvalTargetTurnResult:
    user_message: dict
    assistant_message: dict
    transcript: list[dict]
    target_trace: list[dict]
    next_metadata: dict
    usage_records: list[EvalUsageRecord] = field(default_factory=list)
    safety_override: bool = False
    stop_reason: str = ''


def run_target_turn(
    *,
    session_context: EvalTargetSessionContext,
    transcript: list[dict],
    user_content: str,
) -> EvalTargetTurnResult:
    content = (user_content or '').strip()
    if not content:
        raise ValueError('empty_message')

    user_message = {
        'role': 'user',
        'content': content,
        'metadata': {},
    }
    history_messages = [_serialize_history_message(item) for item in transcript] + [user_message]
    turn_result = execute_assistant_turn(
        session=session_context,
        history_messages=history_messages,
        user_content=content,
    )
    session_context.metadata = dict(turn_result.next_metadata)

    assistant_message = {
        'role': 'assistant',
        'content': turn_result.reply_text,
        'metadata': turn_result.reply_metadata,
    }
    updated_transcript = list(transcript) + [user_message, assistant_message]
    trace_entry = _build_target_trace_entry(
        session_context=session_context,
        turn_result=turn_result,
    )
    usage_records = _build_target_usage_records(session_context=session_context, turn_result=turn_result)
    return EvalTargetTurnResult(
        user_message=user_message,
        assistant_message=assistant_message,
        transcript=updated_transcript,
        target_trace=[trace_entry],
        next_metadata=dict(turn_result.next_metadata),
        usage_records=usage_records,
        safety_override=turn_result.safety_override,
        stop_reason='safety_override' if turn_result.safety_override else '',
    )


def _serialize_history_message(message: dict) -> dict:
    return {
        'role': message.get('role', ''),
        'content': message.get('content', ''),
        'metadata': dict(message.get('metadata') or {}),
    }


def _build_target_trace_entry(*, session_context: EvalTargetSessionContext, turn_result) -> dict:
    metadata = dict(turn_result.next_metadata or {})
    master_state = dict(metadata.get('master_guide_state') or {})
    cbt_state = dict(metadata.get('cbt_state') or {})
    humanistic_state = dict(metadata.get('humanistic_state') or {})
    psychoanalysis_state = dict(metadata.get('psychoanalysis_state') or {})
    crisis_result = turn_result.crisis_result
    return {
        'assistant_engine': turn_result.reply_metadata.get('engine', ''),
        'track': turn_result.reply_metadata.get('track', ''),
        'technique_id': turn_result.reply_metadata.get('technique_id', ''),
        'fallback_used': bool(turn_result.reply_metadata.get('fallback_used')),
        'fallback_kind': turn_result.reply_metadata.get('fallback_kind', ''),
        'safety_override': bool(turn_result.safety_override),
        'json_mode_degraded': bool(turn_result.reply_metadata.get('json_mode_degraded')),
        'completion_mode': turn_result.reply_metadata.get('completion_mode', ''),
        'llm_error_type': turn_result.reply_metadata.get('llm_error_type', ''),
        'crisis_active': bool(metadata.get('crisis_active')),
        'risk_type': crisis_result.risk_type if crisis_result else '',
        'detector_stage': crisis_result.detector_stage if crisis_result else '',
        'route_trace_tail': _tail(master_state.get('route_trace') or []),
        'cbt_trace_tail': _tail(cbt_state.get('technique_trace') or []),
        'humanistic_trace_tail': _tail(humanistic_state.get('technique_trace') or []),
        'psychoanalysis_trace_tail': _tail(psychoanalysis_state.get('technique_trace') or []),
        'persona_id': session_context.persona_id,
    }


def _build_target_usage_records(*, session_context: EvalTargetSessionContext, turn_result) -> list[EvalUsageRecord]:
    reply_metadata = dict(turn_result.reply_metadata or {})
    usage = dict(reply_metadata.get('usage') or {})
    if int(usage.get('total_tokens') or 0) <= 0:
        return []
    engine = str(reply_metadata.get('engine') or '').strip() or 'target_turn'
    return [
        build_usage_record(
            scope='target',
            provider=reply_metadata.get('provider', ''),
            model=reply_metadata.get('model', ''),
            usage=usage,
            request_label=f'target_turn:{engine}',
            metadata={
                'persona_id': session_context.persona_id,
                'engine': engine,
                'track': reply_metadata.get('track', ''),
                'technique_id': reply_metadata.get('technique_id', ''),
                'json_mode_degraded': bool(reply_metadata.get('json_mode_degraded')),
                'completion_mode': reply_metadata.get('completion_mode', ''),
                'fallback_kind': reply_metadata.get('fallback_kind', ''),
            },
        )
    ]


def _tail(items: list[dict]) -> dict:
    if not items:
        return {}
    return dict(items[-1] or {})
