from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest

from backend.moodpal.psychoanalysis import PsychoanalysisGraph, PsychoanalysisNodeRegistry
from backend.moodpal.psychoanalysis import insight_rule_config, router_config
from backend.moodpal.psychoanalysis.executor_prompt_config import PROMPT_TEMPLATE_BY_TECHNIQUE
from backend.moodpal.psychoanalysis.state import make_initial_psychoanalysis_state


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
    state = make_initial_psychoanalysis_state()
    if patch:
        state.update(deepcopy(patch))
    return state


def _evaluate_case(case: RegressionCase):
    graph = PsychoanalysisGraph()
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
        name='containment_to_association',
        initial_state={
            'last_user_message': '我现在整个人都缩起来了，不太敢说。',
            'containment_needed': True,
            'emotional_intensity': 8,
            'association_openness': 'guarded',
        },
        expected_track='containment',
        expected_technique_id='psa_entry_containment',
        execution_patch={
            'containment_needed': False,
            'association_openness': 'partial',
            'emotional_intensity': 6,
        },
        expected_progress_marker='container_stabilized',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '其实我也说不清，就是这几天一直有点紧。',
            'association_openness': 'partial',
            'emotional_intensity': 5,
        },
        expected_followup_track='association',
        expected_followup_technique_id='psa_association_invite',
    ),
    RegressionCase(
        name='defense_to_pattern_linking',
        initial_state={
            'last_user_message': '理智上我知道不是什么大事，但讲这个也没意义。',
            'active_defense': 'intellectualization',
            'resistance_level': 'medium',
            'alliance_strength': 'medium',
        },
        expected_track='defense_clarification',
        expected_technique_id='psa_defense_clarification',
        execution_patch={
            'active_defense': 'intellectualization',
            'resistance_level': 'medium',
        },
        expected_progress_marker='defense_named_softly',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'active_defense': '',
            'last_user_message': '其实不只是这次，每次老板语气一重我都先怪自己。',
            'repetition_theme_candidate': 'authority_tension',
            'pattern_confidence': 0.72,
        },
        expected_followup_track='pattern_linking',
        expected_followup_technique_id='psa_pattern_linking',
    ),
    RegressionCase(
        name='boundary_to_association',
        initial_state={
            'last_user_message': '别分析了，直接告诉我怎么办。',
            'advice_pull_detected': True,
            'association_openness': 'guarded',
        },
        expected_track='boundary',
        expected_technique_id='psa_boundary_advice_pull',
        execution_patch={
            'advice_pull_detected': False,
            'association_openness': 'partial',
        },
        expected_progress_marker='boundary_negotiated',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '如果先只说一个点，那就是每次要回消息我都很僵。',
            'association_openness': 'partial',
        },
        expected_followup_track='association',
        expected_followup_technique_id='psa_association_invite',
    ),
    RegressionCase(
        name='alliance_repair_to_association',
        initial_state={
            'last_user_message': '你根本没听懂，别再分析我了。',
            'alliance_rupture_detected': True,
            'alliance_strength': 'weak',
        },
        expected_track='repair',
        expected_technique_id='psa_exception_alliance_repair',
        execution_patch={
            'alliance_rupture_detected': False,
            'alliance_strength': 'medium',
        },
        expected_progress_marker='alliance_repaired',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '其实我最难受的是一被别人盯住看，我就会想退开。',
            'association_openness': 'partial',
            'relational_pull': '',
        },
        expected_followup_track='association',
        expected_followup_technique_id='psa_association_invite',
    ),
    RegressionCase(
        name='resistance_soften_to_association',
        initial_state={
            'last_user_message': '算了，不想说了。',
            'resistance_spike_detected': True,
            'resistance_level': 'high',
            'alliance_strength': 'medium',
        },
        expected_track='repair',
        expected_technique_id='psa_exception_resistance_soften',
        execution_patch={
            'resistance_spike_detected': False,
            'resistance_level': 'medium',
            'association_openness': 'partial',
        },
        expected_progress_marker='resistance_softened',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '我可以先说一点，就是最近一紧张我就会卡住。',
            'association_openness': 'partial',
        },
        expected_followup_track='association',
        expected_followup_technique_id='psa_association_invite',
    ),
    RegressionCase(
        name='pattern_linking_to_insight',
        initial_state={
            'last_user_message': '不只是这次，每次老板一冷下来我都先怪自己。',
            'repetition_theme_candidate': 'authority_tension',
            'pattern_confidence': 0.72,
            'alliance_strength': 'medium',
            'resistance_level': 'low',
        },
        expected_track='pattern_linking',
        expected_technique_id='psa_pattern_linking',
        execution_patch={
            'repetition_theme_candidate': 'authority_tension',
            'pattern_confidence': 0.72,
        },
        expected_progress_marker='repetition_pattern_glimpsed',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '好像真的是这样。',
            'working_hypothesis': '一面对权威冷下来，你就会先把问题收到自己身上',
            'pattern_confidence': 0.78,
            'insight_ready': True,
        },
        expected_followup_track='insight_integration',
        expected_followup_technique_id='psa_insight_integration',
    ),
    RegressionCase(
        name='relational_to_insight',
        initial_state={
            'last_user_message': '你这么一说，我就更不想讲了。',
            'here_and_now_triggered': True,
            'alliance_strength': 'medium',
        },
        expected_track='relational_reflection',
        expected_technique_id='psa_relational_here_now',
        execution_patch={
            'here_and_now_triggered': True,
            'relational_pull': 'testing_authority',
            'alliance_strength': 'medium',
        },
        expected_progress_marker='here_and_now_named',
        expected_exit_action='switch_same_phase',
        followup_state_patch={
            'last_user_message': '我好像一觉得关系紧了就会先防起来。',
            'here_and_now_triggered': False,
            'relational_pull': '',
            'working_hypothesis': '一感觉到关系里有点紧，你就会先防起来',
            'pattern_confidence': 0.75,
            'insight_ready': True,
            'alliance_strength': 'strong',
        },
        expected_followup_track='insight_integration',
        expected_followup_technique_id='psa_insight_integration',
    ),
    RegressionCase(
        name='insight_wraps_up',
        initial_state={
            'last_user_message': '这好像确实是我一直会做的事。',
            'working_hypothesis': '一感觉到关系紧张，你就会先把自己收回去',
            'pattern_confidence': 0.8,
            'alliance_strength': 'strong',
            'resistance_level': 'low',
        },
        expected_track='insight_integration',
        expected_technique_id='psa_insight_integration',
        execution_patch={
            'working_hypothesis': '一感觉到关系紧张，你就会先把自己收回去',
            'pattern_confidence': 0.8,
            'insight_score': 7,
            'alliance_strength': 'strong',
        },
        expected_progress_marker='insight_landed_lightly',
        expected_exit_action='wrap_up_now',
    ),
)


