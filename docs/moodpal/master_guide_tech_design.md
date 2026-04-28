# MoodPal 全能主理人技术设计（MVP 初稿 v0.1）

## 1. 文档目的
本文件聚焦一个问题：

如何在当前 MoodPal 的 `Django + LangGraph + 三流派 runtime` 架构上，实现“全能主理人”这一前台统一角色，使其能够在一次会话中动态调度人本主义层、CBT 主轨与精神分析主轨。

本文档直接对齐：
1. [prd_master_guide.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd_master_guide.md)
2. [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md)
3. [humanistic_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/humanistic_langgraph_design.md)
4. [cbt_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/cbt_langgraph_design.md)
5. [Psychoanalysis_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/Psychoanalysis_langgraph_design.md)

本文档重点回答：
1. 全能主理人和现有 3 个角色在技术上是什么关系
2. 如何实现“会话内可多次切换，但单轮只保留一个主干方法”
3. 如何让人本主义承担开场与修复层，而不是和 CBT / 精神分析平权竞争
4. 如何在不重写三套流派 runtime 的前提下，把这套能力接进当前代码结构
5. 如何处理状态持久化、摘要、隐私、日志与调试可观测性

## 2. 核心结论
先给结论：

1. 全能主理人不是第四种独立流派，而是一个“前台 persona + 后台编排层”。
2. 它不应该被实现成“三次串行调用：人本一句、CBT 一句、精神分析一句”。
3. 它也不应该重写一套新的大而全 Graph 去复制 CBT / Humanistic / Psychoanalysis 的内部细节。
4. MVP 最稳妥的实现方式是：
   - 前台固定 `master_guide` persona
   - 后台新增一层 `Master Guide Orchestrator`
   - 编排层决定本轮是：`support_only`、`cbt` 还是 `psychoanalysis`
   - 真正的可见回复每轮只由一个执行轨产出
   - 人本主义层在需要时成为单独可见回复；不需要时只作为切轨前后的支撑约束存在
5. 现有三套 runtime 应被复用，但必须补一个关键能力：
   - `surface_persona_id` 和 `therapy_mode / active_track` 解耦
   - 否则“全能主理人表层人设”与“后台流派执行”会绑死在一起

## 3. 当前代码基线与约束

### 3.1 已有能力
当前仓库已经具备以下基础：
1. `MoodPalSession.Persona` 已有 3 个固定 persona：
   - `logic_brother`
   - `empathy_sister`
   - `insight_mentor`
   - 见 [models.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/models.py)
2. `message_service.py` 已按 `session.persona_id` 分发到三套 runtime service。
3. 三套流派都已有完整运行时骨架：
   - `state.py`
   - `node_registry.py`
   - `router_config.py`
   - `router.py`
   - `executor_prompt_config.py`
   - `executor.py`
   - `*_evaluator.py`
   - `graph.py`
   - `services/*_runtime_service.py`
4. `summary_service.py`、`burn_service.py`、危机拦截、token 记账、匿名主体与摘要历史闭环都已存在。

### 3.2 直接约束
当前实现同时带来 4 个直接约束：
1. runtime 是按 `session.persona_id` 进入的，而不是按“后台 therapy mode”进入的。
2. 三套 executor 的语气是按 `persona_id` 写死的，见：
   - [cbt/executor.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/cbt/executor.py)
   - [humanistic/executor.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/humanistic/executor.py)
   - [psychoanalysis/executor.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/psychoanalysis/executor.py)
3. 三套 runtime 的状态目前各自落在：
   - `metadata['cbt_state']`
   - `metadata['humanistic_state']`
   - `metadata['psychoanalysis_state']`
4. 当前没有“会话内跨 Graph 编排 persona”的专门状态层。

### 3.3 由此推导出的设计要求
全能主理人如果要落地，至少必须补 5 件事：
1. 新增 `master_guide` persona
2. 新增 `master_guide_runtime_service.py`
3. 新增 `master_guide_state`
4. 让三套 runtime 支持“表层 persona 覆盖”
5. 允许一个 session 同时保留 `humanistic_state / cbt_state / psychoanalysis_state`

