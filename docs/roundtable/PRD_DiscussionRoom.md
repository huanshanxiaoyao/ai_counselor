# 圆桌会谈讨论室 PRD（实现对齐）

> 本文档覆盖 `/roundtable/d/<id>/` 页面与 `DiscussionConsumer` 的真实行为。

## 1. 目标

讨论室负责承载实时多角色会谈，支持三类身份交互，并通过主持人 Agent 与自动推进服务维持讨论节奏。

## 2. 角色与权限

| 角色 | 发言能力 | 典型交互 |
|---|---|---|
| 主持人 `host` | 可发言 | 输入即“主持人发言”；可 `@角色` 触发回复 |
| 参与者 `participant` | 可发言 | 输入即“你”；可 `@角色` 或 `@主持人` |
| 旁观者 `observer` | 不可发言 | 仅接收消息与状态更新 |

补充权限规则：

- 公开讨论中，非 owner 进入会被降级为 `observer`
- 私密讨论仅 owner 可访问（HTTP 与 WS 都受限）

## 3. WebSocket 协议

### 3.1 连接地址

- `ws/roundtable/d/<discussion_id>/`

### 3.2 入站消息（前端 -> 服务端）

- `{"type":"user_message","content":"..."}`
- `{"type":"poll"}`
- `{"type":"typing_start","character_name":"..."}`
- `{"type":"typing_end"}`

### 3.3 出站消息（服务端 -> 前端）

- `initial_state`：初始全量状态
- `message`：新消息
- `state_update`：轮次/发言者/令牌状态更新
- `poll_response`：poll 返回
- `discussion_end`：讨论结束
- `debug_info`：调试信息
- `system_message`：系统通知
- `read_but_no_reply`：角色婉拒（已读未回）
- `player_waiting`：参与者等待中的提示
- `user_typing` / `user_typing_end`
- `error`

## 4. @ 指令规则

### 4.1 解析方式

- 主规则：匹配 `^@角色名`（中文名、可含 `·`）
- 回退规则：`^@(非空白字符串)`

### 4.2 主持人模式

- 用户消息先落库并显示为“主持人”
- 若 `@角色`，该角色生成回复
- 本轮角色回复后，系统可继续自动邀请下一位发言者

### 4.3 参与者模式

- 用户消息先落库并显示为“你”
- `@主持人`：主持人直接回应
- `@角色`：
  1. 玩家令牌转移到目标角色
  2. 角色判断“回复 or 婉拒”
  3. 完成后归还玩家令牌
- 无 `@`：主持人根据策略决定是否回应，并可能继续邀请角色

### 4.4 旁观者模式

- 任何 `user_message` 均返回错误：`旁观者模式无法发言`

## 5. 令牌机制

### 5.1 主持人令牌

- 字段：`host_token_holder`, `host_token_at`
- 用于记录主持链路中的发言权状态

### 5.2 玩家令牌

- 字段：`player_token_holder`, `player_token_at`, `player_waiting_for`
- 仅参与者模式生效，避免同一参与者并发 `@角色` 打爆链路

### 5.3 超时归还

- 由 `poll` 触发超时检查
- 超时后自动归还主持人令牌/玩家令牌，并推送系统消息

## 6. 自动推进（AutoContinue）

### 6.1 启动时机

- `start` 接口：participant/observer 自动启动
- WS connect（participant + active）会二次调用幂等启动
- `resume` 接口可手动恢复

### 6.2 阶段

- 初始化阶段：按角色顺序轮询
- LLM 决策阶段：每轮由 HostAgent 选择下一位并给过渡语

### 6.3 结束条件

- `current_round >= max_rounds` 或状态已是 `finished`
- 结束时生成主持人结束语并广播 `discussion_end`

## 7. 页面可见行为

- 讨论页根据身份显示不同提示文案与输入状态
- observer 输入框禁用
- 支持手动显示/隐藏 debug 信息
- 断线重连采用指数退避

## 8. 异常处理

- 非法 JSON：返回 `error`
- 角色不存在：返回“未找到角色”
- LLM 失败：记录日志并降级（跳过本轮/错误提示）
- `@主持人 /quit`：可主动结束讨论
