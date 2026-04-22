from __future__ import annotations

from . import router_config
from .state import HumanisticGraphState


GUARDED_HINTS = (
    '不想说',
    '别问了',
    '算了',
    '懒得说',
    '没什么好说',
)

OPEN_HINTS = (
    '其实',
    '我觉得',
    '我发现',
    '好像',
    '最难受的是',
    '我一直',
)

EMOTION_HINTS = {
    '委屈': ('委屈', '不被重视', '不被理解', '憋屈'),
    '失落': ('失落', '落空', '心凉', '很空'),
    '愤怒': ('生气', '愤怒', '火大', '气死', '恼火'),
    '焦虑': ('焦虑', '紧张', '心慌', '发慌', '担心', '不安'),
    '害怕': ('害怕', '怕', '恐惧', '心里发虚'),
    '羞耻': ('羞耻', '丢人', '丢脸', '难堪'),
    '无助': ('无助', '没办法', '做不到', '撑不住'),
    '孤独': ('孤独', '一个人', '没人懂', '没人站我这边'),
    '难过': ('难过', '伤心', '想哭', '低落'),
}

UNMET_NEED_HINTS = {
    '被理解': ('理解我', '懂我', '被看见', '听明白'),
    '安全感': ('安心', '安全感', '稳一点', '别失控'),
    '方向感': ('怎么办', '抓手', '方向', '办法'),
    '被重视': ('被重视', '在意我', '看见我', '回应我'),
    '被支持': ('陪我', '站我这边', '支持我', '接住我'),
}


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    source = (text or '').strip()
    if not source:
        return False
    return any(token in source for token in hints)


def _extract_emotions(text: str) -> list[str]:
    emotions: list[str] = []
    for label, hints in EMOTION_HINTS.items():
        if _contains_any(text, hints):
            emotions.append(label)
    return emotions


def _infer_unmet_need(text: str) -> str:
    for need, hints in UNMET_NEED_HINTS.items():
        if _contains_any(text, hints):
            return need
    return ''


def _infer_intensity(text: str, emotions: list[str], *, self_attack: bool, shame: bool, advice_pull: bool, alliance_rupture: bool) -> int:
    if not (text or '').strip():
        return 0
    intensity = 4
    if '难受' in text or _contains_any(text, router_config.BODY_SIGNAL_HINTS):
        intensity = max(intensity, 6)
    if _contains_any(text, router_config.HIGH_INTENSITY_HINTS):
        intensity = max(intensity, 9)
    if self_attack or shame:
        intensity = max(intensity, 8)
    if alliance_rupture or advice_pull:
        intensity = max(intensity, 7)
    if emotions:
        intensity = max(intensity, 6)
    if '！' in text or '!' in text or '真的' in text or '特别' in text:
        intensity = min(10, intensity + 1)
    return intensity


def _infer_clarity(text: str, emotions: list[str], *, numbness: bool, body_signal: bool) -> str:
    if numbness:
        return 'diffuse'
    if emotions:
        return 'clear'
    if body_signal or '说不上来' in text or '不知道' in text:
        return 'diffuse'
    if len((text or '').strip()) >= 24:
        return 'emerging'
    return 'diffuse'


def _infer_openness(text: str, *, alliance_rupture: bool, advice_pull: bool) -> str:
    if alliance_rupture or advice_pull or _contains_any(text, GUARDED_HINTS):
        return 'guarded'
    if len((text or '').strip()) >= 35 or _contains_any(text, OPEN_HINTS):
        return 'open'
    return 'partial'


def _infer_relational_trust(existing: str, *, alliance_rupture: bool, being_understood: bool, openness_level: str) -> str:
    if alliance_rupture:
        return 'weak'
    if being_understood:
        return 'strong'
    if existing == 'weak' and openness_level in ['partial', 'open']:
        return 'medium'
    return existing or 'medium'


def extract_humanistic_turn_signals(state: HumanisticGraphState) -> dict:
    user_text = (state.get('last_user_message') or '').strip()
    existing_trust = str(state.get('relational_trust') or 'medium')

    alliance_rupture = _contains_any(user_text, router_config.ALLIANCE_RUPTURE_HINTS)
    numbness = _contains_any(user_text, router_config.NUMBNESS_HINTS)
    advice_pull = _contains_any(user_text, router_config.ADVICE_PULL_HINTS)
    self_attack = _contains_any(user_text, router_config.SELF_ATTACK_HINTS)
    shame = _contains_any(user_text, router_config.SHAME_HINTS)
    body_signal = _contains_any(user_text, router_config.BODY_SIGNAL_HINTS)
    being_understood = _contains_any(user_text, router_config.UNDERSTOOD_HINTS)
    emotions = _extract_emotions(user_text)
    unmet_need = _infer_unmet_need(user_text)
    intensity = _infer_intensity(
        user_text,
        emotions,
        self_attack=self_attack,
        shame=shame,
        advice_pull=advice_pull,
        alliance_rupture=alliance_rupture,
    )
    clarity = _infer_clarity(user_text, emotions, numbness=numbness, body_signal=body_signal)
    openness = _infer_openness(user_text, alliance_rupture=alliance_rupture, advice_pull=advice_pull)
    relational_trust = _infer_relational_trust(
        existing_trust,
        alliance_rupture=alliance_rupture,
        being_understood=being_understood,
        openness_level=openness,
    )
    resonance_score = 70 if being_understood else 30 if alliance_rupture else int(state.get('resonance_score') or 0)

    return {
        'emotional_intensity': intensity,
        'dominant_emotions': emotions,
        'emotional_clarity': clarity,
        'openness_level': openness,
        'self_attack_flag': self_attack,
        'shame_signal': shame,
        'body_signal_present': body_signal,
        'body_focus_ready': body_signal and clarity == 'diffuse' and intensity < 9 and not alliance_rupture,
        'being_understood_signal': being_understood,
        'relational_trust': relational_trust,
        'unmet_need_candidate': unmet_need,
        'alliance_rupture_detected': alliance_rupture,
        'numbness_detected': numbness,
        'advice_pull_detected': advice_pull,
        'resonance_score': resonance_score,
        'exception_flags': {
            'alliance_rupture_detected': alliance_rupture,
            'numbness_detected': numbness,
            'advice_pull_detected': advice_pull,
        },
    }
