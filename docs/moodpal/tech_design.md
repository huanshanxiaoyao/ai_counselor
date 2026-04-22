# MoodPal 技术设计（MVP 初稿 v0.1）

## 1. 文档定位
- 文档目标：定义 MoodPal MVP 的整体技术架构、核心主流程、状态机分层方式，以及“阅后即焚”的实现框架。
- 文档边界：本稿优先解决总体方案与主链路，不展开过细的数据模型、字段定义和 API 细节。
- 对齐基线：以 [prd.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd.md) 为产品输入，以当前 Django 项目为实现基础。

## 2. 设计原则
1. 保持现有 Django 架构，不新起一套 FastAPI 服务。
2. 引入 LangGraph 作为多 Agent 业务流程与流派状态机编排层，而不是替代 Django。
3. 角色是前台产品概念，流派和状态机是后台实现概念，两者需要一一映射但不能混淆。
4. 会话原始消息默认不长期保留，围绕“摘要确认后留摘要，其余销毁”设计数据流。
5. 匿名主体、token 记账、配额限制、管理员反馈，复用现有站点基础能力。
6. 高风险场景优先安全，不因追求角色一致性而牺牲危机干预。
7. 异常处理优先采用前置检测（Pre-flight Check），而不是等主链路跑偏后再补救。
8. 每个流派状态机都必须具备最大重试、stall 检测和熔断降级能力，避免节点死循环。

## 3. 当前系统约束

### 3.1 已有基础能力
1. Django 已提供页面路由、模板体系、登录注册能力。
2. 全站已支持匿名主体识别：
   - `session['guest_id']`
   - `anon_usage_id` cookie
   - 见 [middleware.py](/Users/suchong/workspace/ai_counselor/backend/config/middleware.py)
3. 已有统一 LLM 调用封装：
   - `LLMClient`
   - 多 provider / 多 model
   - 见 [client.py](/Users/suchong/workspace/ai_counselor/backend/llm/client.py)
4. 已有 token 配额与反馈链路：
   - 匿名/登录主体统一记账
   - 超额阻断
   - 管理员反馈
   - 见 [token_quota.py](/Users/suchong/workspace/ai_counselor/backend/roundtable/services/token_quota.py)

### 3.2 对 MoodPal 的直接约束
1. MoodPal 必须复用现有 token 配额能力，而不是重新设计一套计费体系。
2. MoodPal 必须支持匿名用户直接使用，并允许匿名用户基于 cookie 保留摘要。
3. MoodPal 必须遵守站点现有 CSRF、认证、模板和部署方式。

## 4. 总体架构

### 4.1 分层结构
推荐采用四层架构：

1. 接入层（Django Web / API Layer）
   - 路由：`/moodpal/`
   - 页面：角色选择页、隐私契约、会话页、摘要确认页
   - API：会话启动、发消息、结束会话、摘要确认、摘要销毁
   - 负责：鉴权、匿名主体识别、请求校验、配额检查、响应格式

2. 编排层（LangGraph Orchestration Layer）
   - 负责多 Agent 协同
   - 负责按流派推进状态机
   - 负责意图评估、阶段判断、知识图谱检索、Prompt 组装、状态更新

3. 领域服务层（MoodPal Domain Services）
   - Session Service
   - Memory / Summary Service
   - Burn Service
   - Crisis Guard Service
   - Model Selection Service
   - Quota Integration Service

4. 基础设施层（Infrastructure Layer）
   - PostgreSQL：长期数据
   - Redis：短期会话缓存、状态快照、自动结束计时辅助
   - LLM Providers：通过现有 `LLMClient` 接入

### 4.2 关键结论
1. Django 负责“接入、落地、持久化、鉴权、配额”。
2. LangGraph 负责“多 Agent 业务流程编排与状态机推进”。
3. 现有 `backend.llm` 继续作为唯一 LLM 接入层。

## 5. 核心概念映射

### 5.1 产品概念
1. Persona：用户看到的虚拟角色
2. Therapy Mode：角色背后对应的流派方法
3. Session：一次会话
4. Summary：一次会话确认后的摘要

### 5.2 技术概念
1. Graph：某个流派对应的 LangGraph 状态机
2. Agent：图中的职责节点或功能代理
3. Session State：当前会话所处的阶段与上下文
4. Memory Tier：
   - 短期记忆：本次会话上下文
   - 长期记忆：确认保存的摘要

### 5.3 映射关系
1. 一个 Persona 对应一个主要 Therapy Mode。
2. 一个 Therapy Mode 对应一套 Graph 模板。
3. 一个 Session 在任一时刻只运行一条主要 Graph 主链路。
4. 危机干预优先级高于 Persona 和 Therapy Mode，会直接抢占主链路。

## 6. 主流程设计

