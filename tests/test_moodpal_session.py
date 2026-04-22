import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from backend.moodpal.models import MoodPalMessage, MoodPalSession, MoodPalSessionEvent
from backend.moodpal.services.crisis_service import detect_crisis_text
from backend.moodpal.services.message_service import append_crisis_response_pair, append_message_pair
from backend.roundtable.models import TokenQuotaState


@contextmanager
def _capture_named_logger(caplog, logger_name: str, level: int = logging.INFO):
    target_logger = logging.getLogger(logger_name)
    previous_level = target_logger.level
    target_logger.addHandler(caplog.handler)
    target_logger.setLevel(level)
    try:
        yield
    finally:
        target_logger.removeHandler(caplog.handler)
        target_logger.setLevel(previous_level)


def _anon_client(cookie_value: str) -> Client:
    client = Client()
    client.cookies['anon_usage_id'] = cookie_value
    return client


@pytest.mark.django_db
def test_moodpal_home_page_renders():
    client = Client()
    resp = client.get('/moodpal/')
    assert resp.status_code == 200
    assert 'MoodPal' in resp.content.decode('utf-8')
    assert '隐私契约与边界说明' in resp.content.decode('utf-8')


@pytest.mark.django_db
def test_moodpal_start_session_and_activate_on_first_open():
    client = Client()

    resp = client.post(
        '/moodpal/',
        data={
            'persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
            'privacy_acknowledged': '1',
        },
    )
    assert resp.status_code == 302

    session = MoodPalSession.objects.get()
    assert session.status == MoodPalSession.Status.STARTING
    assert session.metadata['privacy_acknowledged'] is True
    assert session.metadata['privacy_contract_version'] == 'v1'

    opened = client.get(resp['Location'])
    assert opened.status_code == 200

    session.refresh_from_db()
    assert session.status == MoodPalSession.Status.ACTIVE
    assert session.activated_at is not None


@pytest.mark.django_db
def test_moodpal_start_session_blocks_when_quota_exceeded():
    client = _anon_client('anon-quota-start')
    TokenQuotaState.objects.create(
        subject_key='anon:anon-quota-start',
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id='anon-quota-start',
        used_tokens=100000,
        quota_limit=100000,
    )

    resp = client.post(
        '/moodpal/',
        data={
            'persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
            'privacy_acknowledged': '1',
        },
    )

    assert resp.status_code == 402
    assert MoodPalSession.objects.count() == 0
    assert '配额' in resp.content.decode('utf-8')


@pytest.mark.django_db
def test_moodpal_start_session_requires_privacy_acknowledgement():
    client = Client()

    resp = client.post('/moodpal/', data={'persona_id': MoodPalSession.Persona.LOGIC_BROTHER})

    assert resp.status_code == 400
    assert MoodPalSession.objects.count() == 0
    assert '隐私契约' in resp.content.decode('utf-8')


@pytest.mark.django_db
def test_moodpal_session_start_api_persists_selected_model_and_returns_quota():
    client = _anon_client('anon-start-api')

    resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
                'selected_model': 'deepseek:deepseek-chat',
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )

    assert resp.status_code == 201
    payload = resp.json()
    session = MoodPalSession.objects.get()
    assert session.selected_model == 'deepseek:deepseek-chat'
    assert payload['session']['selected_model'] == 'deepseek:deepseek-chat'
    assert payload['session']['selected_model_label'] == 'DeepSeek / deepseek-chat'
    assert payload['session']['privacy_acknowledged'] is True
    assert payload['quota']['subject_key'] == 'anon:anon-start-api'


@pytest.mark.django_db
def test_moodpal_session_start_api_blocks_when_quota_exceeded():
    client = _anon_client('anon-start-api-quota')
    TokenQuotaState.objects.create(
        subject_key='anon:anon-start-api-quota',
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id='anon-start-api-quota',
        used_tokens=100000,
        quota_limit=100000,
    )

    resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )

    assert resp.status_code == 402
    assert resp.json()['error_code'] == 'quota_exceeded'
    assert MoodPalSession.objects.count() == 0


