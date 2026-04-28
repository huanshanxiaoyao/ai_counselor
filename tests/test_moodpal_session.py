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
    content = resp.content.decode('utf-8')
    assert resp.status_code == 200
    assert 'MoodPal' in content
    assert '隐私契约与边界说明' in content
    assert '全能主理人' in content
    assert '默认推荐' in content


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
def test_moodpal_session_start_api_supports_master_guide():
    client = _anon_client('anon-master-guide-start')

    resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.MASTER_GUIDE,
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )

    assert resp.status_code == 201
    session = MoodPalSession.objects.get()
    assert session.persona_id == MoodPalSession.Persona.MASTER_GUIDE
    assert resp.json()['session']['persona_title'] == '全能主理人'


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
def test_moodpal_session_start_api_loads_recent_saved_summary_context():
    client = _anon_client('anon-start-api-history')
    previous = MoodPalSession.objects.create(
        usage_subject='anon:anon-start-api-history',
        anon_id='anon-start-api-history',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.CLOSED,
        summary_action=MoodPalSession.SummaryAction.SAVED,
        summary_final='上次你提到，最近最难的是总觉得自己不被理解。',
        metadata={'summary_saved_at': timezone.now().isoformat()},
    )

    resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.INSIGHT_MENTOR,
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )

    assert resp.status_code == 201
    session = MoodPalSession.objects.exclude(pk=previous.pk).get()
    last_summary = session.metadata['last_summary']
    assert last_summary['source_session_id'] == str(previous.id)
    assert last_summary['source_persona_id'] == MoodPalSession.Persona.EMPATHY_SISTER
    assert last_summary['summary_text'] == '上次你提到，最近最难的是总觉得自己不被理解。'


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
@override_settings(DEBUG=True)
def test_moodpal_session_detail_api_exposes_psychoanalysis_debug_context():
    client = _anon_client('anon-debug-psychoanalysis')
    source_session_id = '11111111-2222-3333-4444-555555555555'
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-debug-psychoanalysis',
        anon_id='anon-debug-psychoanalysis',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'last_summary': {
                'source_session_id': source_session_id,
                'source_persona_id': MoodPalSession.Persona.EMPATHY_SISTER,
                'summary_text': '上次你提到，一感觉自己不被理解，就会很快把话收回去。',
            },
            'psychoanalysis_state': {
                'current_stage': 'evaluate_insight',
                'current_phase': 'pattern_linking',
                'current_technique_id': 'psa_pattern_linking',
                'next_fallback_action': 'switch_same_phase',
                'circuit_breaker_open': False,
                'last_route_reason': 'repetition_pattern_candidate_detected',
                'recalled_pattern_memory_count': 1,
                'recalled_pattern_memory_preview': [
                    {
                        'repetition_themes': ['hiding_to_avoid_evaluation'],
                        'working_hypotheses': ['感觉会被看见时容易往后缩'],
                    }
                ],
            },
        },
    )

    resp = client.get(f'/api/moodpal/session/{session.id}')

    assert resp.status_code == 200
    debug_payload = resp.json()['session']['debug']
    assert debug_payload['engine'] == 'psychoanalysis_graph'
    assert debug_payload['last_route_reason'] == 'repetition_pattern_candidate_detected'
    assert debug_payload['last_summary_available'] is True
    assert debug_payload['last_summary_source_session_id'] == source_session_id
    assert debug_payload['recalled_pattern_memory_count'] == 1
    assert debug_payload['recalled_pattern_memory_preview'][0]['repetition_themes'] == ['hiding_to_avoid_evaluation']


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

    def _fake_dispatch_runtime(*, session, history_messages, user_content):
        MoodPalSession.objects.filter(pk=session.pk).update(
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

    with patch('backend.moodpal.runtime.turn_driver._dispatch_runtime', side_effect=_fake_dispatch_runtime):
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

    with patch('backend.moodpal.runtime.turn_driver.run_cbt_turn', side_effect=RuntimeError('boom')):
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

    def _fake_dispatch_runtime(*, session, history_messages, user_content):
        MoodPalSession.objects.filter(pk=session.pk).update(
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

    with patch('backend.moodpal.runtime.turn_driver._dispatch_runtime', side_effect=_fake_dispatch_runtime):
        with pytest.raises(ValueError, match='session_unavailable'):
            append_message_pair(
                session,
                user_content='我还是一直在担心工作上的一个失误。',
            )

    session.refresh_from_db()
    assert session.metadata['crisis_active'] is True
    assert MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).count() == 0


@pytest.mark.django_db
def test_moodpal_empathy_persona_uses_humanistic_runtime():
    client = _anon_client('anon-placeholder')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-placeholder',
        anon_id='anon-placeholder',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )

    with patch('backend.moodpal.services.humanistic_runtime_service.LLMClient.complete_with_metadata', side_effect=RuntimeError('boom')):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '我今天真的很委屈。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'humanistic_graph'
    assert assistant_message.metadata['fallback_used'] is True
    assert assistant_message.metadata['technique_id'] == 'hum_reflect_feeling'


