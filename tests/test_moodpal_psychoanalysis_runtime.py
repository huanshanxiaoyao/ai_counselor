import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.moodpal.models import MoodPalSession
from backend.moodpal.psychoanalysis import PsychoanalysisGraph, PsychoanalysisNodeRegistry
from backend.moodpal.psychoanalysis.executor import PsychoanalysisTechniqueExecutor
from backend.moodpal.psychoanalysis.executor_prompt_config import PROMPT_TEMPLATE_BY_TECHNIQUE
from backend.moodpal.psychoanalysis.insight_evaluator import PsychoanalysisInsightEvaluator
from backend.moodpal.psychoanalysis.signal_extractor import extract_psychoanalysis_turn_signals
from backend.moodpal.psychoanalysis.state import make_initial_psychoanalysis_state
from backend.moodpal.services.psychoanalysis_runtime_service import run_psychoanalysis_turn


def test_all_psychoanalysis_nodes_have_prompt_templates():
    registry_ids = {node.node_id for node in PsychoanalysisNodeRegistry().all_nodes()}
    assert set(PROMPT_TEMPLATE_BY_TECHNIQUE.keys()) == registry_ids


def test_psychoanalysis_signal_extractor_derives_dynamic_signals_without_llm():
    state = make_initial_psychoanalysis_state(
        recalled_pattern_memory=[
            {
                'repetition_themes': ['authority_tension'],
                'defense_patterns': ['intellectualization'],
                'relational_pull': [],
                'working_hypotheses': ['在被评价场景里会先收紧'],
            }
        ]
    )
    state['last_user_message'] = '其实也不只是这次，老板一语气重一点，我就又开始先怪自己。'

    patch = extract_psychoanalysis_turn_signals(state)

    assert patch['repetition_theme_candidate'] in ['authority_tension', 'repetition_pattern_present']
    assert patch['pattern_confidence'] >= 0.6
    assert patch['association_openness'] in ['partial', 'open']
    assert patch['advice_pull_detected'] is False


def test_psychoanalysis_executor_includes_pattern_memory_summary_and_dynamic_block():
    executor = PsychoanalysisTechniqueExecutor()
    state = make_initial_psychoanalysis_state(
        recalled_pattern_memory=[
            {
                'repetition_themes': ['authority_tension'],
                'defense_patterns': ['withdrawal'],
                'relational_pull': ['testing_authority'],
                'working_hypotheses': ['在被评价场景里会先收紧'],
            }
        ]
    )
    state.update(
        {
            'persona_id': 'insight_mentor',
            'last_user_message': '你这么说，我就更不想讲了。',
            'here_and_now_triggered': True,
            'relational_pull': 'testing_authority',
            'alliance_strength': 'medium',
            'resistance_level': 'medium',
        }
    )

    payload = executor.build_payload(state, 'psa_relational_here_now')

    assert '动力学信号摘要：' in payload.user_prompt
    assert '召回的脱敏模式记忆：' in payload.user_prompt
    assert 'testing_authority' in payload.user_prompt
    assert payload.metadata['prompt_template_id'] == 'psa_relational_here_now'


def test_psychoanalysis_insight_evaluator_trips_after_attempt_limit():
    evaluator = PsychoanalysisInsightEvaluator()
    state = make_initial_psychoanalysis_state()
    state['working_hypothesis'] = '一感觉到关系紧张，就会先把问题收回到自己身上。'
    state['technique_attempt_count'] = 2
    state['technique_stall_count'] = 0
    state['last_progress_marker'] = ''

    result = evaluator.evaluate(state, 'psa_insight_integration')

    assert result.done is False
    assert result.should_trip_circuit is True
    assert result.trip_reason == 'attempt_limit_reached'
    assert result.next_fallback_action == 'regress_to_containment'


