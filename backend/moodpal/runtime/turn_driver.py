from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from ..models import MoodPalSession
from ..services.cbt_runtime_service import merge_cbt_state_metadata, run_cbt_turn
from ..services.crisis_service import CrisisCheckResult, build_sticky_crisis_result, detect_crisis_text
from ..services.humanistic_runtime_service import merge_humanistic_state_metadata, run_humanistic_turn
from ..services.master_guide_runtime_service import merge_master_guide_state_metadata, run_master_guide_turn
from ..services.psychoanalysis_runtime_service import (
    merge_psychoanalysis_state_metadata,
    run_psychoanalysis_turn,
)


logger = logging.getLogger(__name__)


class RuntimeSessionContext(Protocol):
    id: object
    usage_subject: str
    persona_id: str
    selected_model: str
    status: str
    metadata: dict


@dataclass(frozen=True)
class AssistantTurnResult:
    reply_text: str
    reply_metadata: dict
    next_metadata: dict
    runtime_state_patch: dict | None = None
    safety_override: bool = False
    crisis_result: CrisisCheckResult | None = None
    should_record_crisis_event: bool = False
    used_system_fallback: bool = False


def is_crisis_mode(session: RuntimeSessionContext) -> bool:
    return bool((getattr(session, 'metadata', None) or {}).get('crisis_active'))


def execute_assistant_turn(
    *,
    session: RuntimeSessionContext,
    history_messages: list[dict],
    user_content: str,
    crisis_result: CrisisCheckResult | None = None,
) -> AssistantTurnResult:
    current_metadata = dict(getattr(session, 'metadata', None) or {})
    if crisis_result is None:
        crisis_result = build_sticky_crisis_result() if is_crisis_mode(session) else detect_crisis_text(user_content)

    if crisis_result.triggered:
        next_metadata = build_turn_metadata(
            persona_id=session.persona_id,
            metadata=current_metadata,
            crisis_result=crisis_result,
        )
        return AssistantTurnResult(
            reply_text=crisis_result.response_text,
            reply_metadata=_build_crisis_reply_metadata(crisis_result),
            next_metadata=next_metadata,
            safety_override=True,
            crisis_result=crisis_result,
            should_record_crisis_event=not crisis_result.sticky_mode,
        )

    try:
        reply_text, reply_metadata, runtime_state_patch = _dispatch_runtime(
            session=session,
            history_messages=history_messages,
            user_content=user_content,
        )
        next_metadata = build_turn_metadata(
            persona_id=session.persona_id,
            metadata=current_metadata,
            runtime_state_patch=runtime_state_patch,
        )
        return AssistantTurnResult(
            reply_text=reply_text,
            reply_metadata=reply_metadata,
            next_metadata=next_metadata,
            runtime_state_patch=runtime_state_patch,
        )
    except Exception:
        logger.exception(
            'MoodPal assistant runtime failed, using system fallback session=%s subject=%s persona=%s',
            session.id,
            session.usage_subject,
            session.persona_id,
        )
        reply_text, reply_metadata = _build_system_fallback_reply(session, user_content)
        return AssistantTurnResult(
            reply_text=reply_text,
            reply_metadata=reply_metadata,
            next_metadata=dict(current_metadata),
            used_system_fallback=True,
        )


def build_turn_metadata(
    *,
    persona_id: str,
    metadata: dict | None,
    runtime_state_patch: dict | None = None,
    crisis_result: CrisisCheckResult | None = None,
) -> dict:
    next_metadata = dict(metadata or {})
    if crisis_result and crisis_result.triggered:
        next_metadata['crisis_active'] = True
        return _apply_crisis_runtime_state(persona_id, next_metadata)
    return _merge_runtime_state_metadata(persona_id, next_metadata, runtime_state_patch)


def _dispatch_runtime(
    *,
    session: RuntimeSessionContext,
    history_messages: list[dict],
    user_content: str,
) -> tuple[str, dict, dict | None]:
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        result = run_cbt_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    if session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        result = run_humanistic_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    if session.persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        result = run_master_guide_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    if session.persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        result = run_psychoanalysis_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    return _build_placeholder_reply(session, user_content), {
        'engine': 'placeholder',
        'track': '',
        'technique_id': '',
        'fallback_used': True,
        'fallback_kind': 'placeholder',
        'provider': '',
        'model': '',
        'json_mode_degraded': False,
        'completion_mode': 'rule_fallback',
    }, None


def _build_crisis_reply_metadata(crisis_result: CrisisCheckResult) -> dict:
    return {
        'engine': 'crisis_guard',
        'track': 'safety_override',
        'technique_id': '',
        'fallback_used': True,
        'fallback_kind': 'safety_override',
        'provider': '',
        'model': '',
        'risk_type': crisis_result.risk_type,
        'matched_count': crisis_result.matched_count,
        'detector_stage': crisis_result.detector_stage,
        'sticky_mode': crisis_result.sticky_mode,
        'json_mode_degraded': False,
        'completion_mode': 'rule_fallback',
    }


