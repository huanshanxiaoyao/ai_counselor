from __future__ import annotations

import re
from dataclasses import dataclass


SELF_HARM_PATTERNS = [
    r'(想|准备|打算).{0,6}(自杀|去死|结束生命|不想活)',
    r'(不想活了|活不下去了|想死|想自杀|轻生)',
    r'(割腕|跳楼|吞药|上吊|烧炭|自残)',
]

HARM_OTHERS_PATTERNS = [
    r'(想|准备|打算).{0,6}(杀人|伤害别人|伤害他人|报复社会)',
    r'(弄死他|同归于尽|砍人)',
]


@dataclass(frozen=True)
class CrisisCheckResult:
    triggered: bool
    risk_type: str = ''
    matched_count: int = 0
    detector_stage: str = 'regex'
    response_text: str = ''
    sticky_mode: bool = False


def detect_crisis_text(text: str) -> CrisisCheckResult:
    source = (text or '').strip()
    if not source:
        return CrisisCheckResult(triggered=False)

    match_count = _count_unique_matches(source, SELF_HARM_PATTERNS)
    if match_count > 0:
        return CrisisCheckResult(
            triggered=True,
            risk_type='self_harm',
            matched_count=match_count,
            response_text=build_crisis_response_text(),
        )

    match_count = _count_unique_matches(source, HARM_OTHERS_PATTERNS)
    if match_count > 0:
        return CrisisCheckResult(
            triggered=True,
            risk_type='harm_others',
            matched_count=match_count,
            response_text=build_crisis_response_text(),
        )

    return CrisisCheckResult(triggered=False)


def build_sticky_crisis_result() -> CrisisCheckResult:
    return CrisisCheckResult(
        triggered=True,
        risk_type='crisis_followup',
        matched_count=0,
        detector_stage='sticky_followup',
        response_text=build_crisis_response_text(sticky_mode=True),
        sticky_mode=True,
    )


def build_crisis_response_text(*, sticky_mode: bool = False) -> str:
    if sticky_mode:
        return (
            '普通对话先暂停。请先确认你现在是否安全，并优先联系身边可信任的人陪你，或直接拨打 120 / 110。'
            ' 也可以尝试联系北京心理危机研究与干预中心热线：800-810-1117（座机）或 010-8295-1332（手机）。'
            ' 如果你愿意，只回复我“安全”或“不安全”也可以。'
        )
    return (
        '我先停下普通对话。你刚才提到的内容涉及可能的紧急风险。'
        ' 如果你现在有立刻伤害自己或他人的打算，请不要独处，马上联系身边可信任的人陪你，并立即拨打 120 / 110，或直接前往最近医院急诊。'
        ' 也可以尝试联系北京心理危机研究与干预中心热线：800-810-1117（座机）或 010-8295-1332（手机）。'
        ' 现在如果你愿意，可以只告诉我两个字：“安全”或“不安全”。'
    )


def _count_unique_matches(text: str, patterns: list[str]) -> int:
    matches = set()
    for pattern in patterns:
        found = re.findall(pattern, text)
        if not found:
            continue
        for item in found:
            if isinstance(item, tuple):
                token = ''.join(part for part in item if part)
            else:
                token = str(item)
            if token:
                matches.add(token)
    return len(matches)
