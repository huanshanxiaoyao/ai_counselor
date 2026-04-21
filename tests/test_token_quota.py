import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from backend.roundtable.models import QuotaFeedback, TokenQuotaState, TokenUsageLedger
from backend.roundtable.services.token_quota import parse_subject_key


def _minimal_chars():
    return [
        {'name': f'c{i}', 'era': '', 'viewpoints': {}, 'language_style': {}, 'temporal_constraints': {}}
        for i in range(3)
    ]


@pytest.mark.django_db
@override_settings(TOKEN_QUOTA_LIMIT=100)
def test_quota_status_for_anonymous_user():
    client = Client()
    resp = client.get('/roundtable/api/quota/status/')
    assert resp.status_code == 200
    data = resp.json()
    assert data['quota']['quota_limit'] == 100
    assert data['quota']['subject_key'].startswith('anon:')


@pytest.mark.django_db
@override_settings(TOKEN_QUOTA_LIMIT=100)
def test_quota_feedback_create_success():
    client = Client()
    resp = client.post(
        '/roundtable/api/quota/feedback/',
        data=json.dumps({'contact': 'qa@example.com', 'message': '请加额度'}),
        content_type='application/json',
    )
    assert resp.status_code == 200
    assert resp.json()['success'] is True
    fb = QuotaFeedback.objects.get(id=resp.json()['feedback_id'])
    assert fb.contact == 'qa@example.com'
    assert fb.subject_key.startswith('anon:')


@pytest.mark.django_db
@override_settings(TOKEN_QUOTA_LIMIT=100)
def test_start_blocked_when_quota_exceeded():
    User = get_user_model()
    user = User.objects.create_user(username='quota_u1', password='p')
    TokenQuotaState.objects.create(
        subject_key=f'user:{user.id}',
        subject_type='user',
        user=user,
        used_tokens=100,
        quota_limit=100,
    )
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/roundtable/api/start/',
        data=json.dumps({
            'topic': 'quota topic',
            'characters': _minimal_chars(),
            'user_role': 'participant',
            'max_rounds': 5,
        }),
        content_type='application/json',
    )
    assert resp.status_code == 402
    data = resp.json()
    assert data['error_code'] == 'quota_exceeded'


@pytest.mark.django_db
@override_settings(TOKEN_QUOTA_LIMIT=1000)
def test_chat_single_response_records_usage_ledger():
    User = get_user_model()
    user = User.objects.create_user(username='quota_u2', password='p')
    quota_subject = parse_subject_key(f'user:{user.id}')

    fake_result = SimpleNamespace(
        text='ok',
        model='mock-model',
        elapsed_seconds=0.2,
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )
    class FakeClient:
        def complete_with_metadata(self, **kwargs):
            return fake_result

    fake_client = FakeClient()

    from backend.chat.views import ChatAPIView
    with patch('backend.chat.views.get_llm_client', return_value=fake_client):
        result = ChatAPIView()._get_single_response(
            provider='qwen',
            prompt='hello',
            model='mock-model',
            quota_subject=quota_subject,
        )
    assert result['usage']['total_tokens'] == 18
    state = TokenQuotaState.objects.get(subject_key=f'user:{user.id}')
    assert state.used_tokens == 18
    assert TokenUsageLedger.objects.filter(
        subject_key=f'user:{user.id}',
        source='chat.api.response',
        total_tokens=18,
    ).exists()


@pytest.mark.django_db
@override_settings(TOKEN_QUOTA_LIMIT=10)
def test_chat_api_blocks_when_quota_exceeded():
    User = get_user_model()
    user = User.objects.create_user(username='quota_u3', password='p')
    TokenQuotaState.objects.create(
        subject_key=f'user:{user.id}',
        subject_type='user',
        user=user,
        used_tokens=10,
        quota_limit=10,
    )
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/api/counselor/',
        data=json.dumps({
            'prompt': 'hello',
            'providers': [{'provider': 'qwen', 'model': 'x'}],
        }),
        content_type='application/json',
    )
    assert resp.status_code == 402
    assert resp.json()['error_code'] == 'quota_exceeded'
