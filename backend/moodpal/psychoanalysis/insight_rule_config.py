from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import PsychoanalysisGraphState


StateEvaluator = Callable[[PsychoanalysisGraphState], tuple[bool, float, str, str]]


@dataclass(frozen=True)
class TechniqueInsightRule:
    technique_id: str
    done_action: str
    trip_action: str
    evaluator: StateEvaluator


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


def _evaluate_containment(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = state.get('association_openness') in ['partial', 'open'] and not bool(state.get('containment_needed'))
    return _binary_result(
        done=done,
        done_confidence=0.9,
        pending_confidence=0.76,
        done_reason='container_stabilized',
        pending_reason='still_needs_containment',
        done_marker='container_stabilized',
        pending_marker='containment_in_progress',
    )


def _evaluate_association(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('manifest_theme', '')) or _has_text(state.get('focus_theme', ''))
    return _binary_result(
        done=done,
        done_confidence=0.86,
        pending_confidence=0.72,
        done_reason='material_opened',
        pending_reason='material_still_thin',
        done_marker='material_opened',
        pending_marker='association_in_progress',
    )


def _evaluate_defense(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('active_defense', '')) and state.get('resistance_level') in ['low', 'medium']
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='defense_named_softly',
        pending_reason='defense_not_workable_yet',
        done_marker='defense_named_softly',
        pending_marker='defense_probe_in_progress',
    )


def _evaluate_pattern_linking(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('repetition_theme_candidate', '')) and float(state.get('pattern_confidence') or 0.0) >= 0.6
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='repetition_pattern_glimpsed',
        pending_reason='pattern_still_unclear',
        done_marker='repetition_pattern_glimpsed',
        pending_marker='pattern_probe_in_progress',
    )


def _evaluate_relational_here_now(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = (
        bool(state.get('here_and_now_triggered'))
        and _has_text(state.get('relational_pull', ''))
        and not bool(state.get('alliance_rupture_detected'))
        and state.get('alliance_strength') in ['medium', 'strong']
    )
    return _binary_result(
        done=done,
        done_confidence=0.82,
        pending_confidence=0.68,
        done_reason='here_and_now_named',
        pending_reason='relationship_reaction_still_implicit',
        done_marker='here_and_now_named',
        pending_marker='here_and_now_probe_in_progress',
    )


def _evaluate_insight_integration(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('working_hypothesis', '')) and int(state.get('insight_score') or 0) >= 6
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.68,
        done_reason='insight_landed_lightly',
        pending_reason='insight_not_landed_yet',
        done_marker='insight_landed_lightly',
        pending_marker='integration_in_progress',
    )


def _evaluate_resistance_soften(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('resistance_spike_detected') and state.get('resistance_level') in ['low', 'medium']
    return _binary_result(
        done=done,
        done_confidence=0.84,
        pending_confidence=0.7,
        done_reason='resistance_softened',
        pending_reason='resistance_still_high',
        done_marker='resistance_softened',
        pending_marker='repair_in_progress',
    )


def _evaluate_alliance_repair(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('alliance_rupture_detected') and state.get('alliance_strength') in ['medium', 'strong']
    return _binary_result(
        done=done,
        done_confidence=0.85,
        pending_confidence=0.72,
        done_reason='alliance_repaired',
        pending_reason='alliance_still_fragile',
        done_marker='alliance_repaired',
        pending_marker='alliance_repair_in_progress',
    )


def _evaluate_advice_pull(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = not state.get('advice_pull_detected') and state.get('association_openness') != 'guarded'
    return _binary_result(
        done=done,
        done_confidence=0.82,
        pending_confidence=0.68,
        done_reason='boundary_negotiated',
        pending_reason='advice_pull_still_active',
        done_marker='boundary_negotiated',
        pending_marker='boundary_negotiation_in_progress',
    )


def _evaluate_reflective_close(state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    done = _has_text(state.get('working_hypothesis', '')) or _has_text(state.get('repetition_theme_candidate', '')) or int(state.get('insight_score') or 0) >= 4
    return _binary_result(
        done=done,
        done_confidence=0.9,
        pending_confidence=0.72,
        done_reason='closing_anchor_formed',
        pending_reason='closing_anchor_still_thin',
        done_marker='closing_anchor_formed',
        pending_marker='closing_in_progress',
    )


def _evaluate_unknown(_state: PsychoanalysisGraphState) -> tuple[bool, float, str, str]:
    return False, 0.5, 'unknown_technique', ''


INSIGHT_RULES = (
    TechniqueInsightRule(
        technique_id='psa_entry_containment',
        done_action='switch_same_phase',
        trip_action='regress_to_containment',
        evaluator=_evaluate_containment,
    ),
    TechniqueInsightRule(
        technique_id='psa_association_invite',
        done_action='switch_same_phase',
        trip_action='regress_to_containment',
        evaluator=_evaluate_association,
    ),
    TechniqueInsightRule(
        technique_id='psa_defense_clarification',
        done_action='switch_same_phase',
        trip_action='jump_to_repair',
        evaluator=_evaluate_defense,
    ),
    TechniqueInsightRule(
        technique_id='psa_pattern_linking',
        done_action='switch_same_phase',
        trip_action='switch_same_phase',
        evaluator=_evaluate_pattern_linking,
    ),
    TechniqueInsightRule(
        technique_id='psa_relational_here_now',
        done_action='switch_same_phase',
        trip_action='jump_to_repair',
        evaluator=_evaluate_relational_here_now,
    ),
    TechniqueInsightRule(
        technique_id='psa_insight_integration',
        done_action='wrap_up_now',
        trip_action='regress_to_containment',
        evaluator=_evaluate_insight_integration,
    ),
    TechniqueInsightRule(
        technique_id='psa_exception_resistance_soften',
        done_action='switch_same_phase',
        trip_action='wrap_up_now',
        evaluator=_evaluate_resistance_soften,
    ),
    TechniqueInsightRule(
        technique_id='psa_exception_alliance_repair',
        done_action='switch_same_phase',
        trip_action='wrap_up_now',
        evaluator=_evaluate_alliance_repair,
    ),
    TechniqueInsightRule(
        technique_id='psa_boundary_advice_pull',
        done_action='switch_same_phase',
        trip_action='wrap_up_now',
        evaluator=_evaluate_advice_pull,
    ),
    TechniqueInsightRule(
        technique_id='psa_reflective_close',
        done_action='wrap_up_now',
        trip_action='wrap_up_now',
        evaluator=_evaluate_reflective_close,
    ),
)

INSIGHT_RULE_BY_TECHNIQUE = {
    rule.technique_id: rule
    for rule in INSIGHT_RULES
}

DEFAULT_INSIGHT_RULE = TechniqueInsightRule(
    technique_id='',
    done_action='switch_same_phase',
    trip_action='wrap_up_now',
    evaluator=_evaluate_unknown,
)


def get_insight_rule(technique_id: str) -> TechniqueInsightRule:
    return INSIGHT_RULE_BY_TECHNIQUE.get(technique_id, DEFAULT_INSIGHT_RULE)
