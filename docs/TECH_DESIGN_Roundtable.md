# 圆桌会谈技术设计（代码对齐版）

> 对齐范围：`backend/roundtable/*`、`backend/config/*`、`templates/roundtable/*`
> 更新时间：2026-04-20

## 1. 模块结构

```text
backend/roundtable/
├── models.py               # Discussion / Character / Message
├── views.py                # HTTP 页面 + API
├── urls.py                 # roundtable 路由
├── consumers.py            # WebSocket 讨论消费端
├── routing.py              # WS 路由
├── services/
│   ├── director.py         # 推荐与手动嘉宾评审
│   ├── character.py        # 角色配置/发言/婉拒
│   ├── host_agent.py       # 主持人开场/邀请/决策/总结
│   ├── auto_continue.py    # 后台自动推进线程
│   └── token_quota.py      # token 记账/配额/反馈
└── profiles/
    ├── base_profiles/      # 离线人物设定 JSON
    ├── profile_loader.py
    ├── profile_generator.py
    ├── cache_manager.py    # 话题缓存
    └── candidate_queue.py  # 候选队列
```

## 2. 数据模型

### 2.1 Discussion

关键字段：

- `topic`, `status`, `user_role`
- `character_limit`, `max_rounds`, `token_timeout_seconds`
- `host_token_holder`, `host_token_at`
- `player_token_holder`, `player_token_at`, `player_waiting_for`
- `current_round`, `current_speaker`, `init_completed`, `total_tokens`
- `owner(FK, nullable)`, `visibility(public/private)`

状态枚举：`setup | ready | active | paused | finished`

### 2.2 Character

- 与 `Discussion` 多对一
- 核心设定：`bio/background/viewpoints/language_style/temporal_constraints`
- 统计字段：`message_count`, `consecutive_mentions`, `speaking_order`
- 支持独立模型：`llm_provider`, `llm_model`
- 唯一约束：`(discussion, name)`

### 2.3 Message

- 可指向 `character`（主持人/系统消息可为空）
- 标记位：`is_moderator`, `is_system`, `is_user`
- participant 相关：`player_mentioned_character`, `read_but_no_reply`

### 2.4 TokenQuotaState / TokenUsageLedger / QuotaFeedback

- `TokenQuotaState`：主体累计状态（`subject_key`, `used_tokens`, `quota_limit`, `last_warn_level`）
- `TokenUsageLedger`：逐次流水（来源、模型、prompt/completion/total）
- `QuotaFeedback`：超额反馈工单（联系方式、留言、状态流转）
- `Discussion.usage_subject`：讨论绑定主体，保障后台自动续聊计费归属一致

## 3. HTTP 路由与 API

## 3.1 页面路由

- `GET /roundtable/`
- `GET /roundtable/setup/`
- `GET /roundtable/d/<discussion_id>/`
- `GET /roundtable/characters/`

### 3.2 API 路由

- `POST /roundtable/api/suggestions/`
- `POST /roundtable/api/configure/`
- `POST /roundtable/api/validate-guests/`
- `POST /roundtable/api/start/`
- `POST /roundtable/api/d/<discussion_id>/message/`
- `GET /roundtable/api/d/<discussion_id>/poll/`
- `POST /roundtable/api/d/<discussion_id>/resume/`
- `GET /roundtable/api/history/`
- `POST /roundtable/api/restart/<discussion_id>/`
- `GET /roundtable/api/quota/status/`
- `POST /roundtable/api/quota/feedback/`
- `GET /roundtable/api/profiles/`
- `GET /roundtable/api/profiles/<name>/`
- `GET /roundtable/api/cache/stats/`
- `POST /roundtable/api/cache/delete/`
- `POST /roundtable/api/cache/clear/`
- `GET /roundtable/api/candidates/`
- `POST /roundtable/api/candidates/trigger/`
- `POST /roundtable/api/candidates/reset/`
- `POST /roundtable/api/candidates/delete/`
- `POST /roundtable/api/candidates/clear/`

### 3.3 关键接口行为

- `suggestions`：topic 不能为空且 <=200 字；返回角色时会标注离线设定状态并维护候选队列
- `configure`：3-8 角色，线程池并行配置；离线设定缺失时触发生成
- `start`：创建 Discussion + Character + 开场；可见性仅允许 `public/private`；`max_rounds` 夹紧到 5-200
- `history`：匿名仅公开；登录用户看公开+自己的私密
- `restart`：复制角色配置，不重新生成；新讨论强制 `participant`
- `resume`：仅 `active` 且 `participant/observer` 可重启后台推进线程

## 4. WebSocket 设计

### 4.1 路由

- `ws/roundtable/d/<discussion_id>/`

### 4.2 连接鉴权与访问控制

- 连接要求：已登录用户 或 session 中已有 `guest_id`
- `private` 讨论：仅 owner 可连接
- 非 owner 进入公开讨论：`effective_role` 降为 `observer`

### 4.3 客户端可发消息

- `user_message`
- `poll`
- `typing_start`
- `typing_end`

### 4.4 服务端事件

- `initial_state`
- `message`
- `state_update`
- `poll_response`
- `system_message`
- `debug_info`
- `discussion_end`
- `quota_exceeded`
- `read_but_no_reply`
- `player_waiting`
- `user_typing` / `user_typing_end`

## 5. 讨论推进机制

### 5.1 Consumer 内交互逻辑

- `host`：用户发言记为主持人；`@角色` 触发角色回复
- `participant`：
  - `@主持人` -> 主持人回复
  - `@角色` -> 玩家令牌转移给该角色，角色可回复或婉拒
  - 无 `@` -> 记录用户发言，主持人可选择回应并可能继续邀请角色
- `observer`：拒绝发言

### 5.2 AutoContinueService

- 适用于 `participant` 与 `observer`
- 分阶段：
  - 初始化阶段：按 speaking_order 轮询
  - LLM 阶段：每轮由 HostAgent 通过 LLM 决策下一位
- 通过 `ensure_auto_continue_running(discussion_id)` 幂等启动，避免同讨论多线程重复推进
- 达到最大轮次后写入结束语并广播 `discussion_end`

## 6. Agent 分工

- `DirectorAgent`
  - `suggest_characters(topic, count=20)`
  - `validate_manual_characters(topic, names)`
- `CharacterAgent`
  - `configure_character(...)`
  - `generate_speech(...)`
  - `should_respond_to_player(...)`
  - `generate_decline_response(...)`
- `HostAgent`
  - `generate_opening / generate_invitation / decide_next_speaker / generate_closing`

## 7. 中间件与会话

`GuestSessionMiddleware` 挂在全局中间件链：

- 首次 HTTP 请求为访客分配 `guest_id`（写入 Django session）
- 首次 HTTP 请求也会写入 `anon_usage_id` cookie（用于匿名配额主体）
- WS 侧可读取同一 session，实现匿名但可识别连接

`LoginRequiredMiddleware` 仅保留实现，默认未全局启用。

## 8. 已知实现事实（重要）

- 当前系统核心实时通道是 WebSocket，HTTP `message/poll` 为兼容/补充接口
- Discussion 状态枚举较完整，但主流程主要使用 `active/finished`
- 一些旧测试仍引用 `services.moderator`，与现代码 `services.host_agent` 存在历史差异
