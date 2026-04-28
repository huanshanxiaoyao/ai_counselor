from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.model_option_service import get_default_selected_model, normalize_selected_model
from backend.moodpal_eval.models import MoodPalEvalCase, MoodPalEvalRun, MoodPalEvalRunItem

MAX_RUN_CASE_COUNT = 20
MAX_TURNS_LIMIT = 40
MAX_CONCURRENCY_LIMIT = 6
MAX_PER_TURN_TIMEOUT_SECONDS = 120
MAX_RUNTIME_SECONDS = 3600
MAX_RETRIES = 3


class EvalRunValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RunCreateInput:
    target_mode: str
    target_persona_id: str
    dataset_split: str
    case_count: int
    patient_model: str = ''
    judge_model: str = ''
    target_model: str = ''
    threshold_score: int = 80
    baseline_run_id: str = ''
    max_turns: int = 20
    concurrency: int = 4
    per_turn_timeout_seconds: int = 45
    max_runtime_seconds: int = 900
    max_retries: int = 1
    name: str = ''


def create_run(*, created_by, payload: RunCreateInput) -> MoodPalEvalRun:
    _validate_payload(payload)
    _ensure_no_running_run()
    selected_cases = _select_cases(payload.dataset_split, payload.case_count)
    if len(selected_cases) < payload.case_count:
        raise EvalRunValidationError('not_enough_cases')

    baseline_run = None
    if payload.baseline_run_id:
        try:
            baseline_run = MoodPalEvalRun.objects.get(
                pk=payload.baseline_run_id,
                status=MoodPalEvalRun.Status.COMPLETED,
            )
        except MoodPalEvalRun.DoesNotExist as exc:
            raise EvalRunValidationError('baseline_run_not_found') from exc

    name = payload.name.strip() or _default_run_name(payload)
    with transaction.atomic():
        run = MoodPalEvalRun.objects.create(
            name=name,
            status=MoodPalEvalRun.Status.PENDING,
            target_mode=payload.target_mode,
            target_persona_id=payload.target_persona_id,
            dataset_split=payload.dataset_split,
            selected_case_count=payload.case_count,
            patient_model=normalize_selected_model(payload.patient_model or get_default_selected_model()),
            judge_model=normalize_selected_model(payload.judge_model or get_default_selected_model()),
            target_model=normalize_selected_model(payload.target_model or get_default_selected_model()),
            threshold_score=payload.threshold_score,
            baseline_run=baseline_run,
            max_turns=payload.max_turns,
            concurrency=payload.concurrency,
            per_turn_timeout_seconds=payload.per_turn_timeout_seconds,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_retries=payload.max_retries,
            created_by=created_by,
            metadata={'created_via': 'ops_page'},
        )
        MoodPalEvalRunItem.objects.bulk_create([MoodPalEvalRunItem(run=run, case=case) for case in selected_cases])
    return run


def list_available_splits() -> list[str]:
    return [item['value'] for item in list_split_options() if item['value']]


def list_split_options() -> list[dict]:
    counts: dict[str, int] = {}
    queryset = MoodPalEvalCase.objects.filter(enabled=True).only('splits')
    total_count = queryset.count()
    for case in queryset:
        for item in list(case.splits or []):
            value = str(item or '').strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
    options = [{'value': '', 'label': f'全部已启用样本 ({total_count})', 'count': total_count}]
    for split in sorted(counts):
        options.append({'value': split, 'label': f'{split} ({counts[split]})', 'count': counts[split]})
    return options


def get_run(run_id) -> MoodPalEvalRun:
    return MoodPalEvalRun.objects.select_related('baseline_run', 'created_by').get(pk=run_id)


def get_run_item(item_id) -> MoodPalEvalRunItem:
    return MoodPalEvalRunItem.objects.select_related('run', 'case', 'run__baseline_run').get(pk=item_id)


def list_runs():
    return MoodPalEvalRun.objects.select_related('baseline_run', 'created_by').order_by('-created_at', '-id')


def list_completed_runs():
    return MoodPalEvalRun.objects.filter(status=MoodPalEvalRun.Status.COMPLETED).order_by('-created_at', '-id')


