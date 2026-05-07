import datetime
from collections import defaultdict
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, Exists, Max, Min, OuterRef, Q

from backend.moodpal.models import MoodPalSession, MoodPalSessionEvent

TZ = ZoneInfo('Asia/Shanghai')
PERSONAS = ['master_guide', 'logic_brother', 'empathy_sister', 'insight_mentor']


def get_daily_stats(date: datetime.date) -> dict:
    new_sessions_qs = MoodPalSession.objects.filter(created_at__date=date)
    new_sessions_count = new_sessions_qs.count()

    active_users = (
        MoodPalSession.objects
        .filter(last_activity_at__date=date)
        .values('usage_subject')
        .distinct()
        .count()
    )

    cumulative_users = (
        MoodPalSession.objects
        .filter(created_at__date__lte=date)
        .values('usage_subject')
        .distinct()
        .count()
    )

    registered_count = new_sessions_qs.filter(owner__isnull=False).count()
    registered_ratio = registered_count / new_sessions_count if new_sessions_count else 0.0

    ended_qs = MoodPalSession.objects.filter(ended_at__date=date)
    ended_count = ended_qs.count()
    user_ended = ended_qs.filter(close_reason='user_ended').count()
    idle_timeout = ended_qs.filter(close_reason='idle_timeout').count()
    completion_rate = user_ended / ended_count if ended_count else 0.0
    timeout_rate = idle_timeout / ended_count if ended_count else 0.0

    rounds_result = (
        new_sessions_qs
        .annotate(rounds=Count('messages', filter=Q(messages__role='user')))
        .aggregate(avg=Avg('rounds'))
    )
    avg_rounds = float(rounds_result['avg'] or 0.0)

    ended_with_times = (
        MoodPalSession.objects
        .filter(ended_at__date=date, activated_at__isnull=False, ended_at__isnull=False)
        .only('ended_at', 'activated_at')
    )
    durations = [
        (s.ended_at - s.activated_at).total_seconds() / 60
        for s in ended_with_times
    ]
    avg_duration_minutes = sum(durations) / len(durations) if durations else 0.0

    summary_qs = new_sessions_qs.aggregate(
        saved=Count('id', filter=Q(summary_action='saved')),
        destroyed=Count('id', filter=Q(summary_action='destroyed')),
    )
    save_total = (summary_qs['saved'] or 0) + (summary_qs['destroyed'] or 0)
    summary_save_rate = (summary_qs['saved'] or 0) / save_total if save_total else 0.0

    crisis_count = MoodPalSessionEvent.objects.filter(
        created_at__date=date,
        event_type='crisis_triggered',
    ).count()

    persona_rows = (
        new_sessions_qs
        .values('persona_id')
        .annotate(count=Count('id'))
    )
    persona_dist = {p: 0 for p in PERSONAS}
    for row in persona_rows:
        if row['persona_id'] in persona_dist:
            persona_dist[row['persona_id']] = row['count']

    return {
        'new_sessions': new_sessions_count,
        'active_users': active_users,
        'cumulative_users': cumulative_users,
        'registered_ratio': registered_ratio,
        'completion_rate': completion_rate,
        'timeout_rate': timeout_rate,
        'avg_rounds': avg_rounds,
        'avg_duration_minutes': avg_duration_minutes,
        'summary_save_rate': summary_save_rate,
        'crisis_count': crisis_count,
        'persona_dist': persona_dist,
    }


def get_user_list(
    order_by: str = '-last_active',
    page: int = 1,
    page_size: int = 20,
) -> dict:
    allowed_orderings = {'-last_active', 'last_active', '-session_count', 'session_count'}
    if order_by not in allowed_orderings:
        order_by = '-last_active'

    qs = (
        MoodPalSession.objects
        .values('usage_subject')
        .annotate(
            session_count=Count('id'),
            first_seen=Min('created_at'),
            last_active=Max('last_activity_at'),
            registered_count=Count('owner', filter=Q(owner__isnull=False)),
        )
        .order_by(order_by)
    )

    total = qs.count()
    offset = (page - 1) * page_size
    rows = list(qs[offset:offset + page_size])
    for row in rows:
        row['is_registered'] = row.pop('registered_count') > 0

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'rows': rows,
    }


