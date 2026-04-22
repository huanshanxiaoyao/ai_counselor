from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import CBTGraphState


StateEvaluator = Callable[[CBTGraphState], tuple[bool, float, str, str]]


def _has_text(value: str) -> bool:
    return bool((value or '').strip())


@dataclass(frozen=True)
class TechniqueExitRule:
    technique_id: str
    done_action: str
    trip_action: str
    evaluator: StateEvaluator


def _binary_result(
    *,
    done: bool,
    done_confidence: float,
    pending_confidence: float,
    done_reason: str,
    pending_reason: str,
    done_marker: str,
    pending_marker: str = '',
) -> tuple[bool, float, str, str]:
    if done:
        return True, done_confidence, done_reason, done_marker
    return False, pending_confidence, pending_reason, pending_marker


def _evaluate_agenda(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = bool(state.get('agenda_locked') and _has_text(state.get('agenda_topic', '')))
    return _binary_result(
        done=done,
        done_confidence=0.92,
        pending_confidence=0.78,
        done_reason='agenda_locked',
        pending_reason='agenda_not_locked_yet',
        done_marker='agenda_locked',
        pending_marker='agenda_probing',
    )


def _evaluate_identification(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('captured_automatic_thought', ''))
    return _binary_result(
        done=done,
        done_confidence=0.9,
        pending_confidence=0.74,
        done_reason='automatic_thought_captured',
        pending_reason='automatic_thought_still_missing',
        done_marker='automatic_thought_captured',
    )


def _evaluate_socratic(state: CBTGraphState) -> tuple[bool, float, str, str]:
    has_alternative = _has_text(state.get('alternative_explanation', ''))
    belief_confidence = int(state.get('belief_confidence') or 0)
    softened = belief_confidence > 0 and belief_confidence < 70
    progress_marker = 'alternative_explanation_found' if has_alternative else 'belief_softened' if softened else ''
    return _binary_result(
        done=has_alternative or softened,
        done_confidence=0.88,
        pending_confidence=0.76,
        done_reason='cognitive_reappraisal_progress',
        pending_reason='original_belief_still_rigid',
        done_marker=progress_marker,
    )


def _evaluate_distortion(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('cognitive_distortion_label', ''))
    return _binary_result(
        done=done,
        done_confidence=0.89,
        pending_confidence=0.77,
        done_reason='distortion_labeled',
        pending_reason='distortion_not_named',
        done_marker='distortion_labeled',
    )


def _evaluate_coping_response(state: CBTGraphState) -> tuple[bool, float, str, str]:
    confidence_value = int(state.get('balanced_response_confidence') or 0)
    done = _has_text(state.get('balanced_response', '')) and confidence_value >= 60
    return _binary_result(
        done=done,
        done_confidence=0.9,
        pending_confidence=0.75,
        done_reason='balanced_response_ready',
        pending_reason='balanced_response_not_grounded',
        done_marker='balanced_response_ready',
    )


def _evaluate_activation(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('activation_step', '')) or _has_text(state.get('homework_candidate', ''))
    return _binary_result(
        done=done,
        done_confidence=0.87,
        pending_confidence=0.73,
        done_reason='activation_step_committed',
        pending_reason='activation_step_missing',
        done_marker='activation_step_committed',
    )


def _evaluate_behavioral_experiment(state: CBTGraphState) -> tuple[bool, float, str, str]:
    plan = state.get('experiment_plan') or {}
    done = bool(
        plan.get('action')
        and plan.get('timepoint')
        and plan.get('metric')
        and _has_text(state.get('homework_candidate', ''))
    )
    return _binary_result(
        done=done,
        done_confidence=0.88,
        pending_confidence=0.74,
        done_reason='behavioral_experiment_ready',
        pending_reason='experiment_plan_incomplete',
        done_marker='behavioral_experiment_ready',
    )


def _evaluate_graded_task(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('task_first_step', '')) and _has_text(state.get('homework_candidate', ''))
    return _binary_result(
        done=done,
        done_confidence=0.88,
        pending_confidence=0.74,
        done_reason='task_first_step_locked',
        pending_reason='task_first_step_missing',
        done_marker='task_first_step_locked',
    )


def _evaluate_downward_arrow(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('core_belief_candidate', '')) or _has_text(state.get('intermediate_belief_candidate', ''))
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='core_belief_candidate_extracted',
        pending_reason='deep_theme_not_ready',
        done_marker='core_belief_candidate_extracted',
    )


def _evaluate_alliance_rupture(state: CBTGraphState) -> tuple[bool, float, str, str]:
    repaired = state.get('alliance_strength') in ['medium', 'strong'] and not state.get('alliance_rupture_detected')
    return _binary_result(
        done=repaired,
        done_confidence=0.86,
        pending_confidence=0.72,
        done_reason='alliance_repaired',
        pending_reason='alliance_still_fragile',
        done_marker='alliance_repaired',
    )


