# 圆桌会谈 - 技术设计文档

## 1. 项目结构

```
backend/
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── asgi.py
├── llm/
│   └── client.py              # LLM Client 统一接口
└── roundtable/                # 圆桌会谈 App
    ├── __init__.py
    ├── apps.py
    ├── consumers.py           # WebSocket Consumers
    ├── models.py              # 数据模型
    ├── routing.py             # WebSocket 路由
    ├── urls.py                # URL 路由
    ├── views.py               # API Views (原生 Django)
    ├── profiles/              # 角色设定管理
    │   ├── __init__.py
    │   ├── base_profiles/     # 离线基础设定存储
    │   ├── cache_manager.py   # 话题设定缓存
    │   ├── candidate_queue.py # 候选队列
    │   ├── profile_generator.py
    │   └── profile_loader.py
    └── services/
        ├── __init__.py
        ├── director.py        # 导演 Agent
        ├── host_agent.py      # 主持人 Agent
        ├── character.py       # 角色 Agent
        └── auto_continue.py   # 自动继续服务

templates/
└── roundtable/
    ├── index.html             # 话题设置页面
    ├── setup.html             # 角色配置页面
    ├── discussion.html        # 讨论页面
    └── profiles.html          # 角色设定管理页面
```

## 2. 数据库模型

### 2.1 模型定义

```python
# roundtable/models.py

from django.db import models


class Discussion(models.Model):
    """讨论会话"""

    class Status(models.TextChoices):
        ACTIVE = 'active', '进行中'
        PAUSED = 'paused', '已暂停'
        FINISHED = 'finished', '已结束'

    class UserRole(models.TextChoices):
        HOST = 'host', '主持人'
        PARTICIPANT = 'participant', '参与者'
        OBSERVER = 'observer', '旁观者'

    # 基本信息
    topic = models.CharField(max_length=500)

    # 配置
    user_role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.PARTICIPANT
    )
    character_limit = models.IntegerField(default=200)
    max_rounds = models.IntegerField(default=20)

    # 状态
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )
    current_round = models.IntegerField(default=0)
    current_speaker = models.CharField(max_length=100, blank=True)
    init_completed = models.BooleanField(default=False)

    # 令牌机制
    host_token_holder = models.CharField(max_length=100, null=True, blank=True)
    player_token_holder = models.CharField(max_length=100, null=True, blank=True)

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'roundtable_discussions'


class Character(models.Model):
    """讨论参与者（角色）"""

    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name='characters'
    )

    # 基本信息
    name = models.CharField(max_length=100)
    era = models.CharField(max_length=50)

    # 详细设定
    bio = models.TextField(help_text="一句话简介")
    background = models.TextField(help_text="详细背景")
    major_works = models.JSONField(default=list)
    viewpoints = models.JSONField(default=dict)
    language_style = models.JSONField(default=dict)
    representative_articles = models.JSONField(default=list)
    temporal_constraints = models.JSONField(default=dict)

    # 发言统计
    speaking_order = models.IntegerField(default=0)
    message_count = models.IntegerField(default=0)
    consecutive_mentions = models.IntegerField(default=0)

    class Meta:
        db_table = 'roundtable_characters'
        ordering = ['speaking_order']


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
    word_count = models.IntegerField()

    # 消息类型标记
    is_moderator = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)
    is_user = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'roundtable_messages'
        ordering = ['created_at']
```

## 3. Agent 设计

### 3.1 Director Agent (`services/director.py`)

根据话题通过 LLM 生成候选角色列表。直接使用 `LLMClient`，无基类继承。

**核心方法：**
- `suggest_characters(topic, count=20)` → 返回推荐角色列表

### 3.2 Host Agent (`services/host_agent.py`)

AI 主持人，负责控场和引导讨论。

**核心方法：**
- `generate_opening(topic, characters, user_role)` → 生成开场白
- `generate_invitation(character_name, topic, ...)` → 生成邀请语
- `decide_next_speaker(characters, last_speaker, ...)` → 决定下一位发言者
- `decide_next_with_llm(...)` → LLM 智能决策（承上启下）
- `generate_closing(topic, characters, ...)` → 生成结束语
- `should_respond_to_player(...)` → 判断是否回应玩家

**决策机制：**
- 初始化阶段（Round ≤ 角色数量）：按顺序轮询
- LLM 决策阶段（Round > 角色数量）：每轮使用 LLM 决策下一位发言者

