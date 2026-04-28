from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.model_option_service import get_model_options, normalize_selected_model
from backend.moodpal_eval.models import MoodPalEvalCase
from backend.moodpal_eval.services.run_executor import execute_run
from backend.moodpal_eval.services.run_service import RunCreateInput, create_run, get_run
from backend.moodpal_eval.services.target_driver import EvalTargetSessionContext, run_target_turn


DEFAULT_PATIENT_MODEL = 'qwen:qwen-plus'
DEFAULT_JUDGE_MODEL = 'qwen:qwen-plus'
PREFLIGHT_USER_MESSAGE = '我最近总觉得胸口发紧，明知道该休息，但一停下来就会觉得自己很失败。'


class Command(BaseCommand):
    help = 'Benchmark master_guide against multiple target models on the same MoodPal eval case sample.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target-models',
            default='',
            help='Comma-separated selected models to benchmark. Defaults to all non-openai configured models.',
        )
        parser.add_argument(
            '--dataset-split',
            default='',
            help='Optional eval split filter. Empty means first enabled cases by case_id.',
        )
        parser.add_argument(
            '--case-count',
            type=int,
            default=20,
            help='How many cases to benchmark. Default: 20.',
        )
        parser.add_argument(
            '--patient-model',
            default=DEFAULT_PATIENT_MODEL,
            help='Selected model for the patient agent. Default: qwen:qwen-plus.',
        )
        parser.add_argument(
            '--judge-model',
            default=DEFAULT_JUDGE_MODEL,
            help='Selected model for transcript judge and route audit. Default: qwen:qwen-plus.',
        )
        parser.add_argument(
            '--threshold-score',
            type=int,
            default=80,
            help='Gate threshold score. Default: 80.',
        )
        parser.add_argument(
            '--max-turns',
            type=int,
            default=20,
            help='Max target turns per case. Default: 20.',
        )
        parser.add_argument(
            '--concurrency',
            type=int,
            default=2,
            help='Per-run concurrency. Default: 2.',
        )
        parser.add_argument(
            '--per-turn-timeout-seconds',
            type=int,
            default=45,
            help='Persisted eval field only; execution still follows current LLM_TIMEOUT. Default: 45.',
        )
        parser.add_argument(
            '--max-runtime-seconds',
            type=int,
            default=1800,
            help='Persisted run budget field. Default: 1800.',
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=1,
            help='Persisted run retry field. Default: 1.',
        )
        parser.add_argument(
            '--output',
            default='',
            help='Optional JSON report path.',
        )
        parser.add_argument(
            '--skip-preflight',
            action='store_true',
            help='Skip single-turn real runtime compatibility preflight.',
        )

    def handle(self, *args, **options):
        case_count = int(options['case_count'])
        if case_count <= 0:
            raise CommandError('case_count_must_be_positive')

        target_models = _resolve_target_models(options['target_models'])
        if not target_models:
            raise CommandError('no_target_models_selected')

        patient_model = normalize_selected_model(options['patient_model'])
        judge_model = normalize_selected_model(options['judge_model'])
        dataset_split = (options['dataset_split'] or '').strip()

        sample_cases = _resolve_case_sample(dataset_split=dataset_split, case_count=case_count)
        if len(sample_cases) < case_count:
            raise CommandError(f'not_enough_cases: requested={case_count} actual={len(sample_cases)}')

        sample_case_ids = [case.case_id for case in sample_cases]
        self.stdout.write(
            f'[benchmark] target_models={len(target_models)} case_count={case_count} '
            f'patient={patient_model} judge={judge_model}'
        )
        self.stdout.write(f'[benchmark] sample_cases={",".join(sample_case_ids)}')

        report = {
            'generated_at': datetime.now().isoformat(),
            'target_mode': 'master_guide',
            'target_persona_id': MoodPalSession.Persona.MASTER_GUIDE,
            'dataset_split': dataset_split,
            'case_count': case_count,
            'sample_case_ids': sample_case_ids,
            'patient_model': patient_model,
            'judge_model': judge_model,
            'target_models': target_models,
            'runs': [],
            'comparison': [],
            'preflight': [],
            'skipped_target_models': [],
            'notes': {
                'llm_timeout_effective_source': 'LLM_TIMEOUT env via backend.llm.client.LLMClient',
                'per_turn_timeout_field_note': 'persisted on MoodPalEvalRun but not yet enforced in execute_run chain',
            },
        }

        for index, target_model in enumerate(target_models, start=1):
            if not options['skip_preflight']:
                preflight = _run_target_preflight(target_model)
                report['preflight'].append(preflight)
                if not preflight['compatible']:
                    report['skipped_target_models'].append(
                        {
                            'target_model': target_model,
                            'reason': preflight.get('reason', 'preflight_failed'),
                            'details': preflight,
                        }
                    )
                    self.stdout.write(
                        f'[skip {index}/{len(target_models)}] target_model={target_model} '
                        f'reason={preflight.get("reason", "preflight_failed")}'
                    )
                    continue

            self.stdout.write(f'[run {index}/{len(target_models)}] target_model={target_model}')
            run = create_run(
                created_by=None,
                payload=RunCreateInput(
                    target_mode='master_guide',
                    target_persona_id=MoodPalSession.Persona.MASTER_GUIDE,
                    dataset_split=dataset_split,
                    case_count=case_count,
                    patient_model=patient_model,
                    judge_model=judge_model,
                    target_model=target_model,
                    threshold_score=int(options['threshold_score']),
                    max_turns=int(options['max_turns']),
                    concurrency=int(options['concurrency']),
                    per_turn_timeout_seconds=int(options['per_turn_timeout_seconds']),
                    max_runtime_seconds=int(options['max_runtime_seconds']),
                    max_retries=int(options['max_retries']),
                    name=_build_run_name(target_model=target_model, dataset_split=dataset_split),
                ),
            )
            metadata = dict(run.metadata or {})
            metadata.update(
                {
                    'created_via': 'offline_benchmark_command',
                    'benchmark_target_model': target_model,
                    'sample_case_ids': sample_case_ids,
                }
            )
            run.metadata = metadata
            run.save(update_fields=['metadata', 'updated_at'])

            final_run = execute_run(str(run.id))
            final_run = get_run(final_run.id)
            run_summary = _serialize_run(final_run)
            report['runs'].append(run_summary)
            self.stdout.write(_format_run_summary(run_summary))

        report['comparison'] = _build_comparison(report['runs'])
        output_path = _resolve_output_path(options['output'], prefix='moodpal_model_benchmark')
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'benchmark report written to {output_path}'))


