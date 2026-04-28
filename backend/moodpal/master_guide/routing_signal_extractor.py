from __future__ import annotations

from .state import MasterGuideState


HIGH_DISTRESS_TERMS = (
    '崩溃',
    '撑不住',
    '受不了',
    '很难受',
    '痛苦',
    '压得',
    '喘不过气',
    '委屈',
    '想哭',
)

REPAIR_TERMS = (
    '你根本不懂',
    '你没懂',
    '别分析',
    '别再分析',
    '套模板',
    '没用',
    '别讲道理',
    '烦',
    '不是这个意思',
)

ACTION_TERMS = (
    '怎么办',
    '怎么做',
    '接下来',
    '我该',
    '要不要',
    '怎么处理',
    '怎么应对',
    '怎么说',
    '怎么解决',
)

PATTERN_TERMS = (
    '总是',
    '每次',
    '一直',
    '反复',
    '又会',
    '老是',
    '老这样',
)

PROBLEM_CONTEXT_TERMS = (
    '工作',
    '老板',
    '同事',
    '开会',
    '考试',
    '项目',
    '关系',
    '家里',
    '对象',
    '面试',
    '消息',
    '回复',
)

WHY_PATTERN_TERMS = (
    '为什么我总',
    '为什么每次',
    '我是不是总',
    '又这样',
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    source = text or ''
    return any(term in source for term in terms)


def _level_from_score(score: int) -> str:
    if score >= 3:
        return 'high'
    if score >= 1:
        return 'medium'
    return 'low'


def extract_master_guide_routing_signals(state: MasterGuideState) -> dict:
    text = (state.get('last_user_message') or '').strip()
    cbt_state = dict(state.get('cbt_state') or {})
    psycho_state = dict(state.get('psychoanalysis_state') or {})
    humanistic_state = dict(state.get('humanistic_state') or {})
    history_messages = list(state.get('history_messages') or [])
    assistant_turns = [msg for msg in history_messages if msg.get('role') == 'assistant']

    distress_score = 0
    if _contains_any(text, HIGH_DISTRESS_TERMS):
        distress_score += 2
    if '！' in text or '...' in text:
        distress_score += 1
    if int(humanistic_state.get('emotional_intensity') or 0) >= 7:
        distress_score += 1

    repair_needed = _contains_any(text, REPAIR_TERMS)
    if humanistic_state.get('alliance_rupture_detected') or psycho_state.get('alliance_rupture_detected'):
        repair_needed = True

    problem_score = 0
    if _contains_any(text, PROBLEM_CONTEXT_TERMS):
        problem_score += 1
    if _contains_any(text, ACTION_TERMS):
        problem_score += 1
    if len(text) >= 18:
        problem_score += 1

    action_score = 0
    if _contains_any(text, ACTION_TERMS):
        action_score += 2
    if cbt_state.get('agenda_locked'):
        action_score += 1
    if cbt_state.get('activation_step') or cbt_state.get('task_first_step'):
        action_score += 1

    pattern_score = 0
    if _contains_any(text, PATTERN_TERMS):
        pattern_score += 2
    if _contains_any(text, WHY_PATTERN_TERMS):
        pattern_score += 1
    if cbt_state.get('repeated_theme_detected'):
        pattern_score += 1
    if str(psycho_state.get('repetition_theme_candidate') or '').strip():
        pattern_score += 1
    if float(psycho_state.get('pattern_confidence') or 0.0) >= 0.6:
        pattern_score += 1

    alliance_status = 'medium'
    if repair_needed or humanistic_state.get('relational_trust') == 'weak' or psycho_state.get('alliance_strength') == 'weak':
        alliance_status = 'weak'
    elif psycho_state.get('alliance_strength') == 'strong' or humanistic_state.get('relational_trust') == 'strong':
        alliance_status = 'strong'

    psychoanalysis_readiness_score = 0
    if pattern_score >= 2:
        psychoanalysis_readiness_score += 1
    if len(assistant_turns) >= 1:
        psychoanalysis_readiness_score += 1
    if state.get('last_summary'):
        psychoanalysis_readiness_score += 1
    if alliance_status == 'strong':
        psychoanalysis_readiness_score += 1

    cbt_readiness_score = 0
    if problem_score >= 2:
        cbt_readiness_score += 1
    if action_score >= 2:
        cbt_readiness_score += 1
    if not repair_needed:
        cbt_readiness_score += 1

    recent_track_progress = 'none'
    if cbt_state.get('last_progress_marker') or psycho_state.get('last_progress_marker'):
        recent_track_progress = 'progress'
    if cbt_state.get('circuit_breaker_open') or psycho_state.get('circuit_breaker_open'):
        recent_track_progress = 'stall'

    return {
        'alliance_status': alliance_status,
        'distress_level': _level_from_score(distress_score),
        'problem_clarity': _level_from_score(problem_score),
        'action_readiness': _level_from_score(action_score),
        'pattern_signal_strength': _level_from_score(pattern_score),
        'psychoanalysis_readiness': _level_from_score(psychoanalysis_readiness_score),
        'cbt_readiness': _level_from_score(cbt_readiness_score),
        'repair_needed': repair_needed,
        'recent_track_progress': recent_track_progress,
        'assistant_turn_count': len(assistant_turns),
    }