def test_psychoanalysis_relational_here_now_requires_explicit_relational_pull():
    evaluator = PsychoanalysisInsightEvaluator()
    state = make_initial_psychoanalysis_state()
    state['here_and_now_triggered'] = True
    state['alliance_strength'] = 'medium'
    state['relational_pull'] = ''

    result = evaluator.evaluate(state, 'psa_relational_here_now')

    assert result.done is False
    assert result.progress_marker == 'here_and_now_probe_in_progress'


def test_psychoanalysis_graph_builds_execution_payload_for_relational_node():
    graph = PsychoanalysisGraph()
    state = make_initial_psychoanalysis_state()
    state['persona_id'] = 'insight_mentor'
    state['last_user_message'] = '你这么说，我就更不想讲了。'
    state['here_and_now_triggered'] = True
    state['alliance_strength'] = 'medium'

    plan = graph.plan_turn(state)

    assert plan.selection.technique_id == 'psa_relational_here_now'
    assert plan.payload is not None
    assert '只处理此刻互动里的收紧' in plan.payload.system_prompt
    assert '节点退出标准：' in plan.payload.user_prompt


@pytest.mark.django_db
def test_run_psychoanalysis_turn_resets_attempt_counter_when_switching_technique():
    session = MoodPalSession.objects.create(
        usage_subject='anon:psychoanalysis-counter-reset',
        anon_id='psychoanalysis-counter-reset',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'psychoanalysis_state': {
                'current_technique_id': 'psa_pattern_linking',
                'technique_attempt_count': 2,
                'technique_stall_count': 1,
                'last_progress_marker': 'repetition_pattern_glimpsed',
                'alliance_strength': 'strong',
                'resistance_level': 'low',
                'working_hypothesis': '一感觉到关系紧张，就会先把问题收回到自己身上。',
                'pattern_confidence': 0.82,
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '你这么一连，我突然发现好像真的是这样。'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我也在想，会不会你心里一直有一套很快启动的保护方式：一感觉到关系里有一点危险，你就先把问题收回到自己身上。这个理解不一定完全对，你听听看，哪一部分最贴近你？',
                'state_patch': {
                    'working_hypothesis': '一感觉到关系里有一点危险，你就先把问题收回到自己身上。',
                    'insight_score': 7,
                    'interpretation_depth': 'integration',
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8),
        model='fake-psychoanalysis-model',
    )

    with patch('backend.moodpal.services.psychoanalysis_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        result = run_psychoanalysis_turn(session=session, history_messages=history_messages)

    assert result.reply_metadata['engine'] == 'psychoanalysis_graph'
    assert result.reply_metadata['technique_id'] == 'psa_insight_integration'
    assert result.state['technique_attempt_count'] == 1
    assert result.state['technique_stall_count'] == 0
    assert result.state['current_stage'] == 'wrap_up'
    assert result.persist_patch['current_technique_id'] == 'psa_insight_integration'
    assert result.persist_patch['insight_score'] == 7


@pytest.mark.django_db
def test_run_psychoanalysis_turn_uses_local_signals_to_route_boundary_without_second_llm():
    session = MoodPalSession.objects.create(
        usage_subject='anon:psychoanalysis-boundary',
        anon_id='psychoanalysis-boundary',
        persona_id=MoodPalSession.Persona.INSIGHT_MENTOR,
        status=MoodPalSession.Status.ACTIVE,
        metadata={},
    )
    history_messages = [
        {'role': 'user', 'content': '别分析了，直接告诉我怎么办。'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我听见你现在最受不了的是一点抓手都没有。那我们先不把问题摊太大，只选一个你最想先处理的小点，好吗？',
                'state_patch': {
                    'advice_pull_detected': False,
                    'association_openness': 'partial',
                    'focus_theme': '先找到一个最想处理的小点',
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=4, total_tokens=6),
        model='fake-psychoanalysis-model',
    )

    with patch('backend.moodpal.services.psychoanalysis_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result) as mocked_complete:
        result = run_psychoanalysis_turn(session=session, history_messages=history_messages)

    assert mocked_complete.call_count == 1
    assert result.reply_metadata['technique_id'] == 'psa_boundary_advice_pull'
    assert result.state['current_phase'] == 'boundary'
