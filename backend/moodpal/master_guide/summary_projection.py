from __future__ import annotations

from .router import MasterGuideRouteSelection


_REASON_LABELS = {
    'opening_hold': '先用承接方式把情绪放稳一点',
    'repair_alliance': '先回到关系修复，避免继续硬推',
    'distress_hold': '先把情绪压力放稳，再继续往下走',
    'repair_after_stall': '先退回修复和缓冲，再决定下一步',
    'cbt_problem_solving': '随后转到现实问题拆解与应对',
    'continue_cbt': '继续沿着现实问题拆解往前推',
    'psy_repetition_pattern': '后来开始看到更长期的重复模式线索',
    'continue_psychoanalysis': '继续沿着已经浮现的模式往下看',
    'clarity_hold': '先继续承接，让真正要处理的点慢慢清楚',
}


def append_summary_hint(existing_hints: list[str] | None, selection: MasterGuideRouteSelection) -> list[str]:
    hints = list(existing_hints or [])
    hint = _REASON_LABELS.get(selection.reason_code, '').strip()
    if hint and hint not in hints:
        hints.append(hint)
    return hints[-4:]
