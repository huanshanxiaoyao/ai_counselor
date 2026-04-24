from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


StatePredicate = Callable[[dict], bool]

DEFAULT_FALLBACK_ACTION = 'retry_same_technique'
REPAIR_FALLBACK_ACTION = 'jump_to_repair'
CONTAINMENT_FALLBACK_ACTION = 'regress_to_containment'

ALLIANCE_RUPTURE_HINTS = (
    '你根本没懂',
    '别分析我',
    '你这样让我更烦',
    '你没听懂',
    '不想跟你说了',
)

RESISTANCE_SPIKE_HINTS = (
    '算了',
    '不想说了',
    '说了也没用',
    '没意思',
    '先这样吧',
    '到此为止',
)

ADVICE_PULL_HINTS = (
    '直接告诉我怎么办',
    '你就告诉我怎么办',
    '别分析了',
    '给我个办法',
    '直接说结论',
)

CONTAINMENT_HINTS = (
    '整个人都缩起来了',
    '我有点怕',
    '不太敢说',
    '我想躲起来',
    '我有点想退回去',
)

DEFENSE_HINTS = (
    '其实也没什么',
    '大家都这样',
    '讲这个也没意义',
    '理智上我知道',
    '应该没什么吧',
)

PATTERN_LINK_HINTS = (
    '每次都',
    '总是这样',
    '不只是这次',
    '又来了',
    '一直都是',
    '每回都',
)

RELATIONAL_HINTS = (
    '你这么说',
    '你刚才那句',
    '被你这么一说',
    '你这样说',
    '你是不是在',
)


@dataclass(frozen=True)
class TechniqueRouteRule:
    track: str
    technique_id: str
    reason: str
    predicate: StatePredicate
    fallback_action: str = DEFAULT_FALLBACK_ACTION


def has_text(value: str) -> bool:
    return bool((value or '').strip())


def contains_any(text: str, hints: tuple[str, ...]) -> bool:
    source = (text or '').strip()
    if not source:
        return False
    return any(token in source for token in hints)


def flag_or_hint_predicate(flag_key: str, hints: tuple[str, ...]) -> StatePredicate:
    def _predicate(state: dict) -> bool:
        return bool(state.get(flag_key)) or contains_any(state.get('last_user_message', ''), hints)

    return _predicate


