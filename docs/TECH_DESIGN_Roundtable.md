# 圆桌会谈 - 技术设计文档

> **版本：** 2.0（2026-04-15 更新，与代码实际实现对齐）
> **关联文档：** `PRD_Roundtable.md`（产品设计），`PRD_DiscussionRoom.md`（讨论室详细设计）

---

## 1. 项目结构

```
backend/
├── config/
│   ├── settings.py          # Django 配置（DEBUG 默认 False，需显式设 DEBUG=True）
│   ├── settings_test.py     # 测试配置（SQLite in-memory，继承 settings.py）
│   ├── urls.py              # 根路由
│   └── asgi.py              # ASGI 入口（WebSocket 必须用 daphne/uvicorn）
├── llm/
│   ├── client.py            # LLMClient 统一接口 + OpenAI/Anthropic Backend
│   ├── providers.py         # ProviderConfig 及环境变量注册表（LLMClient 实际读这里）
│   └── exceptions.py        # LLMError 异常层次
└── roundtable/
    ├── models.py            # Discussion / Character / Message
    ├── consumers.py         # WebSocket Consumer（~1250 行，异步）
    ├── views.py             # HTTP Views（原生 Django，非 DRF）
    ├── urls.py              # HTTP 路由
    ├── routing.py           # WebSocket 路由
    ├── profiles/
    │   ├── base_profiles/   # 离线 JSON 基础设定（按角色名命名）
    │   ├── profile_generator.py
    │   ├── profile_loader.py
    │   ├── cache_manager.py # Redis 缓存（key: {角色名}:{话题}）
    │   └── candidate_queue.py
    └── services/
        ├── director.py      # DirectorAgent：推荐候选角色
        ├── host_agent.py    # HostAgent：主持人开场/邀请/决策
        ├── character.py     # CharacterAgent：角色配置 + 发言生成
        └── auto_continue.py # AutoContinueService：后台自动推进讨论

templates/roundtable/
├── index.html               # Step 1：话题输入
├── setup.html               # Step 2：角色配置
├── discussion.html          # Step 3：实时讨论
└── profiles.html            # 角色设定管理

static/                      # 无前端构建步骤，纯原生 JS + 内联 CSS
```

---

## 2. 数据模型

### Discussion（讨论会话）

```python
class Discussion(models.Model):
    class Status(models.TextChoices):
        SETUP    = 'setup'     # 配置中（未开始）
        READY    = 'ready'     # 就绪（角色已配置）
        ACTIVE   = 'active'    # 进行中
        PAUSED   = 'paused'    # 已暂停
        FINISHED = 'finished'  # 已结束

    class UserRole(models.TextChoices):
        HOST        = 'host'        # 主持人
        PARTICIPANT = 'participant' # 参与者
        OBSERVER    = 'observer'    # 旁观者

    # 基本信息
    topic           = CharField(max_length=500)
    status          = CharField(choices=Status, default=Status.SETUP)
    user_role       = CharField(choices=UserRole, default=UserRole.HOST)

    # 配置参数
    character_limit = IntegerField(default=200)   # 每次发言字数上限
    max_rounds      = IntegerField(default=30)    # 最大轮次（1-200）
    token_timeout_seconds = IntegerField(default=60)

    # 主持人令牌状态（host/observer 模式）
    host_token_holder = CharField(null=True)      # '主持人' 或角色名
    host_token_at     = DateTimeField(null=True)  # 令牌获取时间

    # 玩家令牌状态（participant 模式）
    player_token_holder = CharField(null=True)    # '玩家' 或角色名
    player_token_at     = DateTimeField(null=True)
    player_waiting_for  = CharField(null=True)    # 等待哪个角色回复

    # 进度跟踪
    current_round   = IntegerField(default=0)
    current_speaker = CharField(blank=True)
    init_completed  = BooleanField(default=False) # 初始化阶段是否完成

    # Token 统计
    total_tokens    = IntegerField(default=0)     # 会话累计 LLM token 消耗

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    ended_at   = DateTimeField(null=True)

    class Meta:
        db_table = 'roundtable_discussions'
```

### Character（AI 角色）

```python
class Character(models.Model):
    discussion = ForeignKey(Discussion, on_delete=CASCADE)
    name       = CharField(max_length=100)
    era        = CharField(max_length=50)
    bio        = TextField()                    # 一句话简介
    background = TextField()                    # 详细背景（200 字以内）

    major_works              = JSONField(default=list)
    viewpoints               = JSONField(default=dict)  # {维度: 观点}
    language_style           = JSONField(default=dict)  # {tone, catchphrases, speaking_habits}
    representative_articles  = JSONField(default=list)
    temporal_constraints     = JSONField(default=dict)  # {can_discuss, cannot_discuss, knowledge_cutoff}

    message_count        = IntegerField(default=0)
    consecutive_mentions = IntegerField(default=0)
    speaking_order       = IntegerField(default=0)

    # 可为每个角色独立指定 LLM（留空则用项目默认）
    llm_provider = CharField(null=True, blank=True)
    llm_model    = CharField(null=True, blank=True)

    class Meta:
        db_table = 'roundtable_characters'
        ordering = ['speaking_order']
        constraints = [
            UniqueConstraint(fields=['discussion', 'name'],
                             name='unique_character_per_discussion')
        ]
```