### 6.1 新会话主流程
1. 用户进入 `/moodpal/` 页面。
2. 选择一个 Persona。
3. 前端展示隐私契约和边界说明。
4. 用户确认后，Django 创建新会话。
5. 系统读取主体最近一次确认摘要，作为可选历史上下文。
6. 系统初始化 LangGraph 运行上下文。
7. 进入正式对话。

### 6.2 单轮对话主流程
MoodPal 的一轮核心链路为：

`用户输入 -> 意图与状态评估 -> 检索流派知识图谱 / 规则节点 -> 组装 Prompt -> 调用 LLM -> 输出角色化回复 -> 更新状态`

拆解如下：
1. Django API 接收用户输入。
2. 先执行配额检查。
3. 进入 Crisis Guard，判断是否需要中断普通对话。
4. 若安全，通过 LangGraph 进入当前 Therapy Mode 对应的 Graph。
5. Graph 内部执行多个节点：
   - 意图评估
   - 会话阶段判断
   - 流派知识图谱检索
   - Prompt Assembly
   - LLM Generation
   - Response Post-processing
   - State Update
6. 返回前端角色化回复。
7. 记录 token 使用。

### 6.3 会话结束主流程
1. 用户主动结束，或 30 分钟无回复。
2. Session 状态切换为 `ending`。
3. 系统基于本次会话临时消息生成摘要草稿。
4. 前端展示摘要确认页。
5. 用户执行：
   - 确认保存
   - 全文编辑后保存
   - 全盘销毁
6. 系统执行 Burn Pipeline。
7. 会话进入终态，不可恢复；用户后续只能看到摘要结果。

## 7. LangGraph 设计框架

### 7.1 为什么必须引入 LangGraph
1. MoodPal 不是普通单轮聊天，而是“方法驱动”的多阶段对话。
2. 不同流派的推进路径不同，需要显式状态机管理。
3. 一个角色背后存在多个内部职责，如评估、检索、生成、风控，不适合揉成单个 Prompt。

### 7.2 Graph 粒度建议
MVP 建议采用：
1. 一个 Supervisor Graph 负责统一入口、风险抢占、Persona -> Therapy Mode 映射。
2. 每个主要流派一张子图：
   - CBT Graph
   - Humanistic Graph
   - Exploratory Graph

### 7.3 节点职责建议
每张子图至少包含以下概念节点：
1. `AssessIntentNode`
   - 判断用户当前主要诉求和表达类型
2. `AssessStateNode`
   - 判断当前会话阶段与情绪稳定度
3. `RetrieveMethodNode`
   - 检索当前流派相关知识图谱、步骤、规则片段
4. `AssemblePromptNode`
   - 组合角色设定、历史摘要、当前状态、方法片段、模型参数
5. `GenerateReplyNode`
   - 调用 LLM 生成回复
6. `PostProcessNode`
   - 做边界校验、角色语气修正、必要的响应裁剪
7. `UpdateStateNode`
   - 更新当前阶段、homework 候选、下一轮建议状态

### 7.4 CBT Graph 例子
对于 CBT 角色，MVP 可以先覆盖这些阶段：
1. 情绪识别
2. 自动化想法识别
3. 证据梳理
4. 替代性认知尝试
5. 微行动建议

注意：
1. 这不是要求每次会话都完整跑完全部阶段。
2. Graph 应支持根据用户状态和输入内容跳转、暂停、回退。

## 8. 多 Agent 协作方式

### 8.1 推荐角色
MVP 建议按职责拆成以下内部 Agent：
1. `Safety Agent`
   - 危机识别与安全抢占
2. `State Evaluator Agent`
   - 判断当前阶段、情绪稳定度、推进条件
3. `Method Retriever Agent`
   - 检索流派图谱、方法片段、步骤提示
4. `Conversation Agent`
   - 负责生成最终角色化回复
5. `Summary Agent`
   - 在会话结束时生成结构化摘要

### 8.2 设计原则
1. 前台只有一个角色，后台可以有多个 Agent 协作。
2. Agent 输出不直接暴露给用户，只有最终角色化回复对用户可见。
3. Safety Agent 拥有最高优先级，可直接切断常规链路。

## 9. 阅后即焚（Burn Pipeline）初稿

### 9.1 目标
实现以下用户承诺：
1. 原始会话消息不做长期保留。
2. 用户仅确认摘要后，系统才保留摘要内容。
3. 超时自动结束也遵守同样规则。

### 9.2 数据分层
1. 短期层：
   - 本次会话原始消息
   - 当前 Graph 运行状态
   - 会话超时计时信息
   - 建议放 Redis 或其他短期存储
2. 长期层：
   - 用户确认后的摘要
   - 脱敏审计事件
   - token 使用记录
   - 管理员反馈记录

### 9.3 结束触发
会话结束由两类事件触发：
1. 用户主动点击“结束会话”
2. 30 分钟无回复自动结束