@pytest.mark.django_db
def test_moodpal_session_start_api_requires_privacy_acknowledgement():
    client = _anon_client('anon-start-api-privacy')

    resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps({'persona_id': MoodPalSession.Persona.LOGIC_BROTHER}),
        content_type='application/json',
    )

    assert resp.status_code == 400
    assert resp.json()['error'] == 'privacy_ack_required'
    assert MoodPalSession.objects.count() == 0


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_moodpal_session_detail_api_exposes_debug_state_in_debug_mode():
    client = _anon_client('anon-debug-detail')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-debug-detail',
        anon_id='anon-debug-detail',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'current_stage': 'evaluate_exit',
                'current_track': 'cognitive_evaluation',
                'current_technique_id': 'cbt_cog_eval_socratic',
                'next_fallback_action': 'switch_same_track',
                'circuit_breaker_open': False,
                'technique_trace': [
                    {
                        'turn_index': 1,
                        'track': 'agenda',
                        'technique_id': 'cbt_structure_agenda_setting',
                        'progress_marker': 'agenda_locked',
                        'done': True,
                        'should_trip_circuit': False,
                    }
                ],
            }
        },
    )

    resp = client.get(f'/api/moodpal/session/{session.id}')

    assert resp.status_code == 200
    debug_payload = resp.json()['session']['debug']
    assert debug_payload['enabled'] is True
    assert debug_payload['engine'] == 'cbt_graph'
    assert debug_payload['current_stage'] == 'evaluate_exit'
    assert debug_payload['current_track'] == 'cognitive_evaluation'
    assert debug_payload['current_technique_id'] == 'cbt_cog_eval_socratic'
    assert debug_payload['trace_length'] == 1


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_moodpal_session_detail_api_hides_debug_state_outside_debug_mode():
    client = _anon_client('anon-debug-off')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-debug-off',
        anon_id='anon-debug-off',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'current_stage': 'route_track',
            }
        },
    )

    resp = client.get(f'/api/moodpal/session/{session.id}')

    assert resp.status_code == 200
    assert 'debug' not in resp.json()['session']


@pytest.mark.django_db
@override_settings(LLM_DEFAULT_PROVIDER='qwen')
def test_moodpal_message_api_persists_cbt_exchange_for_logic_brother():
    client = _anon_client('anon-message-flow')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-message-flow',
        anon_id='anon-message-flow',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.STARTING,
    )

    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我们先只锁定一个点。此刻最让你反复卡住的，是“担心再犯错”这件事，对吗？',
                'state_patch': {
                    'agenda_topic': '担心工作里再次犯错',
                    'agenda_locked': True,
                    'mood_label': 'anxious',
                    'mood_score': 76,
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=17, total_tokens=28),
        model='fake-cbt-model',
    )

    with patch('backend.moodpal.services.cbt_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我总在反复担心工作里会再犯错。'}),
            content_type='application/json',
        )
    assert resp.status_code == 201

    session.refresh_from_db()
    assert session.status == MoodPalSession.Status.ACTIVE
    assert session.activated_at is not None

    messages = list(MoodPalMessage.objects.filter(session=session).order_by('created_at', 'id'))
    assert len(messages) == 2
    assert messages[0].role == MoodPalMessage.Role.USER
    assert messages[0].content == '我总在反复担心工作里会再犯错。'
    assert messages[1].role == MoodPalMessage.Role.ASSISTANT
    assert '只锁定一个点' in messages[1].content
    assert messages[1].metadata['engine'] == 'cbt_graph'
    assert messages[1].metadata['technique_id'] == 'cbt_structure_agenda_setting'
    assert messages[1].metadata['provider'] == 'qwen'
    assert session.metadata['cbt_state']['agenda_topic'] == '担心工作里再次犯错'
    assert session.metadata['cbt_state']['agenda_locked'] is True

    payload = resp.json()
    assert len(payload['messages']) == 2
    assert payload['session']['raw_message_count'] == 2


@pytest.mark.django_db
def test_moodpal_message_api_uses_selected_model_provider():
    client = _anon_client('anon-model-provider')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-model-provider',
        anon_id='anon-model-provider',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        selected_model='deepseek:deepseek-chat',
    )
    called = {}

    class FakeClient:
        def __init__(self, provider_name=None):
            called['provider_name'] = provider_name

        def complete_with_metadata(self, **kwargs):
            called['model'] = kwargs.get('model')
            return SimpleNamespace(
                text=json.dumps(
                    {
                        'reply': '我们先把你最担心的那句话抓清楚。',
                        'state_patch': {'agenda_topic': '工作上的担心', 'agenda_locked': True},
                    },
                    ensure_ascii=False,
                ),
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8),
                model='deepseek-chat',
            )

    with patch('backend.moodpal.services.cbt_runtime_service.LLMClient', FakeClient):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我很怕明天又出错。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    assert called['provider_name'] == 'deepseek'
    assert called['model'] == 'deepseek-chat'
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['provider'] == 'deepseek'
    assert assistant_message.metadata['model'] == 'deepseek-chat'