def _merge_runtime_state_metadata(persona_id: str, metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not state_patch:
        return next_metadata
    if persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        return merge_master_guide_state_metadata(next_metadata, state_patch)
    if persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        return merge_cbt_state_metadata(next_metadata, state_patch)
    if persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        return merge_humanistic_state_metadata(next_metadata, state_patch)
    if persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        return merge_psychoanalysis_state_metadata(next_metadata, state_patch)
    return next_metadata


def _apply_crisis_runtime_state(persona_id: str, metadata: dict) -> dict:
    next_metadata = dict(metadata)
    if persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        cbt_state = dict(next_metadata.get('cbt_state') or {})
        cbt_state['safety_status'] = 'crisis_override'
        cbt_state['current_stage'] = 'wrap_up'
        next_metadata['cbt_state'] = cbt_state
        return next_metadata
    if persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        master_state = dict(next_metadata.get('master_guide_state') or {})
        master_state['current_stage'] = 'wrap_up'
        master_state['current_turn_mode'] = 'support_only'
        master_state['support_mode'] = 'repair'
        master_state['last_route_reason_code'] = 'safety_override'
        next_metadata['master_guide_state'] = master_state

        humanistic_state = dict(next_metadata.get('humanistic_state') or {})
        humanistic_state['safety_status'] = 'crisis_override'
        humanistic_state['current_stage'] = 'wrap_up'
        humanistic_state['current_phase'] = 'safety_override'
        next_metadata['humanistic_state'] = humanistic_state
        return next_metadata
    if persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        humanistic_state = dict(next_metadata.get('humanistic_state') or {})
        humanistic_state['safety_status'] = 'crisis_override'
        humanistic_state['current_stage'] = 'wrap_up'
        humanistic_state['current_phase'] = 'safety_override'
        next_metadata['humanistic_state'] = humanistic_state
        return next_metadata
    if persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        psychoanalysis_state = dict(next_metadata.get('psychoanalysis_state') or {})
        psychoanalysis_state['safety_status'] = 'crisis_override'
        psychoanalysis_state['current_stage'] = 'wrap_up'
        psychoanalysis_state['current_phase'] = 'safety_override'
        next_metadata['psychoanalysis_state'] = psychoanalysis_state
        return next_metadata
    return next_metadata


def _compact_text(value: str, limit: int = 28) -> str:
    text = ' '.join((value or '').split())
    if len(text) <= limit:
        return text
    return f'{text[:limit].rstrip()}...'


def _build_placeholder_reply(session: RuntimeSessionContext, user_content: str) -> str:
    excerpt = _compact_text(user_content, limit=36)
    if session.persona_id in [MoodPalSession.Persona.EMPATHY_SISTER, MoodPalSession.Persona.MASTER_GUIDE]:
        return (
            f"我先接住你的感受。你提到“{excerpt}”，这听起来确实不轻松。"
            "如果现在只说一个最想被理解的部分，你最想先说哪一块？"
        )
    return (
        f"我先记下这句“{excerpt}”。它不像只是一时情绪，可能和某个反复出现的模式有关。"
        "你愿意继续说说，这种感觉以前通常会在什么场景里冒出来吗？"
    )


def _build_system_fallback_reply(session: RuntimeSessionContext, user_content: str) -> tuple[str, dict]:
    excerpt = _compact_text(user_content, limit=36)
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        reply_text = (
            f"我先接住你刚才提到的“{excerpt}”。这一步我没有处理好，"
            "我们先不继续往下推，只把现在最卡住的那一点说清楚也可以。"
        )
    elif session.persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        reply_text = (
            f"我先接住你刚才提到的“{excerpt}”。这一步我没有处理好，"
            "我们先把最需要被理解的那一点放稳，再继续决定往哪个方向聊。"
        )
    elif session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        reply_text = (
            f"我先接住你刚才说的“{excerpt}”。现在系统这一步没有跟上，"
            "但你可以继续慢一点说，我会先陪你把最难受的部分放在这里。"
        )
    else:
        reply_text = (
            f"我先记下你刚才提到的“{excerpt}”。这一步我没有处理好，"
            "我们先退回一点，只说现在最想弄明白的一件事。"
        )
    return reply_text, {
        'engine': 'system_fallback',
        'track': '',
        'technique_id': '',
        'fallback_used': True,
        'fallback_kind': 'system_fallback',
        'provider': '',
        'model': '',
        'error_code': 'assistant_runtime_failed',
        'json_mode_degraded': False,
        'completion_mode': 'rule_fallback',
    }
