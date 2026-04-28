from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from backend.roundtable.services.token_quota import subject_from_request

from ..models import MoodPalMessage, MoodPalSession
from ..psychoanalysis.pattern_memory import build_psychoanalysis_memory
from .burn_service import (
    destroy_raw_messages,
    mark_summary_destroyed,
    mark_summary_generated,
    mark_summary_saved,
)
from .model_option_service import describe_selected_model, normalize_selected_model
from .summary_service import build_summary_draft


PERSONA_CATALOG = {
    MoodPalSession.Persona.MASTER_GUIDE: {
        'id': MoodPalSession.Persona.MASTER_GUIDE,
        'title': '全能主理人',
        'subtitle': '默认推荐｜整合式陪伴',
        'description': '如果你不确定现在更需要被接住、被梳理，还是想看清反复出现的模式，可以先从这里开始。',
        'problems': ['刚进来不知道选谁', '情绪和问题交织在一起', '希望边聊边判断方向'],
        'recommended': True,
    },
    MoodPalSession.Persona.LOGIC_BROTHER: {
        'id': MoodPalSession.Persona.LOGIC_BROTHER,
        'title': '逻辑派的邻家哥哥',
        'subtitle': 'CBT 内核',
        'description': '擅长把混乱的情绪和想法拆开，帮你一步步看清当下最卡住的地方。',
        'problems': ['脑内反刍', '担心搞砸', '负面假设停不下来'],
        'recommended': False,
    },
    MoodPalSession.Persona.EMPATHY_SISTER: {
        'id': MoodPalSession.Persona.EMPATHY_SISTER,
        'title': '共情派的知心学姐',
        'subtitle': '人本主义陪伴',
        'description': '先接住你的情绪，再慢慢陪你把那些说不清的委屈和疲惫讲明白。',
        'problems': ['今天只想被理解', '情绪泛滥', '不想听大道理'],
        'recommended': False,
    },
    MoodPalSession.Persona.INSIGHT_MENTOR: {
        'id': MoodPalSession.Persona.INSIGHT_MENTOR,
        'title': '深挖派的心理学前辈',
        'subtitle': '探索式对话',
        'description': '适合反复卡在相似关系模式的人，慢慢理解那些总会被触发的深层原因。',
        'problems': ['总遇到同一类问题', '反复掉进旧模式', '想理解更深层触发点'],
        'recommended': False,
    },
}


@dataclass(frozen=True)
class SessionAccessContext:
    subject_key: str
    anon_id: str
    owner_id: int | None


def get_persona_catalog():
    return list(PERSONA_CATALOG.values())


def get_persona_config(persona_id: str) -> dict:
    if persona_id not in PERSONA_CATALOG:
        raise ValueError('invalid_persona')
    return PERSONA_CATALOG[persona_id]


def _now():
    return timezone.now()


def _lock_session(session: MoodPalSession) -> MoodPalSession:
    return MoodPalSession.objects.select_for_update().get(pk=session.pk)


def _access_context_from_request(request) -> SessionAccessContext:
    subject = subject_from_request(request)
    user = getattr(request, 'user', None)
    owner_id = user.id if user is not None and user.is_authenticated else None
    return SessionAccessContext(
        subject_key=subject.key,
        anon_id=subject.anon_id,
        owner_id=owner_id,
    )


def _build_session_metadata(*, privacy_acknowledged: bool) -> dict:
    metadata = {}
    if privacy_acknowledged:
        metadata['privacy_acknowledged'] = True
        metadata['privacy_acknowledged_at'] = _now().isoformat()
        metadata['privacy_contract_version'] = 'v1'
    return metadata


def _compact_context_text(value: str, limit: int = 800) -> str:
    text = (value or '').strip()
    if len(text) <= limit:
        return text
    return f'{text[:limit].rstrip()}...'


