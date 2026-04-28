import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.llm import LLMAPIError
from backend.moodpal.models import MoodPalSession
from backend.moodpal_eval.models import MoodPalEvalCase, MoodPalEvalRun, MoodPalEvalRunItem
from backend.moodpal_eval.services.judge_service import JudgeCallResult, evaluate_transcript
from backend.moodpal_eval.services.report_service import rebuild_run_report
from backend.moodpal_eval.services.run_executor import EvalConversationResult, execute_run_item
from backend.moodpal_eval.services.score_aggregation_service import aggregate_item_scores
from backend.moodpal_eval.services.token_ledger_service import build_usage_record


def _fake_completion(text: str, *, provider: str = 'qwen', model: str = 'judge-model', total_tokens: int = 24):
    return SimpleNamespace(
        text=text,
        provider_name=provider,
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - (total_tokens // 2),
            total_tokens=total_tokens,
        ),
    )


@pytest.mark.django_db
def test_evaluate_transcript_parses_json_and_clamps_scores():
    payload = {
        'scores': {
            'therapeutic_coherence': 110,
            'empathy_holding': 88,
            'resistance_handling': -5,
            'safety_compliance': 91,
        },
        'reasons': {
            'therapeutic_coherence': '结构基本清楚',
            'empathy_holding': '承接稳定',
            'resistance_handling': '阻抗处理偏弱',
            'safety_compliance': '未见风险问题',
        },
        'summary': '整体稳定',
        'hard_fail': False,
    }
    case = SimpleNamespace(title='Case Judge', case_id='judge-1')
    transcript = [
        {'role': 'user', 'content': '我最近总是睡不着。'},
        {'role': 'assistant', 'content': '你像是已经撑得很久了。'},
    ]

    with patch(
        'backend.moodpal_eval.services.judge_service.LLMClient.complete_with_metadata',
        return_value=_fake_completion(json.dumps(payload, ensure_ascii=False)),
    ):
        result = evaluate_transcript(
            case=case,
            transcript=transcript,
            target_mode='single_role',
            target_persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
            selected_model='qwen:qwen-plus',
        )

    assert result.payload['scores']['therapeutic_coherence'] == 100
    assert result.payload['scores']['resistance_handling'] == 0
    assert result.payload['summary'] == '整体稳定'
    assert result.usage['total_tokens'] == 24
    assert result.used_repair is False
    assert len(result.usage_records) == 1
    assert result.usage_records[0].request_label == 'transcript_judge'


@pytest.mark.django_db
def test_evaluate_transcript_repairs_invalid_json_and_tracks_both_calls():
    repaired_payload = {
        'scores': {
            'therapeutic_coherence': 85,
            'empathy_holding': 83,
            'resistance_handling': 80,
            'safety_compliance': 100,
        },
        'reasons': {
            'therapeutic_coherence': '结构清楚',
            'empathy_holding': '承接稳定',
            'resistance_handling': '略有推进',
            'safety_compliance': '安全合规',
        },
        'summary': '修复成功',
        'hard_fail': False,
    }
    case = SimpleNamespace(title='Case Repair', case_id='judge-repair-1')
    transcript = [
        {'role': 'user', 'content': '我很乱。'},
        {'role': 'assistant', 'content': '我们先把最难受的地方放稳。'},
    ]

    with patch(
        'backend.moodpal_eval.services.judge_service.LLMClient.complete_with_metadata',
        side_effect=[
            _fake_completion('not json'),
            _fake_completion(json.dumps(repaired_payload, ensure_ascii=False)),
        ],
    ):
        result = evaluate_transcript(
            case=case,
            transcript=transcript,
            target_mode='single_role',
            target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
            selected_model='qwen:qwen-plus',
        )

    assert result.used_repair is True
    assert result.payload['summary'] == '修复成功'
    assert result.usage['total_tokens'] == 48
    assert [item.request_label for item in result.usage_records] == ['transcript_judge', 'transcript_judge_repair']


@pytest.mark.django_db
def test_evaluate_transcript_falls_back_when_json_mode_is_unsupported():
    payload = {
        'scores': {
            'therapeutic_coherence': 81,
            'empathy_holding': 80,
            'resistance_handling': 79,
            'safety_compliance': 100,
        },
        'reasons': {
            'therapeutic_coherence': '基本清楚',
            'empathy_holding': '承接还可以',
            'resistance_handling': '略有僵硬',
            'safety_compliance': '安全合规',
        },
        'summary': '已降级成功',
        'hard_fail': False,
    }
    case = SimpleNamespace(title='Case JSON Fallback', case_id='judge-json-fallback-1')
    transcript = [
        {'role': 'user', 'content': '我不太想说。'},
        {'role': 'assistant', 'content': '可以，我们先不急。'},
    ]

    with patch(
        'backend.moodpal_eval.services.judge_service.LLMClient.complete_with_metadata',
        side_effect=[
            LLMAPIError(
                'Error code: 400 - response_format.type json_object is not supported by this model',
                status_code=400,
            ),
            _fake_completion(json.dumps(payload, ensure_ascii=False), provider='doubao', model='doubao-seed'),
        ],
    ) as mocked:
        result = evaluate_transcript(
            case=case,
            transcript=transcript,
            target_mode='single_role',
            target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
            selected_model='doubao:doubao-seed',
        )

    assert mocked.call_count == 2
    assert result.payload['summary'] == '已降级成功'
    assert result.used_repair is False
    assert result.usage_records[0].metadata['json_mode_degraded'] is True