### 3.3 Character Agent (`services/character.py`)

角色配置和发言生成。

**核心方法：**
- `configure_character(character, topic, era)` → 生成完整角色配置
- `generate_speech(character_config, topic, ...)` → 生成角色发言
- `has_offline_profile(name)` → 检查是否有离线基础设定
- `get_cache_stats()` → 获取话题设定缓存统计

**话题设定缓存：**
- 使用 Redis 缓存角色话题设定（key: `{character_name}:{topic}`）
- 配置时优先检查缓存，命中则跳过 LLM 调用
- `configure_character` 返回 `_cached` 字段标识缓存命中状态

### 3.4 Auto Continue Service (`services/auto_continue.py`)

自动继续讨论的后台服务。

**工作流程：**
1. 初始化阶段：按顺序邀请每个角色发言
2. LLM 决策阶段：每轮使用 LLM 决策下一位发言者
3. 达到最大轮次后自动结束讨论

## 4. 发言权管理 - 令牌制

### 4.1 令牌类型

| 令牌类型 | 持有者 | 说明 |
|----------|--------|------|
| **主持人令牌** | 主持人 | 控制AI角色发言顺序 |
| **玩家令牌** | 玩家(participant) | 玩家主动@角色时使用 |

### 4.2 主持人令牌流程

```
[主持人]持有令牌
    ↓ @角色A 邀请发言
[角色A]获得令牌 → 发言 → @主持人 归还令牌
    ↓
[主持人]收回令牌
    ↓
[主持人]调用LLM决策下一轮
    ↓ @角色B 邀请发言
[角色B]获得令牌 → ...
```

### 4.3 LLM决策下一轮

主持人收回令牌后，调用LLM分析历史决定：
- **邀请谁**：选择与上一轮观点相关或未充分发言的角色
- **如何承上启下**：总结上一轮观点，自然过渡

```python
# host_agent.py - 决策逻辑
def decide_next_with_llm(self, characters, history, last_speaker, topic):
    """
    LLM智能决策（每3-5轮调用一次）
    平时使用规则轮询节省成本
    """
    prompt = f"""分析以下讨论历史，决定下一轮邀请谁发言：

话题：{topic}
最后发言：{last_speaker}
讨论历史：
{history}

请决定：
1. 邀请谁发言？（选择与上一轮观点相关或发言较少的角色）
2. 如何承上启下？（用一句话概括）

回复格式：{{"invite": "角色名", "transition": "过渡语"}}
"""
```

### 4.4 玩家令牌流程

```
[玩家]持有独立令牌
    ↓ @角色A
[角色A]获得令牌 → 判断是否发言（可礼貌婉拒）→ @玩家 归还令牌
    ↓
[玩家]收回令牌（继续参与或旁观）
```

### 4.5 令牌状态字段

```python
# Discussion模型增加字段
class Discussion(models.Model):
    # 主持人令牌状态
    host_token_holder = models.CharField(max_length=100, null=True)  # 当前持有者
    host_token_at = models.DateTimeField(null=True)  # 获得令牌时间

    # 玩家令牌状态（仅participant模式）
    player_token_holder = models.CharField(max_length=100, null=True)
    player_token_at = models.DateTimeField(null=True)

    # 配置
    token_timeout_seconds = models.IntegerField(default=60)  # 令牌超时
```

### 4.6 发言权规则

| 规则 | 说明 |
|------|------|
| 主持人令牌 | 只有主持人@的角色才能发言 |
| 玩家令牌 | 玩家@的角色才能响应玩家 |
| 令牌超时 | 60秒未使用自动归还 |
| 连续@限制 | 同一角色连续被@最多2次 |
| 角色自主权 | 角色可礼貌婉拒玩家@（保持角色一致性） |

## 5. Prompt 模板

