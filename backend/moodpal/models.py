import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class MoodPalSession(models.Model):
    class Status(models.TextChoices):
        STARTING = 'starting', '开始中'
        ACTIVE = 'active', '进行中'
        ENDING = 'ending', '结束处理中'
        SUMMARY_PENDING = 'summary_pending', '等待摘要确认'
        CLOSED = 'closed', '已关闭'

    class Persona(models.TextChoices):
        MASTER_GUIDE = 'master_guide', '全能主理人'
        LOGIC_BROTHER = 'logic_brother', '逻辑派的邻家哥哥'
        EMPATHY_SISTER = 'empathy_sister', '共情派的知心学姐'
        INSIGHT_MENTOR = 'insight_mentor', '深挖派的心理学前辈'

    class SummaryAction(models.TextChoices):
        NONE = '', '未处理'
        SAVED = 'saved', '已保存'
        DESTROYED = 'destroyed', '已销毁'

    class CloseReason(models.TextChoices):
        NONE = '', '未结束'
        USER_ENDED = 'user_ended', '用户主动结束'
        IDLE_TIMEOUT = 'idle_timeout', '超时自动结束'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='moodpal_sessions',
    )
    usage_subject = models.CharField(max_length=120, db_index=True)
    anon_id = models.CharField(max_length=64, blank=True, default='')
    persona_id = models.CharField(max_length=32, choices=Persona.choices)
    selected_model = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.STARTING)
    timeout_seconds = models.PositiveIntegerField(default=1800)
    summary_draft = models.TextField(blank=True, default='')
    summary_final = models.TextField(blank=True, default='')
    summary_action = models.CharField(
        max_length=16,
        choices=SummaryAction.choices,
        default=SummaryAction.NONE,
        blank=True,
    )
    close_reason = models.CharField(
        max_length=20,
        choices=CloseReason.choices,
        default=CloseReason.NONE,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'moodpal_sessions'
        indexes = [
            models.Index(fields=['status', 'updated_at']),
            models.Index(fields=['usage_subject', 'created_at']),
        ]

    def __str__(self):
        return f"MoodPalSession<{self.id}> {self.persona_id} {self.status}"


class MoodPalMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user', '用户'
        ASSISTANT = 'assistant', '助手'
        SYSTEM = 'system', '系统'

    session = models.ForeignKey(
        MoodPalSession,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'moodpal_messages'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['session', 'created_at']),
        ]

    def __str__(self):
        return f"MoodPalMessage<{self.id}> {self.role}"


class MoodPalSessionEvent(models.Model):
    class EventType(models.TextChoices):
        CRISIS_TRIGGERED = 'crisis_triggered', '危机抢占已触发'
        SUMMARY_GENERATED = 'summary_generated', '摘要已生成'
        SUMMARY_SAVED = 'summary_saved', '摘要已保存'
        SUMMARY_DESTROYED = 'summary_destroyed', '摘要已销毁'
        RAW_MESSAGES_DESTROYED = 'raw_messages_destroyed', '原始消息已销毁'

    session = models.ForeignKey(
        MoodPalSession,
        on_delete=models.CASCADE,
        related_name='events',
    )
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'moodpal_session_events'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['session', 'event_type', 'created_at']),
        ]

    def __str__(self):
        return f"MoodPalSessionEvent<{self.id}> {self.event_type}"
