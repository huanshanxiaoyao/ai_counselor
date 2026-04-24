from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import HumanisticGraphState


StateEvaluator = Callable[[HumanisticGraphState], tuple[bool, float, str, str]]


def _has_text(value: str) -> bool:
    return bool((value or '').strip())


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


@dataclass(frozen=True)
class TechniqueResonanceRule:
    technique_id: str
    done_action: str
    trip_action: str
    evaluator: StateEvaluator


def _evaluate_validate(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = bool(state.get('being_understood_signal')) or int(state.get('emotional_intensity') or 0) <= 7 or state.get('emotional_clarity') in ['emerging', 'clear']
    return _binary_result(
        done=done,
        done_confidence=0.9,
        pending_confidence=0.76,
        done_reason='emotional_container_stabilized',
        pending_reason='still_needs_holding',
        done_marker='holding_stabilized',
        pending_marker='holding_in_progress',
    )


def _evaluate_reflect(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = bool(state.get('being_understood_signal')) or state.get('emotional_clarity') == 'clear' or bool(state.get('dominant_emotions'))
    return _binary_result(
        done=done,
        done_confidence=0.88,
        pending_confidence=0.74,
        done_reason='deeper_emotion_named',
        pending_reason='emotion_still_diffuse',
        done_marker='deeper_emotion_named',
        pending_marker='emotion_probe_in_progress',
    )


def _evaluate_body_focus(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('felt_sense_description', '')) or state.get('emotional_clarity') in ['emerging', 'clear']
    return _binary_result(
        done=done,
        done_confidence=0.86,
        pending_confidence=0.72,
        done_reason='felt_sense_emerged',
        pending_reason='felt_sense_still_missing',
        done_marker='felt_sense_emerged',
        pending_marker='body_attention_in_progress',
    )


def _evaluate_accepting(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('self_compassion_shift', '')) or (not state.get('self_attack_flag') and int(state.get('resonance_score') or 0) >= 60)
    return _binary_result(
        done=done,
        done_confidence=0.86,
        pending_confidence=0.72,
        done_reason='self_attack_softened',
        pending_reason='self_attack_still_active',
        done_marker='self_attack_softened',
        pending_marker='acceptance_in_progress',
    )


def _evaluate_alliance_repair(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('alliance_rupture_detected') and state.get('relational_trust') in ['medium', 'strong']
    return _binary_result(
        done=done,
        done_confidence=0.85,
        pending_confidence=0.72,
        done_reason='alliance_repaired',
        pending_reason='alliance_still_fragile',
        done_marker='alliance_repaired',
        pending_marker='repair_in_progress',
    )


def _evaluate_numbness_unfreeze(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('numbness_detected') and (
        bool(state.get('body_signal_present'))
        or _has_text(state.get('felt_sense_description', ''))
        or state.get('emotional_clarity') in ['emerging', 'clear']
    )
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='numbness_softened',
        pending_reason='still_disconnected',
        done_marker='numbness_softened',
        pending_marker='numbness_unfreeze_in_progress',
    )


def _evaluate_advice_pull(state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('advice_pull_detected') and (state.get('openness_level') != 'guarded' or _has_text(state.get('homework_candidate', '')))
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='advice_pull_contained',
        pending_reason='still_pulling_for_direct_answer',
        done_marker='advice_pull_contained',
        pending_marker='boundary_negotiation_in_progress',
    )


def _evaluate_unknown(_state: HumanisticGraphState) -> tuple[bool, float, str, str]:
    return False, 0.5, 'unknown_technique', ''


RESONANCE_RULES = (
    TechniqueResonanceRule(
        technique_id='hum_validate_normalize',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_validate,
    ),
    TechniqueResonanceRule(
        technique_id='hum_reflect_feeling',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_reflect,
    ),
    TechniqueResonanceRule(
        technique_id='hum_body_focus',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_body_focus,
    ),
    TechniqueResonanceRule(
        technique_id='hum_unconditional_regard',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_accepting,
    ),
    TechniqueResonanceRule(
        technique_id='hum_exception_alliance_repair',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_alliance_repair,
    ),
    TechniqueResonanceRule(
        technique_id='hum_exception_numbness_unfreeze',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_numbness_unfreeze,
    ),
    TechniqueResonanceRule(
        technique_id='hum_boundary_advice_pull',
        done_action='switch_same_phase',
        trip_action='regress_to_holding',
        evaluator=_evaluate_advice_pull,
    ),
)

RESONANCE_RULE_BY_TECHNIQUE = {
    rule.technique_id: rule
    for rule in RESONANCE_RULES
}

DEFAULT_RESONANCE_RULE = TechniqueResonanceRule(
    technique_id='',
    done_action='switch_same_phase',
    trip_action='wrap_up_now',
    evaluator=_evaluate_unknown,
)


def get_resonance_rule(technique_id: str) -> TechniqueResonanceRule:
    return RESONANCE_RULE_BY_TECHNIQUE.get(technique_id, DEFAULT_RESONANCE_RULE)