def has_running_run() -> bool:
    return MoodPalEvalRun.objects.filter(status=MoodPalEvalRun.Status.RUNNING).exists()


def mark_run_running(run: MoodPalEvalRun) -> MoodPalEvalRun:
    with transaction.atomic():
        locked = MoodPalEvalRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != MoodPalEvalRun.Status.PENDING:
            raise EvalRunValidationError('run_not_pending')
        if MoodPalEvalRun.objects.filter(status=MoodPalEvalRun.Status.RUNNING).exclude(pk=locked.pk).exists():
            raise EvalRunValidationError('another_run_running')
        locked.status = MoodPalEvalRun.Status.RUNNING
        locked.started_at = timezone.now()
        locked.save(update_fields=['status', 'started_at', 'updated_at'])
        return locked


def mark_run_completed(run: MoodPalEvalRun) -> MoodPalEvalRun:
    run.status = MoodPalEvalRun.Status.COMPLETED
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'finished_at', 'updated_at'])
    return run


def mark_run_failed(run: MoodPalEvalRun, *, reason: str) -> MoodPalEvalRun:
    run.status = MoodPalEvalRun.Status.FAILED
    run.finished_at = timezone.now()
    run.gate_passed = False
    run.gate_failure_reason = reason
    run.save(update_fields=['status', 'finished_at', 'gate_passed', 'gate_failure_reason', 'updated_at'])
    return run


def _validate_payload(payload: RunCreateInput):
    if payload.case_count <= 0:
        raise EvalRunValidationError('invalid_case_count')
    if payload.case_count > MAX_RUN_CASE_COUNT:
        raise EvalRunValidationError('case_count_exceeded')
    if payload.target_mode not in [MoodPalEvalRun.TargetMode.MASTER_GUIDE, MoodPalEvalRun.TargetMode.SINGLE_ROLE]:
        raise EvalRunValidationError('invalid_target_mode')
    if payload.threshold_score < 0 or payload.threshold_score > 100:
        raise EvalRunValidationError('invalid_threshold_score')
    if payload.max_turns <= 0 or payload.max_turns > MAX_TURNS_LIMIT:
        raise EvalRunValidationError('invalid_max_turns')
    if payload.concurrency <= 0 or payload.concurrency > MAX_CONCURRENCY_LIMIT:
        raise EvalRunValidationError('invalid_concurrency')
    if payload.per_turn_timeout_seconds <= 0 or payload.per_turn_timeout_seconds > MAX_PER_TURN_TIMEOUT_SECONDS:
        raise EvalRunValidationError('invalid_per_turn_timeout')
    if payload.max_runtime_seconds <= 0 or payload.max_runtime_seconds > MAX_RUNTIME_SECONDS:
        raise EvalRunValidationError('invalid_max_runtime')
    if payload.max_retries < 0 or payload.max_retries > MAX_RETRIES:
        raise EvalRunValidationError('invalid_max_retries')

    persona_values = {choice[0] for choice in MoodPalSession.Persona.choices}
    if payload.target_persona_id not in persona_values:
        raise EvalRunValidationError('invalid_target_persona')
    if payload.target_mode == MoodPalEvalRun.TargetMode.MASTER_GUIDE and payload.target_persona_id != MoodPalSession.Persona.MASTER_GUIDE:
        raise EvalRunValidationError('master_guide_persona_required')
    if payload.target_mode == MoodPalEvalRun.TargetMode.SINGLE_ROLE and payload.target_persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        raise EvalRunValidationError('single_role_persona_required')


def _ensure_no_running_run():
    if has_running_run():
        raise EvalRunValidationError('run_already_running')


def _select_cases(dataset_split: str, case_count: int) -> list[MoodPalEvalCase]:
    queryset = MoodPalEvalCase.objects.filter(enabled=True).order_by('case_id')
    if not dataset_split:
        return list(queryset[:case_count])
    selected = []
    for case in queryset:
        if dataset_split in list(case.splits or []):
            selected.append(case)
        if len(selected) >= case_count:
            break
    return selected


def _default_run_name(payload: RunCreateInput) -> str:
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    suffix = payload.dataset_split or 'default'
    return f'{payload.target_persona_id}-{suffix}-{stamp}'