```python
# roundtable/agents/prompts.py

DIRECTOR_SYSTEM_PROMPT = """你是一位经验丰富的导演，负责为圆桌讨论挑选最合适的角色。

你的职责：
1. 深入理解讨论话题的核心意图
2. 根据话题特点，推荐最合适的角色组合
3. 确保角色之间有观点的多样性和碰撞空间
4. 考虑角色的时代背景、专业领域与话题的相关性

推荐角色时考虑：
- 角色的专业背景与话题的匹配度
- 角色之间的观点差异和思想碰撞
- 角色扮演的难度（某些角色较难扮演）
- 讨论的深度和广度需求

你的推荐应该既有广度又有深度，既考虑学术严谨性也考虑趣味性。"""

MODERATOR_SYSTEM_PROMPT = """你是一位专业、中立的主持人，负责主持圆桌讨论。

你的职责：
1. 开场：介绍话题、参与者和讨论规则
2. 控场：确保讨论围绕主题，不跑题
3. 平衡：让每位参与者都有发言机会
4. 引导：当讨论偏离主题时适时拉回
5. 总结：适时进行阶段性总结
6. 收尾：生成最终总结

你的风格：
- 中立：不表达自己的观点
- 引导性：多用提问引导讨论
- 简洁：发言简短有力
- 礼貌：维护良好的讨论氛围

发言权管理规则：
- 当有人请求发言时，根据讨论情况决定是否授权
- 确保每次只有一人发言
- 注意平衡各方的发言机会"""

CHARACTER_SYSTEM_PROMPT = """你扮演角色：{name}

角色简介：{bio}

背景信息：{background}

语言风格：
- 语气：{language_style.get('tone', '中性')}
- 常用表达：{language_style.get('catchphrases', [])}
- 避免的话题/表达：{forbidden_topics}

知识边界：{knowledge_cutoff}

重要规则：
1. 始终保持角色设定，用角色的视角和语气说话
2. 控制在 {character_limit} 字以内
3. 如果被问到角色不了解的话题，诚实地表示不知道
4. 积极参与讨论，回应其他角色的观点
5. 用 @主持人 结束发言，表示发言权交回
6. 不要主动打断他人，除非讨论严重跑题

请开始扮演这个角色参与讨论。"""
```

## 5. API 设计

### 5.1 Views

```python
# roundtable/views.py

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import render

from .models import Character, Discussion, DiscussionParticipant, Message
from .serializers import (
    CharacterSerializer,
    DiscussionSerializer,
    MessageSerializer,
)
from .services.director import DirectorAgent
from .services.moderator import ModeratorAgent


class DiscussionViewSet(viewsets.ModelViewSet):
    """讨论管理"""

    queryset = Discussion.objects.all()
    serializer_class = DiscussionSerializer

    @action(detail=False, methods=['post'])
    def setup(self, request):
        """创建讨论并获取角色推荐"""
        topic = request.data.get('topic')
        discussion_type = request.data.get('discussion_type', 'seminar')
        user_role = request.data.get('user_role', 'moderator')

        # 创建讨论
        discussion = Discussion.objects.create(
            topic=topic,
            discussion_type=discussion_type,
            user_role=user_role
        )

        # 导演 Agent 推荐角色
        director = DirectorAgent()
        suggestions = director.suggest_characters(topic, discussion_type)

        return Response({
            'discussion_id': discussion.id,
            'suggestions': suggestions
        })

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """开始讨论"""
        discussion = self.get_object()

        # 更新状态
        discussion.status = 'active'
        discussion.save()

        # 创建主持人 Agent
        moderator = ModeratorAgent()
        participants = discussion.participants.all()

        # 生成开场白
        opening = moderator.generate_opening(
            topic=discussion.topic,
            participants=[
                {'display_name': p.display_name}
                for p in participants
            ],
            user_role=discussion.user_role
        )

        # 保存主持人开场消息
        moderator_participant = participants.filter(is_moderator=True).first()
        if moderator_participant:
            Message.objects.create(
                discussion=discussion,
                participant=moderator_participant,
                content=opening,
                word_count=len(opening),
                is_moderator_message=True
            )

        return Response({
            'status': 'active',
            'opening': opening
        })

    @action(detail=True, methods=['post'])
    def message(self, request, pk=None):
        """发送消息"""
        discussion = self.get_object()
        content = request.data.get('content')
        participant_id = request.data.get('participant_id')

        participant = DiscussionParticipant.objects.get(id=participant_id)

        # 保存消息
        message = Message.objects.create(
            discussion=discussion,
            participant=participant,
            content=content,
            word_count=len(content)
        )

        # 更新发言统计
        participant.message_count += 1
        participant.save()

        return Response(MessageSerializer(message).data)


class CharacterViewSet(viewsets.ReadOnlyModelViewSet):
    """角色管理"""

    queryset = Character.objects.all()
    serializer_class = CharacterSerializer

    @action(detail=False, methods=['get'])
    def search(self, request):
        """搜索角色"""
        q = request.query_params.get('q', '')
        era = request.query_params.get('era', '')

        queryset = self.queryset
        if q:
            queryset = queryset.filter(name__icontains=q)
        if era:
            queryset = queryset.filter(era=era)

        return Response(CharacterSerializer(queryset, many=True).data)
```