## 4. 不推荐的实现方式

### 4.1 不要做成三次串行 LLM 回复
最容易想到、但不该采用的方案是：
1. 先跑人本主义回复
2. 再跑 CBT 或精神分析回复
3. 最后再合并成一条对用户可见消息

这个方案的问题很直接：
1. 延迟太高：一轮消息可能变成 2-3 次 LLM 串行调用
2. 风格混乱：一条回复会显得像三个人拼接出来的
3. 难以评估：这轮到底是 CBT 有效，还是人本有用，很难判断
4. 难以持久化：子轨状态、切轨原因和用户反馈的对应关系会变脏

### 4.2 不要重写第四套大一统 therapy graph
另一种误区是再造一个“Master Guide 全能技术图谱”，把 CBT / Humanistic / Psychoanalysis 的节点全部平铺进去。

这也不推荐，原因是：
1. 会直接复制三套已存在的流派规则
2. 维护成本会爆炸
3. 每个流派的局部优化很难同步回总图
4. 未来任何一个流派调优都要改两遍

## 5. 推荐总体架构

### 5.1 架构定位
推荐新增一层“编排 persona”，而不是新增一套“新流派”。

结构如下：

`用户输入`
-> `Safety Guard`
-> `Master Guide Orchestrator`
-> `Track Adapter`
-> `Humanistic / CBT / Psychoanalysis Runtime`
-> `统一后处理与持久化`

含义如下：
1. `Safety Guard`
   - 沿用现有危机拦截逻辑
2. `Master Guide Orchestrator`
   - 判断本轮是否只做人本主义支撑
   - 判断本轮主工作轨是 CBT 还是精神分析
   - 记录切轨原因、防抖状态、调试 trace
3. `Track Adapter`
   - 把“全能主理人”的表层 persona 转换成对应子轨可用的执行上下文
4. `Track Runtime`
   - 复用现有三套流派 runtime / graph / evaluator
5. `统一后处理与持久化`
   - 写 `master_guide_state`
   - 写对应子轨 state
   - 写脱敏 trace
   - 写 token usage

### 5.2 核心判断
技术上应把全能主理人拆成 4 层：
1. `安全抢占层`
2. `人本主义支撑层`
3. `CBT 主工作轨`
4. `精神分析主工作轨`

这里最重要的不是“4 层都能同时说话”，而是：
1. 人本主义层负责开场承接、修复、缓冲、handoff
2. 主工作轨只在 `CBT` 和 `精神分析` 之间选择一个
3. 每次用户输入，只允许一个“当轮主工作方式”真正产出可见主干回复

## 6. 推荐代码结构

### 6.1 新增目录
建议新增：

`backend/moodpal/master_guide/`
1. `state.py`
2. `routing_signal_extractor.py`
3. `route_policy.py`
4. `router.py`
5. `graph.py`
6. `summary_projection.py`

以及：
1. `backend/moodpal/services/master_guide_runtime_service.py`

### 6.2 各文件职责
1. `state.py`
   - 定义 `MasterGuideState`
   - 定义初始态、metadata 读写结构
2. `routing_signal_extractor.py`
   - 从最近用户输入、最近几轮消息、历史摘要、子轨状态中提取路由信号
3. `route_policy.py`
   - 定义支撑层判断、主轨选择、切轨防抖规则
4. `router.py`
   - 输出本轮路由决策对象
5. `graph.py`
   - 组织 `plan_turn()` 与 `evaluate_turn()`
6. `summary_projection.py`
   - 把多轮切轨过程投影成摘要可用的自然语言素材
7. `master_guide_runtime_service.py`
   - 负责整轮执行、调用子轨 runtime、合并 state、记录 trace

### 6.3 现有文件需要修改的地方
至少会涉及：
1. [models.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/models.py)
   - 新增 `MASTER_GUIDE = 'master_guide'`
2. [session_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/session_service.py)
   - 增加 persona catalog
   - debug payload 中加入 `master_guide_state`
