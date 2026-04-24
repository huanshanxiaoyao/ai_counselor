from __future__ import annotations

from . import router_config
from .state import PsychoanalysisGraphState


DEFENSE_PATTERN_HINTS = {
    'intellectualization': ('理智上我知道', '其实也没什么', '应该没什么吧', '讲这个也没意义'),
    'minimization': ('没什么大不了', '也就那样', '没事'),
    'topic_shift': ('顺便', '另外', '算了换个话题', '不说这个了'),
    'withdrawal': ('不想说了', '算了', '到此为止', '我先不聊了'),
}

RELATIONAL_PULL_HINTS = {
    'approval_seeking': ('你觉得我是不是', '你会不会觉得我', '你是不是也觉得我'),
    'testing_authority': ('你凭什么这么说', '你是不是在评判我', '你怎么知道'),
    'withdrawing': ('不想跟你说了', '算了不讲了', '我收回'),
    'dependency_pull': ('你告诉我怎么办', '你替我决定', '你直接给我答案'),
}

PATTERN_THEME_HINTS = {
    'authority_tension': ('老板', '领导', '上级', '老师', '权威'),
    'self_blame_under_relationship_stress': ('都是我的错', '先怪自己', '是不是我不够好'),
    'hiding_to_avoid_evaluation': ('缩起来', '躲起来', '藏起来', '不想被看见'),
    'rejection_alarm': ('别人一不高兴', '一冷淡', '不回我', '语气一重'),
}


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    source = (text or '').strip()
    if not source:
        return False
    return any(token in source for token in hints)


def _infer_association_openness(text: str, *, resistance_spike: bool, alliance_rupture: bool, containment_needed: bool) -> str:
    if alliance_rupture or resistance_spike or containment_needed:
        return 'guarded'
    if len((text or '').strip()) >= 40 or any(token in text for token in ('我发现', '其实', '每次', '不只是这次', '好像')):
        return 'open'
    return 'partial'


def _infer_active_defense(text: str) -> str:
    for label, hints in DEFENSE_PATTERN_HINTS.items():
        if _contains_any(text, hints):
            return label
    return ''


def _infer_relational_pull(text: str, *, advice_pull: bool, alliance_rupture: bool) -> str:
    if advice_pull:
        return 'dependency_pull'
    if alliance_rupture:
        return 'testing_authority'
    for label, hints in RELATIONAL_PULL_HINTS.items():
        if _contains_any(text, hints):
            return label
    return ''


def _infer_manifest_theme(text: str) -> str:
    cleaned = ' '.join((text or '').split())
    if not cleaned:
        return ''
    return cleaned[:60].rstrip() + '...' if len(cleaned) > 60 else cleaned


def _infer_repetition_theme(text: str, recalled_pattern_memory: list[dict]) -> tuple[str, float]:
    for label, hints in PATTERN_THEME_HINTS.items():
        if _contains_any(text, hints):
            return label, 0.72

    for memory in recalled_pattern_memory:
        for theme in memory.get('repetition_themes') or []:
            if theme and (_contains_any(text, tuple(theme.split('_'))) or '每次' in text or '总是' in text or '不只是这次' in text):
                return theme, 0.68

    if any(token in text for token in ('每次', '总是', '不只是这次', '又来了', '一直都是')):
        return 'repetition_pattern_present', 0.6
    return '', 0.0


def _infer_containment_needed(text: str, *, alliance_rupture: bool, resistance_spike: bool) -> bool:
    if alliance_rupture or resistance_spike:
        return True
    if _contains_any(text, router_config.CONTAINMENT_HINTS):
        return True
    return any(token in text for token in ('缩起来', '有点怕', '不太敢说', '想躲', '我想收回'))


def _infer_here_and_now(text: str) -> bool:
    return _contains_any(text, router_config.RELATIONAL_HINTS)


def _infer_alliance_strength(existing: str, *, alliance_rupture: bool, resistance_spike: bool, openness: str) -> str:
    if alliance_rupture:
        return 'weak'
    if resistance_spike and openness == 'guarded':
        return 'weak'
    if openness == 'open':
        return 'strong'
    return existing or 'medium'