### 9.4 执行步骤
1. 锁定会话，避免并发继续写入消息。
2. 基于短期消息生成摘要草稿。
3. 将摘要草稿交给前端确认。
4. 等待用户操作：
   - 确认保存
   - 编辑后保存
   - 全盘销毁
5. 一旦收到用户确认指令，立即执行原始消息销毁。
6. 若是保存路径，只写入确认后的摘要结果。
7. 会话状态切换为终态，不允许恢复原始对话。

### 9.5 异常处理要求
1. 摘要生成失败时，应给用户明确提示并支持重试。
2. 原始消息销毁失败时，不应把失败暴露为“已销毁”。
3. 销毁动作需要幂等，可安全重复执行。
4. 审计日志仅记录“何时生成摘要、何时确认、何时销毁、是否成功”，不记录原始文本。

## 10. 危机干预框架

### 10.1 目标
在用户表达自伤、他伤、自杀等高风险意图时，优先保护用户安全，而不是继续角色化陪伴。

### 10.2 主流程
1. 每轮用户输入先经过 Crisis Guard。
2. 若命中高危规则，直接中断普通 Graph。
3. 切换为安全干预输出：
   - 安抚与建议立即寻求线下帮助
   - 中国大陆地区热线信息
   - 明确产品不能替代紧急援助

### 10.3 当前建议
MVP 先采用两段式策略：
1. 规则词库 / 模板检测
2. 轻量模型或结构化分类二次判断

说明：
1. 本稿先定义框架，不展开分级字段与阈值。
2. 危机策略细化可放到下一轮专题文档。

## 11. 历史摘要与连续陪伴

### 11.1 读取规则
1. 登录用户按账号读取最近一次已确认摘要。
2. 匿名用户按 `anon_usage_id` cookie 读取最近一次已确认摘要。
3. 清 cookie 后，V1 视为新主体。

### 11.2 注入规则
历史摘要只作为辅助上下文，不直接替代当前轮用户输入。

建议注入的信息包括：
1. 上次核心情绪状态
2. 上次探讨焦点
3. 上次 homework
4. 与本次角色相关的连续陪伴线索

### 11.3 homework 规则
1. homework 仅作为摘要字段存在。
2. 后续会话里只在用户情绪稳定时自然提及。
3. homework 不单独作为一套复杂任务系统实现。

## 12. 模型与配额对齐

### 12.1 模型选择
1. 系统有默认模型配置。
2. 用户可以在前台选择模型。
3. 模型选择影响调用链路，但不改变 Persona / Therapy Mode 定义。

### 12.2 token 记账原则
1. 每次 LLM 成功调用后记录 token usage。
2. 配额主体沿用现有逻辑：
   - 登录：`user:<id>`
   - 匿名：`anon:<anon_usage_id>`
3. 若主体已超额，则在业务入口直接阻断，不进入后续 Graph。

### 12.3 超额反馈
1. 超额时前端展示统一提示。
2. 用户可提交联系管理员反馈。
3. 运营承诺 12 小时内响应。

## 13. 页面与接口边界

### 13.1 页面建议
1. `/moodpal/`
   - 角色选择页
   - 非医疗建议声明
2. `/moodpal/session/<id>/`
   - 会话主页面
   - 模型选择
   - 隐私契约确认后进入
3. `/moodpal/session/<id>/summary/`
   - 摘要确认页

### 13.2 API 草案
本轮只定义边界，不锁定最终字段：
1. `POST /api/moodpal/session/start`
2. `POST /api/moodpal/session/<id>/message`
3. `POST /api/moodpal/session/<id>/end`
4. `POST /api/moodpal/session/<id>/summary/save`
5. `POST /api/moodpal/session/<id>/summary/destroy`
6. `GET /api/moodpal/session/<id>`

## 14. 可观测性与运维要求
1. 关键事件必须可观测：
   - 会话创建
   - 会话结束
   - 摘要生成
   - 摘要确认/销毁
   - 危机触发
   - 配额超额
2. 日志必须脱敏，不记录用户原始敏感文本。
3. 上游模型超时或失败时，要有统一兜底响应，不能裸露 500。

## 15. 本文档暂不展开的内容
1. 详细数据模型与字段定义
2. LangGraph state schema 细节
3. API request / response schema 细节
4. 危机干预分级阈值
5. 角色设定卡文案与视觉规范

## 16. 下一轮建议继续补的内容
1. Session / Summary / CrisisEvent 的数据模型草案
2. LangGraph state schema 与节点输入输出
3. CBT Graph 的首版节点定义
   - 详见 [cbt_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/cbt_langgraph_design.md)
4. Humanistic Graph 的首版节点定义
   - 详见 [humanistic_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/humanistic_langgraph_design.md)
5. Burn Pipeline 的失败补偿与幂等实现
6. 前端页面状态与交互细化

实施顺序建议：
- 详见 [mvp_execution_plan.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/mvp_execution_plan.md)