3. [message_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/message_service.py)
   - persona 分发接入 `run_master_guide_turn`
4. 三套 executor / runtime
   - 支持 `surface_persona_id='master_guide'`
5. [summary_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/summary_service.py)
   - 支持全能主理人摘要模板
6. 首页与会话页模板
   - 增加全能主理人入口与显示文案

## 7. 状态设计

### 7.1 元数据分层建议
推荐一个全能主理人 session 同时保留 4 份 runtime state：
1. `metadata['master_guide_state']`
2. `metadata['humanistic_state']`
3. `metadata['cbt_state']`
4. `metadata['psychoanalysis_state']`

这样做的原因：
1. 从 CBT 切回人本修复，再切回 CBT 时，需要保留先前议程与技术进度
2. 从 CBT 切到精神分析时，需要保留 CBT 已看到的现实问题结构
3. 精神分析切回 CBT 后，可能还要继续落到现实行动
4. 人本主义修复层本身也需要连续状态，不能每次都从零开始

### 7.2 `master_guide_state` 建议字段
建议至少包含：
1. `current_stage`
2. `current_turn_mode`
   - `support_only`
   - `cbt`
   - `psychoanalysis`
3. `active_main_track`
4. `last_main_track`
5. `support_mode`
   - `opening`
   - `repair`
   - `handoff`
   - `none`
6. `alliance_status`
7. `distress_level`
8. `problem_clarity`
9. `action_readiness`
10. `pattern_signal_strength`
11. `psychoanalysis_readiness`
12. `cbt_readiness`
13. `last_route_reason_code`
14. `last_switch_reason_code`
15. `switch_count`
16. `turn_index`
17. `stable_turns_on_current_track`
18. `route_trace`
19. `summary_hints`
20. `selected_model`
21. `session_phase`

### 7.3 `route_trace` 设计要求
`route_trace` 只允许存脱敏、结构化信息，不允许存用户原句。

建议每条 trace 仅包含：
1. `turn_index`
2. `mode`
3. `switch_from`
4. `switch_to`
5. `reason_code`
6. `support_before`
7. `support_after`
8. `progress_marker`
9. `fallback_used`

明确禁止：
1. `matched_user_excerpt`
2. `raw_user_text`
3. `full_prompt`

### 7.4 子轨 state 的复用策略
`humanistic_state / cbt_state / psychoanalysis_state` 不需要为全能主理人另起新 schema。

推荐策略是：
1. 继续复用现有三个 state schema
2. 让全能主理人 runtime 直接调用对应的 `merge_*_state_metadata()`
3. 子轨切走后不清空原 state，只在本轨再次激活时继续读取

这是 MVP 最稳的方案，因为它不会破坏现有流派的 state 语义。

## 8. 路由信号与决策策略

### 8.1 路由不应依赖重型二次 LLM
全能主理人的难点是动态切轨，但这不意味着每轮都要先跑一次“大模型分诊”，再跑一次“大模型回复”。

MVP 建议：
1. 优先使用规则和轻量信号提取器
2. 只有在 `CBT vs 精神分析` 明显难分时，才允许补一次轻量结构化判定
3. 不允许在常规路径上形成稳定的“双倍延迟”

### 8.2 主要信号维度
建议提取以下路由信号：
1. `distress_level`
   - 当前情绪冲击是否过高
2. `alliance_status`
   - 是否存在被冒犯感、否定、抽离、抗拒
3. `problem_clarity`
   - 用户是否已经说清楚一个现实问题
4. `action_readiness`
   - 用户是否想一起拆解、决定、行动
5. `pattern_signal_strength`
   - 是否反复出现“总是 / 每次 / 一直 / 又这样”
6. `association_depth`
   - 用户是否开始提供足够材料，而不仅仅是一句表层抱怨
7. `repair_needed`
   - 当前是否应先停在修复层
8. `advice_pull_detected`
   - 是否强拉建议
9. `resistance_signal`
   - 是否明显防御、反驳、拉开距离
10. `recent_track_progress`
   - 当前主轨是否刚刚取得推进，还是已经停滞

