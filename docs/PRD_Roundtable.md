# 圆桌会谈（Roundtable Discussion）PRD

> 本文档以当前代码实现为准（`backend/roundtable` + `templates/roundtable`）。

## 1. 产品目标

打造一个多角色 AI 会谈系统：用户输入话题后，系统推荐嘉宾、生成角色设定并进入实时讨论。用户可用三种身份参与：主持人、参与者、旁观者。

## 2. 当前已实现范围

### 2.1 页面与路由

- `GET /roundtable/`：话题页（推荐角色 + 手动加人 + 历史会谈）
- `GET /roundtable/setup/`：配置页（生成角色设定、选择每个角色 LLM、设置轮次与可见性）
- `GET /roundtable/d/<discussion_id>/`：讨论页（WebSocket 实时）
- `GET /roundtable/characters/`：离线人物设定管理页

### 2.2 讨论身份

- `host` 主持人：用户发言显示为“主持人”；可 `@角色` 触发该角色回复
- `participant` 参与者：用户发言显示为“你”；可 `@角色` 或 `@主持人`
- `observer` 旁观者：只读，输入被拒绝

### 2.3 可见性与访问控制

- 支持 `public` / `private`
- `private`：仅 owner 可访问详情页和 WebSocket
- `public`：可被其他人查看；非 owner 进入讨论时会被强制降级为 `observer`
- 匿名用户可创建讨论（`owner=None`）

## 3. 用户流程（代码实装）

### 3.1 Step 1：话题与选人（`/roundtable/`）

1. 输入话题（最多 200 字）
2. 调用 `POST /roundtable/api/suggestions/` 获取最多 20 位推荐角色
3. 用户从推荐中选择 3-8 位
4. 可手动补充最多 3 位嘉宾（每个名字最多 20 字），通过 `POST /roundtable/api/validate-guests/` 评审
5. 通过后进入 `/roundtable/setup/`

### 3.2 Step 2：配置与开局（`/roundtable/setup/`）

1. 调用 `POST /roundtable/api/configure/` 并行生成角色设定
2. 可为每个角色指定独立 LLM（provider + model）
3. 设置 `max_rounds`（最终会被后端夹紧到 5-200）
4. 设置会谈可见性（public/private）
5. 调用 `POST /roundtable/api/start/` 创建讨论并生成开场

### 3.3 Step 3：实时讨论（`/roundtable/d/<id>/`）

- WebSocket: `ws/roundtable/d/<id>/`
- `observer` 和 `participant` 会自动启动后台 AutoContinue 线程推进讨论
- `host` 主要由用户驱动，必要时可触发后续自动续轮
- `@主持人 /quit` 可结束讨论

## 4. 关键业务规则

### 4.1 角色数量与配置约束

- 配置接口最少 3 人、最多 8 人
- 开始讨论前后端都会校验人数下限

### 4.2 手动嘉宾评审规则

- 推荐角色接口：仅推荐真实历史人物
- 手动嘉宾评审接口：允许“真实人物 + 知名虚构角色”
- 评审不通过时，前端统一显示固定文案：`评委会未能通过你推荐的人物`

### 4.3 历史会谈

- `GET /roundtable/api/history/`
- 匿名：仅看公开讨论
- 登录用户：可看公开 + 自己的私密讨论
- 返回字段包含：`visibility`、`is_mine`、轮次、状态、角色摘要

### 4.4 重新开始

- `POST /roundtable/api/restart/<id>/`
- 复制原角色配置创建新讨论
- 新讨论固定 `user_role='participant'`
- 可单独传新可见性参数

### 4.5 Token 计费与配额（V1）

- 登录/匿名用户默认都可直接使用，不先要求购买
- 系统按“主体”累计 token：
- 登录：`user:{id}`
- 匿名：`anon:{anon_usage_id}`（由中间件持久化 cookie）
- 默认配额：
- 调试环境 `100,000`
- 生产环境 `1,000,000`
- 超额后返回 `error_code=quota_exceeded` 并阻断后续 LLM 调用
- 讨论页提供低干扰 token 徽章（已用/上限），并在超额时弹“联系管理员”反馈框
- 反馈接口：`POST /roundtable/api/quota/feedback/`

## 5. 非目标（当前版本未做）

- DRF 化 API（当前均为 Django View + JsonResponse）
- 多人协作同屏编辑
- 前端构建链（当前模板内联 JS/CSS）
