from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest

from backend.moodpal.cbt import CBTGraph, CBTNodeRegistry
from backend.moodpal.cbt import exit_rule_config, router_config
from backend.moodpal.cbt.executor_prompt_config import PROMPT_TEMPLATE_BY_TECHNIQUE
from backend.moodpal.cbt.state import make_initial_cbt_state


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
    state = make_initial_cbt_state()
    if patch:
        state.update(deepcopy(patch))
    return state


def _evaluate_case(case: RegressionCase):
    graph = CBTGraph()
    state = _build_state(case.initial_state)

    plan = graph.plan_turn(state)
    assert plan.selection.track == case.expected_track, case.name
    assert plan.selection.technique_id == case.expected_technique_id, case.name

    runtime_state = dict(state)
    runtime_state.update(deepcopy(case.execution_patch))
    runtime_state['current_track'] = plan.selection.track
    runtime_state['current_technique_id'] = plan.selection.technique_id

    evaluation = graph.evaluate_turn(runtime_state, plan.selection.technique_id)
    assert evaluation.progress_marker == case.expected_progress_marker, case.name
    assert evaluation.next_fallback_action == case.expected_exit_action, case.name

    if case.expected_followup_track and case.expected_followup_technique_id:
        next_state = dict(runtime_state)
        next_state.update(evaluation.state_patch)
        if case.followup_state_patch:
            next_state.update(deepcopy(case.followup_state_patch))

        followup_plan = graph.plan_turn(next_state)
        assert followup_plan.selection.track == case.expected_followup_track, case.name
        assert followup_plan.selection.technique_id == case.expected_followup_technique_id, case.name