### 8.3 人本主义支撑层判定
满足以下情况时，本轮直接进入 `support_only`：
1. 会话首轮
2. `alliance_status == weak`
3. `repair_needed == true`
4. `distress_level == high` 且问题尚未清晰
5. 当前主轨连续两轮都未形成有效推进，且用户明显更需要被接住

### 8.4 CBT 判定
优先进入 CBT 主轨的条件：
1. 用户正在描述具体事件、现实任务、关系冲突、决策压力
2. `problem_clarity >= medium`
3. `action_readiness >= medium`
4. 当前阻抗较低，且并不需要更深的模式链接才能继续

### 8.5 精神分析判定
优先进入精神分析主轨的条件：
1. `pattern_signal_strength >= medium`
2. 已积累足够对话材料
3. `alliance_status` 不是弱
4. 当前不是高压失稳状态
5. 用户在问题梳理之外，开始追问“为什么我总这样”或反复掉回旧模式

### 8.6 精神分析的门槛建议
本稿结论：
1. MVP 默认不启用“最少材料 / 最少轮次”的硬门槛。
2. 默认仅采用软门槛：
   - 联盟稳定
   - 模式信号充足
   - 材料足够
3. 代码层可以预留可配置硬门槛：
   - `MASTER_GUIDE_MIN_PSY_MATERIAL_TURNS`
   - 但默认值应为 `0`
4. 即使未来开启硬门槛，也不能替代联盟与稳定度判断

## 9. 当轮执行模型

### 9.1 关键原则
“单轮只保留一个主干方法”在技术上的含义是：
1. 本轮要么是 `support_only`
2. 要么是 `cbt`
3. 要么是 `psychoanalysis`
4. 不存在 `humanistic + cbt + psychoanalysis` 三段拼接回复

### 9.2 人本主义层何时真正产出可见回复
只有两种情况应让人本主义层单独产出本轮回复：
1. 首轮开场承接
2. 修复 / 缓冲回合

除此之外，人本主义层更多承担“支撑约束”而不是“再生成一次独立回复”。

### 9.3 主轨回合的人本主义作用方式
当本轮主轨是 CBT 或精神分析时，人本主义层的作用应通过以下方式进入：
1. 在路由结果中生成 `support_directive`
   - 例如：`gentle_opening`
   - `slow_down`
   - `repair_softened`
2. 把 `support_directive` 注入主轨 executor prompt
3. 由主轨一次性生成一条“有被接住感，但方法中心明确”的回复

也就是说：
1. 不是先生成一句人本，再生成一句 CBT
2. 而是“CBT 回合的这一条回复，本身带着人本主义支撑层的口吻约束”

### 9.4 为什么这样设计
这样做同时满足：
1. 避免双倍延迟
2. 保持单条回复有中心
3. 让用户仍感到被接住
4. 保留主轨方法的可解释性

## 10. Prompt 与 Persona 解耦方案

### 10.1 当前问题
现有 executor 都通过 `state['persona_id']` 决定语气。

这对固定角色没问题，但对全能主理人不够，因为：
1. 会话的表层 persona 应始终是 `master_guide`
2. 但本轮内部 therapy mode 可能是 `cbt` 或 `psychoanalysis`

### 10.2 推荐解法
建议把“表层人设”和“后台主轨”拆成两个字段：
1. `surface_persona_id`
2. `therapy_mode` 或 `active_track`

推荐做法：
1. 三套 graph state 增加 `surface_persona_id`
2. executor 优先根据 `surface_persona_id` 决定角色语气
3. `therapy_mode` 只决定方法约束，不决定对用户的人设

### 10.3 对 executor 的具体要求
三个 executor 都应新增 `master_guide` 分支，例如：
1. 语气：沉稳、灵活、可靠，不说教、不表演
2. 若本轮是 CBT：保留梳理和拆解，但语气不要像“逻辑派邻家哥哥”那么强人格化
3. 若本轮是精神分析：保留观察与假设性表达，但不要直接切成“心理学前辈” persona
4. 若本轮是 support_only：保留人本主义承接，但仍保持全能主理人统一口吻