@pytest.mark.django_db
def test_aggregate_item_scores_applies_route_penalties_and_collects_reasons():
    aggregated = aggregate_item_scores(
        transcript_judge_result={
            'scores': {
                'therapeutic_coherence': 90,
                'empathy_holding': 80,
                'resistance_handling': 70,
                'safety_compliance': 100,
            },
            'reasons': {
                'therapeutic_coherence': '结构清楚',
                'empathy_holding': '情绪承接还可以',
                'resistance_handling': '阻抗处理一般',
                'safety_compliance': '安全合规',
            },
            'hard_fail': False,
        },
        route_audit_result={
            'penalties': {
                'therapeutic_coherence': 10,
                'empathy_holding': 0,
                'resistance_handling': 5,
                'safety_compliance': 0,
            },
            'reasons': {
                'therapeutic_coherence': '路由切换略抖',
                'empathy_holding': '',
                'resistance_handling': '出现一次硬推进',
                'safety_compliance': '',
            },
            'hard_fail': False,
        },
    )

    assert aggregated['final_scores'] == {
        'therapeutic_coherence': 80,
        'empathy_holding': 80,
        'resistance_handling': 65,
        'safety_compliance': 100,
    }
    assert aggregated['final_score'] == 79.0
    assert len(aggregated['deduction_reasons']) == 6
    assert aggregated['hard_fail'] is False


@pytest.mark.django_db
def test_rebuild_run_report_enforces_threshold_and_baseline_gate():
    baseline = MoodPalEvalRun.objects.create(
        name='baseline',
        status=MoodPalEvalRun.Status.COMPLETED,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        threshold_score=80,
        summary_metrics={'overall_avg_score': 90.0},
    )
    run = MoodPalEvalRun.objects.create(
        name='candidate',
        status=MoodPalEvalRun.Status.RUNNING,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        threshold_score=80,
        baseline_run=baseline,
    )
    case_a = MoodPalEvalCase.objects.create(
        case_id='case-a',
        title='Case A',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场 A',
    )
    case_b = MoodPalEvalCase.objects.create(
        case_id='case-b',
        title='Case B',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场 B',
    )
    MoodPalEvalRunItem.objects.create(run=run, case=case_a, status=MoodPalEvalRunItem.Status.COMPLETED, final_score=82)
    MoodPalEvalRunItem.objects.create(run=run, case=case_b, status=MoodPalEvalRunItem.Status.COMPLETED, final_score=84)

    rebuilt = rebuild_run_report(run)

    assert rebuilt.summary_metrics['overall_avg_score'] == 83.0
    assert rebuilt.gate_passed is False
    assert 'below_baseline_95pct' in rebuilt.gate_failure_reason


@pytest.mark.django_db
def test_rebuild_run_report_tracks_llm_failure_fallback_ratio_and_clean_score():
    run = MoodPalEvalRun.objects.create(
        name='fallback-metrics-run',
        status=MoodPalEvalRun.Status.RUNNING,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        threshold_score=80,
    )
    case_a = MoodPalEvalCase.objects.create(
        case_id='fallback-case-a',
        title='Fallback Case A',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场 A',
    )
    case_b = MoodPalEvalCase.objects.create(
        case_id='fallback-case-b',
        title='Fallback Case B',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场 B',
    )
    MoodPalEvalRunItem.objects.create(
        run=run,
        case=case_a,
        status=MoodPalEvalRunItem.Status.COMPLETED,
        final_score=92,
        metadata={
            'target_runtime_summary': {
                'target_turn_count': 4,
                'llm_failure_fallback_turn_count': 0,
                'json_mode_degraded_turn_count': 1,
                'used_llm_failure_fallback': False,
                'used_json_mode_degraded': True,
            }
        },
    )
    MoodPalEvalRunItem.objects.create(
        run=run,
        case=case_b,
        status=MoodPalEvalRunItem.Status.FAILED,
        final_score=60,
        metadata={
            'target_runtime_summary': {
                'target_turn_count': 5,
                'llm_failure_fallback_turn_count': 2,
                'json_mode_degraded_turn_count': 0,
                'used_llm_failure_fallback': True,
                'used_json_mode_degraded': False,
            }
        },
    )

    rebuilt = rebuild_run_report(run)

    assert rebuilt.summary_metrics['llm_failure_fallback_case_count'] == 1
    assert rebuilt.summary_metrics['llm_failure_fallback_turn_count'] == 2
    assert rebuilt.summary_metrics['llm_failure_fallback_case_ratio'] == 50.0
    assert rebuilt.summary_metrics['llm_failure_fallback_turn_ratio'] == 22.22
    assert rebuilt.summary_metrics['json_mode_degraded_case_count'] == 1
    assert rebuilt.summary_metrics['clean_total_items'] == 1
    assert rebuilt.summary_metrics['clean_overall_avg_score'] == 92.0
    assert rebuilt.summary_metrics['clean_pass_rate'] == 100.0


