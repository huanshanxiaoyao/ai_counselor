"""
Database models for Roundtable Discussion.
"""
from django.conf import settings
from django.db import models


class Discussion(models.Model):
    """讨论会话"""

    class Status(models.TextChoices):
        SETUP = 'setup', '配置中'
        READY = 'ready', '就绪'
        ACTIVE = 'active', '进行中'
        PAUSED = 'paused', '已暂停'
        FINISHED = 'finished', '已结束'

    class UserRole(models.TextChoices):
        HOST = 'host', '主持人'
        PARTICIPANT = 'participant', '参与者'
        OBSERVER = 'observer', '旁观者'

    # 基本信息
    topic = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SETUP
    )
    user_role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.HOST
    )

    # 配置
    character_limit = models.IntegerField(default=200)
    max_rounds = models.IntegerField(default=30)
    token_timeout_seconds = models.IntegerField(default=60)  # 令牌超时时间

    # 主持人令牌状态
    host_token_holder = models.CharField(max_length=100, null=True, blank=True)  # 当前持有者
    host_token_at = models.DateTimeField(null=True, blank=True)  # 获得令牌时间

    # 玩家令牌状态（仅participant模式）
    player_token_holder = models.CharField(max_length=100, null=True, blank=True)
    player_token_at = models.DateTimeField(null=True, blank=True)
    player_waiting_for = models.CharField(max_length=100, null=True, blank=True)  # 等待谁回复

    # 初始化状态
    init_completed = models.BooleanField(default=False)  # 初始化轮询是否完成

    # 当前状态
    current_round = models.IntegerField(default=0)
    current_speaker = models.CharField(max_length=100, blank=True)

    # Token 统计
    total_tokens = models.IntegerField(default=0)  # 会话累计消耗 tokens

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Visibility(models.TextChoices):
        PUBLIC = 'public', '公开'
        PRIVATE = 'private', '仅自己可见'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='discussions',
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )

    class Meta:
        db_table = 'roundtable_discussions'

    def __str__(self):
        return f"讨论: {self.topic}"


class Character(models.Model):
    """角色配置模板（用于存储已配置的角色）"""

    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name='characters'
    )

    # 基础信息
    name = models.CharField(max_length=100)
    era = models.CharField(max_length=50)
    bio = models.TextField(blank=True)
    background = models.TextField(blank=True)

    # 角色设定
    major_works = models.JSONField(default=list)
    viewpoints = models.JSONField(default=dict)
    language_style = models.JSONField(default=dict)
    representative_articles = models.JSONField(default=list)

    # 时代约束
    temporal_constraints = models.JSONField(default=dict)

    # 发言统计
    message_count = models.IntegerField(default=0)
    consecutive_mentions = models.IntegerField(default=0)  # 连续被@次数

    # LLM 配置（为空则使用项目默认）
    llm_provider = models.CharField(max_length=50, blank=True, null=True)
    llm_model = models.CharField(max_length=100, blank=True, null=True)

    # 顺序
    speaking_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'roundtable_characters'
        ordering = ['speaking_order']
        constraints = [
            models.UniqueConstraint(fields=['discussion', 'name'], name='unique_character_per_discussion')
        ]

    def __str__(self):
        return f"{self.name}（{self.era}）"


class Message(models.Model):
    """讨论消息"""

    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='messages',
        null=True,
        blank=True
    )

    content = models.TextField()
    word_count = models.IntegerField(default=0)

    # 消息类型
    is_moderator = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)
    is_user = models.BooleanField(default=False)

    # 玩家@相关
    player_mentioned_character = models.CharField(max_length=100, null=True)  # 玩家@的角色
    read_but_no_reply = models.BooleanField(default=False)  # 已读未回标记

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'roundtable_messages'
        ordering = ['created_at']

    def __str__(self):
        speaker = self.character.name if self.character else '系统'
        return f"{speaker}: {self.content[:50]}..."