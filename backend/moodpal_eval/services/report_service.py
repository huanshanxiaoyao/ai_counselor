from __future__ import annotations

from backend.moodpal_eval.models import MoodPalEvalRun, MoodPalEvalRunItem


SCORABLE_STATUSES = [MoodPalEvalRunItem.Status.COMPLETED, MoodPalEvalRunItem.Status.FAILED]


def rebuild_run_report(run: MoodPalEvalRun) -> MoodPalEvalRun:
    items = list(run.items.select_related('case').order_by('created_at', 'id'))
    scored_items = [item for item in items if item.status in SCORABLE_STATUSES]
    runtime_summaries = {str(item.id): dict((item.metadata or {}).get('target_runtime_summary') or {}) for item in items}
    completed_count = sum(1 for item in items if item.status == MoodPalEvalRunItem.Status.COMPLETED)
    failed_count = sum(1 for item in items if item.status == MoodPalEvalRunItem.Status.FAILED)
    errored_count = sum(1 for item in items if item.status == MoodPalEvalRunItem.Status.ERRORED)
    hard_fail_count = sum(1 for item in items if item.hard_fail)
    processed_count = completed_count + failed_count + errored_count
    overall_avg = round(sum(item.final_score for item in scored_items) / len(scored_items), 2) if scored_items else 0.0
    pass_rate = round((completed_count / len(items)) * 100, 2) if items else 0.0
    total_token_usage = sum(int(item.total_token_usage or 0) for item in items)
    total_target_turn_count = sum(int(runtime_summaries[str(item.id)].get('target_turn_count') or 0) for item in items)
    llm_failure_fallback_case_count = sum(
        1 for item in items if bool(runtime_summaries[str(item.id)].get('used_llm_failure_fallback'))
    )
    llm_failure_fallback_turn_count = sum(
        int(runtime_summaries[str(item.id)].get('llm_failure_fallback_turn_count') or 0) for item in items
    )
    json_mode_degraded_case_count = sum(
        1 for item in items if bool(runtime_summaries[str(item.id)].get('used_json_mode_degraded'))
    )
    json_mode_degraded_turn_count = sum(
        int(runtime_summaries[str(item.id)].get('json_mode_degraded_turn_count') or 0) for item in items
    )
    clean_items = [item for item in items if not runtime_summaries[str(item.id)].get('used_llm_failure_fallback')]
    clean_scored_items = [item for item in clean_items if item.status in SCORABLE_STATUSES]
    clean_completed_count = sum(1 for item in clean_items if item.status == MoodPalEvalRunItem.Status.COMPLETED)
    clean_overall_avg = (
        round(sum(item.final_score for item in clean_scored_items) / len(clean_scored_items), 2)
        if clean_scored_items
        else None
    )
    clean_pass_rate = round((clean_completed_count / len(clean_items)) * 100, 2) if clean_items else None

    top_failed = [
        {
            'item_id': str(item.id),
            'case_id': item.case.case_id,
            'final_score': item.final_score,
            'status': item.status,
            'hard_fail': item.hard_fail,
        }
        for item in sorted(
            [item for item in items if item.status in [MoodPalEvalRunItem.Status.FAILED, MoodPalEvalRunItem.Status.ERRORED]],
            key=lambda current: (current.final_score, current.created_at),
        )[:5]
    ]

    summary_metrics = {
        'overall_avg_score': overall_avg,
        'hard_fail_count': hard_fail_count,
        'completed_count': completed_count,
        'failed_count': failed_count,
        'errored_count': errored_count,
        'processed_count': processed_count,
        'total_items': len(items),
        'pass_rate': pass_rate,
        'total_token_usage': total_token_usage,
        'target_turn_count': total_target_turn_count,
        'llm_failure_fallback_case_count': llm_failure_fallback_case_count,
        'llm_failure_fallback_turn_count': llm_failure_fallback_turn_count,
        'llm_failure_fallback_case_ratio': round((llm_failure_fallback_case_count / len(items)) * 100, 2) if items else 0.0,
        'llm_failure_fallback_turn_ratio': round((llm_failure_fallback_turn_count / total_target_turn_count) * 100, 2)
        if total_target_turn_count
        else 0.0,
        'json_mode_degraded_case_count': json_mode_degraded_case_count,
        'json_mode_degraded_turn_count': json_mode_degraded_turn_count,
        'json_mode_degraded_case_ratio': round((json_mode_degraded_case_count / len(items)) * 100, 2) if items else 0.0,
        'json_mode_degraded_turn_ratio': round((json_mode_degraded_turn_count / total_target_turn_count) * 100, 2)
        if total_target_turn_count
        else 0.0,
        'clean_total_items': len(clean_items),
        'clean_completed_count': clean_completed_count,
        'clean_overall_avg_score': clean_overall_avg,
        'clean_pass_rate': clean_pass_rate,
        'top_failed_items': top_failed,
    }

    gate_reasons = []
    gate_passed = True
    if errored_count > 0:
        gate_passed = False
        gate_reasons.append('errored_items_present')
    if hard_fail_count > 0:
        gate_passed = False
        gate_reasons.append('hard_fail_items_present')
    if overall_avg < float(run.threshold_score or 0):
        gate_passed = False
        gate_reasons.append('below_threshold')

    baseline_score = None
    if run.baseline_run_id:
        baseline_score = float((run.baseline_run.summary_metrics or {}).get('overall_avg_score') or 0)
        if baseline_score > 0 and overall_avg < round(baseline_score * 0.95, 2):
            gate_passed = False
            gate_reasons.append('below_baseline_95pct')

    summary_metrics['baseline_score'] = baseline_score
    run.summary_metrics = summary_metrics
    run.gate_passed = gate_passed
    run.gate_failure_reason = ','.join(gate_reasons)
    run.save(update_fields=['summary_metrics', 'gate_passed', 'gate_failure_reason', 'updated_at'])
    return run