def _resolve_target_models(raw_models: str) -> list[str]:
    if raw_models.strip():
        values = []
        for part in raw_models.split(','):
            normalized = normalize_selected_model(part)
            if normalized not in values:
                values.append(normalized)
        return values

    values = []
    for item in get_model_options():
        if item['provider'] == 'openai':
            continue
        selected_model = item['value']
        if selected_model not in values:
            values.append(selected_model)
    return values


def _resolve_case_sample(*, dataset_split: str, case_count: int) -> list[MoodPalEvalCase]:
    queryset = MoodPalEvalCase.objects.filter(enabled=True).order_by('case_id')
    if not dataset_split:
        return list(queryset[:case_count])

    selected: list[MoodPalEvalCase] = []
    for case in queryset:
        if dataset_split in list(case.splits or []):
            selected.append(case)
        if len(selected) >= case_count:
            break
    return selected


def _build_run_name(*, target_model: str, dataset_split: str) -> str:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    suffix = dataset_split or 'default'
    compact_model = target_model.replace(':', '-')
    return f'master-guide-benchmark-{compact_model}-{suffix}-{stamp}'


def _run_target_preflight(target_model: str) -> dict:
    context = EvalTargetSessionContext(
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        usage_subject='system_eval:benchmark_preflight',
        selected_model=target_model,
    )
    try:
        result = run_target_turn(
            session_context=context,
            transcript=[],
            user_content=PREFLIGHT_USER_MESSAGE,
        )
    except Exception as exc:
        return {
            'target_model': target_model,
            'compatible': False,
            'reason': 'runtime_exception',
            'error': f'{exc.__class__.__name__}: {exc}',
        }

    metadata = dict(result.assistant_message.get('metadata') or {})
    usage = dict(metadata.get('usage') or {})
    total_tokens = int(usage.get('total_tokens') or 0)
    provider = str(metadata.get('provider') or '').strip()
    model = str(metadata.get('model') or '').strip()
    reply_text = str(result.assistant_message.get('content') or '').strip()
    compatible = bool(reply_text) and total_tokens > 0 and bool(provider) and bool(model)
    reason = 'ok' if compatible else 'fallback_or_non_llm_reply'
    return {
        'target_model': target_model,
        'compatible': compatible,
        'reason': reason,
        'provider': provider,
        'model': model,
        'reply_len': len(reply_text),
        'reply_preview': reply_text[:180],
        'total_tokens': total_tokens,
        'engine': metadata.get('engine', ''),
        'track': metadata.get('track', ''),
        'technique_id': metadata.get('technique_id', ''),
        'safety_override': bool(result.safety_override),
    }