def _evaluate_redirecting(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('topic_drift_detected') and _has_text(state.get('agenda_topic', ''))
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.72,
        done_reason='agenda_relocked',
        pending_reason='topic_drift_persists',
        done_marker='agenda_relocked',
    )


def _evaluate_homework_obstacle(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('captured_automatic_thought', '')) or _has_text(state.get('task_first_step', ''))
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.72,
        done_reason='obstacle_reframed',
        pending_reason='obstacle_still_opaque',
        done_marker='obstacle_reframed',
    )


def _evaluate_yes_but(state: CBTGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('head_heart_split_detected') and (
        _has_text(state.get('core_belief_candidate', ''))
        or _has_text(state.get('homework_candidate', ''))
        or _has_text(state.get('balanced_response', ''))
    )
    return _binary_result(
        done=done,
        done_confidence=0.82,
        pending_confidence=0.7,
        done_reason='head_heart_gap_contained',
        pending_reason='head_heart_gap_persists',
        done_marker='head_heart_gap_contained',
    )


def _evaluate_unknown(_state: CBTGraphState) -> tuple[bool, float, str, str]:
    return False, 0.5, 'unknown_technique', ''


EXIT_RULES = (
    TechniqueExitRule(
        technique_id='cbt_structure_agenda_setting',
        done_action='handoff_to_cognitive_track',
        trip_action='wrap_up_now',
        evaluator=_evaluate_agenda,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_identify_at_basic',
        done_action='switch_same_track',
        trip_action='switch_same_track',
        evaluator=_evaluate_identification,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_identify_at_telegraphic',
        done_action='switch_same_track',
        trip_action='jump_to_exception',
        evaluator=_evaluate_identification,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_identify_at_imagery',
        done_action='switch_same_track',
        trip_action='jump_to_exception',
        evaluator=_evaluate_identification,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_eval_socratic',
        done_action='switch_same_track',
        trip_action='switch_same_track',
        evaluator=_evaluate_socratic,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_eval_distortion',
        done_action='switch_same_track',
        trip_action='jump_to_exception',
        evaluator=_evaluate_distortion,
    ),
    TechniqueExitRule(
        technique_id='cbt_cog_response_coping',
        done_action='wrap_up_now',
        trip_action='jump_to_exception',
        evaluator=_evaluate_coping_response,
    ),
    TechniqueExitRule(
        technique_id='cbt_beh_activation',
        done_action='wrap_up_now',
        trip_action='handoff_to_behavioral_track',
        evaluator=_evaluate_activation,
    ),
    TechniqueExitRule(
        technique_id='cbt_beh_experiment',
        done_action='wrap_up_now',
        trip_action='switch_same_track',
        evaluator=_evaluate_behavioral_experiment,
    ),
    TechniqueExitRule(
        technique_id='cbt_beh_graded_task',
        done_action='wrap_up_now',
        trip_action='handoff_to_behavioral_track',
        evaluator=_evaluate_graded_task,
    ),
    TechniqueExitRule(
        technique_id='cbt_core_downward_arrow',
        done_action='wrap_up_now',
        trip_action='switch_same_track',
        evaluator=_evaluate_downward_arrow,
    ),
    TechniqueExitRule(
        technique_id='cbt_exception_alliance_rupture',
        done_action='switch_same_track',
        trip_action='wrap_up_now',
        evaluator=_evaluate_alliance_rupture,
    ),
    TechniqueExitRule(
        technique_id='cbt_exception_redirecting',
        done_action='switch_same_track',
        trip_action='wrap_up_now',
        evaluator=_evaluate_redirecting,
    ),
    TechniqueExitRule(
        technique_id='cbt_exception_homework_obstacle',
        done_action='switch_same_track',
        trip_action='wrap_up_now',
        evaluator=_evaluate_homework_obstacle,
    ),
    TechniqueExitRule(
        technique_id='cbt_exception_yes_but',
        done_action='switch_same_track',
        trip_action='wrap_up_now',
        evaluator=_evaluate_yes_but,
    ),
)

EXIT_RULE_BY_TECHNIQUE = {
    rule.technique_id: rule
    for rule in EXIT_RULES
}

DEFAULT_EXIT_RULE = TechniqueExitRule(
    technique_id='',
    done_action='switch_same_track',
    trip_action='wrap_up_now',
    evaluator=_evaluate_unknown,
)


def get_exit_rule(technique_id: str) -> TechniqueExitRule:
    return EXIT_RULE_BY_TECHNIQUE.get(technique_id, DEFAULT_EXIT_RULE)
