from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from ..models import MoodPalMessage, MoodPalSession, MoodPalSessionEvent
from .cbt_runtime_service import merge_cbt_state_metadata, run_cbt_turn
from .burn_service import record_session_event
from .crisis_service import CrisisCheckResult, build_sticky_crisis_result
from .humanistic_runtime_service import merge_humanistic_state_metadata, run_humanistic_turn


logger = logging.getLogger(__name__)


def _compact_text(value: str, limit: int = 28) -> str:
    text = ' '.join((value or '').split())
    if len(text) <= limit:
        return text
    return f'{text[:limit].rstrip()}...'


def serialize_message(message: MoodPalMessage) -> dict:
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat(),
        'metadata': message.metadata or {},
    }


def list_serialized_messages(session: MoodPalSession) -> list[dict]:
    return [serialize_message(item) for item in session.messages.order_by('created_at', 'id')]


def _build_placeholder_reply(session: MoodPalSession, user_content: str) -> str:
    excerpt = _compact_text(user_content, limit=36)
    if session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        return (
            f"我先接住你的感受。你提到“{excerpt}”，这听起来确实不轻松。"
            "如果现在只说一个最想被理解的部分，你最想先说哪一块？"
        )
    return (
        f"我先记下这句“{excerpt}”。它不像只是一时情绪，可能和某个反复出现的模式有关。"
        "你愿意继续说说，这种感觉以前通常会在什么场景里冒出来吗？"
    )


def is_crisis_mode(session: MoodPalSession) -> bool:
    return bool((session.metadata or {}).get('crisis_active'))


def _build_assistant_reply(
    session: MoodPalSession,
    history_messages: list[dict],
    user_content: str,
) -> tuple[str, dict, dict | None]:
    if is_crisis_mode(session):
        crisis_result = build_sticky_crisis_result()
        logger.warning(
            'MoodPal crisis sticky mode continued session=%s subject=%s risk_type=%s',
            session.id,
            session.usage_subject,
            crisis_result.risk_type,
        )
        return crisis_result.response_text, {
            'engine': 'crisis_guard',
            'track': 'safety_override',
            'technique_id': '',
            'fallback_used': True,
            'provider': '',
            'model': '',
            'risk_type': crisis_result.risk_type,
            'matched_count': crisis_result.matched_count,
            'detector_stage': crisis_result.detector_stage,
            'sticky_mode': True,
        }, None
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        result = run_cbt_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    if session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        result = run_humanistic_turn(session=session, history_messages=history_messages)
        return result.reply_text, result.reply_metadata, result.persist_patch
    return _build_placeholder_reply(session, user_content), {
        'engine': 'placeholder',
        'track': '',
        'technique_id': '',
        'fallback_used': True,
        'provider': '',
        'model': '',
    }, None


def _build_system_fallback_reply(session: MoodPalSession, user_content: str) -> tuple[str, dict]:
    excerpt = _compact_text(user_content, limit=36)
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        reply_text = (
            f"我先接住你刚才提到的“{excerpt}”。这一步我没有处理好，"
            "我们先不继续往下推，只把现在最卡住的那一点说清楚也可以。"
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
        'provider': '',
        'model': '',
        'error_code': 'assistant_runtime_failed',
    }


def _merge_runtime_state_metadata(session: MoodPalSession, state_patch: dict | None) -> dict:
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        return merge_cbt_state_metadata(session.metadata, state_patch)
    if session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        return merge_humanistic_state_metadata(session.metadata, state_patch)
    return dict(session.metadata or {})


def _apply_crisis_runtime_state(session: MoodPalSession, metadata: dict) -> dict:
    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        cbt_state = dict(metadata.get('cbt_state') or {})
        cbt_state['safety_status'] = 'crisis_override'
        cbt_state['current_stage'] = 'wrap_up'
        metadata['cbt_state'] = cbt_state
        return metadata
    if session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        humanistic_state = dict(metadata.get('humanistic_state') or {})
        humanistic_state['safety_status'] = 'crisis_override'
        humanistic_state['current_stage'] = 'wrap_up'
        humanistic_state['current_phase'] = 'safety_override'
        metadata['humanistic_state'] = humanistic_state
        return metadata
    return metadata


