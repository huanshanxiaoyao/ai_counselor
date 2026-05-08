import datetime
from collections import defaultdict
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, Min, Max, Q, Sum

from backend.roundtable.models import (
    Character,
    Discussion,
    QuotaFeedback,
    TokenQuotaState,
    TokenUsageLedger,
)

TZ = ZoneInfo('Asia/Shanghai')


def get_rt_daily_stats(date: datetime.date) -> dict:
    new_qs = Discussion.objects.filter(created_at__date=date)
    new_count = new_qs.count()

    finished_today = Discussion.objects.filter(ended_at__date=date, status='finished')
    finished_count = finished_today.count()

    active_users = (
        Discussion.objects
        .filter(Q(created_at__date=date) | Q(updated_at__date=date))
        .values('usage_subject')
        .distinct()
        .count()
    )
    cumulative_users = (
        Discussion.objects
        .filter(created_at__date__lte=date)
        .values('usage_subject')
        .distinct()
        .count()
    )

    registered_count = new_qs.filter(owner__isnull=False).count()
    registered_ratio = registered_count / new_count if new_count else 0.0

    completion_rate = finished_count / new_count if new_count else 0.0

    finished_with_times = list(
        finished_today.filter(ended_at__isnull=False).only('created_at', 'ended_at', 'current_round')
    )
    durations = [
        (d.ended_at - d.created_at).total_seconds() / 60
        for d in finished_with_times
    ]
    avg_duration_minutes = sum(durations) / len(durations) if durations else 0.0
    rounds = [d.current_round for d in finished_with_times if d.current_round]
    avg_rounds = sum(rounds) / len(rounds) if rounds else 0.0

    daily_tokens = (
        TokenUsageLedger.objects
        .filter(created_at__date=date)
        .aggregate(total=Sum('total_tokens'))
    )['total'] or 0

    role_agg = new_qs.aggregate(
        host=Count('id', filter=Q(user_role='host')),
        participant=Count('id', filter=Q(user_role='participant')),
        observer=Count('id', filter=Q(user_role='observer')),
    )
    user_role_dist = {
        'host': role_agg['host'] or 0,
        'participant': role_agg['participant'] or 0,
        'observer': role_agg['observer'] or 0,
    }

    top10_chars = list(
        Character.objects
        .filter(discussion__created_at__date=date)
        .values('name')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    provider_rows = (
        TokenUsageLedger.objects
        .filter(created_at__date=date)
        .values('provider')
        .annotate(tokens=Sum('total_tokens'))
        .order_by('-tokens')
    )
    provider_dist = [{'provider': r['provider'] or 'unknown', 'tokens': r['tokens']} for r in provider_rows]

    public_count = new_qs.filter(visibility='public').count()
    public_ratio = public_count / new_count if new_count else 0.0

    return {
        'new_discussions': new_count,
        'finished_discussions': finished_count,
        'active_users': active_users,
        'cumulative_users': cumulative_users,
        'registered_ratio': registered_ratio,
        'completion_rate': completion_rate,
        'avg_duration_minutes': avg_duration_minutes,
        'avg_rounds': avg_rounds,
        'daily_tokens': daily_tokens,
        'user_role_dist': user_role_dist,
        'top10_chars': top10_chars,
        'provider_dist': provider_dist,
        'public_ratio': public_ratio,
    }


def get_rt_user_list(
    order_by: str = '-last_active',
    page: int = 1,
    page_size: int = 20,
) -> dict:
    allowed = {'-last_active', 'last_active', '-discussion_count', 'discussion_count', '-used_tokens', 'used_tokens'}
    if order_by not in allowed:
        order_by = '-last_active'

    qs = (
        Discussion.objects
        .values('usage_subject')
        .annotate(
            discussion_count=Count('id'),
            first_seen=Min('created_at'),
            last_active=Max('updated_at'),
            registered_count=Count('owner', filter=Q(owner__isnull=False)),
        )
        .order_by(order_by)
    )

    total = qs.count()
    offset = (page - 1) * page_size
    rows = list(qs[offset:offset + page_size])

    subject_keys = [r['usage_subject'] for r in rows]
    quota_map = {
        q.subject_key: q
        for q in TokenQuotaState.objects.filter(subject_key__in=subject_keys)
    }

    for row in rows:
        row['is_registered'] = row.pop('registered_count') > 0
        q = quota_map.get(row['usage_subject'])
        if q:
            row['used_tokens'] = q.used_tokens
            row['quota_limit'] = q.quota_limit
            row['quota_rate'] = q.used_tokens / q.quota_limit if q.quota_limit else 0.0
        else:
            row['used_tokens'] = 0
            row['quota_limit'] = 0
            row['quota_rate'] = 0.0

    return {'total': total, 'page': page, 'page_size': page_size, 'rows': rows}


def get_rt_user_detail(subject_key: str) -> dict:
    disc_qs = Discussion.objects.filter(usage_subject=subject_key)

    agg = disc_qs.aggregate(
        total=Count('id'),
        finished=Count('id', filter=Q(status='finished')),
        first_seen=Min('created_at'),
        last_active=Max('updated_at'),
    )

    try:
        quota = TokenQuotaState.objects.get(subject_key=subject_key)
        used_tokens = quota.used_tokens
        quota_limit = quota.quota_limit
        quota_rate = used_tokens / quota_limit if quota_limit else 0.0
    except TokenQuotaState.DoesNotExist:
        used_tokens = quota_limit = 0
        quota_rate = 0.0

    quota_exceeded_count = QuotaFeedback.objects.filter(subject_key=subject_key).count()

    top3_chars = list(
        Character.objects
        .filter(discussion__usage_subject=subject_key)
        .values('name')
        .annotate(count=Count('id'))
        .order_by('-count')[:3]
    )

    role_agg = disc_qs.aggregate(
        host=Count('id', filter=Q(user_role='host')),
        participant=Count('id', filter=Q(user_role='participant')),
        observer=Count('id', filter=Q(user_role='observer')),
    )
    role_dist = {
        'host': role_agg['host'] or 0,
        'participant': role_agg['participant'] or 0,
        'observer': role_agg['observer'] or 0,
    }

    finished_qs = list(disc_qs.filter(status='finished', ended_at__isnull=False).only('created_at', 'ended_at', 'current_round'))
    rounds_list = [d.current_round for d in finished_qs if d.current_round]
    avg_rounds = sum(rounds_list) / len(rounds_list) if rounds_list else 0.0

    is_registered = False
    username = None
    first_with_owner = disc_qs.filter(owner__isnull=False).select_related('owner').first()
    if first_with_owner:
        is_registered = True
        username = first_with_owner.owner.username

    basic = {
        'usage_subject': subject_key,
        'is_registered': is_registered,
        'username': username,
        'first_seen': agg['first_seen'],
        'last_active': agg['last_active'],
    }

    cumulative = {
        'total_discussions': agg['total'] or 0,
        'finished_discussions': agg['finished'] or 0,
        'used_tokens': used_tokens,
        'quota_limit': quota_limit,
        'quota_rate': quota_rate,
        'quota_exceeded_count': quota_exceeded_count,
        'top3_chars': top3_chars,
        'role_dist': role_dist,
        'avg_rounds': avg_rounds,
    }

    # 近30天数据
    thirty_days_ago = datetime.datetime.now(TZ) - datetime.timedelta(days=30)
    recent_discs = list(
        disc_qs.filter(created_at__gte=thirty_days_ago)
        .only('id', 'created_at', 'topic')
    )
    recent_disc_ids = [d.id for d in recent_discs]

    ledger_30d = defaultdict(int)
    for row in (
        TokenUsageLedger.objects
        .filter(discussion_id__in=recent_disc_ids)
        .values('created_at__date')
        .annotate(tokens=Sum('total_tokens'))
    ):
        ledger_30d[row['created_at__date']] += row['tokens']

    daily_map: dict = defaultdict(lambda: {'discussions': [], 'tokens': 0})
    for d in recent_discs:
        day = d.created_at.astimezone(TZ).date()
        daily_map[day]['discussions'].append(d)

    for day, tokens in ledger_30d.items():
        daily_map[day]['tokens'] += tokens

    daily_rows = []
    for day in sorted(daily_map.keys(), reverse=True):
        entry = daily_map[day]
        daily_rows.append({
            'date': day,
            'discussion_count': len(entry['discussions']),
            'tokens': entry['tokens'],
            'topics': [d.topic[:30] for d in entry['discussions']],
        })

    # 讨论级流水（全量，倒序）
    all_discs = list(
        disc_qs
        .only('id', 'created_at', 'ended_at', 'topic', 'user_role', 'current_round', 'status', 'visibility')
        .order_by('-created_at')
    )
    all_disc_ids = [d.id for d in all_discs]

    chars_by_disc: dict = defaultdict(list)
    for c in Character.objects.filter(discussion_id__in=all_disc_ids).values('discussion_id', 'name'):
        chars_by_disc[c['discussion_id']].append(c['name'])

    tokens_by_disc: dict = defaultdict(int)
    for row in (
        TokenUsageLedger.objects
        .filter(discussion_id__in=all_disc_ids)
        .values('discussion_id')
        .annotate(tokens=Sum('total_tokens'))
    ):
        tokens_by_disc[row['discussion_id']] = row['tokens']

    session_rows = []
    for d in all_discs:
        duration = None
        if d.ended_at and d.created_at:
            duration = (d.ended_at - d.created_at).total_seconds() / 60
        session_rows.append({
            'discussion_id': d.id,
            'created_at': d.created_at,
            'topic': d.topic,
            'user_role': d.user_role,
            'characters': chars_by_disc.get(d.id, []),
            'current_round': d.current_round,
            'duration_minutes': duration,
            'status': d.status,
            'tokens': tokens_by_disc.get(d.id, 0),
            'visibility': d.visibility,
        })

    return {
        'basic': basic,
        'cumulative': cumulative,
        'daily': daily_rows,
        'discussions': session_rows,
    }