@pytest.mark.django_db
def test_moodpal_message_api_falls_back_when_cbt_llm_fails():
    client = _anon_client('anon-message-fallback')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-message-fallback',
        anon_id='anon-message-fallback',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '会议里的失误',
                'agenda_locked': True,
            }
        },
    )

    with patch('backend.moodpal.services.cbt_runtime_service.LLMClient.complete_with_metadata', side_effect=RuntimeError('boom')):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我想不起来当时脑子里在想什么。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    session.refresh_from_db()
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'cbt_graph'
    assert assistant_message.metadata['fallback_used'] is True
    assert session.metadata['cbt_state']['thought_format'] == 'imagery'


@pytest.mark.django_db
def test_moodpal_message_api_blocks_when_quota_exceeded():
    client = _anon_client('anon-quota-message')
    TokenQuotaState.objects.create(
        subject_key='anon:anon-quota-message',
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id='anon-quota-message',
        used_tokens=100000,
        quota_limit=100000,
    )
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-quota-message',
        anon_id='anon-quota-message',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )

    resp = client.post(
        f'/api/moodpal/session/{session.id}/message',
        data=json.dumps({'content': '我今天真的很难受。'}),
        content_type='application/json',
    )

    assert resp.status_code == 402
    assert resp.json()['error_code'] == 'quota_exceeded'
    assert MoodPalMessage.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_moodpal_crisis_message_bypasses_quota_and_enters_safety_mode(caplog):
    client = _anon_client('anon-crisis')
    TokenQuotaState.objects.create(
        subject_key='anon:anon-crisis',
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id='anon-crisis',
        used_tokens=100000,
        quota_limit=100000,
    )
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-crisis',
        anon_id='anon-crisis',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
    )

    with _capture_named_logger(caplog, 'backend.moodpal.services.message_service', level=logging.WARNING):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我真的不想活了，我想自杀。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    payload = resp.json()
    assert payload['safety_override'] is True
    session.refresh_from_db()
    assert session.metadata['crisis_active'] is True
    assert session.metadata['cbt_state']['safety_status'] == 'crisis_override'
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'crisis_guard'
    assert assistant_message.metadata['matched_count'] > 0
    assert assistant_message.metadata['detector_stage'] == 'regex'
    assert 'matched_terms' not in assistant_message.metadata
    assert '120 / 110' in assistant_message.content
    event = MoodPalSessionEvent.objects.get(
        session=session,
        event_type=MoodPalSessionEvent.EventType.CRISIS_TRIGGERED,
    )
    assert event.metadata['risk_type'] == 'self_harm'
    assert event.metadata['matched_count'] > 0
    assert event.metadata['detector_stage'] == 'regex'
    assert 'matched_terms' not in event.metadata
    assert 'MoodPal crisis override triggered' in caplog.text
    assert '想自杀' not in caplog.text
    assert '不想活了' not in caplog.text


@pytest.mark.django_db
def test_moodpal_crisis_mode_stays_active_for_followup_message(caplog):
    client = _anon_client('anon-crisis-followup')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-crisis-followup',
        anon_id='anon-crisis-followup',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'crisis_active': True,
            'cbt_state': {'safety_status': 'crisis_override'},
        },
    )

    with _capture_named_logger(caplog, 'backend.moodpal.services.message_service', level=logging.WARNING):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我现在不知道该怎么办。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'crisis_guard'
    assert assistant_message.metadata['sticky_mode'] is True
    assert assistant_message.metadata['matched_count'] == 0
    assert assistant_message.metadata['detector_stage'] == 'sticky_followup'
    assert MoodPalSessionEvent.objects.filter(
        session=session,
        event_type=MoodPalSessionEvent.EventType.CRISIS_TRIGGERED,
    ).count() == 0
    assert 'MoodPal crisis sticky response persisted' in caplog.text


