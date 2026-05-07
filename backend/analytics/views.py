import datetime
import json
import math

from django.contrib import admin
from django.shortcuts import render

from .queries import get_daily_stats, get_user_detail, get_user_list

PERSONA_KEYS = ['master_guide', 'logic_brother', 'empathy_sister', 'insight_mentor']
PERSONA_LABELS = ['全能主理人', '逻辑派的邻家哥哥', '共情派的知心学姐', '深挖派的心理学前辈']
ALLOWED_DAYS = {7, 14, 30}
ALLOWED_ORDER_BY = {'-last_active', 'last_active', '-session_count', 'session_count'}


def _mask_subject(s: str) -> str:
    return s[:6] + '***' if len(s) > 6 else s


def moodpal_daily_view(request):
    try:
        days = int(request.GET.get('days', 14))
    except (ValueError, TypeError):
        days = 14
    if days not in ALLOWED_DAYS:
        days = 14

    today = datetime.date.today()
    dates = [today - datetime.timedelta(days=i) for i in range(days)]

    stats_list = []
    for d in dates:
        stat = get_daily_stats(d)
        stat['date'] = d
        stats_list.append(stat)

    # chart data in chronological order (oldest first)
    chart_dates = list(reversed(dates))
    chart_stats = list(reversed(stats_list))

    chart_labels = json.dumps([str(d) for d in chart_dates], ensure_ascii=False)
    chart_new_sessions = json.dumps([s['new_sessions'] for s in chart_stats])
    chart_active_users = json.dumps([s['active_users'] for s in chart_stats])
    chart_avg_rounds = json.dumps([round(s['avg_rounds'], 2) for s in chart_stats])

    persona_totals_list = [
        sum(s['persona_dist'].get(k, 0) for s in stats_list)
        for k in PERSONA_KEYS
    ]
    persona_labels = json.dumps(PERSONA_LABELS, ensure_ascii=False)
    persona_totals = json.dumps(persona_totals_list)

    ctx = {
        'title': 'MoodPal 天级数据',
        'days': days,
        'stats_list': stats_list,
        'chart_labels': chart_labels,
        'chart_new_sessions': chart_new_sessions,
        'chart_active_users': chart_active_users,
        'chart_avg_rounds': chart_avg_rounds,
        'persona_labels': persona_labels,
        'persona_totals': persona_totals,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/moodpal_daily.html', ctx)


def moodpal_users_view(request):
    order_by = request.GET.get('order_by', '-last_active')
    if order_by not in ALLOWED_ORDER_BY:
        order_by = '-last_active'

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    result = get_user_list(order_by=order_by, page=page)

    rows = []
    for row in result['rows']:
        raw = row['usage_subject']
        rows.append({
            **row,
            'subject_key_raw': raw,
            'usage_subject': _mask_subject(raw),
        })

    total_pages = math.ceil(result['total'] / result['page_size']) if result['total'] else 1

    ctx = {
        'title': 'MoodPal 用户列表',
        'rows': rows,
        'total': result['total'],
        'page': result['page'],
        'page_size': result['page_size'],
        'total_pages': total_pages,
        'order_by': order_by,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/moodpal_users.html', ctx)


def moodpal_user_detail_view(request, subject_key):
    detail = get_user_detail(subject_key)

    try:
        session_page = max(1, int(request.GET.get('session_page', 1)))
    except (ValueError, TypeError):
        session_page = 1

    page_size = 20
    all_sessions = detail['sessions']
    total_sessions = len(all_sessions)
    session_total_pages = math.ceil(total_sessions / page_size) if total_sessions else 1
    offset = (session_page - 1) * page_size
    sessions_page = all_sessions[offset:offset + page_size]

    persona_values_list = [
        detail['cumulative']['persona_counts'].get(k, 0)
        for k in PERSONA_KEYS
    ]
    persona_labels = json.dumps(PERSONA_LABELS, ensure_ascii=False)
    persona_values = json.dumps(persona_values_list)

    ctx = {
        'title': '用户详情',
        'subject_key': subject_key,
        'subject_display': _mask_subject(subject_key),
        'basic': detail['basic'],
        'cumulative': detail['cumulative'],
        'daily': detail['daily'],
        'sessions': sessions_page,
        'session_page': session_page,
        'session_total_pages': session_total_pages,
        'persona_labels': persona_labels,
        'persona_values': persona_values,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/moodpal_user_detail.html', ctx)