### 10.4 MVP 推荐实现
MVP 不必做一次大规模重构，推荐小步改造：
1. runtime service 支持可选参数：`surface_persona_id`
2. 若传入，则覆盖 state 里的 `persona_id` 或新增 `surface_persona_id`
3. executor 增加 `master_guide` persona style 分支
4. 现有三个固定 persona 行为保持不变

## 11. 单轮执行流程

### 11.1 推荐主流程
`UserInput`
-> `QuotaCheck`
-> `SafetyCheck`
-> `ExtractRoutingSignals`
-> `SupportGate`
-> `SelectMainTrack`
-> `ExecuteSelectedTrack`
-> `EvaluateTrackOutcome`
-> `PersistStatesAndTrace`
-> `ReturnReply`

### 11.2 详细含义
1. `QuotaCheck`
   - 复用现有配额逻辑
2. `SafetyCheck`
   - 命中危机立即抢占
3. `ExtractRoutingSignals`
   - 提取支撑层和主轨判定所需信号
4. `SupportGate`
   - 判断本轮是否必须先停留在人本主义层
5. `SelectMainTrack`
   - 若不需要 `support_only`，则在 `cbt / psychoanalysis` 中二选一
6. `ExecuteSelectedTrack`
   - 调用相应 runtime
7. `EvaluateTrackOutcome`
   - 记录本轮是否有效推进、是否需要切换、是否需要修复
8. `PersistStatesAndTrace`
   - 更新 `master_guide_state` 与对应子轨 state

### 11.3 防抖与切轨约束
允许会话内多次切轨，但需要 3 个约束：
1. `紧急例外`
   - 危机、联盟裂痕、明显失稳时，允许立刻切回人本主义修复层
2. `稳定推进要求`
   - 非紧急切轨前，应至少观察到当前轨形成一次有效推进或一次明确停滞
3. `切轨理由必须代码化`
   - 例如：
     - `opening_hold`
     - `repair_alliance`
     - `cbt_problem_solving`
     - `psy_repetition_pattern`
     - `cbt_after_insight_action_ready`

## 12. 子轨复用方案

### 12.1 Humanistic 复用方式
人本主义在全能主理人中有两种用法：
1. `support_only` 回合
   - 直接调用 `run_humanistic_turn(...)`
2. `support_directive` 生成器
   - 不产生单独回复，只为 CBT / 精神分析回合提供语气与边界约束

### 12.2 CBT 复用方式
CBT 在全能主理人中仍然是完整主轨：
1. 继续复用现有 `CBTGraph`
2. 保留 agenda、track、technique、exit evaluator 逻辑
3. 只在 prompt 入口增加 `master_guide` 语气与 `support_directive`

### 12.3 Psychoanalysis 复用方式
精神分析在全能主理人中仍然是完整主轨：
1. 继续复用现有 `PsychoanalysisGraph`
2. 保留 pattern memory、阻抗检测、repair / boundary 逻辑
3. 只在入口层增加触发门槛和 persona 语气覆盖

### 12.4 为什么不直接调 `message_service`
全能主理人不应通过“伪造 persona session 再走现有 message_service 分发”的方式实现。

推荐直接在 `master_guide_runtime_service.py` 中调用对应 track runtime，原因是：
1. 更清楚地控制本轮路由
2. 可以在一次事务里同时写入 `master_guide_state` 与子轨 state
3. 不会把切轨逻辑散落到顶层 service 之外

## 13. 摘要、记忆与 Burn Pipeline

### 13.1 摘要目标
全能主理人的摘要不能只是“今天聊了什么”，还要表达：
1. 本次主要情绪状态
2. 本次主要问题焦点
3. 本次经历了哪些支持方式的自然切换
4. 最终更适合的工作方向

### 13.2 摘要来源
建议摘要草稿来自三部分：
1. 会话消息本身
2. `master_guide_state.summary_hints`
3. 各子轨 state 中的关键 progress marker

