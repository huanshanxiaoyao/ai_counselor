from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest

from backend.moodpal.humanistic import HumanisticGraph, HumanisticNodeRegistry
from backend.moodpal.humanistic import resonance_rule_config, router_config
from backend.moodpal.humanistic.executor_prompt_config import PROMPT_TEMPLATE_BY_TECHNIQUE
from backend.moodpal.humanistic.state import make_initial_humanistic_state


@dataclass(frozen=True)
class RegressionCase:
    name: str
    initial_state: dict
    expected_track: str
    expected_technique_id: str
    execution_patch: dict
    expected_progress_marker: str
    expected_exit_action: str
    followup_state_patch: dict | None = None
    expected_followup_track: str | None = None
    expected_followup_technique_id: str | None = None


def _build_state(patch: dict | None = None) -> dict:
    state = make_initial_humanistic_state()
    if patch:
        state.update(deepcopy(patch))
    return state


def _evaluate_case(case: RegressionCase):
    graph = HumanisticGraph()
    state = _build_state(case.initial_state)

    plan = graph.plan_turn(state)
    assert plan.selection.track == case.expected_track, case.name
    assert plan.selection.technique_id == case.expected_technique_id, case.name

    runtime_state = dict(state)
    runtime_state.update(deepcopy(case.execution_patch))
    runtime_state['current_phase'] = plan.selection.track
    runtime_state['current_technique_id'] = plan.selection.technique_id

    evaluation = graph.evaluate_turn(runtime_state, plan.selection.technique_id)
    assert evaluation.progress_marker == case.expected_progress_marker, case.name
    assert evaluation.next_fallback_action == case.expected_exit_action, case.name

    if case.expected_followup_track and case.expected_followup_technique_id:
        next_state = dict(runtime_state)
        next_state.update(evaluation.state_patch)
        next_state['current_stage'] = 'determine_phase'
        if case.followup_state_patch:
            next_state.update(deepcopy(case.followup_state_patch))

        followup_plan = graph.plan_turn(next_state)
        assert followup_plan.selection.track == case.expected_followup_track, case.name
        assert followup_plan.selection.technique_id == case.expected_followup_technique_id, case.name


