from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


StatePredicate = Callable[[dict], bool]

DEFAULT_FALLBACK_ACTION = 'retry_same_technique'
REPAIR_FALLBACK_ACTION = 'jump_to_repair'
PHASE_PRIORITY = (
    'safety_override',
    'repair',
    'holding',
    'accepting',
    'body_focusing',
    'clarifying',
)

ALLIANCE_RUPTURE_HINTS = (
    '你根本没懂',
    '别套模板',
    '像机器人',
    '你没明白',
    '别再分析我',
)

NUMBNESS_HINTS = (
    '什么都感觉不到',
    '脑子一片空白',
    '空掉了',
    '麻木',
)

ADVICE_PULL_HINTS = (
    '直接告诉我怎么办',
    '别安慰我了',
    '别共情了',
    '给我个办法',
    '直接说我该怎么办',
)

SHAME_HINTS = (
    '太丢人了',
    '很丢脸',
    '好羞耻',
    '我是不是很脆弱',
)

HIGH_INTENSITY_HINTS = (
    '崩溃',
    '大哭',
    '撑不住',
    '受不了',
    '太难受了',
)

SELF_ATTACK_HINTS = (
    '我很糟糕',
    '我是废物',
    '不配',
    '烂人',
    '一无是处',
    '没人会喜欢我',
)

BODY_SIGNAL_HINTS = (
    '胸口闷',
    '堵得慌',
    '喘不过气',
    '喉咙堵',
    '心口',
    '胃里',
    '身体很紧',
)

UNDERSTOOD_HINTS = (
    '你懂我',
    '是这样',
    '就是这种感觉',
    '对，就是',
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


def _holding_needed(state: dict) -> bool:
    intensity = int(state.get('emotional_intensity') or 0)
    if intensity >= 8:
        return True
    user_text = state.get('last_user_message', '')
    return bool(state.get('shame_signal')) or contains_any(user_text, SHAME_HINTS + HIGH_INTENSITY_HINTS)


def _accepting_needed(state: dict) -> bool:
    user_text = state.get('last_user_message', '')
    return bool(state.get('self_attack_flag')) or contains_any(user_text, SELF_ATTACK_HINTS)


def _body_focus_ready(state: dict) -> bool:
    if bool(state.get('alliance_rupture_detected')):
        return False
    if int(state.get('emotional_intensity') or 0) >= 9:
        return False
    user_text = state.get('last_user_message', '')
    has_body_signal = bool(state.get('body_signal_present')) or contains_any(user_text, BODY_SIGNAL_HINTS)
    return has_body_signal and state.get('emotional_clarity', 'diffuse') == 'diffuse'


def _clarifying_default(_state: dict) -> bool:
    return True


REPAIR_ROUTE_RULES = (
    TechniqueRouteRule(
        track='repair',
        technique_id='hum_exception_alliance_repair',
        reason='alliance_rupture_detected',
        predicate=flag_or_hint_predicate('alliance_rupture_detected', ALLIANCE_RUPTURE_HINTS),
        fallback_action=REPAIR_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='repair',
        technique_id='hum_exception_numbness_unfreeze',
        reason='numbness_detected',
        predicate=flag_or_hint_predicate('numbness_detected', NUMBNESS_HINTS),
        fallback_action=REPAIR_FALLBACK_ACTION,
    ),
    TechniqueRouteRule(
        track='repair',
        technique_id='hum_boundary_advice_pull',
        reason='advice_pull_detected',
        predicate=flag_or_hint_predicate('advice_pull_detected', ADVICE_PULL_HINTS),
        fallback_action=REPAIR_FALLBACK_ACTION,
    ),
)

HOLDING_ROUTE_RULE = TechniqueRouteRule(
    track='holding',
    technique_id='hum_validate_normalize',
    reason='holding_needed',
    predicate=_holding_needed,
)

ACCEPTING_ROUTE_RULE = TechniqueRouteRule(
    track='accepting',
    technique_id='hum_unconditional_regard',
    reason='self_attack_detected',
    predicate=_accepting_needed,
)

BODY_FOCUS_ROUTE_RULE = TechniqueRouteRule(
    track='body_focusing',
    technique_id='hum_body_focus',
    reason='body_signal_present_and_diffuse',
    predicate=_body_focus_ready,
)

CLARIFYING_ROUTE_RULE = TechniqueRouteRule(
    track='clarifying',
    technique_id='hum_reflect_feeling',
    reason='clarifying_default',
    predicate=_clarifying_default,
)

PHASE_CANDIDATES = {
    'holding': ('hum_validate_normalize',),
    'clarifying': ('hum_reflect_feeling',),
    'body_focusing': ('hum_body_focus',),
    'accepting': ('hum_unconditional_regard',),
    'repair': (
        'hum_exception_alliance_repair',
        'hum_exception_numbness_unfreeze',
        'hum_boundary_advice_pull',
    ),
}

TECHNIQUE_PHASES = {
    technique_id: phase
    for phase, candidates in PHASE_CANDIDATES.items()
    for technique_id in candidates
}

SAME_PHASE_FALLBACKS = {
    'hum_validate_normalize': (),
    'hum_reflect_feeling': ('hum_validate_normalize',),
    'hum_body_focus': ('hum_validate_normalize',),
    'hum_unconditional_regard': ('hum_reflect_feeling', 'hum_validate_normalize'),
    'hum_exception_alliance_repair': ('hum_validate_normalize',),
    'hum_exception_numbness_unfreeze': ('hum_validate_normalize',),
    'hum_boundary_advice_pull': ('hum_validate_normalize',),
}

GRAPH_EXCEPTION_HANDLERS = {
    'alliance_rupture_detected': 'hum_exception_alliance_repair',
    'numbness_detected': 'hum_exception_numbness_unfreeze',
    'advice_pull_detected': 'hum_boundary_advice_pull',
}

TERMINAL_FALLBACK_ACTIONS = ('wrap_up_now', 'handoff_to_safety')
DEFAULT_REPAIR_FALLBACK_TECHNIQUE = 'hum_exception_alliance_repair'