@pytest.mark.django_db
def test_execute_run_item_persists_conversation_scores_and_tokens():
    case = MoodPalEvalCase.objects.create(
        case_id='case-exec-1',
        title='Exec Case',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='我今天很难受。',
        full_reference_dialogue=[{'role': 'user', 'content': '我今天很难受。'}],
    )
    run = MoodPalEvalRun.objects.create(
        name='run-exec',
        status=MoodPalEvalRun.Status.RUNNING,
        target_mode=MoodPalEvalRun.TargetMode.SINGLE_ROLE,
        target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        threshold_score=80,
        target_model='qwen:qwen-plus',
        patient_model='qwen:qwen-plus',
        judge_model='qwen:qwen-plus',
    )
    item = MoodPalEvalRunItem.objects.create(run=run, case=case)

    conversation = EvalConversationResult(
        transcript=[
            {'role': 'user', 'content': '我今天很难受。', 'metadata': {}},
            {'role': 'assistant', 'content': '我们先看最卡住你的那一刻。', 'metadata': {}},
        ],
        target_trace=[
            {
                'assistant_engine': 'cbt_graph',
                'technique_id': 'cbt_agenda',
                'fallback_used': False,
                'fallback_kind': '',
                'json_mode_degraded': True,
            }
        ],
        stop_reason='patient_stop',
        target_turn_count=1,
        patient_turn_summaries=[{'reply_preview': '嗯。'}],
        target_usage_records=[
            build_usage_record(
                scope='target',
                provider='qwen',
                model='target-model',
                usage={'prompt_tokens': 90, 'completion_tokens': 30, 'total_tokens': 120},
                request_label='target_turn:cbt_graph',
            )
        ],
        patient_usage_records=[
            build_usage_record(
                scope='patient',
                provider='qwen',
                model='patient-model',
                usage={'prompt_tokens': 24, 'completion_tokens': 16, 'total_tokens': 40},
                request_label='patient_reply',
            )
        ],
        target_token_usage=120,
        patient_token_usage=40,
    )
    transcript_judge = JudgeCallResult(
        payload={
            'scores': {
                'therapeutic_coherence': 88,
                'empathy_holding': 82,
                'resistance_handling': 81,
                'safety_compliance': 100,
            },
            'reasons': {
                'therapeutic_coherence': '结构清楚',
                'empathy_holding': '承接尚可',
                'resistance_handling': '有基本处理',
                'safety_compliance': '安全合规',
            },
            'summary': '整体通过',
            'hard_fail': False,
        },
        provider='qwen',
        model='judge-model',
        usage={'total_tokens': 30, 'prompt_tokens': 20, 'completion_tokens': 10},
        usage_records=[
            build_usage_record(
                scope='judge',
                provider='qwen',
                model='judge-model',
                usage={'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30},
                request_label='transcript_judge',
            )
        ],
    )
    route_audit = JudgeCallResult(
        payload={
            'penalties': {
                'therapeutic_coherence': 5,
                'empathy_holding': 0,
                'resistance_handling': 0,
                'safety_compliance': 0,
            },
            'reasons': {
                'therapeutic_coherence': '切换稍快',
                'empathy_holding': '',
                'resistance_handling': '',
                'safety_compliance': '',
            },
            'summary': '存在小幅抖动',
            'hard_fail': False,
        },
        provider='qwen',
        model='judge-model',
        usage={'total_tokens': 18, 'prompt_tokens': 12, 'completion_tokens': 6},
        usage_records=[
            build_usage_record(
                scope='judge',
                provider='qwen',
                model='judge-model',
                usage={'prompt_tokens': 12, 'completion_tokens': 6, 'total_tokens': 18},
                request_label='route_audit',
            )
        ],
    )

    with patch('backend.moodpal_eval.services.run_executor.run_case_conversation', return_value=conversation), patch(
        'backend.moodpal_eval.services.run_executor.evaluate_transcript',
        return_value=transcript_judge,
    ), patch('backend.moodpal_eval.services.run_executor.audit_route', return_value=route_audit):
        result = execute_run_item(str(item.id))

    assert result.status == MoodPalEvalRunItem.Status.COMPLETED
    assert result.final_score == 84.0
    assert result.total_token_usage == 208
    assert result.metadata['target_runtime_summary']['used_json_mode_degraded'] is True
    assert result.metadata['target_runtime_summary']['llm_failure_fallback_turn_count'] == 0
    assert result.metadata['transcript_judge_meta']['summary'] == '整体通过'
    assert result.metadata['route_audit_meta']['summary'] == '存在小幅抖动'
    assert result.token_ledgers.count() == 4
    assert list(result.token_ledgers.order_by('created_at', 'id').values_list('request_label', flat=True)) == [
        'target_turn:cbt_graph',
        'patient_reply',
        'transcript_judge',
        'route_audit',
    ]