def _infer_insight_readiness(*, repetition_theme: str, pattern_confidence: float, resistance_level: str, alliance_strength: str) -> bool:
    return bool(repetition_theme) and pattern_confidence >= 0.68 and resistance_level != 'high' and alliance_strength in ['medium', 'strong']


def _infer_emotional_intensity(text: str, *, alliance_rupture: bool, resistance_spike: bool) -> int:
    if not text:
        return 0
    intensity = 4
    if any(token in text for token in ('难受', '僵住', '缩起来', '慌', '怕')):
        intensity = max(intensity, 6)
    if any(token in text for token in ('崩溃', '受不了', '撑不住', '太难受了')):
        intensity = max(intensity, 8)
    if alliance_rupture or resistance_spike:
        intensity = max(intensity, 7)
    return intensity


def extract_psychoanalysis_turn_signals(state: PsychoanalysisGraphState) -> dict:
    user_text = (state.get('last_user_message') or '').strip()
    existing_alliance = str(state.get('alliance_strength') or 'medium')
    recalled = list(state.get('recalled_pattern_memory') or [])

    alliance_rupture = _contains_any(user_text, router_config.ALLIANCE_RUPTURE_HINTS)
    resistance_spike = _contains_any(user_text, router_config.RESISTANCE_SPIKE_HINTS)
    advice_pull = _contains_any(user_text, router_config.ADVICE_PULL_HINTS)
    containment_needed = _infer_containment_needed(
        user_text,
        alliance_rupture=alliance_rupture,
        resistance_spike=resistance_spike,
    )
    openness = _infer_association_openness(
        user_text,
        resistance_spike=resistance_spike,
        alliance_rupture=alliance_rupture,
        containment_needed=containment_needed,
    )
    resistance_level = 'high' if resistance_spike else 'medium' if _contains_any(user_text, router_config.DEFENSE_HINTS) else 'low'
    active_defense = _infer_active_defense(user_text)
    relational_pull = _infer_relational_pull(user_text, advice_pull=advice_pull, alliance_rupture=alliance_rupture)
    manifest_theme = _infer_manifest_theme(user_text)
    repetition_theme, pattern_confidence = _infer_repetition_theme(user_text, recalled)
    if not repetition_theme and state.get('repetition_theme_candidate'):
        repetition_theme = str(state.get('repetition_theme_candidate') or '')
    if pattern_confidence <= 0 and state.get('pattern_confidence'):
        try:
            pattern_confidence = float(state.get('pattern_confidence') or 0.0)
        except (TypeError, ValueError):
            pattern_confidence = 0.0
    here_and_now_triggered = _infer_here_and_now(user_text)
    alliance_strength = _infer_alliance_strength(
        existing_alliance,
        alliance_rupture=alliance_rupture,
        resistance_spike=resistance_spike,
        openness=openness,
    )
    insight_ready = _infer_insight_readiness(
        repetition_theme=repetition_theme,
        pattern_confidence=pattern_confidence,
        resistance_level=resistance_level,
        alliance_strength=alliance_strength,
    )

    return {
        'focus_theme': manifest_theme or state.get('focus_theme', ''),
        'association_openness': openness,
        'manifest_theme': manifest_theme,
        'repetition_theme_candidate': repetition_theme,
        'pattern_confidence': pattern_confidence,
        'insight_ready': insight_ready,
        'interpretation_depth': 'surface',
        'active_defense': active_defense,
        'resistance_level': resistance_level,
        'alliance_strength': alliance_strength,
        'relational_pull': relational_pull,
        'here_and_now_triggered': here_and_now_triggered,
        'containment_needed': containment_needed,
        'emotional_intensity': _infer_emotional_intensity(
            user_text,
            alliance_rupture=alliance_rupture,
            resistance_spike=resistance_spike,
        ),
        'alliance_rupture_detected': alliance_rupture,
        'resistance_spike_detected': resistance_spike,
        'advice_pull_detected': advice_pull,
        'exception_flags': {
            'alliance_rupture_detected': alliance_rupture,
            'resistance_spike_detected': resistance_spike,
            'advice_pull_detected': advice_pull,
        },
    }