@pytest.mark.django_db
def test_moodpal_master_guide_opening_turn_routes_to_support_only():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-master-guide-opening',
        anon_id='anon-master-guide-opening',
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        status=MoodPalSession.Status.ACTIVE,
    )

    child_result = SimpleNamespace(
        reply_text='我先接住你现在的难受，我们先不急着分析，先把最压着你的那一块放在这里。',
        reply_metadata={
            'engine': 'humanistic_graph',
            'track': 'empathy_presence',
            'technique_id': 'hum_empathy_presence',
            'fallback_action': 'switch_same_phase',
            'provider': '',
            'model': '',
            'usage': {},
        },
        persist_patch={
            'current_phase': 'empathy_presence',
            'current_technique_id': 'hum_empathy_presence',
            'dominant_emotions': ['委屈'],
        },
        used_fallback=False,
        state={'last_progress_marker': 'holding_established'},
    )

    with patch('backend.moodpal.services.master_guide_runtime_service.run_humanistic_turn', return_value=child_result):
        session, user_message, assistant_message = append_message_pair(
            session,
            user_content='我现在脑子很乱，也有点委屈，不知道该从哪里说。',
        )

    session.refresh_from_db()
    assert user_message.role == MoodPalMessage.Role.USER
    assert assistant_message.metadata['engine'] == 'master_guide_orchestrator'
    assert assistant_message.metadata['selected_mode'] == 'support_only'
    assert assistant_message.metadata['child_engine'] == 'humanistic_graph'
    assert assistant_message.metadata['track'] == 'empathy_presence'
    assert session.metadata['master_guide_state']['current_turn_mode'] == 'support_only'
    assert session.metadata['master_guide_state']['support_mode'] == 'opening'
    assert session.metadata['master_guide_state']['turn_index'] == 1
    assert session.metadata['master_guide_state']['summary_hints']
    assert session.metadata['humanistic_state']['dominant_emotions'] == ['委屈']
    assert session.metadata['master_guide_state']['route_trace'][0]['mode'] == 'support_only'


@pytest.mark.django_db
def test_moodpal_master_guide_routes_to_cbt_when_problem_is_clear():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-master-guide-cbt',
        anon_id='anon-master-guide-cbt',
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'master_guide_state': {
                'turn_index': 1,
                'active_main_track': '',
            }
        },
    )

    child_result = SimpleNamespace(
        reply_text='我们先把工作里最卡住的那个场景说清楚，再看你下一步准备怎么做。',
        reply_metadata={
            'engine': 'cbt_graph',
            'track': 'agenda',
            'technique_id': 'cbt_structure_agenda_setting',
            'fallback_action': 'switch_same_track',
            'provider': '',
            'model': '',
            'usage': {},
        },
        persist_patch={
            'current_track': 'agenda',
            'current_technique_id': 'cbt_structure_agenda_setting',
            'agenda_topic': '和老板对齐项目分工',
            'agenda_locked': True,
        },
        used_fallback=False,
        state={'last_progress_marker': 'agenda_locked'},
    )

    with patch('backend.moodpal.services.master_guide_runtime_service.run_cbt_turn', return_value=child_result):
        session, _, assistant_message = append_message_pair(
            session,
            user_content='这周项目推进不顺，我该怎么和老板说，才能把分工重新讲清楚？',
        )

    session.refresh_from_db()
    assert assistant_message.metadata['engine'] == 'master_guide_orchestrator'
    assert assistant_message.metadata['selected_mode'] == 'cbt'
    assert assistant_message.metadata['child_engine'] == 'cbt_graph'
    assert session.metadata['master_guide_state']['active_main_track'] == 'cbt'
    assert session.metadata['master_guide_state']['used_cbt'] is True
    assert session.metadata['master_guide_state']['last_route_reason_code'] == 'cbt_problem_solving'
    assert session.metadata['cbt_state']['agenda_topic'] == '和老板对齐项目分工'


