from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from backend.moodpal.models import MoodPalSession
from backend.moodpal_eval.models import MoodPalEvalCase, MoodPalEvalRun, MoodPalEvalRunItem, MoodPalEvalTokenLedger


User = get_user_model()


def _staff_client(username: str = 'eval_staff') -> Client:
    user = User.objects.create_user(username=username, password='StrongPass12345', is_staff=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_staff_can_open_run_create_page():
    client = _staff_client('eval_staff_create_get')

    response = client.get(reverse('moodpal_eval:run_create'))

    assert response.status_code == 200
    assert '新建 Eval Run' in response.content.decode('utf-8')


@pytest.mark.django_db
def test_staff_can_create_run_and_trigger_launcher():
    client = _staff_client('eval_staff_create_post')
    MoodPalEvalCase.objects.create(
        case_id='view-case-1',
        title='View Case 1',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        splits=['smoke'],
        first_user_message='开场 1',
    )
    MoodPalEvalCase.objects.create(
        case_id='view-case-2',
        title='View Case 2',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        splits=['smoke'],
        first_user_message='开场 2',
    )

    with patch('backend.moodpal_eval.views.run_launcher.launch_run') as mocked_launch:
        response = client.post(
            reverse('moodpal_eval:run_create'),
            {
                'name': 'smoke-run',
                'target_mode': MoodPalEvalRun.TargetMode.SINGLE_ROLE,
                'target_persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
                'dataset_split': 'smoke',
                'case_count': 2,
                'target_model': 'qwen:qwen-plus',
                'patient_model': 'qwen:qwen-plus',
                'judge_model': 'qwen:qwen-plus',
                'threshold_score': 80,
                'baseline_run_id': '',
                'max_turns': 12,
                'concurrency': 2,
                'per_turn_timeout_seconds': 45,
                'max_runtime_seconds': 900,
                'max_retries': 1,
            },
        )

    run = MoodPalEvalRun.objects.get(name='smoke-run')
    assert response.status_code == 302
    assert response['Location'].endswith(reverse('moodpal_eval:run_detail', args=[run.id]))
    assert run.items.count() == 2
    mocked_launch.assert_called_once_with(str(run.id))


@pytest.mark.django_db
@pytest.mark.parametrize('case_count', [21, 999])
def test_run_create_rejects_case_count_over_limit(case_count):
    client = _staff_client(f'eval_staff_limit_{case_count}')

    response = client.post(
        reverse('moodpal_eval:run_create'),
        {
            'name': 'too-many',
            'target_mode': MoodPalEvalRun.TargetMode.SINGLE_ROLE,
            'target_persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
            'dataset_split': '',
            'case_count': case_count,
            'target_model': 'qwen:qwen-plus',
            'patient_model': 'qwen:qwen-plus',
            'judge_model': 'qwen:qwen-plus',
            'threshold_score': 80,
            'baseline_run_id': '',
            'max_turns': 12,
            'concurrency': 2,
            'per_turn_timeout_seconds': 45,
            'max_runtime_seconds': 900,
            'max_retries': 1,
        },
    )

    assert response.status_code == 200
    assert MoodPalEvalRun.objects.count() == 0
    assert 'case_count' in response.context['form'].errors


@pytest.mark.django_db
def test_run_create_rejects_when_other_run_is_running():
    client = _staff_client('eval_staff_running_guard')
    MoodPalEvalCase.objects.create(
        case_id='view-case-running',
        title='View Case Running',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        splits=['smoke'],
        first_user_message='开场',
    )
    MoodPalEvalRun.objects.create(
        name='active-run',
        status=MoodPalEvalRun.Status.RUNNING,
        target_mode=MoodPalEvalRun.TargetMode.MASTER_GUIDE,
        target_persona_id=MoodPalSession.Persona.MASTER_GUIDE,
    )

    response = client.post(
        reverse('moodpal_eval:run_create'),
        {
            'name': 'blocked-run',
            'target_mode': MoodPalEvalRun.TargetMode.SINGLE_ROLE,
            'target_persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
            'dataset_split': 'smoke',
            'case_count': 1,
            'target_model': 'qwen:qwen-plus',
            'patient_model': 'qwen:qwen-plus',
            'judge_model': 'qwen:qwen-plus',
            'threshold_score': 80,
            'baseline_run_id': '',
            'max_turns': 12,
            'concurrency': 2,
            'per_turn_timeout_seconds': 45,
            'max_runtime_seconds': 900,
            'max_retries': 1,
        },
    )

    assert response.status_code == 200
    assert MoodPalEvalRun.objects.filter(name='blocked-run').exists() is False
    assert '当前已有运行中的评测' in response.content.decode('utf-8')


@pytest.mark.django_db
def test_run_detail_and_item_detail_render_core_fields():
    client = _staff_client('eval_staff_detail')
    case = MoodPalEvalCase.objects.create(
        case_id='detail-case-1',
        title='Detail Case',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场',
    )
    run = MoodPalEvalRun.objects.create(
        name='detail-run',
        status=MoodPalEvalRun.Status.COMPLETED,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        gate_passed=True,
        summary_metrics={
            'overall_avg_score': 88.5,
            'clean_overall_avg_score': 90.0,
            'pass_rate': 100,
            'total_items': 1,
            'llm_failure_fallback_case_count': 0,
            'llm_failure_fallback_turn_count': 0,
            'llm_failure_fallback_case_ratio': 0,
            'llm_failure_fallback_turn_ratio': 0,
            'json_mode_degraded_case_ratio': 100,
            'json_mode_degraded_turn_ratio': 100,
        },
    )
    item = run.items.create(
        case=case,
        status=MoodPalEvalRunItem.Status.COMPLETED,
        turn_count=2,
        stop_reason='patient_stop',
        transcript=[
            {'role': 'user', 'content': '我很累。'},
            {'role': 'assistant', 'content': '我听见你已经很累了。'},
        ],
        target_trace=[{'assistant_engine': 'humanistic_graph'}],
        transcript_judge_result={'scores': {'empathy_holding': 90}},
        route_audit_result={'penalties': {'empathy_holding': 0}},
        final_scores={'empathy_holding': 90},
        final_score=90,
        total_token_usage=123,
        metadata={
            'target_runtime_summary': {
                'llm_failure_fallback_turn_count': 0,
                'system_fallback_turn_count': 0,
                'json_mode_degraded_turn_count': 1,
                'used_llm_failure_fallback': False,
                'used_json_mode_degraded': True,
            }
        },
    )
    MoodPalEvalTokenLedger.objects.create(
        run=run,
        run_item=item,
        scope=MoodPalEvalTokenLedger.Scope.TARGET,
        provider='qwen',
        model='qwen-plus',
        prompt_tokens=80,
        completion_tokens=43,
        total_tokens=123,
        request_label='target_turn:humanistic_graph',
    )

    run_response = client.get(reverse('moodpal_eval:run_detail', args=[run.id]))
    item_response = client.get(reverse('moodpal_eval:item_detail', args=[item.id]))

    assert run_response.status_code == 200
    assert item_response.status_code == 200
    assert 'detail-run' in run_response.content.decode('utf-8')
    assert 'LLM 失败规则兜底' in run_response.content.decode('utf-8')
    assert 'Detail Case' in item_response.content.decode('utf-8')
    assert 'JSON 降级轮次' in item_response.content.decode('utf-8')
    assert '我听见你已经很累了。' in item_response.content.decode('utf-8')
    assert 'target_turn:humanistic_graph' in item_response.content.decode('utf-8')


@pytest.mark.django_db
def test_run_detail_and_item_detail_render_error_information():
    client = _staff_client('eval_staff_error_detail')
    case = MoodPalEvalCase.objects.create(
        case_id='detail-case-error-1',
        title='Detail Case Error',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场',
    )
    run = MoodPalEvalRun.objects.create(
        name='detail-run-error',
        status=MoodPalEvalRun.Status.COMPLETED,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        gate_passed=False,
        gate_failure_reason='errored_items_present',
        summary_metrics={'overall_avg_score': 0, 'pass_rate': 0, 'total_items': 1, 'errored_count': 1},
    )
    item = run.items.create(
        case=case,
        status=MoodPalEvalRunItem.Status.ERRORED,
        error_code='LLMAPIError',
        error_message='response_format.type json_object is not supported by this model',
    )

    run_response = client.get(reverse('moodpal_eval:run_detail', args=[run.id]))
    item_response = client.get(reverse('moodpal_eval:item_detail', args=[item.id]))

    assert run_response.status_code == 200
    assert item_response.status_code == 200
    assert 'LLMAPIError' in run_response.content.decode('utf-8')
    assert 'json_object is not supported by this model' in item_response.content.decode('utf-8')