### Message（讨论消息）

```python
class Message(models.Model):
    discussion = ForeignKey(Discussion, on_delete=CASCADE)
    character  = ForeignKey(Character, null=True, on_delete=CASCADE)

    content    = TextField()
    word_count = IntegerField(default=0)

    is_moderator = BooleanField(default=False)  # 主持人消息
    is_system    = BooleanField(default=False)  # 系统消息
    is_user      = BooleanField(default=False)  # 用户消息

    # participant 模式专用
    player_mentioned_character = CharField(null=True)
    read_but_no_reply          = BooleanField(default=False)

    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'roundtable_messages'
        ordering = ['created_at']
```

---

## 3. LLM 客户端层（`backend/llm/`）

### 调用入口

`LLMClient` 是唯一调用入口，根据 `provider.sdk_type` 分派到不同 Backend：

| sdk_type | Backend | 适用 Provider |
|----------|---------|--------------|
| `"openai"`（默认） | `OpenAIBackend` | Qwen、DeepSeek、Doubao、OpenAI |
| `"anthropic"` | `AnthropicBackend` | MiniMax（Claude API 格式） |

Provider 注册表在 `providers.py`（`settings.py` 中的 `LLM_PROVIDERS` 未被 `LLMClient` 使用，仅供参考）。

### 重试策略

```
LLMTimeoutError（网络超时/连接断开）→ 重试，指数退避
LLMAPIError (status=400/401/403/404) → 立即抛出，不重试（auth/bad request）
LLMAPIError (status=429/5xx)         → 重试，指数退避
```

最大重试次数由 `LLM_MAX_RETRIES` 环境变量控制（默认 3）。

### 主要方法

```python
client = LLMClient(provider_name="qwen")

# 只返回文本
text = client.complete(prompt, system_prompt=None, model=None, json_mode=False)

# 返回完整元数据（含 token 用量、耗时）
result: CompletionResult = client.complete_with_metadata(...)
result.text            # str
result.usage.total_tokens
result.elapsed_seconds
```

---

## 4. Agent 设计

### 4.1 DirectorAgent（`services/director.py`）

根据话题通过 LLM 推荐候选历史人物列表。

**核心方法：**
- `suggest_characters(topic, count=20)` → `list[dict]`（含 name, era, reason）

**注意：** 调用方需自行检查返回列表长度（LLM 可能返回少于 count 的结果）。

---

### 4.2 HostAgent（`services/host_agent.py`）

AI 主持人，负责控场、邀请和决策。

**核心方法：**

| 方法 | 说明 |
|------|------|
| `generate_opening(topic, characters, user_role)` | 生成开场白 |
| `generate_invitation(character_name, topic, conversation_history, transition)` | 生成邀请语 |
| `decide_next_speaker(characters, last_speaker, history, topic, use_llm, round_count)` | 决定下一位发言者 |
| `generate_closing(topic, characters, history)` | 生成结束语 |
| `should_respond_to_player(player_message, history)` | 判断是否回应参与者发言 |

**发言者决策机制：**

```
初始化阶段（round <= 角色数量）：
  → 按 speaking_order 轮询，不调用 LLM

LLM 决策阶段（round > 角色数量）：
  → 调用 LLM，分析历史决定：邀请谁、如何承上启下
  → 返回 (next_speaker_name, transition_sentence)
```

---

### 4.3 CharacterAgent（`services/character.py`）

负责生成角色配置（profile）和运行时发言。

**核心方法：**

| 方法 | 说明 |
|------|------|
| `configure_character(character, topic, era)` | 生成角色的详细 profile |
| `generate_speech(character_config, topic, history, invitation, character_limit)` | 生成角色发言 |
| `should_respond_to_player(character_config, player_message, history)` | 判断是否回应 participant |
| `generate_decline_response(character_config, player_message)` | 生成礼貌婉拒 |
| `has_offline_profile(name)` | 检查是否有离线基础设定 |

**话题设定缓存：**
- 缓存 key：`{角色名}:{话题}`，存于 Redis
- 配置时先查缓存，命中则跳过 LLM 调用
- 离线基础设定存于 `profiles/base_profiles/{角色名}.json`

---

