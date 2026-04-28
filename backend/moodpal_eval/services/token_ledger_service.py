from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.moodpal_eval.models import MoodPalEvalRun, MoodPalEvalRunItem, MoodPalEvalTokenLedger


@dataclass(frozen=True)
class EvalUsageRecord:
    scope: str
    provider: str = ''
    model: str = ''
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_label: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


def build_usage_record(
    *,
    scope: str,
    provider: str = '',
    model: str = '',
    usage: dict | Any | None = None,
    request_label: str = '',
    metadata: dict[str, Any] | None = None,
) -> EvalUsageRecord:
    usage_dict = _coerce_usage_dict(usage)
    return EvalUsageRecord(
        scope=scope,
        provider=(provider or '').strip(),
        model=(model or '').strip(),
        prompt_tokens=usage_dict['prompt_tokens'],
        completion_tokens=usage_dict['completion_tokens'],
        total_tokens=usage_dict['total_tokens'],
        request_label=(request_label or '').strip(),
        metadata=dict(metadata or {}),
    )


def sum_usage_records(records: Iterable[EvalUsageRecord], *, scope: str = '') -> int:
    total = 0
    for record in records:
        if scope and record.scope != scope:
            continue
        total += int(record.total_tokens or 0)
    return total


def summarize_usage_records(records: Iterable[EvalUsageRecord], *, scope: str = '') -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    for record in records:
        if scope and record.scope != scope:
            continue
        prompt_tokens += int(record.prompt_tokens or 0)
        completion_tokens += int(record.completion_tokens or 0)
        total_tokens += int(record.total_tokens or 0)
    return {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
    }


def persist_usage_records(*, run: MoodPalEvalRun, run_item: MoodPalEvalRunItem, records: Iterable[EvalUsageRecord]) -> int:
    normalized = [record for record in list(records) if int(record.total_tokens or 0) > 0]
    MoodPalEvalTokenLedger.objects.filter(run_item=run_item).delete()
    if not normalized:
        return 0

    MoodPalEvalTokenLedger.objects.bulk_create(
        [
            MoodPalEvalTokenLedger(
                run=run,
                run_item=run_item,
                scope=record.scope,
                provider=record.provider,
                model=record.model,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
                request_label=record.request_label,
                metadata=dict(record.metadata or {}),
            )
            for record in normalized
        ]
    )
    return len(normalized)


def _coerce_usage_dict(usage: dict | Any | None) -> dict[str, int]:
    if isinstance(usage, dict):
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
    else:
        prompt_tokens = getattr(usage, 'prompt_tokens', 0) if usage is not None else 0
        completion_tokens = getattr(usage, 'completion_tokens', 0) if usage is not None else 0
        total_tokens = getattr(usage, 'total_tokens', 0) if usage is not None else 0
    return {
        'prompt_tokens': _int_value(prompt_tokens),
        'completion_tokens': _int_value(completion_tokens),
        'total_tokens': _int_value(total_tokens),
    }


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