@pytest.mark.parametrize('case', REGRESSION_CASES, ids=[case.name for case in REGRESSION_CASES])
def test_psychoanalysis_regression_cases(case: RegressionCase):
    _evaluate_case(case)


def test_all_psychoanalysis_nodes_have_prompt_and_insight_templates():
    registry_ids = {node.node_id for node in PsychoanalysisNodeRegistry().all_nodes()}

    assert set(PROMPT_TEMPLATE_BY_TECHNIQUE.keys()) == registry_ids
    assert set(insight_rule_config.INSIGHT_RULE_BY_TECHNIQUE.keys()) == registry_ids


def test_router_phase_candidates_cover_known_nodes():
    registry_ids = {node.node_id for node in PsychoanalysisNodeRegistry().all_nodes()}
    routed_ids = {
        technique_id
        for candidates in router_config.PHASE_CANDIDATES.values()
        for technique_id in candidates
    }

    assert routed_ids == registry_ids


def test_prompt_template_context_keys_are_valid_state_fields():
    state_keys = set(make_initial_psychoanalysis_state().keys())

    for technique_id, template in PROMPT_TEMPLATE_BY_TECHNIQUE.items():
        unknown_keys = set(template.relevant_context_keys) - state_keys
        assert not unknown_keys, f'{technique_id} has unknown context keys: {sorted(unknown_keys)}'
