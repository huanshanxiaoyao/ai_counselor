from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .models import MoodPalEvalRun, MoodPalEvalRunItem
from .forms import MoodPalEvalRunCreateForm
from .services import run_launcher
from .services.run_service import (
    EvalRunValidationError,
    RunCreateInput,
    create_run,
    get_run,
    get_run_item,
    has_running_run,
    list_runs,
)


ERROR_MESSAGES = {
    'run_already_running': '当前已有运行中的评测，请等待完成后再发起新的 Run。',
    'another_run_running': '当前已有运行中的评测，请稍后再试。',
    'case_count_exceeded': '单次最多只能运行 20 个 Case。',
    'invalid_case_count': 'Case 数量不合法。',
    'not_enough_cases': '当前筛选条件下可用 Case 数量不足。',
    'baseline_run_not_found': '选择的稳定基线 Run 不存在，或尚未完成。',
    'invalid_target_mode': '目标模式不合法。',
    'invalid_target_persona': '目标角色不合法。',
    'master_guide_persona_required': '全能主理人模式必须选择 master_guide。',
    'single_role_persona_required': '单角色模式不能选择 master_guide。',
    'invalid_threshold_score': '总分门槛必须在 0 到 100 之间。',
    'invalid_max_turns': '最大轮数超出允许范围。',
    'invalid_concurrency': '并发数超出允许范围。',
    'invalid_per_turn_timeout': '单轮超时秒数超出允许范围。',
    'invalid_max_runtime': '总运行超时秒数超出允许范围。',
    'invalid_max_retries': '最大重试次数超出允许范围。',
}


@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    return redirect('moodpal_eval:run_list')


@staff_member_required
def run_list(request: HttpRequest) -> HttpResponse:
    runs = list(list_runs()[:50])
    return render(
        request,
        'moodpal_eval/run_list.html',
        {
            'runs': runs,
            'has_running_run': has_running_run(),
            'page_title': 'MoodPal Eval Sandbox',
        },
    )


@staff_member_required
def run_create(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = MoodPalEvalRunCreateForm(request.POST)
        if form.is_valid():
            payload = RunCreateInput(**form.cleaned_data)
            try:
                run = create_run(created_by=request.user, payload=payload)
                run_launcher.launch_run(str(run.id))
            except EvalRunValidationError as exc:
                form.add_error(None, ERROR_MESSAGES.get(str(exc), str(exc)))
            except Exception as exc:
                form.add_error(None, f'启动 Run 失败: {exc.__class__.__name__}')
            else:
                messages.success(request, f'评测已启动：{run.name or run.id}')
                return redirect('moodpal_eval:run_detail', run_id=run.id)
    else:
        form = MoodPalEvalRunCreateForm()

    return render(
        request,
        'moodpal_eval/run_create.html',
        {
            'form': form,
            'has_running_run': has_running_run(),
            'page_title': '新建 Eval Run',
        },
    )


@staff_member_required
def run_detail(request: HttpRequest, run_id) -> HttpResponse:
    try:
        run = get_run(run_id)
    except MoodPalEvalRun.DoesNotExist as exc:
        raise Http404('run_not_found') from exc
    items = list(run.items.select_related('case').order_by('created_at', 'id'))
    errored_items = [item for item in items if item.status == MoodPalEvalRunItem.Status.ERRORED]
    return render(
        request,
        'moodpal_eval/run_detail.html',
        {
            'run': run,
            'items': items,
            'errored_items_preview': errored_items[:5],
            'summary_metrics': dict(run.summary_metrics or {}),
            'gate_failure_reasons': [item for item in (run.gate_failure_reason or '').split(',') if item],
            'page_title': run.name or str(run.id),
            'auto_refresh_seconds': 4 if run.status in [MoodPalEvalRun.Status.PENDING, MoodPalEvalRun.Status.RUNNING] else 0,
        },
    )


@staff_member_required
def item_detail(request: HttpRequest, item_id) -> HttpResponse:
    try:
        item = get_run_item(item_id)
    except MoodPalEvalRunItem.DoesNotExist as exc:
        raise Http404('run_item_not_found') from exc
    return render(
        request,
        'moodpal_eval/item_detail.html',
        {
            'item': item,
            'token_ledgers': list(item.token_ledgers.order_by('created_at', 'id')),
            'dialogue_rows': _build_dialogue_rows(item.transcript),
            'target_trace_json': json.dumps(item.target_trace or [], ensure_ascii=False, indent=2),
            'transcript_judge_json': json.dumps(item.transcript_judge_result or {}, ensure_ascii=False, indent=2),
            'route_audit_json': json.dumps(item.route_audit_result or {}, ensure_ascii=False, indent=2),
            'metadata_json': json.dumps(item.metadata or {}, ensure_ascii=False, indent=2),
            'page_title': f'{item.case.title or item.case.case_id}',
        },
    )


def _build_dialogue_rows(transcript: list[dict]) -> list[dict]:
    rows = []
    pending_user = None
    for message in list(transcript or []):
        role = str(message.get('role') or '')
        content = str(message.get('content') or '').strip()
        if not content:
            continue
        if role == 'user':
            if pending_user is not None:
                rows.append({'user': pending_user, 'assistant': ''})
            pending_user = content
            continue
        if role == 'assistant':
            rows.append({'user': pending_user or '', 'assistant': content})
            pending_user = None
            continue
        rows.append({'user': f'[{role}] {content}', 'assistant': ''})
    if pending_user is not None:
        rows.append({'user': pending_user, 'assistant': ''})
    return rows