REGRESSION_CASES = (
    RegressionCase(
        name='agenda_to_identification',
        initial_state={
            'last_user_message': '完了，如果我搞砸了怎么办？',
        },
        expected_track='agenda',
        expected_technique_id='cbt_structure_agenda_setting',
        execution_patch={
            'agenda_topic': '明天开会怕搞砸',
            'agenda_locked': True,
        },
        expected_progress_marker='agenda_locked',
        expected_exit_action='handoff_to_cognitive_track',
        expected_followup_track='cognitive_identification',
        expected_followup_technique_id='cbt_cog_identify_at_telegraphic',
    ),
    RegressionCase(
        name='identification_to_evaluation',
        initial_state={
            'agenda_topic': '老板没回消息',
            'agenda_locked': True,
            'last_user_message': '如果老板不回我，我就完了。',
        },
        expected_track='cognitive_identification',
        expected_technique_id='cbt_cog_identify_at_telegraphic',
        execution_patch={
            'captured_automatic_thought': '如果老板不回我，我就完了。',
        },
        expected_progress_marker='automatic_thought_captured',
        expected_exit_action='switch_same_track',
        expected_followup_track='cognitive_evaluation',
        expected_followup_technique_id='cbt_cog_eval_distortion',
    ),
    RegressionCase(
        name='evaluation_to_response',
        initial_state={
            'agenda_topic': '老板没回消息',
            'agenda_locked': True,
            'captured_automatic_thought': '老板不回我，说明我做得很差。',
            'last_user_message': '我现在就觉得自己完蛋了。',
        },
        expected_track='cognitive_evaluation',
        expected_technique_id='cbt_cog_eval_socratic',
        execution_patch={
            'cognitive_distortion_label': '灾难化',
            'alternative_explanation': '老板可能在忙，并不等于我做得差。',
        },
        expected_progress_marker='alternative_explanation_found',
        expected_exit_action='switch_same_track',
        expected_followup_track='cognitive_response',
        expected_followup_technique_id='cbt_cog_response_coping',
    ),
    RegressionCase(
        name='behavioral_activation_wrap_up',
        initial_state={
            'agenda_topic': '下班后什么都做不了',
            'agenda_locked': True,
            'last_user_message': '我什么都不想干，完全动不了。',
            'energy_level': 'low',
            'behavioral_shutdown': True,
        },
        expected_track='behavioral_activation',
        expected_technique_id='cbt_beh_activation',
        execution_patch={
            'activation_step': '起身去洗把脸',
            'homework_candidate': '起身去洗把脸',
        },
        expected_progress_marker='activation_step_committed',
        expected_exit_action='wrap_up_now',
    ),
    RegressionCase(
        name='behavioral_experiment_wrap_up',
        initial_state={
            'agenda_topic': '给同事发消息',
            'agenda_locked': True,
            'captured_automatic_thought': '如果我主动发消息，他肯定会嫌我烦。',
            'last_user_message': '我一想到要发消息就很慌。',
            'emotion_stability': 'medium',
        },
        expected_track='behavioral_experiment',
        expected_technique_id='cbt_beh_experiment',
        execution_patch={
            'experiment_plan': {
                'action': '给一位熟悉同事发一句简短消息',
                'timepoint': '今晚八点',
                'metric': '记录对方是否回复以及我的紧张程度',
            },
            'homework_candidate': '今晚八点给一位熟悉同事发一句简短消息',
        },
        expected_progress_marker='behavioral_experiment_ready',
        expected_exit_action='wrap_up_now',
    ),
    RegressionCase(
        name='homework_obstacle_to_graded_task',
        initial_state={
            'agenda_topic': '上周约好的小行动',
            'agenda_locked': True,
            'last_user_message': '我没做，上周那件事还是做不到。',
        },
        expected_track='exception',
        expected_technique_id='cbt_exception_homework_obstacle',
        execution_patch={
            'task_first_step': '先把文档打开并写标题',
            'homework_obstacle_detected': False,
        },
        expected_progress_marker='obstacle_reframed',
        expected_exit_action='switch_same_track',
        followup_state_patch={
            'last_user_message': '还是太难了，我不知道从哪开始。',
        },
        expected_followup_track='graded_task',
        expected_followup_technique_id='cbt_beh_graded_task',
    ),
    RegressionCase(
        name='yes_but_to_response',
        initial_state={
            'agenda_topic': '开会发言',
            'agenda_locked': True,
            'last_user_message': '理智上我知道没那么严重，但我心里还是很慌。',
            'balanced_response': '即使我会紧张，也不代表我一定会搞砸。',
            'balanced_response_confidence': 65,
            'head_heart_split_detected': True,
        },
        expected_track='exception',
        expected_technique_id='cbt_exception_yes_but',
        execution_patch={
            'head_heart_split_detected': False,
            'homework_candidate': '开会前先写下一句提醒自己的平衡想法',
        },
        expected_progress_marker='head_heart_gap_contained',
        expected_exit_action='switch_same_track',
        followup_state_patch={
            'last_user_message': '这句话现在比刚才稍微能进一点了。',
        },
        expected_followup_track='cognitive_response',
        expected_followup_technique_id='cbt_cog_response_coping',
    ),
    RegressionCase(
        name='alliance_rupture_back_to_identification',
        initial_state={
            'agenda_topic': '老板没回消息',
            'agenda_locked': True,
            'last_user_message': '你根本不懂，这些大道理没用。',
            'alliance_rupture_detected': True,
            'alliance_strength': 'weak',
        },
        expected_track='exception',
        expected_technique_id='cbt_exception_alliance_rupture',
        execution_patch={
            'alliance_rupture_detected': False,
            'alliance_strength': 'medium',
        },
        expected_progress_marker='alliance_repaired',
        expected_exit_action='switch_same_track',
        followup_state_patch={
            'last_user_message': '我其实最怕的是老板不回我之后会觉得我很差。',
        },
        expected_followup_track='cognitive_identification',
        expected_followup_technique_id='cbt_cog_identify_at_basic',
    ),
)


@pytest.mark.parametrize('case', REGRESSION_CASES, ids=[case.name for case in REGRESSION_CASES])
def test_cbt_regression_cases(case: RegressionCase):
    _evaluate_case(case)


def test_all_cbt_nodes_have_prompt_and_exit_templates():
    registry_ids = {node.node_id for node in CBTNodeRegistry().all_nodes()}

    assert set(PROMPT_TEMPLATE_BY_TECHNIQUE.keys()) == registry_ids
    assert set(exit_rule_config.EXIT_RULE_BY_TECHNIQUE.keys()) == registry_ids


def test_router_track_candidates_cover_known_nodes():
    registry_ids = {node.node_id for node in CBTNodeRegistry().all_nodes()}
    routed_ids = {
        technique_id
        for candidates in router_config.TRACK_CANDIDATES.values()
        for technique_id in candidates
    }

    assert routed_ids == registry_ids


def test_prompt_template_context_keys_are_valid_state_fields():
    state_keys = set(make_initial_cbt_state().keys())

    for technique_id, template in PROMPT_TEMPLATE_BY_TECHNIQUE.items():
        unknown_keys = set(template.relevant_context_keys) - state_keys
        assert not unknown_keys, f'{technique_id} has unknown context keys: {sorted(unknown_keys)}'
