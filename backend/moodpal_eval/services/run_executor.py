from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from backend.moodpal.models import MoodPalSession
from backend.moodpal_eval.models import MoodPalEvalRun, MoodPalEvalRunItem

from .judge_service import audit_route, evaluate_transcript
from .patient_agent_service import PatientAgentTurnResult, build_opening_user_message, generate_patient_reply
from .report_service import rebuild_run_report
from .run_service import EvalRunValidationError, get_run, mark_run_completed, mark_run_failed, mark_run_running
from .score_aggregation_service import aggregate_item_scores
from .target_driver import EvalTargetSessionContext, EvalTargetTurnResult, run_target_turn
from .token_ledger_service import EvalUsageRecord, persist_usage_records, sum_usage_records


LLM_FAILURE_FALLBACK_KINDS = {'llm_local_rule', 'system_fallback'}


@dataclass
class EvalConversationState:
    session_context: EvalTargetSessionContext
    transcript: list[dict] = field(default_factory=list)
    target_trace: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class EvalConversationResult:
    transcript: list[dict]
    target_trace: list[dict]
    stop_reason: str
    target_turn_count: int
    patient_turn_summaries: list[dict] = field(default_factory=list)
    target_usage_records: list[EvalUsageRecord] = field(default_factory=list)
    patient_usage_records: list[EvalUsageRecord] = field(default_factory=list)
    target_token_usage: int = 0
    patient_token_usage: int = 0


def append_target_turn(state: EvalConversationState, *, user_content: str) -> EvalTargetTurnResult:
    turn_result = run_target_turn(
        session_context=state.session_context,
        transcript=state.transcript,
        user_content=user_content,
    )
    state.transcript = list(turn_result.transcript)
    state.target_trace.extend(turn_result.target_trace)
    return turn_result


def run_case_conversation(
    *,
    case,
    target_persona_id: str,
    target_model: str = '',
    patient_model: str = '',
    max_turns: int = 20,
    usage_subject: str = 'system_eval:single_case',
) -> EvalConversationResult:
    if max_turns <= 0:
        raise ValueError('invalid_max_turns')

    state = EvalConversationState(
        session_context=EvalTargetSessionContext(
            persona_id=target_persona_id,
            usage_subject=usage_subject,
            selected_model=target_model,
            status=MoodPalSession.Status.ACTIVE,
        )
    )
    patient_turn_summaries: list[dict] = []
    target_usage_records: list[EvalUsageRecord] = []
    patient_usage_records: list[EvalUsageRecord] = []
    target_turn_count = 0
    target_token_usage = 0
    patient_token_usage = 0

    opening_message = build_opening_user_message(case)
    target_result = append_target_turn(state, user_content=opening_message)
    target_usage_records.extend(list(getattr(target_result, 'usage_records', None) or []))
    target_turn_count += 1
    target_token_usage += sum_usage_records(getattr(target_result, 'usage_records', None) or [])
    if target_result.safety_override:
        return EvalConversationResult(
            transcript=list(state.transcript),
            target_trace=list(state.target_trace),
            stop_reason=target_result.stop_reason or 'safety_override',
            target_turn_count=target_turn_count,
            patient_turn_summaries=patient_turn_summaries,
            target_usage_records=target_usage_records,
            patient_usage_records=patient_usage_records,
            target_token_usage=target_token_usage,
            patient_token_usage=patient_token_usage,
        )

    while target_turn_count < max_turns:
        patient_turn = generate_patient_reply(
            case=case,
            transcript=state.transcript,
            target_persona_id=target_persona_id,
            selected_model=patient_model,
        )
        patient_turn_summaries.append(_serialize_patient_turn(patient_turn))
        patient_usage_records.extend(list(getattr(patient_turn, 'usage_records', None) or []))
        patient_token_usage += int((patient_turn.usage or {}).get('total_tokens') or 0)
        if not patient_turn.should_continue:
            return EvalConversationResult(
                transcript=list(state.transcript),
                target_trace=list(state.target_trace),
                stop_reason=patient_turn.stop_reason or 'patient_stop',
                target_turn_count=target_turn_count,
                patient_turn_summaries=patient_turn_summaries,
                target_usage_records=target_usage_records,
                patient_usage_records=patient_usage_records,
                target_token_usage=target_token_usage,
                patient_token_usage=patient_token_usage,
            )
        if not patient_turn.reply_text.strip():
            return EvalConversationResult(
                transcript=list(state.transcript),
                target_trace=list(state.target_trace),
                stop_reason='patient_empty_reply',
                target_turn_count=target_turn_count,
                patient_turn_summaries=patient_turn_summaries,
                target_usage_records=target_usage_records,
                patient_usage_records=patient_usage_records,
                target_token_usage=target_token_usage,
                patient_token_usage=patient_token_usage,
            )

        target_result = append_target_turn(state, user_content=patient_turn.reply_text)
        target_usage_records.extend(list(getattr(target_result, 'usage_records', None) or []))
        target_turn_count += 1
        target_token_usage += sum_usage_records(getattr(target_result, 'usage_records', None) or [])
        if target_result.safety_override:
            return EvalConversationResult(
                transcript=list(state.transcript),
                target_trace=list(state.target_trace),
                stop_reason=target_result.stop_reason or 'safety_override',
                target_turn_count=target_turn_count,
                patient_turn_summaries=patient_turn_summaries,
                target_usage_records=target_usage_records,
                patient_usage_records=patient_usage_records,
                target_token_usage=target_token_usage,
                patient_token_usage=patient_token_usage,
            )

    return EvalConversationResult(
        transcript=list(state.transcript),
        target_trace=list(state.target_trace),
        stop_reason='max_turns',
        target_turn_count=target_turn_count,
        patient_turn_summaries=patient_turn_summaries,
        target_usage_records=target_usage_records,
        patient_usage_records=patient_usage_records,
        target_token_usage=target_token_usage,
        patient_token_usage=patient_token_usage,
    )


