from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


StatePredicate = Callable[[dict], bool]

DEFAULT_FALLBACK_ACTION = 'retry_same_technique'
BEHAVIORAL_FALLBACK_ACTION = 'handoff_to_behavioral_track'
EXCEPTION_FALLBACK_ACTION = 'jump_to_exception'

ALLIANCE_RUPTURE_HINTS = (
    '你根本不懂',
    '这些大道理没用',
    '你只是个机器人',
    '放屁',
)

REDIRECTING_HINTS = (
    '顺便',
    '还有就是',
    '另外我还想说',
)

HOMEWORK_OBSTACLE_HINTS = (
    '没做',
    '忘了',
    '我太懒了',
    '做不到',
)

HEAD_HEART_SPLIT_HINTS = (
    '理智上我知道',
    '但我心里还是',
    '我知道你说得对',
    '还是很难受',
)

DISTORTION_HINTS = (
    '总是',
    '从不',
    '必须',
    '一定',
    '肯定',
    '完了',
    '全毁了',
    '没救了',
    '什么都做不好',
)

TELEGRAPHIC_HINTS = (
    '完了',
    '糟糕',
    '死定了',
    '没戏了',
    '麻了',
)

IMAGERY_HINTS = (
    '想不起来',
    '脑子空白',
    '大脑一片空白',
    '忘了',
    '记不得',
)

BEHAVIORAL_ACTIVATION_HINTS = (
    '什么都不想干',
    '完全动不了',
    '整天都在床上',
    '没有力气',
)

TASK_OVERWHELM_HINTS = (
    '太难了',
    '做不到',
    '无法开始',
    '根本没法开始',
    '不可能',
)

BEHAVIOR_EXPERIMENT_HINTS = (
    '如果',
    '一定会',
    '肯定会',
)


def has_text(value: str) -> bool:
    return bool((value or '').strip())


def contains_any(text: str, hints: tuple[str, ...]) -> bool:
    source = (text or '').strip()
    if not source:
        return False
    return any(token in source for token in hints)


def looks_like_prediction(text: str) -> bool:
    source = (text or '').strip()
    if not source or '如果' not in source:
        return False
    return any(token in source for token in ('会', '一定', '肯定', '应该', '就会'))


def merge_text(*parts: str) -> str:
    return '\n'.join(part for part in parts if (part or '').strip())


def flag_or_hint_predicate(flag_key: str, hints: tuple[str, ...]) -> StatePredicate:
    def _predicate(state: dict) -> bool:
        return bool(state.get(flag_key)) or contains_any(state.get('last_user_message', ''), hints)

    return _predicate


@dataclass(frozen=True)
class TechniqueRouteRule:
    track: str
    technique_id: str
    reason: str
    predicate: StatePredicate
    fallback_action: str = DEFAULT_FALLBACK_ACTION


def _agenda_not_locked(state: dict) -> bool:
    return not bool(state.get('agenda_locked')) or not has_text(state.get('agenda_topic', ''))


def _deep_exploration_ready(state: dict) -> bool:
    if not state.get('repeated_theme_detected'):
        return False
    if state.get('emotion_stability') != 'high':
        return False
    if state.get('alliance_strength') == 'weak':
        return False
    if state.get('session_phase') in ['summary_pending', 'closed']:
        return False
    return True


def _cognitive_response_ready(state: dict) -> bool:
    return has_text(state.get('alternative_explanation', '')) or int(state.get('balanced_response_confidence') or 0) > 0


def _cognitive_evaluation_ready(state: dict) -> bool:
    return has_text(state.get('captured_automatic_thought', ''))


def _distortion_evaluation_ready(state: dict) -> bool:
    if not _cognitive_evaluation_ready(state):
        return False
    thought_text = merge_text(
        state.get('captured_automatic_thought', ''),
        state.get('last_user_message', ''),
    )
    return contains_any(thought_text, DISTORTION_HINTS)


def _behavioral_activation_ready(state: dict) -> bool:
    return bool(state.get('behavioral_shutdown')) or (
        state.get('energy_level') == 'low'
        and contains_any(state.get('last_user_message', ''), BEHAVIORAL_ACTIVATION_HINTS)
    )


def _graded_task_in_progress(state: dict) -> bool:
    return has_text(state.get('task_first_step', ''))


def _task_overwhelm_detected(state: dict) -> bool:
    return contains_any(state.get('last_user_message', ''), TASK_OVERWHELM_HINTS)


def _behavioral_experiment_ready(state: dict) -> bool:
    prediction_source = merge_text(
        state.get('captured_automatic_thought', ''),
        state.get('last_user_message', ''),
    )
    return (
        contains_any(prediction_source, BEHAVIOR_EXPERIMENT_HINTS)
        and looks_like_prediction(prediction_source)
        and state.get('emotion_stability') != 'low'
    )


def _telegraphic_identification_needed(state: dict) -> bool:
    user_text = state.get('last_user_message', '')
    return (
        state.get('thought_format') in ['telegraphic', 'question']
        or contains_any(user_text, TELEGRAPHIC_HINTS)
        or user_text.endswith('?')
    )


def _imagery_identification_needed(state: dict) -> bool:
    return state.get('thought_format') == 'imagery' or contains_any(
        state.get('last_user_message', ''),
        IMAGERY_HINTS,
    )


