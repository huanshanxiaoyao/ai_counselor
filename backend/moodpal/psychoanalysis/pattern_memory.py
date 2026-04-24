from __future__ import annotations

from typing import Any

from django.utils import timezone

from ..models import MoodPalSession


THEME_HYPOTHESIS_MAP = {
    'authority_tension': '在被评价或面对权威时容易先收紧自己',
    'self_blame_under_relationship_stress': '关系一紧张时容易先把问题收到自己身上',
    'hiding_to_avoid_evaluation': '感觉会被看见或被评价时容易退回去保护自己',
    'rejection_alarm': '一感到可能被冷落或否定时会迅速警觉和自我收缩',
    'repetition_pattern_present': '某类相似情境会反复触发旧的紧张反应',
}

DEFENSE_HYPOTHESIS_MAP = {
    'intellectualization': '会先用讲道理的方式拉开和感受之间的距离',
    'minimization': '会先把自己受影响的程度压小',
    'topic_shift': '一靠近难受处就容易把话题转开',
    'withdrawal': '一感觉压力上来就容易先把自己收回去',
}

RELATIONAL_PULL_HYPOTHESIS_MAP = {
    'approval_seeking': '在关系里容易先确认自己有没有被认可',
    'testing_authority': '面对被理解或被判断的不确定时会先试探对方',
    'withdrawing': '一觉得不安全就容易往后退',
    'dependency_pull': '焦虑升高时会更想立刻得到明确答案',
}


def _as_unique_list(value: Any, *, allowed: set[str] | None = None) -> list[str]:
    items = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or '').strip()
        if not text:
            continue
        if allowed is not None and text not in allowed:
            continue
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(0.95, confidence))


def build_psychoanalysis_memory(session: MoodPalSession) -> dict[str, Any]:
    if session.persona_id != MoodPalSession.Persona.INSIGHT_MENTOR:
        return {}

    state = dict((session.metadata or {}).get('psychoanalysis_state') or {})
    if not state:
        return {}

    repetition_themes = _as_unique_list(
        state.get('repetition_theme_candidate'),
        allowed=set(THEME_HYPOTHESIS_MAP.keys()),
    )
    defense_patterns = _as_unique_list(
        state.get('active_defense'),
        allowed=set(DEFENSE_HYPOTHESIS_MAP.keys()),
    )
    relational_pull = _as_unique_list(
        state.get('relational_pull'),
        allowed=set(RELATIONAL_PULL_HYPOTHESIS_MAP.keys()),
    )

    working_hypotheses: list[str] = []
    seen_hypotheses: set[str] = set()
    for theme in repetition_themes:
        hypothesis = THEME_HYPOTHESIS_MAP.get(theme, '')
        if hypothesis and hypothesis not in seen_hypotheses:
            working_hypotheses.append(hypothesis)
            seen_hypotheses.add(hypothesis)
    for defense in defense_patterns:
        hypothesis = DEFENSE_HYPOTHESIS_MAP.get(defense, '')
        if hypothesis and hypothesis not in seen_hypotheses:
            working_hypotheses.append(hypothesis)
            seen_hypotheses.add(hypothesis)
    for pull in relational_pull:
        hypothesis = RELATIONAL_PULL_HYPOTHESIS_MAP.get(pull, '')
        if hypothesis and hypothesis not in seen_hypotheses:
            working_hypotheses.append(hypothesis)
            seen_hypotheses.add(hypothesis)

    if not repetition_themes and not defense_patterns and not relational_pull and not working_hypotheses:
        return {}

    confidence = _clamp_confidence(state.get('pattern_confidence'))
    if repetition_themes:
        confidence = max(confidence, 0.65)
    elif defense_patterns or relational_pull:
        confidence = max(confidence, 0.55)

    return {
        'schema_version': 'v1',
        'repetition_themes': repetition_themes,
        'defense_patterns': defense_patterns,
        'relational_pull': relational_pull,
        'working_hypotheses': working_hypotheses[:3],
        'confidence': confidence,
        'source_session_id': str(session.id),
        'updated_at': timezone.now().isoformat(),
    }


def load_recent_pattern_memory(*, session: MoodPalSession, limit: int = 3) -> list[dict[str, Any]]:
    queryset = (
        MoodPalSession.objects.filter(
            usage_subject=session.usage_subject,
            summary_action=MoodPalSession.SummaryAction.SAVED,
        )
        .exclude(pk=session.pk)
        .order_by('-updated_at', '-created_at')
    )

    memories: list[dict[str, Any]] = []
    for item in queryset[:limit]:
        memory = dict((item.metadata or {}).get('psychoanalysis_memory_v1') or {})
        if memory:
            memories.append(memory)
    return memories