def execute_run(run_id: str) -> MoodPalEvalRun:
    run = get_run(run_id)
    try:
        run = mark_run_running(run)
    except EvalRunValidationError as exc:
        run.refresh_from_db()
        if str(exc) == 'run_not_pending':
            return run
        return mark_run_failed(run, reason=str(exc))

    item_ids = list(run.items.order_by('created_at', 'id').values_list('id', flat=True))
    if not item_ids:
        return mark_run_failed(run, reason='no_run_items')

    try:
        with ThreadPoolExecutor(max_workers=max(1, min(run.concurrency, len(item_ids)))) as executor:
            futures = [executor.submit(execute_run_item, str(item_id)) for item_id in item_ids]
            for future in as_completed(futures):
                future.result()
        run.refresh_from_db()
        rebuild_run_report(run)
        return mark_run_completed(run)
    except Exception as exc:
        run.refresh_from_db()
        return mark_run_failed(run, reason=f'run_executor_failed:{exc.__class__.__name__}')


def execute_run_item(run_item_id: str) -> MoodPalEvalRunItem:
    with transaction.atomic():
        item = MoodPalEvalRunItem.objects.select_for_update().select_related('run', 'case').get(pk=run_item_id)
        if item.status != MoodPalEvalRunItem.Status.PENDING:
            return item
        item.status = MoodPalEvalRunItem.Status.RUNNING
        item.started_at = timezone.now()
        item.save(update_fields=['status', 'started_at', 'updated_at'])

    try:
        item.refresh_from_db()
        conversation = run_case_conversation(
            case=item.case,
            target_persona_id=item.run.target_persona_id,
            target_model=item.run.target_model,
            patient_model=item.run.patient_model,
            max_turns=item.run.max_turns,
            usage_subject=f'system_eval:{item.run_id}:{item.id}',
        )
        transcript_judge = evaluate_transcript(
            case=item.case,
            transcript=conversation.transcript,
            target_mode=item.run.target_mode,
            target_persona_id=item.run.target_persona_id,
            selected_model=item.run.judge_model,
        )
        route_audit = audit_route(
            case=item.case,
            transcript=conversation.transcript,
            target_trace=conversation.target_trace,
            target_mode=item.run.target_mode,
            target_persona_id=item.run.target_persona_id,
            selected_model=item.run.judge_model,
        )
        aggregated = aggregate_item_scores(
            transcript_judge_result=transcript_judge.payload,
            route_audit_result=route_audit.payload,
        )
        usage_records = _collect_usage_records(
            conversation=conversation,
            transcript_judge=transcript_judge,
            route_audit=route_audit,
        )

        item.status = _resolve_run_item_status(item.run.threshold_score, aggregated)
        item.turn_count = conversation.target_turn_count
        item.stop_reason = conversation.stop_reason
        item.transcript = conversation.transcript
        item.target_trace = conversation.target_trace
        item.transcript_judge_result = transcript_judge.payload
        item.route_audit_result = route_audit.payload
        item.final_scores = aggregated['final_scores']
        item.final_score = aggregated['final_score']
        item.hard_fail = aggregated['hard_fail']
        item.deduction_reasons = aggregated['deduction_reasons']
        item.target_token_usage = conversation.target_token_usage
        item.patient_token_usage = conversation.patient_token_usage
        item.judge_token_usage = sum_usage_records(usage_records, scope='judge')
        item.total_token_usage = item.target_token_usage + item.patient_token_usage + item.judge_token_usage
        item.metadata = _build_item_metadata(
            conversation=conversation,
            transcript_judge=transcript_judge,
            route_audit=route_audit,
        )
        item.finished_at = timezone.now()
        item.error_code = ''
        item.error_message = ''
        item.save()
        persist_usage_records(run=item.run, run_item=item, records=usage_records)
        return item
    except Exception as exc:
        item.refresh_from_db()
        item.status = MoodPalEvalRunItem.Status.ERRORED
        item.error_code = exc.__class__.__name__
        item.error_message = str(exc)
        item.finished_at = timezone.now()
        item.save(update_fields=['status', 'error_code', 'error_message', 'finished_at', 'updated_at'])
        return item