@pytest.mark.django_db
def test_append_crisis_response_pair_rolls_back_when_event_write_fails():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-crisis-rollback',
        anon_id='anon-crisis-rollback',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
    )
    crisis_result = detect_crisis_text('我真的不想活了，我想自杀。')

    with patch('backend.moodpal.services.message_service.record_session_event', side_effect=RuntimeError('event_write_fail')):
        with pytest.raises(RuntimeError, match='event_write_fail'):
            append_crisis_response_pair(
                session,
                user_content='我真的不想活了，我想自杀。',
                crisis_result=crisis_result,
            )

    session.refresh_from_db()
    assert session.metadata == {}
    assert MoodPalMessage.objects.filter(session=session).count() == 0
    assert MoodPalSessionEvent.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_append_message_pair_preserves_concurrent_metadata_updates():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-message-merge',
        anon_id='anon-message-merge',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '旧议题',
                'agenda_locked': False,
            },
        },
    )

    def _fake_build_reply(current_session, history_messages, user_content):
        MoodPalSession.objects.filter(pk=current_session.pk).update(
            metadata={
                'summary_generated_at': '2026-04-22T10:00:00+08:00',
                'raw_messages_destroyed_at': '2026-04-22T10:05:00+08:00',
                'cbt_state': {
                    'agenda_topic': '旧议题',
                    'agenda_locked': False,
                    'repeated_theme_detected': True,
                },
            }
        )
        return (
            '我们先把最卡住的一点说清楚。',
            {
                'engine': 'cbt_graph',
                'track': 'agenda',
                'technique_id': 'cbt_structure_agenda_setting',
                'fallback_used': False,
                'provider': 'qwen',
                'model': 'fake-model',
            },
            {
                'agenda_topic': '新议题',
                'agenda_locked': True,
                'current_track': 'agenda',
                'current_technique_id': 'cbt_structure_agenda_setting',
            },
        )

    with patch('backend.moodpal.services.message_service._build_assistant_reply', side_effect=_fake_build_reply):
        session, user_message, assistant_message = append_message_pair(
            session,
            user_content='我还是一直在担心工作上的一个失误。',
        )

    session.refresh_from_db()
    assert user_message.role == MoodPalMessage.Role.USER
    assert assistant_message.role == MoodPalMessage.Role.ASSISTANT
    assert session.metadata['summary_generated_at'] == '2026-04-22T10:00:00+08:00'
    assert session.metadata['raw_messages_destroyed_at'] == '2026-04-22T10:05:00+08:00'
    assert session.metadata['cbt_state']['repeated_theme_detected'] is True
    assert session.metadata['cbt_state']['agenda_topic'] == '新议题'
    assert session.metadata['cbt_state']['agenda_locked'] is True


@pytest.mark.django_db
def test_append_message_pair_returns_system_fallback_when_runtime_raises():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-system-fallback',
        anon_id='anon-system-fallback',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
    )

    with patch('backend.moodpal.services.message_service.run_cbt_turn', side_effect=RuntimeError('boom')):
        session, user_message, assistant_message = append_message_pair(
            session,
            user_content='我现在脑子很乱，不知道该从哪说起。',
        )

    assert user_message.role == MoodPalMessage.Role.USER
    assert assistant_message.role == MoodPalMessage.Role.ASSISTANT
    assert assistant_message.metadata['engine'] == 'system_fallback'
    assert assistant_message.metadata['fallback_used'] is True
    assert assistant_message.metadata['error_code'] == 'assistant_runtime_failed'


@pytest.mark.django_db
def test_append_message_pair_aborts_normal_reply_after_concurrent_crisis_activation():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-crisis-guard',
        anon_id='anon-crisis-guard',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
    )

    def _fake_build_reply(current_session, history_messages, user_content):
        MoodPalSession.objects.filter(pk=current_session.pk).update(
            metadata={
                'crisis_active': True,
                'cbt_state': {
                    'safety_status': 'crisis_override',
                    'current_stage': 'wrap_up',
                },
            }
        )
        return (
            '这是一条不应该被落库的普通回复。',
            {
                'engine': 'cbt_graph',
                'track': 'agenda',
                'technique_id': 'cbt_structure_agenda_setting',
                'fallback_used': False,
                'provider': 'qwen',
                'model': 'fake-model',
            },
            {
                'agenda_topic': '新议题',
                'agenda_locked': True,
            },
        )

    with patch('backend.moodpal.services.message_service._build_assistant_reply', side_effect=_fake_build_reply):
        with pytest.raises(ValueError, match='session_unavailable'):
            append_message_pair(
                session,
                user_content='我还是一直在担心工作上的一个失误。',
            )

    session.refresh_from_db()
    assert session.metadata['crisis_active'] is True
    assert MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).count() == 0