EXCEPTION_ROUTE_RULES = (
    TechniqueRouteRule(
        track='exception',
        technique_id='cbt_exception_alliance_rupture',
        reason='alliance_rupture_detected',
        predicate=flag_or_hint_predicate('alliance_rupture_detected', ALLIANCE_RUPTURE_HINTS),
        fallback_action=EXCEPTION_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='exception',
        technique_id='cbt_exception_redirecting',
        reason='topic_drift_detected',
        predicate=flag_or_hint_predicate('topic_drift_detected', REDIRECTING_HINTS),
        fallback_action=EXCEPTION_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='exception',
        technique_id='cbt_exception_homework_obstacle',
        reason='homework_obstacle_detected',
        predicate=flag_or_hint_predicate('homework_obstacle_detected', HOMEWORK_OBSTACLE_HINTS),
        fallback_action=EXCEPTION_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='exception',
        technique_id='cbt_exception_yes_but',
        reason='head_heart_split_detected',
        predicate=flag_or_hint_predicate('head_heart_split_detected', HEAD_HEART_SPLIT_HINTS),
        fallback_action=EXCEPTION_FALLBACK_ACTION,
    ),
)

AGENDA_ROUTE_RULE = TechniqueRouteRule(
    track='agenda',
    technique_id='cbt_structure_agenda_setting',
    reason='agenda_not_locked',
    predicate=_agenda_not_locked,
)

DEEP_EXPLORATION_ROUTE_RULE = TechniqueRouteRule(
    track='deep_exploration',
    technique_id='cbt_core_downward_arrow',
    reason='repeated_theme_with_stable_alliance',
    predicate=_deep_exploration_ready,
)

BEHAVIORAL_ROUTE_RULES = (
    TechniqueRouteRule(
        track='behavioral_activation',
        technique_id='cbt_beh_activation',
        reason='low_energy_and_behavioral_shutdown',
        predicate=_behavioral_activation_ready,
        fallback_action=BEHAVIORAL_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='graded_task',
        technique_id='cbt_beh_graded_task',
        reason='task_breakdown_already_in_progress',
        predicate=_graded_task_in_progress,
        fallback_action=BEHAVIORAL_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='graded_task',
        technique_id='cbt_beh_graded_task',
        reason='task_overwhelm_detected',
        predicate=_task_overwhelm_detected,
        fallback_action=BEHAVIORAL_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='behavioral_experiment',
        technique_id='cbt_beh_experiment',
        reason='testable_negative_prediction_detected',
        predicate=_behavioral_experiment_ready,
        fallback_action=BEHAVIORAL_FALLBACK_ACTION,
    ),
)

COGNITIVE_RESPONSE_ROUTE_RULE = TechniqueRouteRule(
    track='cognitive_response',
    technique_id='cbt_cog_response_coping',
    reason='ready_to_compose_balanced_response',
    predicate=_cognitive_response_ready,
    fallback_action='wrap_up_now',
)

COGNITIVE_EVALUATION_ROUTE_RULES = (
    TechniqueRouteRule(
        track='cognitive_evaluation',
        technique_id='cbt_cog_eval_distortion',
        reason='automatic_thought_ready_for_evaluation',
        predicate=_distortion_evaluation_ready,
    ),
    TechniqueRouteRule(
        track='cognitive_evaluation',
        technique_id='cbt_cog_eval_socratic',
        reason='automatic_thought_ready_for_evaluation',
        predicate=_cognitive_evaluation_ready,
    ),
)

IDENTIFICATION_ROUTE_RULES = (
    TechniqueRouteRule(
        track='cognitive_identification',
        technique_id='cbt_cog_identify_at_telegraphic',
        reason='telegraphic_or_question_thought_detected',
        predicate=_telegraphic_identification_needed,
    ),
    TechniqueRouteRule(
        track='cognitive_identification',
        technique_id='cbt_cog_identify_at_imagery',
        reason='imagery_reconstruction_needed',
        predicate=_imagery_identification_needed,
    ),
    TechniqueRouteRule(
        track='cognitive_identification',
        technique_id='cbt_cog_identify_at_basic',
        reason='need_capture_automatic_thought',
        predicate=lambda state: True,
    ),
)

TRACK_CANDIDATES = {
    'agenda': (
        'cbt_structure_agenda_setting',
    ),
    'cognitive_identification': (
        'cbt_cog_identify_at_basic',
        'cbt_cog_identify_at_telegraphic',
        'cbt_cog_identify_at_imagery',
    ),
    'cognitive_evaluation': (
        'cbt_cog_eval_socratic',
        'cbt_cog_eval_distortion',
    ),
    'cognitive_response': (
        'cbt_cog_response_coping',
    ),
    'behavioral_activation': (
        'cbt_beh_activation',
    ),
    'behavioral_experiment': (
        'cbt_beh_experiment',
    ),
    'graded_task': (
        'cbt_beh_graded_task',
    ),
    'deep_exploration': (
        'cbt_core_downward_arrow',
    ),
    'exception': tuple(rule.technique_id for rule in EXCEPTION_ROUTE_RULES),
}

TECHNIQUE_TRACKS = {
    technique_id: track
    for track, candidates in TRACK_CANDIDATES.items()
    for technique_id in candidates
}

SAME_TRACK_FALLBACKS = {
    'cbt_cog_identify_at_basic': (
        'cbt_cog_identify_at_telegraphic',
        'cbt_cog_identify_at_imagery',
    ),
    'cbt_cog_eval_socratic': (
        'cbt_cog_eval_distortion',
    ),
    'cbt_beh_experiment': (
        'cbt_beh_graded_task',
    ),
    'cbt_core_downward_arrow': (
        'cbt_exception_yes_but',
    ),
}

BEHAVIORAL_FALLBACK_CANDIDATES = (
    'cbt_beh_graded_task',
    'cbt_beh_activation',
    'cbt_beh_experiment',
)

DEFAULT_EXCEPTION_FALLBACK_TECHNIQUE = 'cbt_exception_yes_but'
TERMINAL_FALLBACK_ACTIONS = {'', DEFAULT_FALLBACK_ACTION, 'wrap_up_now'}