REGRESSION_CASES = (
    RegressionCase(
        name='holding_to_clarifying',
        initial_state={
            'last_user_message': '我现在真的快崩溃了。',
            'emotional_intensity': 9,
        },
        expected_track='holding',
        expected_technique_id='hum_validate_normalize',
        execution_patch={
            'being_understood_signal': True,
            'emotional_intensity': 7,
        },
        expected_progress_marker='holding_stabilized',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '其实我更多是委屈和失落。',
            'dominant_emotions': ['委屈', '失落'],
            'emotional_clarity': 'clear',
            'being_understood_signal': False,
        },
        expected_followup_track='clarifying',
        expected_followup_technique_id='hum_reflect_feeling',
    ),
    RegressionCase(
        name='clarifying_to_accepting',
        initial_state={
            'last_user_message': '他那样回我，我心里很委屈。',
            'emotional_intensity': 6,
            'relational_trust': 'medium',
        },
        expected_track='clarifying',
        expected_technique_id='hum_reflect_feeling',
        execution_patch={
            'dominant_emotions': ['委屈', '失落'],
            'emotional_clarity': 'clear',
            'being_understood_signal': True,
        },
        expected_progress_marker='deeper_emotion_named',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '但我还是觉得我就是个废物，不值得被爱。',
            'self_attack_flag': True,
            'being_understood_signal': False,
            'emotional_intensity': 7,
        },
        expected_followup_track='accepting',
        expected_followup_technique_id='hum_unconditional_regard',
    ),
    RegressionCase(
        name='alliance_repair_to_clarifying',
        initial_state={
            'last_user_message': '你根本没懂我，别再套模板了。',
            'alliance_rupture_detected': True,
            'relational_trust': 'weak',
            'emotional_intensity': 7,
        },
        expected_track='repair',
        expected_technique_id='hum_exception_alliance_repair',
        execution_patch={
            'alliance_rupture_detected': False,
            'relational_trust': 'medium',
        },
        expected_progress_marker='alliance_repaired',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '其实我最难受的是委屈，像一直没被看见。',
            'emotional_intensity': 6,
        },
        expected_followup_track='clarifying',
        expected_followup_technique_id='hum_reflect_feeling',
    ),
    RegressionCase(
        name='body_focus_to_clarifying',
        initial_state={
            'last_user_message': '我胸口堵得慌，说不上来。',
            'body_signal_present': True,
            'emotional_clarity': 'diffuse',
            'emotional_intensity': 6,
        },
        expected_track='body_focusing',
        expected_technique_id='hum_body_focus',
        execution_patch={
            'felt_sense_description': '胸口像堵着一团气',
            'emotional_clarity': 'emerging',
        },
        expected_progress_marker='felt_sense_emerged',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '好像是委屈卡在这里。',
            'body_signal_present': False,
        },
        expected_followup_track='clarifying',
        expected_followup_technique_id='hum_reflect_feeling',
    ),
    RegressionCase(
        name='advice_pull_to_clarifying',
        initial_state={
            'last_user_message': '别安慰我了，直接告诉我怎么办。',
            'advice_pull_detected': True,
            'openness_level': 'guarded',
            'emotional_intensity': 7,
        },
        expected_track='repair',
        expected_technique_id='hum_boundary_advice_pull',
        execution_patch={
            'advice_pull_detected': False,
            'openness_level': 'partial',
            'homework_candidate': '先决定一个最想先处理的小点',
        },
        expected_progress_marker='advice_pull_contained',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '那我最想先处理的是今晚要不要回他消息。',
            'emotional_intensity': 5,
        },
        expected_followup_track='clarifying',
        expected_followup_technique_id='hum_reflect_feeling',
    ),
    RegressionCase(
        name='numbness_repair_to_body_focus',
        initial_state={
            'last_user_message': '我脑子一片空白，什么都感觉不到。',
            'numbness_detected': True,
            'emotional_intensity': 6,
        },
        expected_track='repair',
        expected_technique_id='hum_exception_numbness_unfreeze',
        execution_patch={
            'numbness_detected': False,
            'body_signal_present': True,
            'emotional_clarity': 'diffuse',
        },
        expected_progress_marker='numbness_softened',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '就是胸口空空的。',
        },
        expected_followup_track='body_focusing',
        expected_followup_technique_id='hum_body_focus',
    ),
)


@pytest.mark.parametrize('case', REGRESSION_CASES, ids=[case.name for case in REGRESSION_CASES])
def test_humanistic_regression_cases(case: RegressionCase):
    _evaluate_case(case)


def test_all_humanistic_nodes_have_prompt_and_resonance_templates():
    registry_ids = {node.node_id for node in HumanisticNodeRegistry().all_nodes()}

    assert set(PROMPT_TEMPLATE_BY_TECHNIQUE.keys()) == registry_ids
    assert set(resonance_rule_config.RESONANCE_RULE_BY_TECHNIQUE.keys()) == registry_ids


def test_router_phase_candidates_cover_known_nodes():
    registry_ids = {node.node_id for node in HumanisticNodeRegistry().all_nodes()}
    routed_ids = {
        technique_id
        for candidates in router_config.PHASE_CANDIDATES.values()
        for technique_id in candidates
    }

    assert routed_ids == registry_ids


def test_prompt_template_context_keys_are_valid_state_fields():
    state_keys = set(make_initial_humanistic_state().keys())

    for technique_id, template in PROMPT_TEMPLATE_BY_TECHNIQUE.items():
        unknown_keys = set(template.relevant_context_keys) - state_keys
        assert not unknown_keys, f'{technique_id} has unknown context keys: {sorted(unknown_keys)}'