def get_user_detail(subject_key: str) -> dict:
    sessions_qs = MoodPalSession.objects.filter(usage_subject=subject_key)

    agg = sessions_qs.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(close_reason='user_ended')),
        timeout=Count('id', filter=Q(close_reason='idle_timeout')),
        summary_saved=Count('id', filter=Q(summary_action='saved')),
        summary_destroyed=Count('id', filter=Q(summary_action='destroyed')),
        first_seen=Min('created_at'),
        last_active=Max('last_activity_at'),
    )

    persona_rows = (
        sessions_qs
        .values('persona_id')
        .annotate(count=Count('id'))
    )
    persona_counts = {p: 0 for p in PERSONAS}
    for row in persona_rows:
        if row['persona_id'] in persona_counts:
            persona_counts[row['persona_id']] = row['count']

    crisis_total = MoodPalSessionEvent.objects.filter(
        session__usage_subject=subject_key,
        event_type='crisis_triggered',
    ).count()

    ended_sessions = (
        sessions_qs
        .filter(activated_at__isnull=False, ended_at__isnull=False)
        .only('ended_at', 'activated_at')
    )
    durations = [
        (s.ended_at - s.activated_at).total_seconds() / 60
        for s in ended_sessions
    ]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    is_registered = False
    username = None
    first_session = sessions_qs.filter(owner__isnull=False).select_related('owner').first()
    if first_session:
        is_registered = True
        username = first_session.owner.username

    basic = {
        'usage_subject': subject_key,
        'is_registered': is_registered,
        'username': username,
        'first_seen': agg['first_seen'],
        'last_active': agg['last_active'],
    }

    cumulative = {
        'total_sessions': agg['total'] or 0,
        'completed_sessions': agg['completed'] or 0,
        'timeout_sessions': agg['timeout'] or 0,
        'crisis_total': crisis_total,
        'summary_saved': agg['summary_saved'] or 0,
        'summary_destroyed': agg['summary_destroyed'] or 0,
        'persona_counts': persona_counts,
        'avg_duration_minutes': avg_duration,
    }

    thirty_days_ago = datetime.datetime.now(TZ) - datetime.timedelta(days=30)
    recent_sessions = list(
        sessions_qs
        .filter(created_at__gte=thirty_days_ago)
        .only('id', 'created_at', 'activated_at', 'ended_at', 'persona_id', 'close_reason')
    )

    crisis_30d_ids = set(
        MoodPalSessionEvent.objects.filter(
            session__usage_subject=subject_key,
            event_type='crisis_triggered',
            created_at__gte=thirty_days_ago,
        ).values_list('session_id', flat=True)
    )

    daily_map: dict = defaultdict(lambda: {'sessions': [], 'crisis_count': 0})
    for s in recent_sessions:
        day = s.created_at.astimezone(TZ).date()
        daily_map[day]['sessions'].append(s)
        if s.id in crisis_30d_ids:
            daily_map[day]['crisis_count'] += 1

    daily_rows = []
    for day in sorted(daily_map.keys(), reverse=True):
        day_sessions = daily_map[day]['sessions']
        day_durations = [
            (s.ended_at - s.activated_at).total_seconds() / 60
            for s in day_sessions
            if s.ended_at and s.activated_at
        ]
        daily_rows.append({
            'date': day,
            'session_count': len(day_sessions),
            'avg_duration_minutes': sum(day_durations) / len(day_durations) if day_durations else 0.0,
            'personas': list({s.persona_id for s in day_sessions}),
            'crisis_count': daily_map[day]['crisis_count'],
        })

    crisis_subq = MoodPalSessionEvent.objects.filter(
        session=OuterRef('pk'),
        event_type='crisis_triggered',
    )
    session_flow_qs = (
        sessions_qs
        .annotate(
            rounds=Count('messages', filter=Q(messages__role='user')),
            had_crisis=Exists(crisis_subq),
        )
        .only('id', 'activated_at', 'persona_id', 'ended_at', 'close_reason', 'summary_action')
        .order_by('-activated_at', '-created_at')
    )

    session_rows = []
    for s in session_flow_qs:
        duration = None
        if s.ended_at and s.activated_at:
            duration = (s.ended_at - s.activated_at).total_seconds() / 60
        session_rows.append({
            'session_id': str(s.id),
            'activated_at': s.activated_at,
            'persona_id': s.persona_id,
            'duration_minutes': duration,
            'rounds': s.rounds,
            'close_reason': s.close_reason,
            'summary_action': s.summary_action,
            'had_crisis': s.had_crisis,
        })

    return {
        'basic': basic,
        'cumulative': cumulative,
        'daily': daily_rows,
        'sessions': session_rows,
    }
