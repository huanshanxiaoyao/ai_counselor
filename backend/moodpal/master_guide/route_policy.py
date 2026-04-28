from __future__ import annotations


def choose_support_directive(*, support_mode: str, previous_track: str, next_mode: str) -> str:
    if next_mode == 'support_only':
        if support_mode == 'opening':
            return 'opening_hold'
        if support_mode == 'repair':
            return 'repair_softened'
        return ''
    if support_mode == 'repair':
        return 'repair_softened'
    if previous_track and previous_track != next_mode:
        return 'soft_handoff'
    return 'gentle_focus'


def should_hold_for_support(*, turn_index: int, repair_needed: bool, distress_level: str, problem_clarity: str, recent_track_progress: str) -> tuple[bool, str]:
    if turn_index == 0:
        return True, 'opening_hold'
    if repair_needed:
        return True, 'repair_alliance'
    if distress_level == 'high' and problem_clarity == 'low':
        return True, 'distress_hold'
    if recent_track_progress == 'stall' and distress_level != 'low':
        return True, 'repair_after_stall'
    return False, ''


def should_prefer_psychoanalysis(*, pattern_signal_strength: str, psychoanalysis_readiness: str, action_readiness: str, previous_track: str, text: str) -> bool:
    if pattern_signal_strength == 'high' and psychoanalysis_readiness in {'medium', 'high'}:
        return True
    if previous_track == 'psychoanalysis' and pattern_signal_strength != 'low':
        return True
    if pattern_signal_strength == 'medium' and psychoanalysis_readiness == 'high' and action_readiness == 'low':
        return True
    if '为什么我总' in text or '为什么每次' in text:
        return True
    return False


def should_prefer_cbt(*, problem_clarity: str, action_readiness: str, previous_track: str) -> bool:
    if previous_track == 'cbt' and action_readiness != 'low':
        return True
    if problem_clarity == 'high':
        return True
    if action_readiness in {'medium', 'high'}:
        return True
    if problem_clarity == 'medium' and action_readiness != 'low':
        return True
    return False