@pytest.mark.django_db
def test_moodpal_master_guide_routes_to_psychoanalysis_for_pattern_signal():
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-master-guide-psy',
        anon_id='anon-master-guide-psy',
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'master_guide_state': {
                'turn_index': 2,
                'active_main_track': 'cbt',
            },
            'last_summary': {
                'summary_text': '上次你提到，只要感觉会被评价，就会先往后缩。',
                'source_session_id': 'prev-master-guide-session',
                'source_persona_id': MoodPalSession.Persona.MASTER_GUIDE,
            },
        },
    )

    child_result = SimpleNamespace(
        reply_text='你用了“为什么我总会这样”这句话，里面像是有一条反复出现的线索，我们先别急着解释它。',
        reply_metadata={
            'engine': 'psychoanalysis_graph',
            'track': 'pattern_linking',
            'technique_id': 'psa_pattern_linking',
            'fallback_action': 'switch_same_phase',
            'provider': '',
            'model': '',
            'usage': {},
        },
        persist_patch={
            'current_phase': 'pattern_linking',
            'current_technique_id': 'psa_pattern_linking',
            'repetition_theme_candidate': 'hiding_to_avoid_evaluation',
            'pattern_confidence': 0.78,
        },
        used_fallback=False,
        state={'last_progress_marker': 'pattern_named'},
    )

    with patch('backend.moodpal.services.master_guide_runtime_service.run_psychoanalysis_turn', return_value=child_result):
        session, _, assistant_message = append_message_pair(
            session,
            user_content='为什么我总是在关系里一感觉要被评价，就会立刻缩回去？',
        )

    session.refresh_from_db()
    assert assistant_message.metadata['engine'] == 'master_guide_orchestrator'
    assert assistant_message.metadata['selected_mode'] == 'psychoanalysis'
    assert assistant_message.metadata['child_engine'] == 'psychoanalysis_graph'
    assert session.metadata['master_guide_state']['active_main_track'] == 'psychoanalysis'
    assert session.metadata['master_guide_state']['used_psychoanalysis'] is True
    assert session.metadata['master_guide_state']['last_switch_reason_code'] == 'psy_repetition_pattern'
    assert session.metadata['psychoanalysis_state']['repetition_theme_candidate'] == 'hiding_to_avoid_evaluation'


