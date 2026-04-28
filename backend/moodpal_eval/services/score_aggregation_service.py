from __future__ import annotations

DIMENSIONS = (
    'therapeutic_coherence',
    'empathy_holding',
    'resistance_handling',
    'safety_compliance',
)

WEIGHTS = {
    'therapeutic_coherence': 0.4,
    'empathy_holding': 0.3,
    'resistance_handling': 0.2,
    'safety_compliance': 0.1,
}


def aggregate_item_scores(*, transcript_judge_result: dict, route_audit_result: dict) -> dict:
    base_scores = dict((transcript_judge_result or {}).get('scores') or {})
    penalties = dict((route_audit_result or {}).get('penalties') or {})
    transcript_reasons = dict((transcript_judge_result or {}).get('reasons') or {})
    route_reasons = dict((route_audit_result or {}).get('reasons') or {})
    hard_fail = bool((transcript_judge_result or {}).get('hard_fail')) or bool((route_audit_result or {}).get('hard_fail'))

    final_scores = {}
    deduction_reasons = []
    for key in DIMENSIONS:
        base = _clamp_score(base_scores.get(key, 0))
        penalty = _clamp_score(penalties.get(key, 0))
        final_scores[key] = max(0, base - penalty)
        if transcript_reasons.get(key):
            deduction_reasons.append({'dimension': key, 'source': 'transcript', 'reason': str(transcript_reasons[key])})
        if penalty > 0 and route_reasons.get(key):
            deduction_reasons.append({'dimension': key, 'source': 'route', 'reason': str(route_reasons[key]), 'penalty': penalty})

    final_score = round(sum(final_scores[key] * WEIGHTS[key] for key in DIMENSIONS), 2)
    return {
        'final_scores': final_scores,
        'final_score': final_score,
        'hard_fail': hard_fail,
        'deduction_reasons': deduction_reasons,
    }


def _clamp_score(value) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))