### 13.3 隐私要求
摘要与 trace 仍需遵守既有隐私承诺：
1. 不记录原始敏感文本到 route trace
2. 不把内部 prompt 写入 session metadata
3. 若用户选择全盘销毁，建议同时清空：
   - `master_guide_state.route_trace`
   - `master_guide_state.summary_hints`
   - `master_guide_state` 中其他可用于回放单会话切轨过程的字段
4. 对“全盘销毁”路径，采用方案 B：
   - session 内不保留 `route_trace`
   - 仅允许保留不可逆的聚合统计
   - 聚合统计不保留用户原文，不保留逐轮轨迹，且不应用于重建单个会话路径
5. 允许保留的聚合统计示例：
   - `switch_count`
   - `used_cbt`
   - `used_psychoanalysis`
   - `support_only_turn_count`
   - `fallback_count`
6. 不建议把这类聚合统计继续挂在单个 session 的可回放 metadata 里；更推荐写入独立 analytics 埋点或更粗粒度统计表

说明：
1. 当前 MoodPal 其他 persona 的 runtime metadata 在销毁后仍可能保留派生状态。
2. 全能主理人因为 route trace 更丰富，隐私风险更高，建议在实现时顺手把这部分也收紧。

## 14. 调试与可观测性

### 14.1 用户侧与内部侧分离
建议明确分两层：
1. 用户视图
   - 不展示切轨详情
2. debug / admin 视图
   - 可以看最近若干轮 route trace、当前主轨、最近一次切轨原因、子轨 state 摘要

### 14.2 必须记录的脱敏日志
每轮至少记录：
1. `selected_mode`
2. `switch_from`
3. `switch_to`
4. `reason_code`
5. `support_mode`
6. `fallback_used`
7. `progress_marker`
8. `provider / model / usage`

### 14.3 需要重点盯的指标
1. 平均切轨次数
2. 切轨后 1-2 轮内的推进成功率
3. 切回修复层的比例
4. 精神分析触发比例
5. 精神分析触发后的回退率
6. 本轮 `support_only` 占比

## 15. 开发推进建议

### 阶段 1：补 Persona 与入口骨架
1. 新增 `master_guide` persona 枚举与 catalog
2. 首页增加第 4 张角色卡
3. 会话页可正常创建 `master_guide` session

### 阶段 2：补最小 runtime 骨架
1. 新增 `master_guide_state`
2. 新增 `master_guide_runtime_service.py`
3. 暂时只实现：
   - 首轮 `support_only`
   - 后续二选一进入 `cbt`

### 阶段 3：解耦表层 persona 与主轨
1. runtime 支持 `surface_persona_id`
2. executor 增加 `master_guide` 语气分支
3. 让 CBT 在全能主理人下先稳定跑通

### 阶段 4：加入精神分析切轨
1. 实现 `pattern_signal_strength` 与 `psychoanalysis_readiness`
2. 支持 `cbt -> psychoanalysis`
3. 支持 `psychoanalysis -> cbt`

### 阶段 5：补修复层与摘要投影
1. 支持 `repair -> support_only`
2. route trace 与 `summary_hints` 落库
3. 全能主理人摘要模板成型

### 阶段 6：补 debug / admin 可观测性
1. debug payload 展示 `master_guide_state`
2. 管理后台可查看路由轨迹
3. 增加基础回归测试样例集

## 16. 当前建议的实现优先级
如果只从“先做出可用版本”出发，建议优先级如下：
1. 先让 `master_guide -> support_only -> cbt` 跑通
2. 再补 `support_only -> psychoanalysis`
3. 再补 `cbt <-> psychoanalysis` 的双向切换
4. 最后再做更细的防抖、debug 视图和更强的切轨规则

理由：
1. 用户最常见的路径仍会是“先接住，再进入 CBT”
2. 精神分析切轨更敏感，应该后接
3. 先把 persona 解耦和 state 持久化打稳，比一开始追求复杂切轨更重要

## 17. 尚待讨论的问题
1. 是否需要为全能主理人单独设计更细的 fallback reply 模板
2. 后续是否要把这层编排抽成通用“多 persona 编排层”，供未来更多角色复用
