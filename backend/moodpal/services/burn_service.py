from __future__ import annotations

import logging

from django.utils import timezone

from ..models import MoodPalSession, MoodPalSessionEvent


logger = logging.getLogger(__name__)


def _mark_metadata(session: MoodPalSession, key: str, value):
    metadata = dict(session.metadata or {})
    metadata[key] = value
    session.metadata = metadata
    session.save(update_fields=['metadata', 'updated_at'])


def record_session_event(session: MoodPalSession, event_type: str, *, metadata: dict | None = None):
    return MoodPalSessionEvent.objects.create(
        session=session,
        event_type=event_type,
        metadata=metadata or {},
    )


def mark_summary_generated(
    session: MoodPalSession,
    *,
    raw_message_count: int,
    user_message_count: int,
):
    if (session.metadata or {}).get('summary_generated_at'):
        return
    generated_at = timezone.now().isoformat()
    _mark_metadata(session, 'summary_generated_at', generated_at)
    record_session_event(
        session,
        MoodPalSessionEvent.EventType.SUMMARY_GENERATED,
        metadata={
            'raw_message_count': raw_message_count,
            'user_message_count': user_message_count,
        },
    )
    logger.info(
        'MoodPal summary generated session=%s raw_messages=%s user_messages=%s',
        session.id,
        raw_message_count,
        user_message_count,
    )


def destroy_raw_messages(session: MoodPalSession) -> int:
    if (session.metadata or {}).get('raw_messages_destroyed_at'):
        return int((session.metadata or {}).get('raw_messages_destroyed_count') or 0)

    message_qs = session.messages.all()
    raw_message_count = message_qs.count()
    message_qs.delete()

    destroyed_at = timezone.now().isoformat()
    metadata = dict(session.metadata or {})
    metadata.pop('cbt_state', None)
    metadata.pop('humanistic_state', None)
    metadata.pop('psychoanalysis_state', None)
    metadata.pop('pattern_memory_candidate', None)
    metadata.pop('last_summary', None)
    metadata['raw_messages_destroyed_at'] = destroyed_at
    metadata['raw_messages_destroyed_count'] = raw_message_count
    session.metadata = metadata
    session.save(update_fields=['metadata', 'updated_at'])

    record_session_event(
        session,
        MoodPalSessionEvent.EventType.RAW_MESSAGES_DESTROYED,
        metadata={'raw_message_count': raw_message_count},
    )
    logger.info(
        'MoodPal raw messages destroyed session=%s raw_messages=%s runtime_states_cleared=%s',
        session.id,
        raw_message_count,
        True,
    )
    return raw_message_count


def mark_summary_saved(session: MoodPalSession, *, summary_length: int):
    if (session.metadata or {}).get('summary_saved_at'):
        return
    saved_at = timezone.now().isoformat()
    metadata = dict(session.metadata or {})
    metadata['summary_saved_at'] = saved_at
    session.metadata = metadata
    session.save(update_fields=['metadata', 'updated_at'])
    record_session_event(
        session,
        MoodPalSessionEvent.EventType.SUMMARY_SAVED,
        metadata={'summary_length': summary_length},
    )
    logger.info(
        'MoodPal summary saved session=%s summary_length=%s',
        session.id,
        summary_length,
    )


def mark_summary_destroyed(session: MoodPalSession):
    if (session.metadata or {}).get('summary_destroyed_at'):
        return
    destroyed_at = timezone.now().isoformat()
    metadata = dict(session.metadata or {})
    metadata['summary_destroyed_at'] = destroyed_at
    session.metadata = metadata
    session.save(update_fields=['metadata', 'updated_at'])
    record_session_event(
        session,
        MoodPalSessionEvent.EventType.SUMMARY_DESTROYED,
    )
    logger.info('MoodPal summary destroyed session=%s', session.id)