def _build_item_metadata(*, conversation: EvalConversationResult, transcript_judge, route_audit) -> dict:
    target_runtime_summary = _summarize_target_runtime(conversation.target_trace)
    return {
        'target_runtime_summary': target_runtime_summary,
        'patient_turn_summaries': conversation.patient_turn_summaries,
        'transcript_judge_meta': {
            'provider': transcript_judge.provider,
            'model': transcript_judge.model,
            'usage': transcript_judge.usage,
            'used_repair': transcript_judge.used_repair,
            'summary': transcript_judge.payload.get('summary', ''),
        },
        'route_audit_meta': {
            'provider': route_audit.provider,
            'model': route_audit.model,
            'usage': route_audit.usage,
            'used_repair': route_audit.used_repair,
            'summary': route_audit.payload.get('summary', ''),
        },
    }


def _summarize_target_runtime(target_trace: list[dict]) -> dict:
    turns = list(target_trace or [])
    turn_count = len(turns)
    fallback_kinds = [str(turn.get('fallback_kind') or '') for turn in turns]
    llm_failure_fallback_turn_count = sum(1 for kind in fallback_kinds if kind in LLM_FAILURE_FALLBACK_KINDS)
    json_mode_degraded_turn_count = sum(1 for turn in turns if bool(turn.get('json_mode_degraded')))
    fallback_used_turn_count = sum(1 for turn in turns if bool(turn.get('fallback_used')))
    system_fallback_turn_count = sum(1 for kind in fallback_kinds if kind == 'system_fallback')
    local_rule_fallback_turn_count = sum(1 for kind in fallback_kinds if kind == 'llm_local_rule')

    return {
        'target_turn_count': turn_count,
        'fallback_used_turn_count': fallback_used_turn_count,
        'llm_failure_fallback_turn_count': llm_failure_fallback_turn_count,
        'llm_local_rule_fallback_turn_count': local_rule_fallback_turn_count,
        'system_fallback_turn_count': system_fallback_turn_count,
        'json_mode_degraded_turn_count': json_mode_degraded_turn_count,
        'used_llm_failure_fallback': llm_failure_fallback_turn_count > 0,
        'used_json_mode_degraded': json_mode_degraded_turn_count > 0,
        'llm_failure_fallback_kinds': sorted({kind for kind in fallback_kinds if kind in LLM_FAILURE_FALLBACK_KINDS}),
        'llm_failure_fallback_turn_ratio': round((llm_failure_fallback_turn_count / turn_count), 4) if turn_count else 0.0,
        'json_mode_degraded_turn_ratio': round((json_mode_degraded_turn_count / turn_count), 4) if turn_count else 0.0,
    }


def _serialize_patient_turn(result: PatientAgentTurnResult) -> dict:
    return {
        'should_continue': result.should_continue,
        'stop_reason': result.stop_reason,
        'affect_signal': result.affect_signal,
        'resistance_level': result.resistance_level,
        'provider': result.provider,
        'model': result.model,
        'usage': dict(result.usage or {}),
        'used_repair': result.used_repair,
        'reply_preview': result.reply_text[:120],
    }


def _collect_usage_records(*, conversation: EvalConversationResult, transcript_judge, route_audit) -> list[EvalUsageRecord]:
    return [
        *list(conversation.target_usage_records or []),
        *list(conversation.patient_usage_records or []),
        *list(transcript_judge.usage_records or []),
        *list(route_audit.usage_records or []),
    ]


def _resolve_run_item_status(threshold_score: int, aggregated: dict) -> str:
    if aggregated['hard_fail']:
        return MoodPalEvalRunItem.Status.FAILED
    if float(aggregated['final_score']) < float(threshold_score or 0):
        return MoodPalEvalRunItem.Status.FAILED
    return MoodPalEvalRunItem.Status.COMPLETED
