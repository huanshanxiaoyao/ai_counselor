import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.moodpal.models import MoodPalSession
from backend.moodpal.psychoanalysis import PsychoanalysisGraph, PsychoanalysisNodeRegistry
from backend.moodpal.psychoanalysis.executor import PsychoanalysisTechniqueExecutor
from backend.moodpal.psychoanalysis.insight_evaluator import PsychoanalysisInsightEvaluator
from backend.moodpal.psychoanalysis.signal_extractor import extract_psychoanalysis_turn_signals
from backend.moodpal.psychoanalysis.state import make_initial_psychoanalysis_state
from backend.moodpal.services.psychoanalysis_runtime_service import run_psychoanalysis_turn


def test_all_psychoanalysis_nodes_have_awareness_hints():
    from backend.moodpal.awareness_hints import AWARENESS_HINTS
    registry_ids = {node.node_id for node in PsychoanalysisNodeRegistry().all_nodes()}
    for node_id in registry_ids:
        assert node_id in AWARENESS_HINTS, f'Missing awareness hint for {node_id}'


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


def test_psychoanalysis_executor_user_prompt_contains_last_message():
    executor = PsychoanalysisTechniqueExecutor()
    state = make_initial_psychoanalysis_state()
    state.update(
        {
            'persona_id': 'insight_mentor',
            'surface_persona_id': 'insight_mentor',
            'last_user_message': '你这么说，我就更不想讲了。',
            'here_and_now_triggered': True,
            'relational_pull': 'testing_authority',
            'alliance_strength': 'medium',
            'resistance_level': 'medium',
        }
    )

    payload = executor.build_payload(state, 'psa_relational_here_now')

    assert '你这么说，我就更不想讲了' in payload.user_prompt
    assert '动力学信号摘要' not in payload.user_prompt
    assert '召回的脱敏模式记忆' not in payload.user_prompt
    assert '{' not in payload.user_prompt
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
    state['surface_persona_id'] = 'insight_mentor'
    state['last_user_message'] = '你这么说，我就更不想讲了。'
    state['here_and_now_triggered'] = True
    state['alliance_strength'] = 'medium'

    plan = graph.plan_turn(state)

    assert plan.selection.technique_id == 'psa_relational_here_now'
    assert plan.payload is not None
    assert '心理学前辈' in plan.payload.system_prompt
    assert '你这么说，我就更不想讲了' in plan.payload.user_prompt