@pytest.mark.django_db
def test_moodpal_non_cbt_persona_keeps_placeholder_reply():
    client = _anon_client('anon-placeholder')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-placeholder',
        anon_id='anon-placeholder',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )

    resp = client.post(
        f'/api/moodpal/session/{session.id}/message',
        data=json.dumps({'content': '我今天真的很委屈。'}),
        content_type='application/json',
    )

    assert resp.status_code == 201
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'placeholder'
    assert '最想被理解的部分' in assistant_message.content


@pytest.mark.django_db
def test_moodpal_session_times_out_into_summary_pending():
    client = _anon_client('anon-timeout-test')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-timeout-test',
        anon_id='anon-timeout-test',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        last_activity_at=timezone.now() - timezone.timedelta(seconds=1900),
    )

    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='最近总是睡不好，脑子停不下来。',
    )

    resp = client.get(f'/moodpal/session/{session.id}/')
    assert resp.status_code == 302
    assert resp['Location'].endswith(f'/moodpal/session/{session.id}/summary/')

    session.refresh_from_db()
    assert session.status == MoodPalSession.Status.SUMMARY_PENDING
    assert session.close_reason == MoodPalSession.CloseReason.IDLE_TIMEOUT
    assert '睡不好' in session.summary_draft
    assert MoodPalSessionEvent.objects.filter(
        session=session,
        event_type=MoodPalSessionEvent.EventType.SUMMARY_GENERATED,
    ).exists()


@pytest.mark.django_db
def test_moodpal_summary_draft_includes_cbt_state_material():
    client = _anon_client('anon-cbt-summary')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-cbt-summary',
        anon_id='anon-cbt-summary',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '担心开会出错',
                'balanced_response': '虽然我会紧张，但还没有证据证明我一定会搞砸。',
                'homework_candidate': '明天开会前先写下一个想问的问题',
            }
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我一想到明天开会就很紧张。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='我们先把最担心的一句想法抓出来。',
    )

    resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert resp.status_code == 200

    session.refresh_from_db()
    assert '本次锁定的议题：担心开会出错' in session.summary_draft
    assert '当前形成的平衡想法：虽然我会紧张，但还没有证据证明我一定会搞砸。' in session.summary_draft
    assert '建议带走的微行动：明天开会前先写下一个想问的问题' in session.summary_draft


@pytest.mark.django_db
def test_moodpal_summary_save_closes_session_and_burns_raw_messages():
    client = _anon_client('anon-summary-save')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-summary-save',
        anon_id='anon-summary-save',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我最近总觉得自己什么都做不好。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='这种持续否定自己的感觉确实会很累。',
    )

    end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert end_resp.status_code == 200

    save_resp = client.post(
        f'/moodpal/session/{session.id}/summary/',
        data={'action': 'save', 'summary_text': '编辑后的摘要'},
    )
    assert save_resp.status_code == 302

    session.refresh_from_db()
    assert session.status == MoodPalSession.Status.CLOSED
    assert session.summary_action == MoodPalSession.SummaryAction.SAVED
    assert session.summary_final == '编辑后的摘要'
    assert MoodPalMessage.objects.filter(session=session).count() == 0
    assert 'cbt_state' not in session.metadata

    event_types = list(session.events.values_list('event_type', flat=True))
    assert MoodPalSessionEvent.EventType.SUMMARY_GENERATED in event_types
    assert MoodPalSessionEvent.EventType.RAW_MESSAGES_DESTROYED in event_types
    assert MoodPalSessionEvent.EventType.SUMMARY_SAVED in event_types


@pytest.mark.django_db
def test_moodpal_summary_save_logs_burn_pipeline(caplog):
    client = _anon_client('anon-summary-save-log')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-summary-save-log',
        anon_id='anon-summary-save-log',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )
    MoodPalMessage.objects.create(session=session, role=MoodPalMessage.Role.USER, content='我最近总觉得自己什么都做不好。')
    MoodPalMessage.objects.create(session=session, role=MoodPalMessage.Role.ASSISTANT, content='这种持续否定自己的感觉确实会很累。')

    with _capture_named_logger(caplog, 'backend.moodpal.services.burn_service'):
        end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
        save_resp = client.post(
            f'/moodpal/session/{session.id}/summary/',
            data={'action': 'save', 'summary_text': '编辑后的摘要'},
        )

    assert end_resp.status_code == 200
    assert save_resp.status_code == 302
    assert 'MoodPal summary generated' in caplog.text
    assert 'MoodPal raw messages destroyed' in caplog.text
    assert 'MoodPal summary saved' in caplog.text