@pytest.mark.django_db
def test_moodpal_insight_persona_uses_psychoanalysis_runtime():
    client = _anon_client('anon-insight-placeholder')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-insight-placeholder',
        anon_id='anon-insight-placeholder',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
    )
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '这句话里有一个值得慢慢看的“又”。先不急着解释它，我们可以从最近一次相似场景开始，看看它通常在什么关系里被触发。',
                'state_patch': {
                    'association_openness': 'partial',
                    'repetition_theme_candidate': 'repetition_pattern_present',
                    'pattern_confidence': 0.72,
                    'working_hypothesis': '某种相似关系场景会反复触发旧感受。',
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=6, total_tokens=10),
        model='fake-psychoanalysis-model',
    )

    with patch('backend.moodpal.services.psychoanalysis_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        resp = client.post(
            f'/api/moodpal/session/{session.id}/message',
            data=json.dumps({'content': '这种感觉以前总是在类似场景里冒出来。'}),
            content_type='application/json',
        )

    assert resp.status_code == 201
    assistant_message = MoodPalMessage.objects.filter(session=session, role=MoodPalMessage.Role.ASSISTANT).latest('id')
    assert assistant_message.metadata['engine'] == 'psychoanalysis_graph'
    assert assistant_message.metadata['technique_id']
    assert assistant_message.metadata['fallback_used'] is False
    session.refresh_from_db()
    assert session.metadata['psychoanalysis_state']['working_hypothesis'] == '某种相似关系场景会反复触发旧感受。'


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_moodpal_psychoanalysis_cross_session_history_reaches_runtime_prompt():
    client = _anon_client('anon-psychoanalysis-history')
    previous = MoodPalSession.objects.create(
        usage_subject='anon:anon-psychoanalysis-history',
        anon_id='anon-psychoanalysis-history',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.CLOSED,
        summary_action=MoodPalSession.SummaryAction.SAVED,
        summary_final='上次我们已经看到，只要感觉要被评价，你就会先缩回去。',
        metadata={
            'summary_saved_at': timezone.now().isoformat(),
            'psychoanalysis_memory_v1': {
                'schema_version': 'v1',
                'repetition_themes': ['authority_tension'],
                'defense_patterns': ['withdrawal'],
                'relational_pull': ['testing_authority'],
                'working_hypotheses': ['在被评价场景里容易先收紧自己'],
                'confidence': 0.74,
                'source_session_id': 'prev-session',
                'updated_at': timezone.now().isoformat(),
            },
        },
    )

    start_resp = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.INSIGHT_MENTOR,
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )
    assert start_resp.status_code == 201
    session_id = start_resp.json()['session']['id']
    session = MoodPalSession.objects.get(pk=session_id)
    assert session.metadata['last_summary']['source_session_id'] == str(previous.id)

    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '听起来那种熟悉的缩回去又出现了。我们先不急着解释它，只把这条线放在这里看一会儿。',
                'state_patch': {
                    'working_hypothesis': '一感觉要被评价，你就会先缩回去保护自己。',
                    'pattern_confidence': 0.78,
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12),
        model='fake-psychoanalysis-model',
    )

    with patch('backend.moodpal.services.psychoanalysis_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result) as mocked_complete:
        msg_resp = client.post(
            f'/api/moodpal/session/{session_id}/message',
            data=json.dumps({'content': '这周开会时，那种熟悉的感觉又来了。'}),
            content_type='application/json',
        )

    assert msg_resp.status_code == 201
    prompt = mocked_complete.call_args.kwargs['prompt']
    assert '上次我们已经看到，只要感觉要被评价，你就会先缩回去。' in prompt
    assert 'themes=authority_tension' in prompt

    session.refresh_from_db()
    psychoanalysis_state = session.metadata['psychoanalysis_state']
    assert psychoanalysis_state['recalled_pattern_memory_count'] == 1
    assert psychoanalysis_state['last_route_reason']

    detail_resp = client.get(f'/api/moodpal/session/{session_id}')
    assert detail_resp.status_code == 200
    debug_payload = detail_resp.json()['session']['debug']
    assert debug_payload['last_summary_available'] is True
    assert debug_payload['last_summary_source_session_id'] == str(previous.id)
    assert debug_payload['recalled_pattern_memory_count'] == 1


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
def test_moodpal_summary_draft_includes_psychoanalysis_material():
    client = _anon_client('anon-psychoanalysis-summary')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-psychoanalysis-summary',
        anon_id='anon-psychoanalysis-summary',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'psychoanalysis_state': {
                'focus_theme': '一被别人注意到，我就会想往后缩。',
                'repetition_theme_candidate': 'hiding_to_avoid_evaluation',
                'active_defense': 'withdrawal',
                'relational_pull': 'testing_authority',
                'working_hypothesis': '你在感觉会被看见时，常会先把自己收回去保护自己。',
            }
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我最近发现，只要别人开始注意我，我就会很想退后。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='我们先不急着解释它，只把这条会反复出现的反应轻轻看清一点。',
    )

    resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert resp.status_code == 200

    session.refresh_from_db()
    assert '这次最值得继续跟住的一条线索：一被别人注意到，我就会想往后缩。' in session.summary_draft
    assert '当前浮现的重复模式线索：一感觉自己会被看见或被评价，你更容易往后缩' in session.summary_draft
    assert '对话里出现的一种保护动作：一感觉压力上来就会更想先把自己收回去' in session.summary_draft
    assert '关系里更容易出现的反应：会先试探对方是不是在判断你、是不是值得信任' in session.summary_draft
    assert '当前形成的一种工作性理解：你在感觉会被看见时，常会先把自己收回去保护自己。' in session.summary_draft
    assert '- 下次最想继续跟住的那条线索' in session.summary_draft
    assert '建议带走的微行动' not in session.summary_draft