### 4.4 AutoContinueService（`services/auto_continue.py`）

以后台线程方式自动推进讨论，消除 host/observer 模式下对手动触发的依赖。

**启动方式：**
```python
# views.py - DiscussionStartView.post()
thread = threading.Thread(target=service.run, daemon=True)
thread.start()
```

**主循环逻辑：**

```
while 未达到 max_rounds 且 status == 'active':
    if current_round <= 角色数量:
        初始化阶段：按顺序邀请角色（不用 LLM 决策）
    else:
        LLM 决策阶段：HostAgent.decide_next_speaker()
    
    生成邀请语 → 角色发言 → 广播 → sleep(1)

→ 达到最大轮次后调用 HostAgent.generate_closing()
```

**注意（已知限制）：**
- AutoContinueService 和 DiscussionConsumer 并发写入同一 Discussion 行，`current_round` 修改存在竞态条件（待以原子操作优化）
- `time.sleep(1)` 固定间隔，未根据 LLM 响应时间动态调整

---

## 5. 发言权管理（令牌制）

### 5.1 令牌类型

| 令牌 | 模式 | 持有者初始值 | 说明 |
|------|------|------------|------|
| 主持人令牌 | host / observer | `'主持人'` | 控制 AI 角色轮流发言 |
| 玩家令牌 | participant | `'玩家'` | 处理用户 @ 特定角色 |

### 5.2 主持人令牌流程（host 模式）

```
[主持人] 持有令牌
    ↓ 用户 @角色A 或 AutoContinue 决策
[角色A] 获得令牌 → LLM 生成发言
    ↓
[主持人] 收回令牌 → HostAgent 决定下一轮
    ↓
[角色B] 获得令牌 → ...
```

### 5.3 玩家令牌流程（participant 模式）

```
情况A：参与者无 @
  → 发言显示，AI 主持人决定是否 @某角色
  → 主持人令牌流转

情况B：参与者 @角色A
  → 玩家令牌转移给角色A
  → 角色A 判断是否回应（can decline）
  → 回应或婉拒后，玩家令牌归还
```

### 5.4 令牌超时自动释放

每次 WebSocket `poll` 请求时触发 `_release_expired_tokens()`：

```python
# 超时判断：token_at + token_timeout_seconds < now
# 主持人令牌：非'主持人'持有超时 → 归还给'主持人'
# 玩家令牌：非'玩家'持有超时 → 归还给'玩家'，清空 player_waiting_for
```

### 5.5 发言权规则

| 规则 | 说明 |
|------|------|
| 令牌独占 | 只有持有令牌的角色才能发言 |
| 令牌超时 | `token_timeout_seconds`（默认 60 秒）未使用自动归还 |
| 连续@限制 | 同一角色 `consecutive_mentions` 超过 2 次，降低被邀请优先级 |
| 角色自主权 | 角色可礼貌婉拒 participant 的 @（通过 `should_respond_to_player` 决策） |

---

## 6. HTTP API（`views.py`）

> 所有 View 均为原生 Django View（非 DRF），返回 JsonResponse。

### 路由表（`/roundtable/`）

| 方法 | 路径 | View | 功能 |
|------|------|------|------|
| GET | `/roundtable/` | IndexView | 话题输入页面 |
| GET | `/roundtable/setup/` | SetupView | 角色配置页面 |
| GET | `/roundtable/d/<id>/` | DiscussionView | 讨论页面 |
| GET | `/roundtable/profiles/` | ProfilesView | 角色设定管理 |
| POST | `/roundtable/api/suggestions/` | SuggestionView | DirectorAgent 推荐候选角色 |
| POST | `/roundtable/api/configure/` | ConfigureView | 生成角色详细配置（并行） |
| POST | `/roundtable/api/start/` | DiscussionStartView | 创建讨论，生成开场白，启动 AutoContinue |
| POST | `/roundtable/api/message/` | DiscussionMessageView | 用户发言（非 WebSocket 路径） |
| GET | `/roundtable/api/poll/<id>/` | DiscussionPollView | 轮询讨论状态 |
| GET | `/roundtable/api/history/` | DiscussionHistoryView | 历史讨论列表 |
| POST | `/roundtable/api/restart/<id>/` | DiscussionRestartView | 复制配置重新开始 |
| GET | `/roundtable/api/profiles/` | ProfileListView | 角色设定列表 |
| POST | `/roundtable/api/candidates/enqueue/` | CandidateEnqueueView | 加入候选队列 |

### 角色配置并行机制（ConfigureView）

```python
# views.py - ConfigureView.post()
with ThreadPoolExecutor(max_workers=min(len(characters), 5)) as executor:
    futures = {executor.submit(configure_one, char): char for char in characters}
    for future in as_completed(futures):
        result = future.result()  # CharacterAgent.configure_character()
```