def append_crisis_response_pair(session: MoodPalSession, *, user_content: str, crisis_result: CrisisCheckResult):
    content = (user_content or '').strip()
    if not content:
        raise ValueError('empty_message')

    with transaction.atomic():
        session = MoodPalSession.objects.select_for_update().get(pk=session.pk)
        now = timezone.now()
        if session.status == MoodPalSession.Status.STARTING:
            session.status = MoodPalSession.Status.ACTIVE
            session.activated_at = now
        if session.status != MoodPalSession.Status.ACTIVE:
            raise ValueError('session_unavailable')

        user_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.USER,
            content=content,
        )

        metadata = dict(session.metadata or {})
        metadata['crisis_active'] = True
        metadata = _apply_crisis_runtime_state(session, metadata)
        session.metadata = metadata
        session.last_activity_at = now
        session.save(update_fields=['status', 'activated_at', 'metadata', 'last_activity_at', 'updated_at'])

        assistant_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.ASSISTANT,
            content=crisis_result.response_text,
            metadata={
                'engine': 'crisis_guard',
                'track': 'safety_override',
                'technique_id': '',
                'fallback_used': True,
                'provider': '',
                'model': '',
                'risk_type': crisis_result.risk_type,
                'matched_count': crisis_result.matched_count,
                'detector_stage': crisis_result.detector_stage,
                'sticky_mode': crisis_result.sticky_mode,
            },
        )

        if not crisis_result.sticky_mode:
            record_session_event(
                session,
                MoodPalSessionEvent.EventType.CRISIS_TRIGGERED,
                metadata={
                    'risk_type': crisis_result.risk_type,
                    'matched_count': crisis_result.matched_count,
                    'detector_stage': crisis_result.detector_stage,
                },
            )

    if crisis_result.sticky_mode:
        logger.warning(
            'MoodPal crisis sticky response persisted session=%s subject=%s risk_type=%s',
            session.id,
            session.usage_subject,
            crisis_result.risk_type,
        )
    else:
        logger.warning(
            'MoodPal crisis override triggered session=%s subject=%s risk_type=%s matched_count=%s detector_stage=%s',
            session.id,
            session.usage_subject,
            crisis_result.risk_type,
            crisis_result.matched_count,
            crisis_result.detector_stage,
        )
    return session, user_message, assistant_message


def append_message_pair(session: MoodPalSession, *, user_content: str):
    content = (user_content or '').strip()
    if not content:
        raise ValueError('empty_message')

    with transaction.atomic():
        session = MoodPalSession.objects.select_for_update().get(pk=session.pk)
        now = timezone.now()
        if session.status == MoodPalSession.Status.STARTING:
            session.status = MoodPalSession.Status.ACTIVE
            session.activated_at = now
        if session.status != MoodPalSession.Status.ACTIVE:
            raise ValueError('session_unavailable')

        user_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.USER,
            content=content,
        )
        session.last_activity_at = now
        session.save(update_fields=['status', 'activated_at', 'last_activity_at', 'updated_at'])

    session.refresh_from_db()
    if session.status != MoodPalSession.Status.ACTIVE:
        raise ValueError('session_unavailable')
    history_messages = list_serialized_messages(session)
    try:
        assistant_content, assistant_metadata, runtime_state_patch = _build_assistant_reply(session, history_messages, content)
    except Exception:
        logger.exception(
            'MoodPal assistant runtime failed, using system fallback session=%s subject=%s persona=%s',
            session.id,
            session.usage_subject,
            session.persona_id,
        )
        assistant_content, assistant_metadata = _build_system_fallback_reply(session, content)
        runtime_state_patch = None

    with transaction.atomic():
        session = MoodPalSession.objects.select_for_update().get(pk=session.pk)
        if session.status != MoodPalSession.Status.ACTIVE:
            raise ValueError('session_unavailable')
        if (session.metadata or {}).get('crisis_active') and assistant_metadata.get('engine') != 'crisis_guard':
            raise ValueError('session_unavailable')
        update_fields = ['last_activity_at', 'updated_at']
        if runtime_state_patch:
            session.metadata = _merge_runtime_state_metadata(session, runtime_state_patch)
            update_fields.append('metadata')
        session.last_activity_at = timezone.now()
        session.save(update_fields=update_fields)
        assistant_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.ASSISTANT,
            content=assistant_content,
            metadata=assistant_metadata,
        )
    return session, user_message, assistant_message