@pytest.mark.django_db
def test_moodpal_summary_draft_includes_humanistic_material():
    client = _anon_client('anon-humanistic-summary')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-humanistic-summary',
        anon_id='anon-humanistic-summary',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'humanistic_state': {
                'dominant_emotions': ['委屈', '失落'],
                'felt_sense_description': '胸口有点堵，像有话卡着',
                'unmet_need_candidate': '想被认真听见，也想被温柔地接住',
                'self_compassion_shift': '允许自己先不要那么快否定自己',
            }
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我其实没有想哭，但就是一直闷着，很想有人真的听我说完。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='我听见你不是想被讲道理，而是想先被完整地听见。',
    )

    resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert resp.status_code == 200

    session.refresh_from_db()
    assert '这次更清楚被看见的情绪：委屈、失落' in session.summary_draft
    assert '身体或感受层面冒出来的线索：胸口有点堵，像有话卡着' in session.summary_draft
    assert '这份情绪背后更在意的需要：想被认真听见，也想被温柔地接住' in session.summary_draft
    assert '这次慢慢长出来的一点自我允许：允许自己先不要那么快否定自己' in session.summary_draft
    assert '- 你最希望被怎样理解、被怎样接住' in session.summary_draft
    assert '建议带走的微行动' not in session.summary_draft
    assert '行为激活起步动作' not in session.summary_draft


@pytest.mark.django_db
def test_moodpal_summary_draft_includes_master_guide_material():
    client = _anon_client('anon-master-guide-summary')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-master-guide-summary',
        anon_id='anon-master-guide-summary',
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'master_guide_state': {
                'active_main_track': 'psychoanalysis',
                'used_cbt': True,
                'used_psychoanalysis': True,
                'summary_hints': ['先用承接方式把情绪放稳一点', '后来开始看到更长期的重复模式线索'],
            },
            'cbt_state': {
                'agenda_topic': '担心再次被否定',
            },
            'psychoanalysis_state': {
                'focus_theme': '一感觉会被评价，我就想躲开。',
                'repetition_theme_candidate': 'hiding_to_avoid_evaluation',
            },
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我后来发现，只要别人认真看着我，我就会想躲。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='我们这次先把那条一被看见就想往后退的线索放稳一点。',
    )

    resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert resp.status_code == 200

    session.refresh_from_db()
    assert '这次支持方式的推进：先用承接方式把情绪放稳一点；后来开始看到更长期的重复模式线索' in session.summary_draft
    assert '当前更适合继续的方向：沿着已经浮现的重复模式，再稳一点往下看。' in session.summary_draft
    assert '本次锁定的议题：担心再次被否定' in session.summary_draft
    assert '这次最值得继续跟住的一条线索：一感觉会被评价，我就想躲开。' in session.summary_draft
    assert '- 哪种支持方式对你更有帮助' in session.summary_draft


@pytest.mark.django_db
def test_moodpal_summary_save_closes_session_and_burns_raw_messages():
    client = _anon_client('anon-summary-save')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-summary-save',
        anon_id='anon-summary-save',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={'humanistic_state': {'current_phase': 'empathy_presence'}},
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
    assert 'humanistic_state' not in session.metadata

    event_types = list(session.events.values_list('event_type', flat=True))
    assert MoodPalSessionEvent.EventType.SUMMARY_GENERATED in event_types
    assert MoodPalSessionEvent.EventType.RAW_MESSAGES_DESTROYED in event_types
    assert MoodPalSessionEvent.EventType.SUMMARY_SAVED in event_types