---

## 7. WebSocket（`consumers.py`）

### 连接路由

```
ws://.../ws/discussion/<discussion_id>/
```

Group name: `discussion_<discussion_id>`

### 消息类型（客户端 → 服务端）

| type | 说明 |
|------|------|
| `user_message` | 用户发言（content 字段） |
| `poll` | 轮询当前状态（触发令牌超时检查） |
| `typing_start` | 用户开始输入 |
| `typing_end` | 用户停止输入 |

### 消息类型（服务端 → 客户端）

| type | 说明 |
|------|------|
| `initial_state` | 连接时推送完整初始状态 |
| `message` | 新消息（speaker, content, is_moderator, is_user） |
| `state_update` | 状态变化（status, current_round, token holders） |
| `poll_response` | 响应 poll 请求 |
| `error` | 错误消息 |
| `system_message` | 系统通知（令牌超时释放等） |
| `debug_info` | 调试信息（仅开发用） |
| `typing` / `typing_end` | 输入状态广播 |

### 用户角色处理逻辑

```
receive(text_data)
  ├─ host     → _handle_host_message()
  │              ├─ 保存为"主持人"消息
  │              ├─ 若 @角色 → _get_character_response()
  │              └─ 触发 _auto_continue_discussion()
  ├─ participant → _handle_participant_message()
  │              ├─ 保存为"你"的消息
  │              ├─ 情况A（无@）→ 主持人决定是否接话
  │              └─ 情况B（@角色）→ _get_character_response_with_decline()
  └─ observer → 拒绝发言
```

### @mention 解析

`parse_mention(message)` 位于 `consumers.py` 顶部：

```python
# 主模式：匹配中文角色名（含中点·），后接特定分隔符
pattern = r'^@([\u4e00-\u9fa5·]+)(?:[（\-—""''\s]|$)(.*)$'

# fallback：匹配任意非空白字符（更宽松）
pattern_fallback = r'^@(\S+)\s*(.*)$'
```

返回 `{has_mention: bool, target: str|None, content: str}`。

---

## 8. 环境配置

### 必需环境变量

```bash
# LLM API Keys（至少一个）
QWEN_API_KEY=...
DEEPSEEK_API_KEY=...
ANTHROPIC_API_KEY=...    # MiniMax 使用
DOUBAO_API_KEY=...

# 默认 Provider
LLM_DEFAULT_PROVIDER=qwen   # qwen / deepseek / minimax / doubao

# 生产必须设置
DEBUG=False
DJANGO_SECRET_KEY=...        # 生产环境必须设置，否则启动失败
ALLOWED_HOSTS=yourdomain.com

# 可选
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
LLM_TIMEOUT=12               # 单次 LLM 调用超时（秒）
LLM_MAX_RETRIES=3
```

### 开发启动

```bash
# 需要 ASGI（WebSocket 必须）
cd backend && daphne -p 8000 backend.config.asgi:application

# 无 WebSocket 的简单开发
cd backend && python manage.py runserver

# 数据库迁移
cd backend && python manage.py migrate
```

### Redis（可选）

- 有 Redis：使用 RedisChannelLayer（支持多进程）+ 角色设定缓存
- 无 Redis：自动降级为 InMemoryChannelLayer（单进程），缓存关闭
- 检测逻辑：`settings.py` 中 ping Redis，失败则降级（会打印警告日志）

---

## 9. 已知架构限制（待优化）

| 问题 | 影响 | 优化方向 |
|------|------|---------|
| LLM 同步调用在 `@database_sync_to_async` 线程池内执行 | 长时间 LLM 调用耗尽数据库连接线程 | 拆分为独立 `sync_to_async` 调用 |
| AutoContinueService（后台线程）与 Consumer（ASGI）并发写 Discussion | current_round 竞态，可能重复计数 | 改为原子操作 `F('current_round') + 1` |
| 无 WebSocket 重连机制 | 网络断开后客户端静默失联 | 前端实现指数退避重连 |
| AutoContinueService 使用固定 sleep(1) | LLM 响应慢时积压，响应快时浪费 | 动态间隔或事件驱动 |
| 无速率限制 | 单用户可大量消耗 LLM 配额 | 接入 django-ratelimit |

---

## 10. 测试

```bash
# 项目根目录
pytest tests/ -v

# backend 内部测试
pytest backend/ -v

# 单个文件
pytest tests/test_api.py::TestClass::test_method -v
```

测试使用 `settings_test`（SQLite in-memory），由 `pytest.ini` 指定。

**当前覆盖范围：** DirectorAgent、CharacterAgent 单元测试（mock LLM）。  
**待补充：** WebSocket Consumer 集成测试、AutoContinueService 并发测试、错误路径测试。