def _serialize_last_summary_context(source_session: MoodPalSession) -> dict:
    summary_text = _compact_context_text(source_session.summary_final or source_session.summary_draft)
    if not summary_text:
        return {}
    return {
        'source_session_id': str(source_session.id),
        'source_persona_id': source_session.persona_id,
        'source_persona_title': source_session.get_persona_id_display(),
        'summary_text': summary_text,
        'saved_at': (source_session.metadata or {}).get('summary_saved_at') or source_session.updated_at.isoformat(),
    }


def _load_recent_saved_summary_context(subject_key: str) -> dict:
    queryset = (
        MoodPalSession.objects.filter(
            usage_subject=subject_key,
            summary_action=MoodPalSession.SummaryAction.SAVED,
        )
        .order_by('-updated_at', '-created_at')
    )
    for session in queryset[:5]:
        payload = _serialize_last_summary_context(session)
        if payload:
            return payload
    return {}


def create_session(
    *,
    request,
    persona_id: str,
    selected_model: str = '',
    privacy_acknowledged: bool = False,
) -> MoodPalSession:
    get_persona_config(persona_id)
    if not privacy_acknowledged:
        raise ValueError('privacy_ack_required')
    access = _access_context_from_request(request)
    metadata = _build_session_metadata(privacy_acknowledged=privacy_acknowledged)
    last_summary = _load_recent_saved_summary_context(access.subject_key)
    if last_summary:
        metadata['last_summary'] = last_summary
    return MoodPalSession.objects.create(
        owner_id=access.owner_id,
        usage_subject=access.subject_key,
        anon_id=access.anon_id,
        persona_id=persona_id,
        selected_model=normalize_selected_model(selected_model),
        metadata=metadata,
        status=MoodPalSession.Status.STARTING,
        last_activity_at=_now(),
    )


def can_access_session(*, request, session: MoodPalSession) -> bool:
    access = _access_context_from_request(request)
    if session.owner_id and access.owner_id == session.owner_id:
        return True
    if session.anon_id and access.anon_id and session.anon_id == access.anon_id:
        return True
    return False


def get_session_or_404(*, request, session_id) -> MoodPalSession:
    try:
        session = MoodPalSession.objects.get(pk=session_id)
    except MoodPalSession.DoesNotExist as exc:
        raise Http404('session_not_found') from exc
    if not can_access_session(request=request, session=session):
        raise Http404('session_not_found')
    return sync_timeout(session)


def activate_session(session: MoodPalSession) -> MoodPalSession:
    if session.status != MoodPalSession.Status.STARTING:
        return session
    now = _now()
    session.status = MoodPalSession.Status.ACTIVE
    session.activated_at = now
    session.last_activity_at = now
    session.save(update_fields=['status', 'activated_at', 'last_activity_at', 'updated_at'])
    return session


def touch_session(session: MoodPalSession) -> MoodPalSession:
    if session.status not in [MoodPalSession.Status.STARTING, MoodPalSession.Status.ACTIVE]:
        return session
    session.last_activity_at = _now()
    session.save(update_fields=['last_activity_at', 'updated_at'])
    return session


def _set_summary_pending(session: MoodPalSession, reason: str) -> MoodPalSession:
    with transaction.atomic():
        session = _lock_session(session)
        if session.status in [MoodPalSession.Status.SUMMARY_PENDING, MoodPalSession.Status.CLOSED]:
            return session

        now = _now()
        session.ended_at = session.ended_at or now
        session.close_reason = reason

        raw_message_count = session.messages.count()
        user_message_count = session.messages.filter(role=MoodPalMessage.Role.USER).count()
        session.summary_draft = build_summary_draft(session)
        session.status = MoodPalSession.Status.SUMMARY_PENDING
        session.last_activity_at = now
        session.save(update_fields=['ended_at', 'close_reason', 'summary_draft', 'status', 'last_activity_at', 'updated_at'])

        mark_summary_generated(
            session,
            raw_message_count=raw_message_count,
            user_message_count=user_message_count,
        )
        return session