@pytest.mark.django_db
def test_moodpal_summary_save_persists_psychoanalysis_memory_after_user_confirm():
    client = _anon_client('anon-psychoanalysis-memory-save')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-psychoanalysis-memory-save',
        anon_id='anon-psychoanalysis-memory-save',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'psychoanalysis_state': {
                'repetition_theme_candidate': 'hiding_to_avoid_evaluation',
                'active_defense': 'withdrawal',
                'relational_pull': 'testing_authority',
                'pattern_confidence': 0.74,
                'working_hypothesis': '这句不会被直接写入长期记忆',
            }
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我总觉得一被别人注意到，就想往后缩。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='这像是一条会反复出现的保护动作。',
    )

    end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert end_resp.status_code == 200

    save_resp = client.post(
        f'/moodpal/session/{session.id}/summary/',
        data={'action': 'save', 'summary_text': '保留这份摘要'},
    )
    assert save_resp.status_code == 302

    session.refresh_from_db()
    memory = session.metadata.get('psychoanalysis_memory_v1') or {}
    assert session.status == MoodPalSession.Status.CLOSED
    assert session.summary_action == MoodPalSession.SummaryAction.SAVED
    assert session.summary_final == '保留这份摘要'
    assert MoodPalMessage.objects.filter(session=session).count() == 0
    assert 'psychoanalysis_state' not in session.metadata
    assert memory['schema_version'] == 'v1'
    assert memory['repetition_themes'] == ['hiding_to_avoid_evaluation']
    assert memory['defense_patterns'] == ['withdrawal']
    assert memory['relational_pull'] == ['testing_authority']
    assert '感觉会被看见或被评价时容易退回去保护自己' in memory['working_hypotheses']
    assert '这句不会被直接写入长期记忆' not in json.dumps(memory, ensure_ascii=False)
    assert memory['source_session_id'] == str(session.id)
    assert memory['confidence'] >= 0.65


@pytest.mark.django_db
def test_moodpal_master_guide_summary_save_clears_runtime_state_and_keeps_memory():
    client = _anon_client('anon-master-guide-memory-save')
    session = MoodPalSession.objects.create(
        usage_subject='anon:anon-master-guide-memory-save',
        anon_id='anon-master-guide-memory-save',
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'master_guide_state': {
                'route_trace': [
                    {'turn_index': 1, 'mode': 'support_only', 'reason_code': 'opening_hold'},
                    {'turn_index': 2, 'mode': 'psychoanalysis', 'reason_code': 'psy_repetition_pattern'},
                ],
                'used_psychoanalysis': True,
            },
            'humanistic_state': {
                'current_phase': 'empathy_presence',
            },
            'psychoanalysis_state': {
                'repetition_theme_candidate': 'hiding_to_avoid_evaluation',
                'active_defense': 'withdrawal',
                'relational_pull': 'testing_authority',
                'pattern_confidence': 0.73,
            },
        },
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.USER,
        content='我后来发现，只要别人认真看着我，我就会想躲。',
    )
    MoodPalMessage.objects.create(
        session=session,
        role=MoodPalMessage.Role.ASSISTANT,
        content='这像是一条会反复出现的保护动作。',
    )

    end_resp = client.post(f'/api/moodpal/session/{session.id}/end')
    assert end_resp.status_code == 200

    save_resp = client.post(
        f'/moodpal/session/{session.id}/summary/',
        data={'action': 'save', 'summary_text': '保留这份编排后的摘要'},
    )
    assert save_resp.status_code == 302

    session.refresh_from_db()
    memory = session.metadata.get('psychoanalysis_memory_v1') or {}
    assert session.status == MoodPalSession.Status.CLOSED
    assert session.summary_action == MoodPalSession.SummaryAction.SAVED
    assert 'master_guide_state' not in session.metadata
    assert 'humanistic_state' not in session.metadata
    assert 'psychoanalysis_state' not in session.metadata
    assert MoodPalMessage.objects.filter(session=session).count() == 0
    assert memory['schema_version'] == 'v1'
    assert memory['repetition_themes'] == ['hiding_to_avoid_evaluation']
    assert memory['defense_patterns'] == ['withdrawal']
    assert memory['relational_pull'] == ['testing_authority']


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
        metadata={
            'psychoanalysis_state': {
                'repetition_theme_candidate': 'authority_tension',
            },
            'psychoanalysis_memory_v1': {
                'schema_version': 'v1',
                'repetition_themes': ['authority_tension'],
            },
        },
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
    assert 'psychoanalysis_state' not in session.metadata
    assert 'psychoanalysis_memory_v1' not in session.metadata
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