### 5.2 URLs

```python
# roundtable/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'discussions', views.DiscussionViewSet)
router.register(r'characters', views.CharacterViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('roundtable/', views.SetupView.as_view(), name='roundtable_setup'),
    path('roundtable/d/<int:discussion_id>/', views.DiscussionView.as_view(), name='roundtable_discussion'),
]
```

## 6. WebSocket 设计

```python
# roundtable/websocket/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async


class DiscussionConsumer(AsyncWebsocketConsumer):
    """讨论 WebSocket Consumer"""

    async def connect(self):
        self.discussion_id = self.scope['url_route']['kwargs']['discussion_id']
        self.room_group_name = f'discussion_{self.discussion_id}'

        # 加入房间组
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # 离开房间组
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """接收消息"""
        data = json.loads(text_data)
        message_type = data.get('type')

        if message_type == 'user_message':
            await self.handle_user_message(data)
        elif message_type == 'request_speaking_rights':
            await self.handle_speaking_request(data)
        elif message_type == 'grant_speaking_rights':
            await self.handle_grant_speaking_rights(data)

    async def handle_user_message(self, data):
        """处理用户消息"""
        content = data['content']
        participant_id = data['participant_id']

        # 保存消息到数据库
        message = await self.save_message(participant_id, content)

        # 广播消息
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message
            }
        )

        # 如果是角色，生成回复
        if not data.get('is_user'):
            await self.generate_character_response(message)

    async def generate_character_response(self, user_message):
        """生成角色回复"""
        # 调用角色 Agent 生成回复
        # ...

        # 广播角色回复
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'character_message',
                'content': '...',
                'speaker': '...'
            }
        )

    async def chat_message(self, event):
        """发送聊天消息到 WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': event['message']
        }))

    async def character_message(self, event):
        """发送角色消息到 WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'character_message',
            'content': event['content'],
            'speaker': event['speaker']
        }))

    async def speaking_rights_update(self, event):
        """发言权更新"""
        await self.send(text_data=json.dumps({
            'type': 'speaking_rights_update',
            'granted_to': event['granted_to'],
            'revoked_from': event.get('revoked_from')
        }))
```

## 7. 前端页面结构

```
templates/
├── common/
│   └── base.html              # 基础模板
├── home/
│   └── index.html             # 首页
└── roundtable/
    ├── index.html             # 话题设置页面
    ├── setup.html             # 角色配置页面
    ├── discussion.html        # 讨论页面
    └── profiles.html          # 角色设定管理页面

static/
└── css/
    └── style.css              # 全局样式
```

**技术栈：**
- Django 模板引擎
- 原生 JavaScript（无框架）
- WebSocket 客户端（原生 WebSocket API）
- CSS（内联样式为主）

---

## 8. 实施状态

### 已完成

- [x] 基础框架
  - [x] 创建 roundtable Django app
  - [x] 定义数据模型
  - [x] 基础 API Views
- [x] Agent 实现
  - [x] Director Agent
  - [x] Host Agent
  - [x] Character Agent
  - [x] Auto Continue Service
- [x] 前端页面
  - [x] 话题设置页面
  - [x] 角色配置页面
  - [x] 讨论页面
  - [x] 角色设定管理页面
- [x] 实时通信
  - [x] WebSocket 集成
  - [x] 实时消息
  - [x] 发言权控制（双令牌机制）
- [x] 增强功能
  - [x] Redis 缓存（话题设定）
  - [x] 离线基础设定管理
  - [x] 历史讨论列表
  - [x] 讨论导出功能

### 技术说明

**已实现的优化：**
1. 话题设定缓存：角色配置结果缓存到 Redis，减少 LLM 调用
2. 离线基础设定：候选角色自动加入队列并生成离线设定
3. 自动继续服务：开场后自动引导讨论，无需用户手动触发
4. 双令牌机制：主持人令牌控制 AI 发言，玩家令牌处理用户@指令
5. Redis 持久化：通过 AOF 确保缓存数据不丢失

**代码结构特点：**
- 原生 Django Views + JsonResponse（非 DRF）
- Django 模板引擎（非 React）
- Agent 直接使用 LLMClient（无基类继承）
- WebSocket Consumer 内联数据库操作