@pytest.mark.django_db
def test_moodpal_destroy_summary_clears_summary_and_burns_raw_messages():
    client = _anon_client('anon-summary-destroy')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-summary-destroy',
        anon_id='anon-summary-destroy',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我发现自己在人际关系里总会退缩。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='这可能和某个反复出现的关系模式有关。',
    )

    end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert end_resp.status_code == 200

    destroy_resp = client.post(f'/api/moodpal/session/{session.id}/summary/destroy')
    assert destroy_resp.status_code == 200

    session.refresh_from_db()
    assert session.status == MoodPalSession.Status.CLOSED
    assert session.summary_action == MoodPalSession.SummaryAction.DESTROYED
    assert session.summary_draft == ''
    assert session.summary_final == ''
    assert MoodPalMessage.objects.filter(session=session).count() == 0
    assert MoodPalSessionEvent.objects.filter(
        session=session,
        event_type=MoodPalSessionEvent.EventType.SUMMARY_DESTROYED,
    ).exists()


@pytest.mark.django_db
def test_moodpal_destroy_summary_logs_burn_pipeline(caplog):
    client = _anon_client('anon-summary-destroy-log')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-summary-destroy-log',
        anon_id='anon-summary-destroy-log',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
    )
    MoodPalMessage.objects.create(session=session, role=MoodPalMessage.Role.USER, content='我发现自己在人际关系里总会退缩。')
    MoodPalMessage.objects.create(session=session, role=MoodPalMessage.Role.ASSISTANT, content='这可能和某个反复出现的关系模式有关。')

    with _capture_named_logger(caplog, 'backend.moodpal.services.burn_service'):
        end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
        destroy_resp = client.post(f'/api/moodpal/session/{session.id}/summary/destroy')

    assert end_resp.status_code == 200
    assert destroy_resp.status_code == 200
    assert 'MoodPal summary generated' in caplog.text
    assert 'MoodPal raw messages destroyed' in caplog.text
    assert 'MoodPal summary destroyed' in caplog.text


@pytest.mark.django_db
def test_closed_session_cannot_recover_raw_messages():
    client = _anon_client('anon-closed-session')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-closed-session',
        anon_id='anon-closed-session',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我明知道不用担心，但就是停不下来。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='我们可以先把最强的自动想法拆出来。',
    )

    client.post(f'/api/moodpal/session/{session.id}/end')
    client.post(
        f'/api/moodpal/session/{session.id}/summary/save',
        data=json.dumps({'summary_text': '保留摘要'}),
        content_type='application/json',
    )

    detail = client.get(f'/api/moodpal/session/{session.id}')
    assert detail.status_code == 200
    assert detail.json()['messages'] == []
    assert detail.json()['session']['raw_message_count'] == 0

    send_again = client.post(
        f'/api/moodpal/session/{session.id}/message',
        data=json.dumps({'content': '还能继续吗？'}),
        content_type='application/json',
    )
    assert send_again.status_code == 409


@pytest.mark.django_db
def test_moodpal_anonymous_session_not_accessible_from_other_cookie():
    owner = _anon_client('anon-owner')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-owner',
        anon_id='anon-owner',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
    )

    other = _anon_client('anon-other')
    resp = other.get(f'/moodpal/session/{session.id}/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_moodpal_message_api_logs_quota_block(caplog):
    client = _anon_client('anon-quota-message-log')
    TokenQuotaState.objects.create(
        subject_key='anon:anon-quota-message-log',
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id='anon-quota-message-log',
        used_tokens=100000,
        quota_limit=100000,
    )
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-quota-message-log',
        anon_id='anon-quota-message-log',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )

    with _capture_named_logger(caplog, 'backend.moodpal.views', level=logging.WARNING):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我今天真的很难受。'}),
            content_type='application/json',
        )

    assert resp.status_code == 402
    assert 'MoodPal quota blocked context=session_message_api' in caplog.text
