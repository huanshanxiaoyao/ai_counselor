import uuid

from django.conf import settings
from django.db import models

from backend.moodpal.models import MoodPalSession


class MoodPalEvalCase(models.Model):
    class CaseType(models.TextChoices):
        DATASET_REAL = 'dataset_real', '真实开源 Case'
        SYNTHETIC_EXTREME = 'synthetic_extreme', '人工极端 Case'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case_id = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=255, blank=True, default='')
    case_type = models.CharField(max_length=24, choices=CaseType.choices)
    source_dataset = models.CharField(max_length=120, blank=True, default='')
    topic_tag = models.CharField(max_length=120, blank=True, default='')
    splits = models.JSONField(default=list, blank=True)
    full_reference_dialogue = models.JSONField(default=list, blank=True)
    first_user_message = models.TextField(blank=True, default='')
    turn_count = models.PositiveIntegerField(default=0)
    risk_hint = models.CharField(max_length=80, blank=True, default='')
    enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')
    source_hash = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'moodpal_eval_cases'
        indexes = [
            models.Index(fields=['case_type', 'enabled', 'updated_at']),
            models.Index(fields=['source_dataset', 'topic_tag']),
        ]

    def __str__(self):
        return self.title or self.case_id


class MoodPalEvalRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待执行'
        RUNNING = 'running', '执行中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        CANCELED = 'canceled', '已取消'

    class TargetMode(models.TextChoices):
        MASTER_GUIDE = 'master_guide', '全能主理人'
        SINGLE_ROLE = 'single_role', '单角色'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    target_mode = models.CharField(max_length=20, choices=TargetMode.choices)
    target_persona_id = models.CharField(max_length=32, choices=MoodPalSession.Persona.choices)
    dataset_split = models.CharField(max_length=64, blank=True, default='')
    selected_case_count = models.PositiveIntegerField(default=0)
    patient_model = models.CharField(max_length=120, blank=True, default='')
    judge_model = models.CharField(max_length=120, blank=True, default='')
    target_model = models.CharField(max_length=120, blank=True, default='')
    max_turns = models.PositiveIntegerField(default=20)
    concurrency = models.PositiveIntegerField(default=4)
    per_turn_timeout_seconds = models.PositiveIntegerField(default=45)
    max_runtime_seconds = models.PositiveIntegerField(default=900)
    max_retries = models.PositiveIntegerField(default=1)
    baseline_run = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='baseline_children',
    )
    threshold_score = models.PositiveSmallIntegerField(default=80)
    gate_passed = models.BooleanField(null=True, blank=True)
    gate_failure_reason = models.TextField(blank=True, default='')
    summary_metrics = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='moodpal_eval_runs',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'moodpal_eval_runs'
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['target_mode', 'target_persona_id', 'created_at']),
        ]

    def __str__(self):
        return self.name or f'EvalRun<{self.id}>'


class MoodPalEvalRunItem(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待执行'
        RUNNING = 'running', '执行中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        ERRORED = 'errored', '异常'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(MoodPalEvalRun, on_delete=models.CASCADE, related_name='items')
    case = models.ForeignKey(MoodPalEvalCase, on_delete=models.CASCADE, related_name='run_items')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    turn_count = models.PositiveIntegerField(default=0)
    stop_reason = models.CharField(max_length=64, blank=True, default='')
    transcript = models.JSONField(default=list, blank=True)
    target_trace = models.JSONField(default=list, blank=True)
    transcript_judge_result = models.JSONField(default=dict, blank=True)
    route_audit_result = models.JSONField(default=dict, blank=True)
    final_scores = models.JSONField(default=dict, blank=True)
    final_score = models.FloatField(default=0)
    hard_fail = models.BooleanField(default=False)
    deduction_reasons = models.JSONField(default=list, blank=True)
    target_token_usage = models.PositiveIntegerField(default=0)
    patient_token_usage = models.PositiveIntegerField(default=0)
    judge_token_usage = models.PositiveIntegerField(default=0)
    total_token_usage = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'moodpal_eval_run_items'
        indexes = [
            models.Index(fields=['run', 'status', 'created_at']),
            models.Index(fields=['run', 'final_score']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['run', 'case'], name='moodpal_eval_unique_case_per_run'),
        ]

    def __str__(self):
        return f'RunItem<{self.run_id}:{self.case_id}>'


class MoodPalEvalTokenLedger(models.Model):
    class Scope(models.TextChoices):
        TARGET = 'target', '目标角色'
        PATIENT = 'patient', '模拟来访者'
        JUDGE = 'judge', '裁判'

    run = models.ForeignKey(MoodPalEvalRun, on_delete=models.CASCADE, related_name='token_ledgers')
    run_item = models.ForeignKey(
        MoodPalEvalRunItem,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='token_ledgers',
    )
    scope = models.CharField(max_length=16, choices=Scope.choices)
    provider = models.CharField(max_length=64, blank=True, default='')
    model = models.CharField(max_length=128, blank=True, default='')
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    request_label = models.CharField(max_length=120, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'moodpal_eval_token_ledger'
        indexes = [
            models.Index(fields=['run', 'scope', 'created_at']),
            models.Index(fields=['run_item', 'created_at']),
        ]

    def __str__(self):
        return f'{self.scope}:{self.total_tokens}'