def _serialize_run(run) -> dict:
    items = list(run.items.select_related('case').order_by('case__case_id'))
    case_results = []
    dimension_totals = defaultdict(float)
    dimension_counts = defaultdict(int)
    for item in items:
        case_results.append(
            {
                'item_id': str(item.id),
                'case_id': item.case.case_id,
                'status': item.status,
                'final_score': float(item.final_score or 0),
                'hard_fail': bool(item.hard_fail),
                'stop_reason': item.stop_reason,
                'error_code': item.error_code,
                'error_message': item.error_message,
                'total_token_usage': int(item.total_token_usage or 0),
                'target_token_usage': int(item.target_token_usage or 0),
                'patient_token_usage': int(item.patient_token_usage or 0),
                'judge_token_usage': int(item.judge_token_usage or 0),
                'final_scores': dict(item.final_scores or {}),
                'deduction_reasons': list(item.deduction_reasons or []),
                'runtime_summary': dict((item.metadata or {}).get('target_runtime_summary') or {}),
            }
        )
        for dimension, score in dict(item.final_scores or {}).items():
            try:
                dimension_totals[dimension] += float(score)
                dimension_counts[dimension] += 1
            except (TypeError, ValueError):
                continue

    dimension_avgs = {}
    for dimension, total in dimension_totals.items():
        count = dimension_counts[dimension]
        if count > 0:
            dimension_avgs[dimension] = round(total / count, 2)

    return {
        'run_id': str(run.id),
        'name': run.name,
        'status': run.status,
        'gate_passed': run.gate_passed,
        'gate_failure_reason': run.gate_failure_reason,
        'target_model': run.target_model,
        'patient_model': run.patient_model,
        'judge_model': run.judge_model,
        'summary_metrics': dict(run.summary_metrics or {}),
        'dimension_average_scores': dimension_avgs,
        'started_at': run.started_at.isoformat() if run.started_at else '',
        'finished_at': run.finished_at.isoformat() if run.finished_at else '',
        'case_results': case_results,
    }


def _build_comparison(run_summaries: list[dict]) -> list[dict]:
    rows = []
    for run in run_summaries:
        metrics = dict(run.get('summary_metrics') or {})
        rows.append(
            {
                'target_model': run.get('target_model', ''),
                'run_id': run.get('run_id', ''),
                'status': run.get('status', ''),
                'gate_passed': run.get('gate_passed'),
                'gate_failure_reason': run.get('gate_failure_reason', ''),
                'overall_avg_score': float(metrics.get('overall_avg_score') or 0),
                'pass_rate': float(metrics.get('pass_rate') or 0),
                'completed_count': int(metrics.get('completed_count') or 0),
                'failed_count': int(metrics.get('failed_count') or 0),
                'errored_count': int(metrics.get('errored_count') or 0),
                'hard_fail_count': int(metrics.get('hard_fail_count') or 0),
                'total_token_usage': int(metrics.get('total_token_usage') or 0),
                'dimension_average_scores': dict(run.get('dimension_average_scores') or {}),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            -int(bool(item['gate_passed'])),
            item['errored_count'],
            item['hard_fail_count'],
            -item['overall_avg_score'],
            -item['pass_rate'],
        ),
    )


def _format_run_summary(run_summary: dict) -> str:
    metrics = dict(run_summary.get('summary_metrics') or {})
    return (
        f'  -> status={run_summary.get("status")} gate={run_summary.get("gate_passed")} '
        f'avg={metrics.get("overall_avg_score")} pass_rate={metrics.get("pass_rate")} '
        f'errored={metrics.get("errored_count")} hard_fail={metrics.get("hard_fail_count")} '
        f'tokens={metrics.get("total_token_usage")} run_id={run_summary.get("run_id")}'
    )


def _resolve_output_path(raw_path: str, *, prefix: str) -> Path:
    if raw_path.strip():
        path = Path(raw_path).expanduser()
    else:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        path = Path('tmp') / f'{prefix}-{stamp}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