def sync_timeout(session: MoodPalSession) -> MoodPalSession:
    if session.status not in [MoodPalSession.Status.STARTING, MoodPalSession.Status.ACTIVE]:
        return session
    timeout_at = session.last_activity_at + timezone.timedelta(seconds=session.timeout_seconds)
    if timeout_at <= _now():
        return _set_summary_pending(session, MoodPalSession.CloseReason.IDLE_TIMEOUT)
    return session


def end_session(session: MoodPalSession, *, reason: str = MoodPalSession.CloseReason.USER_ENDED) -> MoodPalSession:
    session = sync_timeout(session)
    if session.status in [MoodPalSession.Status.SUMMARY_PENDING, MoodPalSession.Status.CLOSED]:
        return session
    return _set_summary_pending(session, reason)


def save_summary(session: MoodPalSession, *, summary_text: str) -> MoodPalSession:
    with transaction.atomic():
        session = _lock_session(session)
        if session.status == MoodPalSession.Status.ACTIVE:
            raise ValueError('session_still_active')
        if session.status == MoodPalSession.Status.STARTING:
            raise ValueError('session_not_started')
        if session.status == MoodPalSession.Status.CLOSED:
            if session.summary_action == MoodPalSession.SummaryAction.SAVED:
                return session
            raise ValueError('session_closed')

        session.summary_final = (summary_text or '').strip() or session.summary_draft
        session.summary_action = MoodPalSession.SummaryAction.SAVED
        session.status = MoodPalSession.Status.CLOSED
        metadata = dict(session.metadata or {})
        psychoanalysis_memory = build_psychoanalysis_memory(session)
        if psychoanalysis_memory:
            metadata['psychoanalysis_memory_v1'] = psychoanalysis_memory
        else:
            metadata.pop('psychoanalysis_memory_v1', None)
        session.metadata = metadata
        session.save(update_fields=['summary_final', 'summary_action', 'status', 'metadata', 'updated_at'])

        destroy_raw_messages(session)
        mark_summary_saved(session, summary_length=len(session.summary_final))
        return session


def destroy_summary(session: MoodPalSession) -> MoodPalSession:
    with transaction.atomic():
        session = _lock_session(session)
        if session.status == MoodPalSession.Status.ACTIVE:
            raise ValueError('session_still_active')
        if session.status == MoodPalSession.Status.STARTING:
            raise ValueError('session_not_started')
        if session.status == MoodPalSession.Status.CLOSED:
            if session.summary_action == MoodPalSession.SummaryAction.DESTROYED:
                return session
            raise ValueError('session_closed')

        session.summary_final = ''
        session.summary_draft = ''
        session.summary_action = MoodPalSession.SummaryAction.DESTROYED
        session.status = MoodPalSession.Status.CLOSED
        metadata = dict(session.metadata or {})
        metadata.pop('psychoanalysis_memory_v1', None)
        metadata.pop('pattern_memory_candidate', None)
        if session.persona_id == MoodPalSession.Persona.MASTER_GUIDE:
            metadata.pop('master_guide_state', None)
            metadata.pop('humanistic_state', None)
            metadata.pop('cbt_state', None)
            metadata.pop('psychoanalysis_state', None)
        session.metadata = metadata
        session.save(update_fields=['summary_final', 'summary_draft', 'summary_action', 'status', 'metadata', 'updated_at'])

        destroy_raw_messages(session)
        mark_summary_destroyed(session)
        return session


