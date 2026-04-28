from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from ..runtime.turn_driver import build_turn_metadata, execute_assistant_turn, is_crisis_mode
from ..models import MoodPalMessage, MoodPalSession, MoodPalSessionEvent
from .burn_service import record_session_event
from .crisis_service import CrisisCheckResult


logger = logging.getLogger(__name__)


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

        history_messages = list_serialized_messages(session)
        turn_result = execute_assistant_turn(
            session=session,
            history_messages=history_messages,
            user_content=content,
            crisis_result=crisis_result,
        )
        session.metadata = turn_result.next_metadata
        session.last_activity_at = now
        session.save(update_fields=['status', 'activated_at', 'metadata', 'last_activity_at', 'updated_at'])

        assistant_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.ASSISTANT,
            content=turn_result.reply_text,
            metadata=turn_result.reply_metadata,
        )

        if turn_result.should_record_crisis_event:
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
    turn_result = execute_assistant_turn(
        session=session,
        history_messages=history_messages,
        user_content=content,
    )

    with transaction.atomic():
        session = MoodPalSession.objects.select_for_update().get(pk=session.pk)
        if session.status != MoodPalSession.Status.ACTIVE:
            raise ValueError('session_unavailable')
        if (session.metadata or {}).get('crisis_active') and turn_result.reply_metadata.get('engine') != 'crisis_guard':
            raise ValueError('session_unavailable')
        update_fields = ['last_activity_at', 'updated_at', 'metadata']
        session.metadata = build_turn_metadata(
            persona_id=session.persona_id,
            metadata=session.metadata,
            runtime_state_patch=turn_result.runtime_state_patch,
            crisis_result=turn_result.crisis_result if turn_result.safety_override else None,
        )
        session.last_activity_at = timezone.now()
        session.save(update_fields=update_fields)
        assistant_message = MoodPalMessage.objects.create(
            session=session,
            role=MoodPalMessage.Role.ASSISTANT,
            content=turn_result.reply_text,
            metadata=turn_result.reply_metadata,
        )
        if turn_result.should_record_crisis_event:
            record_session_event(
                session,
                MoodPalSessionEvent.EventType.CRISIS_TRIGGERED,
                metadata={
                    'risk_type': turn_result.crisis_result.risk_type if turn_result.crisis_result else '',
                    'matched_count': turn_result.crisis_result.matched_count if turn_result.crisis_result else 0,
                    'detector_stage': turn_result.crisis_result.detector_stage if turn_result.crisis_result else '',
                },
            )
    return session, user_message, assistant_message
