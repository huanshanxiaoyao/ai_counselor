"""
Token usage accounting + quota guard services.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction

from backend.roundtable.models import (
    Discussion,
    QuotaFeedback,
    TokenQuotaState,
    TokenUsageLedger,
)

ANON_USAGE_COOKIE_KEY = "anon_usage_id"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageSubject:
    """Normalized quota subject."""

    key: str
    subject_type: str
    user_id: Optional[int] = None
    anon_id: str = ""


class QuotaExceededError(Exception):
    """Raised when subject usage is already over quota."""

    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        super().__init__("quota_exceeded")


def _default_quota_limit() -> int:
    return int(getattr(settings, "TOKEN_QUOTA_LIMIT", 100000))


def parse_subject_key(subject_key: str) -> UsageSubject:
    if subject_key.startswith("user:"):
        try:
            user_id = int(subject_key.split(":", 1)[1])
        except (IndexError, ValueError):
            user_id = None
        return UsageSubject(key=subject_key, subject_type=TokenQuotaState.SubjectType.USER, user_id=user_id)
    anon_id = ""
    if subject_key.startswith("anon:"):
        anon_id = subject_key.split(":", 1)[1]
    return UsageSubject(key=subject_key, subject_type=TokenQuotaState.SubjectType.ANON, anon_id=anon_id)


def subject_from_request(request) -> UsageSubject:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return UsageSubject(
            key=f"user:{user.id}",
            subject_type=TokenQuotaState.SubjectType.USER,
            user_id=user.id,
        )

    anon_id = (
        request.COOKIES.get(ANON_USAGE_COOKIE_KEY)
        or getattr(request, "anon_usage_id", "")
        or request.session.get("guest_id", "")
        or uuid.uuid4().hex
    )
    return UsageSubject(
        key=f"anon:{anon_id}",
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id=anon_id,
    )


def subject_from_scope(scope) -> UsageSubject:
    user = scope.get("user")
    if user is not None and getattr(user, "is_authenticated", False):
        return UsageSubject(
            key=f"user:{user.id}",
            subject_type=TokenQuotaState.SubjectType.USER,
            user_id=user.id,
        )
    cookies = scope.get("cookies", {}) or {}
    session = scope.get("session")
    anon_id = (
        cookies.get(ANON_USAGE_COOKIE_KEY, "")
        or (session.get("guest_id") if session else "")
        or uuid.uuid4().hex
    )
    return UsageSubject(
        key=f"anon:{anon_id}",
        subject_type=TokenQuotaState.SubjectType.ANON,
        anon_id=anon_id,
    )


def _calc_warn_level(used_tokens: int, quota_limit: int) -> int:
    if quota_limit <= 0:
        return 0
    ratio = used_tokens / quota_limit
    if ratio >= 1:
        return 100
    if ratio >= 0.9:
        return 90
    if ratio >= 0.8:
        return 80
    return 0


def _serialize_snapshot(state: TokenQuotaState) -> dict:
    used = int(state.used_tokens)
    limit = int(state.quota_limit or 0)
    remaining = max(limit - used, 0)
    pct = round((used / limit) * 100, 2) if limit > 0 else 0
    warn_level = _calc_warn_level(used, limit)
    return {
        "subject_key": state.subject_key,
        "used_tokens": used,
        "quota_limit": limit,
        "remaining_tokens": remaining,
        "used_percent": pct,
        "warn_level": warn_level,
        "is_exceeded": used >= limit if limit > 0 else False,
    }


def _get_or_create_quota_state(subject: UsageSubject) -> TokenQuotaState:
    defaults = {
        "subject_type": subject.subject_type,
        "user_id": subject.user_id,
        "anon_id": subject.anon_id,
        "quota_limit": _default_quota_limit(),
    }
    state, _created = TokenQuotaState.objects.get_or_create(
        subject_key=subject.key,
        defaults=defaults,
    )
    dirty = False
    if state.quota_limit <= 0:
        state.quota_limit = _default_quota_limit()
        dirty = True
    if state.subject_type != subject.subject_type:
        state.subject_type = subject.subject_type
        dirty = True
    if subject.user_id and state.user_id != subject.user_id:
        state.user_id = subject.user_id
        dirty = True
    if subject.anon_id and state.anon_id != subject.anon_id:
        state.anon_id = subject.anon_id
        dirty = True
    if dirty:
        state.save(update_fields=["quota_limit", "subject_type", "user", "anon_id", "updated_at"])
    return state


def get_quota_snapshot(subject: UsageSubject) -> dict:
    state = _get_or_create_quota_state(subject)
    return _serialize_snapshot(state)


def ensure_within_quota_or_raise(subject: UsageSubject) -> dict:
    snapshot = get_quota_snapshot(subject)
    if snapshot["is_exceeded"]:
        logger.warning(
            "Token quota exceeded subject=%s used=%s limit=%s warn_level=%s",
            snapshot["subject_key"],
            snapshot["used_tokens"],
            snapshot["quota_limit"],
            snapshot["warn_level"],
        )
        raise QuotaExceededError(snapshot)
    return snapshot


def record_token_usage(
    *,
    subject: UsageSubject,
    source: str,
    total_tokens: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    provider: str = "",
    model: str = "",
    discussion: Discussion | None = None,
    metadata: Optional[dict] = None,
) -> dict:
    total = int(total_tokens or 0)
    if total <= 0:
        return get_quota_snapshot(subject)

    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    with transaction.atomic():
        state = (
            TokenQuotaState.objects.select_for_update()
            .filter(subject_key=subject.key)
            .first()
        )
        if state is None:
            state = _get_or_create_quota_state(subject)
            state = TokenQuotaState.objects.select_for_update().get(pk=state.pk)

        previous_warn_level = int(state.last_warn_level or 0)
        TokenUsageLedger.objects.create(
            subject_key=subject.key,
            subject_type=subject.subject_type,
            user_id=subject.user_id,
            anon_id=subject.anon_id,
            discussion=discussion,
            source=source,
            provider=provider or "",
            model=model or "",
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            metadata=metadata or {},
        )
        state.used_tokens += total
        state.last_warn_level = _calc_warn_level(state.used_tokens, state.quota_limit)
        state.save(update_fields=["used_tokens", "last_warn_level", "updated_at"])
        snapshot = _serialize_snapshot(state)
        if snapshot["warn_level"] > previous_warn_level:
            logger.warning(
                "Token quota warn level raised subject=%s source=%s previous=%s current=%s used=%s limit=%s",
                subject.key,
                source,
                previous_warn_level,
                snapshot["warn_level"],
                snapshot["used_tokens"],
                snapshot["quota_limit"],
            )
        return snapshot


def submit_quota_feedback(
    *,
    subject: UsageSubject,
    contact: str = "",
    message: str = "",
) -> QuotaFeedback:
    snapshot = get_quota_snapshot(subject)
    return QuotaFeedback.objects.create(
        subject_key=subject.key,
        subject_type=subject.subject_type,
        user_id=subject.user_id,
        anon_id=subject.anon_id,
        contact=(contact or "").strip(),
        message=(message or "").strip(),
        used_tokens=snapshot["used_tokens"],
        quota_limit=snapshot["quota_limit"],
    )
