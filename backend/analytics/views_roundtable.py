import datetime
import json
import math

from django.contrib import admin
from django.shortcuts import render

from .queries_roundtable import get_rt_daily_stats, get_rt_user_detail, get_rt_user_list

ALLOWED_DAYS = {7, 14, 30}
ALLOWED_ORDER_BY = {
    '-last_active', 'last_active',
    '-discussion_count', 'discussion_count',
    '-used_tokens', 'used_tokens',
}


def rt_daily_view(request):
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
        stat = get_rt_daily_stats(d)
        stat['date'] = d
        stats_list.append(stat)

    chart_dates = list(reversed(dates))
    chart_stats = list(reversed(stats_list))

    chart_labels = json.dumps([str(d) for d in chart_dates], ensure_ascii=False)
    chart_new_discussions = json.dumps([s['new_discussions'] for s in chart_stats])
    chart_active_users = json.dumps([s['active_users'] for s in chart_stats])
    chart_daily_tokens = json.dumps([s['daily_tokens'] for s in chart_stats])
    chart_avg_rounds = json.dumps([round(s['avg_rounds'], 2) for s in chart_stats])

    # 汇总 top10 历史人物（整个时间窗口）
    char_totals: dict = {}
    for s in stats_list:
        for item in s['top10_chars']:
            char_totals[item['name']] = char_totals.get(item['name'], 0) + item['count']
    top10_sorted = sorted(char_totals.items(), key=lambda x: -x[1])[:10]
    top10_char_labels = json.dumps([x[0] for x in top10_sorted], ensure_ascii=False)
    top10_char_values = json.dumps([x[1] for x in top10_sorted])

    # 汇总 provider 分布
    provider_totals: dict = {}
    for s in stats_list:
        for item in s['provider_dist']:
            key = item['provider']
            provider_totals[key] = provider_totals.get(key, 0) + item['tokens']
    provider_sorted = sorted(provider_totals.items(), key=lambda x: -x[1])
    provider_labels = json.dumps([x[0] for x in provider_sorted], ensure_ascii=False)
    provider_values = json.dumps([x[1] for x in provider_sorted])

    ctx = {
        'title': 'Roundtable 天级数据',
        'days': days,
        'stats_list': stats_list,
        'chart_labels': chart_labels,
        'chart_new_discussions': chart_new_discussions,
        'chart_active_users': chart_active_users,
        'chart_daily_tokens': chart_daily_tokens,
        'chart_avg_rounds': chart_avg_rounds,
        'top10_char_labels': top10_char_labels,
        'top10_char_values': top10_char_values,
        'provider_labels': provider_labels,
        'provider_values': provider_values,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/rt_daily.html', ctx)


def rt_users_view(request):
    order_by = request.GET.get('order_by', '-last_active')
    if order_by not in ALLOWED_ORDER_BY:
        order_by = '-last_active'

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    result = get_rt_user_list(order_by=order_by, page=page)
    total_pages = math.ceil(result['total'] / result['page_size']) if result['total'] else 1

    ctx = {
        'title': 'Roundtable 用户列表',
        'rows': result['rows'],
        'total': result['total'],
        'page': result['page'],
        'page_size': result['page_size'],
        'total_pages': total_pages,
        'order_by': order_by,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/rt_users.html', ctx)


def rt_user_detail_view(request, subject_key):
    detail = get_rt_user_detail(subject_key)

    try:
        disc_page = max(1, int(request.GET.get('disc_page', 1)))
    except (ValueError, TypeError):
        disc_page = 1

    page_size = 20
    all_discs = detail['discussions']
    total_discs = len(all_discs)
    disc_total_pages = math.ceil(total_discs / page_size) if total_discs else 1
    offset = (disc_page - 1) * page_size
    discs_page = all_discs[offset:offset + page_size]

    top3 = detail['cumulative']['top3_chars']
    top3_labels = json.dumps([x['name'] for x in top3], ensure_ascii=False)
    top3_values = json.dumps([x['count'] for x in top3])

    ctx = {
        'title': '用户详情',
        'subject_key': subject_key,
        'basic': detail['basic'],
        'cumulative': detail['cumulative'],
        'daily': detail['daily'],
        'discussions': discs_page,
        'disc_page': disc_page,
        'disc_total_pages': disc_total_pages,
        'top3_labels': top3_labels,
        'top3_values': top3_values,
        **admin.site.each_context(request),
    }
    return render(request, 'analytics/rt_user_detail.html', ctx)
