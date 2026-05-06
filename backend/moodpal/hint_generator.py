from __future__ import annotations

from typing import Optional


_MIN_TURNS = 3
_MIN_HINT_GAP = 2


def generate_hint(
    signals: dict,
    turn_index: int,
    last_hint_turn_index: int = -99,
) -> Optional[str]:
    if not _passes_gate(signals, turn_index, last_hint_turn_index):
        return None
    return _select_hint(signals)


def _passes_gate(signals: dict, turn_index: int, last_hint_turn_index: int) -> bool:
    if turn_index < _MIN_TURNS:
        return False
    if signals.get('repair_needed'):
        return False
    if signals.get('alliance_status') == 'weak':
        return False
    distress = signals.get('distress_level', 'low')
    clarity = signals.get('problem_clarity', 'low')
    if distress == 'high' and clarity == 'low':
        return False
    if turn_index - last_hint_turn_index < _MIN_HINT_GAP:
        return False
    return (
        signals.get('cbt_readiness', 'low') in {'medium', 'high'}
        or signals.get('psychoanalysis_readiness', 'low') in {'medium', 'high'}
        or signals.get('action_readiness', 'low') in {'medium', 'high'}
        or signals.get('pattern_signal_strength', 'low') in {'medium', 'high'}
    )


def _select_hint(signals: dict) -> Optional[str]:
    pattern = signals.get('pattern_signal_strength', 'low')
    alliance = signals.get('alliance_status', 'medium')
    action = signals.get('action_readiness', 'low')
    cbt = signals.get('cbt_readiness', 'low')
    psycho = signals.get('psychoanalysis_readiness', 'low')
    distress = signals.get('distress_level', 'low')

    if pattern in {'medium', 'high'} and alliance == 'strong':
        return '用户的一些话里有重复的影子，有机会可以轻轻点一下，不用说透。'
    if pattern in {'medium', 'high'} and psycho in {'medium', 'high'}:
        return '用户似乎在绕圈子，可以帮他轻轻找到最想说的那根线。'
    if action in {'medium', 'high'} and cbt in {'medium', 'high'}:
        return '用户好像想往前走，可以帮他把第一步压到最小。'
    if distress == 'high' and cbt in {'medium', 'high'}:
        return '用户情绪还很满，先接住，等他自己松一点再说。'
    if cbt in {'medium', 'high'}:
        return '用户好像在找一个抓手，可以帮他把问题收束到一个具体的点上。'
    if psycho in {'medium', 'high'}:
        return '用户的话里有一些反复出现的感受，可以在合适的时候温和地映照一下。'
    return None