def _serialize_debug_payload(session: MoodPalSession) -> dict | None:
    if not settings.DEBUG:
        return None

    metadata = dict(session.metadata or {})
    last_summary = dict(metadata.get('last_summary') or {})
    runtime_state_key = ''
    engine = 'placeholder'
    runtime_state = {}
    current_path_key = 'current_track'

    if session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        runtime_state_key = 'cbt_state'
        engine = 'cbt_graph'
        runtime_state = dict(metadata.get(runtime_state_key) or {})
        current_path_key = 'current_track'
    elif session.persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        runtime_state_key = 'master_guide_state'
        engine = 'master_guide_orchestrator'
        runtime_state = dict(metadata.get(runtime_state_key) or {})
        current_path_key = 'active_main_track'
    elif session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        runtime_state_key = 'humanistic_state'
        engine = 'humanistic_graph'
        runtime_state = dict(metadata.get(runtime_state_key) or {})
        current_path_key = 'current_phase'
    elif session.persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        runtime_state_key = 'psychoanalysis_state'
        engine = 'psychoanalysis_graph'
        runtime_state = dict(metadata.get(runtime_state_key) or {})
        current_path_key = 'current_phase'
    else:
        runtime_state = {}

    if session.persona_id not in [MoodPalSession.Persona.INSIGHT_MENTOR, MoodPalSession.Persona.MASTER_GUIDE] and not runtime_state and not last_summary:
        return None

    technique_trace = list(runtime_state.get('technique_trace') or [])
    route_trace = list(runtime_state.get('route_trace') or [])
    payload = {
        'enabled': True,
        'engine': engine,
        'current_stage': runtime_state.get('current_stage', ''),
        'current_track': runtime_state.get(current_path_key, ''),
        'current_phase': runtime_state.get('current_phase', ''),
        'current_turn_mode': runtime_state.get('current_turn_mode', ''),
        'current_technique_id': runtime_state.get('current_technique_id', ''),
        'next_fallback_action': runtime_state.get('next_fallback_action', ''),
        'circuit_breaker_open': bool(runtime_state.get('circuit_breaker_open')),
        'last_route_reason': runtime_state.get('last_route_reason', ''),
        'technique_trace': technique_trace,
        'trace_length': len(technique_trace),
        'route_trace': route_trace,
        'route_trace_length': len(route_trace),
        'last_summary_available': bool(last_summary.get('summary_text')),
        'last_summary_source_session_id': last_summary.get('source_session_id', ''),
        'last_summary_source_persona_id': last_summary.get('source_persona_id', ''),
        'last_summary_preview': _compact_context_text(last_summary.get('summary_text', ''), limit=180),
        'recalled_pattern_memory_count': int(runtime_state.get('recalled_pattern_memory_count') or 0),
        'recalled_pattern_memory_preview': runtime_state.get('recalled_pattern_memory_preview') or [],
        'summary_hints': list(runtime_state.get('summary_hints') or []),
        'runtime_state_key': runtime_state_key,
        'runtime_state': runtime_state,
    }
    return payload


def serialize_session(session: MoodPalSession) -> dict:
    persona = get_persona_config(session.persona_id)
    payload = {
        'id': str(session.id),
        'status': session.status,
        'persona_id': session.persona_id,
        'persona_title': persona['title'],
        'selected_model': session.selected_model,
        'selected_model_label': describe_selected_model(session.selected_model),
        'privacy_acknowledged': bool((session.metadata or {}).get('privacy_acknowledged')),
        'privacy_acknowledged_at': (session.metadata or {}).get('privacy_acknowledged_at'),
        'crisis_active': bool((session.metadata or {}).get('crisis_active')),
        'summary_action': session.summary_action,
        'close_reason': session.close_reason,
        'timeout_seconds': session.timeout_seconds,
        'created_at': session.created_at.isoformat(),
        'activated_at': session.activated_at.isoformat() if session.activated_at else None,
        'last_activity_at': session.last_activity_at.isoformat() if session.last_activity_at else None,
        'ended_at': session.ended_at.isoformat() if session.ended_at else None,
        'summary_draft': session.summary_draft,
        'summary_final': session.summary_final,
        'raw_message_count': session.messages.count(),
    }
    debug_payload = _serialize_debug_payload(session)
    if debug_payload:
        payload['debug'] = debug_payload
    return payload