def _float_confidence(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _should_close(state: dict) -> bool:
    return state.get('current_stage') == 'wrap_up' or state.get('session_phase') in ['ending', 'summary_pending']


def _containment_needed(state: dict) -> bool:
    if bool(state.get('containment_needed')):
        return True
    if int(state.get('emotional_intensity') or 0) >= 8:
        return True
    if state.get('association_openness') == 'guarded':
        return True
    return contains_any(state.get('last_user_message', ''), CONTAINMENT_HINTS)


def _defense_clarification_ready(state: dict) -> bool:
    if state.get('resistance_level') == 'high':
        return False
    if bool(state.get('alliance_rupture_detected')):
        return False
    if has_text(state.get('active_defense', '')):
        return True
    return contains_any(state.get('last_user_message', ''), DEFENSE_HINTS)


def _pattern_linking_ready(state: dict) -> bool:
    if state.get('resistance_level') == 'high':
        return False
    if state.get('alliance_strength') == 'weak':
        return False
    if has_text(state.get('repetition_theme_candidate', '')):
        return True
    recalled_pattern_memory = list(state.get('recalled_pattern_memory') or [])
    if recalled_pattern_memory and (
        has_text(state.get('manifest_theme', ''))
        or contains_any(state.get('last_user_message', ''), PATTERN_LINK_HINTS)
    ):
        return True
    return False


def _relational_reflection_ready(state: dict) -> bool:
    if bool(state.get('alliance_rupture_detected')):
        return False
    if bool(state.get('here_and_now_triggered')):
        return True
    return has_text(state.get('relational_pull', '')) and contains_any(
        state.get('last_user_message', ''),
        RELATIONAL_HINTS,
    )


def _insight_integration_ready(state: dict) -> bool:
    if state.get('resistance_level') == 'high':
        return False
    if state.get('alliance_strength') == 'weak':
        return False
    if bool(state.get('insight_ready')):
        return True
    return has_text(state.get('working_hypothesis', '')) and _float_confidence(state.get('pattern_confidence')) >= 0.65


def _association_default(_state: dict) -> bool:
    return True


CLOSING_ROUTE_RULE = TechniqueRouteRule(
    track='closing',
    technique_id='psa_reflective_close',
    reason='wrap_up_requested',
    predicate=_should_close,
    fallback_action='wrap_up_now',
)

REPAIR_ROUTE_RULES = (
    TechniqueRouteRule(
        track='repair',
        technique_id='psa_exception_alliance_repair',
        reason='alliance_rupture_detected',
        predicate=flag_or_hint_predicate('alliance_rupture_detected', ALLIANCE_RUPTURE_HINTS),
        fallback_action=REPAIR_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='repair',
        technique_id='psa_exception_resistance_soften',
        reason='resistance_spike_detected',
        predicate=lambda state: bool(state.get('resistance_spike_detected'))
        or state.get('resistance_level') == 'high'
        or contains_any(state.get('last_user_message', ''), RESISTANCE_SPIKE_HINTS),
        fallback_action=REPAIR_FALLBACK_ACTION,
    ),
)

BOUNDARY_ROUTE_RULE = TechniqueRouteRule(
    track='boundary',
    technique_id='psa_boundary_advice_pull',
    reason='advice_pull_detected',
    predicate=flag_or_hint_predicate('advice_pull_detected', ADVICE_PULL_HINTS),
    fallback_action=REPAIR_FALLBACK_ACTION,
)

CONTAINMENT_ROUTE_RULE = TechniqueRouteRule(
    track='containment',
    technique_id='psa_entry_containment',
    reason='containment_needed',
    predicate=_containment_needed,
    fallback_action=CONTAINMENT_FALLBACK_ACTION,
)

RELATIONAL_ROUTE_RULE = TechniqueRouteRule(
    track='relational_reflection',
    technique_id='psa_relational_here_now',
    reason='here_and_now_triggered',
    predicate=_relational_reflection_ready,
)

INSIGHT_ROUTE_RULE = TechniqueRouteRule(
    track='insight_integration',
    technique_id='psa_insight_integration',
    reason='working_hypothesis_ready',
    predicate=_insight_integration_ready,
)

DEFENSE_ROUTE_RULE = TechniqueRouteRule(
    track='defense_clarification',
    technique_id='psa_defense_clarification',
    reason='defense_clarification_ready',
    predicate=_defense_clarification_ready,
)

PATTERN_LINK_ROUTE_RULE = TechniqueRouteRule(
    track='pattern_linking',
    technique_id='psa_pattern_linking',
    reason='repetition_pattern_candidate_detected',
    predicate=_pattern_linking_ready,
)

ASSOCIATION_ROUTE_RULE = TechniqueRouteRule(
    track='association',
    technique_id='psa_association_invite',
    reason='association_default',
    predicate=_association_default,
)

PHASE_CANDIDATES = {
    'containment': ('psa_entry_containment',),
    'association': ('psa_association_invite',),
    'defense_clarification': ('psa_defense_clarification',),
    'pattern_linking': ('psa_pattern_linking',),
    'relational_reflection': ('psa_relational_here_now',),
    'insight_integration': ('psa_insight_integration',),
    'repair': ('psa_exception_resistance_soften', 'psa_exception_alliance_repair'),
    'boundary': ('psa_boundary_advice_pull',),
    'closing': ('psa_reflective_close',),
}

TECHNIQUE_PHASES = {
    technique_id: phase
    for phase, candidates in PHASE_CANDIDATES.items()
    for technique_id in candidates
}

SAME_PHASE_FALLBACKS = {
    'psa_entry_containment': (),
    'psa_association_invite': ('psa_entry_containment',),
    'psa_defense_clarification': ('psa_association_invite', 'psa_entry_containment'),
    'psa_pattern_linking': ('psa_association_invite', 'psa_entry_containment'),
    'psa_relational_here_now': ('psa_entry_containment',),
    'psa_insight_integration': ('psa_pattern_linking', 'psa_entry_containment'),
    'psa_exception_resistance_soften': ('psa_entry_containment',),
    'psa_exception_alliance_repair': ('psa_entry_containment',),
    'psa_boundary_advice_pull': ('psa_entry_containment',),
    'psa_reflective_close': (),
}

GRAPH_EXCEPTION_HANDLERS = {
    'alliance_rupture_detected': 'psa_exception_alliance_repair',
    'resistance_spike_detected': 'psa_exception_resistance_soften',
    'advice_pull_detected': 'psa_boundary_advice_pull',
}

DEFAULT_REPAIR_FALLBACK_TECHNIQUE = 'psa_exception_resistance_soften'
# `wrap_up_now` is intentionally not terminal here: psychoanalysis still routes
# into the explicit closing node so the final turn can land as a reflective close.
TERMINAL_FALLBACK_ACTIONS = ('handoff_to_safety',)
