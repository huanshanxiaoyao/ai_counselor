# MoodPal 精神分析 + LangGraph 设计（MVP v1 草案）

## 1. 文档目的
本文件聚焦一个问题：

如何在 MoodPal 当前的 Django + LangGraph 架构下，把“深挖派的心理学前辈”这一角色背后的精神分析式探索路径，设计成一套可落地、可扩展、可控风险的状态机实现。

本文档是 [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md) 的专题细化稿，也会显式对齐：
1. 当前 `backend/moodpal/` 已有的运行时分层方式
2. CBT 与人本主义两套已落地的 Graph 实现模式
3. MoodPal 的“摘要确认后保留，原始消息销毁”的隐私闭环
4. 精神分析流派独有的特殊需求：模式识别、阻抗处理、关系张力、跨会话线索提取

命名约定补充：
1. `tech_design.md` 里此前出现过更泛化的 `Exploratory Graph` 提法。
2. 从这份文档开始，第三条流派子图建议统一命名为 `Psychoanalysis Graph`，避免产品名、流派名和代码目录名分裂。

结论先说：
1. 旧草稿里的方向有价值，但还不能直接落到当前项目。
2. 精神分析流派不能简单复用 CBT 或人本主义的阶段名，但可以复用同一套运行时骨架。
3. 这条线的关键不是“更深”，而是“更稳地深一层”，并且要比其他两类流派更严格地控制过度解释风险。

## 2. 对旧草稿的理解与修正

### 2.1 旧草稿中值得保留的核心思路
旧稿里有 4 个判断是正确的，应该保留：
1. 精神分析流派的核心价值不在给建议，而在帮助用户看见重复出现的内在模式。
2. “阻抗”不是异常噪音，而是主流程中的一等信号，必须前置检测。
3. 跨会话连续性不应依赖原始消息长期保留，而应依赖脱敏后的抽象模式记忆。
4. 执行器的语气必须体现“稳、慢、观察、假设性”，而不是武断地下结论。

### 2.2 旧草稿中必须修正的地方
旧稿和当前项目存在 6 个关键不对齐点：
1. 旧稿默认有 Vector DB 与独立模式检索层，但当前项目并没有这套基础设施。
2. 旧稿把原始消息的销毁理解成 `redis.delete`，但当前 MoodPal 的原始消息主存储是 Postgres 中的 `MoodPalMessage`，销毁路径应对齐现有 `destroy_raw_messages()`。
3. 旧稿倾向于把“提取到的抽象模式”在会话结束时直接长期保存，这和当前产品“用户可选择全盘销毁”的承诺有冲突。
4. 旧稿默认可以在阻抗出现时直接切到人本主义逻辑，但当前运行时没有跨 Graph 切换框架，MVP 第一版不应把这件事作为必需前提。
5. 旧稿中的“移情处理”描述偏临床概念，若直接照搬，容易把 AI 产品做成过度解释型角色。
6. 旧稿没有按当前代码里的 `state / router / executor / evaluator / runtime_service` 分层来组织，因此无法直接指导开发。

### 2.3 修正后的总体判断
在 MoodPal 里，精神分析流派的目标不应定义为“复刻传统精神分析”，而应定义为：

一种带有精神分析式观察框架的、边界清晰的探索型对话。

它的实现重点是：
1. 从“表层困扰”中识别重复模式
2. 温和识别阻抗、防御和关系张力
3. 在合适时机做一层“链接与整合”
4. 只保存脱敏后的抽象模式线索，不保存敏感原文

## 3. 当前项目中的对齐基线

### 3.1 现有角色与运行时现状
当前项目中：
1. Persona 已有 `insight_mentor`，对应“深挖派的心理学前辈”
2. 该角色已在 `message_service.py` 中接入 `psychoanalysis_runtime_service.py`
3. `session_service.py` 的 debug 序列化已支持第三套 runtime state：`psychoanalysis_state`

这意味着：
1. 产品入口已存在
2. 模型选择、会话页、摘要页、配额与危机拦截闭环已存在
3. 精神分析流派的 Graph 与 runtime service 已有 MVP 骨架，后续重点转向模式记忆、摘要质量和节点调优

### 3.2 已落地的实现模板
CBT 与人本主义当前都采用同一实现骨架：
1. `state.py`
   - 定义运行时状态字段与初始态构造器
2. `node_registry.py`
   - 注册结构化技术节点
3. `router_config.py`
   - 维护规则、提示词和 fallback 映射
4. `router.py`
   - 根据状态选择当前技术节点
5. `executor_prompt_config.py`
   - 定义每个技术节点的 Prompt 模板
6. `executor.py`
   - 将“技术节点 + 当前状态”组装为 LLM 执行 payload
7. `*_evaluator.py`
   - 评估当前节点是否完成、是否停滞、是否需要熔断
8. `graph.py`
   - 输出 `plan_turn()` 与 `evaluate_turn()`
9. `services/*_runtime_service.py`
   - 负责状态加载、LLM 调用、state patch 合并、trace 记录和 metadata 持久化

精神分析流派应完全对齐这一骨架，不应额外造一套平行架构。

### 3.3 当前项目的特殊约束
精神分析流派必须遵守以下约束：
1. 仍然运行在 Django 主项目里，不新增独立服务。
2. 仍然复用现有 `LLMClient`、token 配额、危机检测、Burn Pipeline。
3. 匿名用户也可以使用，并基于 cookie 保留经过确认的摘要。
4. 会话结束后，用户若选择销毁，则不应额外偷偷保留“内部模式档案”。

## 4. 精神分析流派在 MoodPal 中的定位

### 4.1 产品定位
“深挖派的心理学前辈”不是做诊断，也不是给人生建议，而是帮助用户：
1. 发现某个问题为什么总是以相似方式出现
2. 看到自己在关系、权威、自我评价中的重复拉扯
3. 慢慢形成一种“我好像开始理解自己为什么会这样”的体验

### 4.2 与 CBT / 人本主义的区别
和其他两类流派相比，它的不同点在于：
1. 比 CBT 更少追求“立刻解决”，更关注模式与动力。
2. 比人本主义更允许点出矛盾、回避和重复，但点出的方式必须温和、假设化。
3. 它不是纯粹承接情绪，也不是纯粹拆解认知，而是试图把“当下困扰”和“反复出现的模式”连起来。

### 4.3 这条线最容易出问题的地方
精神分析流派的风险比另外两条线更高，主要在 4 方面：
1. 过度解释：AI 轻率给出“你其实是在……”的结论。
2. 过度深入：用户还没准备好，就被强行往童年、创伤、关系原型方向带。
3. 关系刺激：用户把 AI 当成评判者、权威者或“总想分析我”的对象。
4. 隐私越界：如果把重复模式做成长期记忆，稍不注意就会留下可识别原文痕迹。

所以这条线的实现核心不是“能不能深挖”，而是：
1. 是否只深一层
2. 是否有前置阻抗检测
3. 是否有最大重试和熔断机制
4. 是否把长期记忆做成抽象脱敏层

## 5. 推荐总体方案

### 5.1 核心思想
推荐仍然采用“两层结构 + 一个额外的脱敏模式记忆子能力”：

1. 上层：Psychoanalysis LangGraph 宏状态机
   - 控制阶段推进
   - 控制阻抗与关系异常的前置抢占
   - 控制什么时候可以做链接，什么时候只能收住

2. 下层：精神分析技术节点库
   - 以结构化节点方式定义
   - 被 Router 选中后交给 Executor 执行

3. 旁路能力：Pattern Memory Extractor / Recall
   - 不直接参与每轮可见回复
   - 负责提取、保存、召回脱敏模式线索
   - 与 Burn Pipeline 强绑定

### 5.2 为什么不能照搬旧稿里的“独立模式引擎”
在当前项目下，MVP 不应该一开始就引入独立向量检索系统，原因是：
1. 现有代码里没有这条基础设施链路。
2. 当前摘要、会话、事件都在同一 Django 数据模型里，先做关系型 JSON 存储更稳妥。
3. 当前产品还没把精神分析的长期记忆 schema 定稳，过早上向量库会增加维护复杂度。

因此推荐：
1. MVP v1 先把抽象模式记忆保存在 `MoodPalSession.metadata` 的脱敏结构中。
2. 等后续数据模型稳定，再考虑抽成独立表或向量索引。

### 5.3 推荐的目标代码结构
当前 MVP 已按以下结构落地，后续扩展应继续沿用该分层：

`backend/moodpal/psychoanalysis/`
1. `state.py`
2. `node_registry.py`
3. `router_config.py`
4. `router.py`
5. `executor_prompt_config.py`
6. `executor.py`
7. `insight_evaluator.py`
8. `insight_rule_config.py`
9. `signal_extractor.py`
10. `graph.py`
11. `pattern_memory.py`

以及：
1. `backend/moodpal/services/psychoanalysis_runtime_service.py`
2. 对 `message_service.py` 的 persona 分发接入
3. 对 `session_service.py` debug payload 的第三套 runtime_state 接入
4. 对 `summary_service.py` / save-summary 流程的精神分析脱敏模式提取接入

## 6. 推荐的 Psychoanalysis Graph 结构

### 6.1 Graph 分层
建议拆成三类状态：

1. 会话级状态
   - 新会话初始化
   - 安全检查
   - 模式记忆召回
   - 建立本轮探索焦点
   - 收尾与摘要素材沉淀

2. 分析级状态
   - 关联材料展开
   - 防御/阻抗澄清
   - 重复模式链接
   - 这里此刻的关系反应反思
   - 领悟整合

3. 中断级状态
   - 危机安全抢占
   - 联盟修复
   - 阻抗升高后的减压/收束
   - 强建议拉扯的边界修正

补充要求：
1. 中断级状态优先级高于普通深挖。
2. 每轮进入主链前都必须做 Pre-flight Check。
3. 精神分析流派的“异常”往往不是技术故障，而是内容本身的一部分，所以需要单独阶段承接。

### 6.2 推荐的阶段（Stages）
建议在 `psychoanalysis/state.py` 中定义以下 stage：
1. `session_start`
2. `safety_check`
3. `preflight_dynamic_check`
4. `recall_pattern_memory`
5. `establish_focus`
6. `determine_phase`
7. `select_technique`
8. `execute_technique`
9. `evaluate_insight`
10. `handle_repair`
11. `wrap_up`

### 6.3 推荐的相位（Phases）
建议定义以下 phase：
1. `containment`
2. `association`
3. `defense_clarification`
4. `pattern_linking`
5. `relational_reflection`
6. `insight_integration`
7. `repair`
8. `boundary`
9. `closing`
10. `safety_override`
11. `''`

### 6.4 主链路
推荐的主链路如下：

`SessionStart`
-> `SafetyCheck`
-> `PreFlightDynamicCheck`
-> `RecallPatternMemory`
-> `EstablishFocus`
-> `DeterminePhase`
-> `SelectTechnique`
-> `TechniqueExecution`
-> `EvaluateInsight`
-> `NextStepDecision`
-> `WrapUp`

含义如下：
1. `SessionStart`
   - 初始化运行时状态
   - 读取最近一次保存的摘要
   - 注入 Persona、模型选择与会话上下文

2. `SafetyCheck`
   - 复用现有危机拦截链路
   - 命中高危则不进入普通精神分析主链

3. `PreFlightDynamicCheck`
   - 先检查是否存在联盟裂痕、阻抗升高、强建议拉扯、明显不适合继续深挖的情况
   - 若命中，则优先进入 `repair` 或 `boundary`
   - 实现约束：MVP 默认禁止把它做成“再来一次完整大模型分析”的串行第二跳；优先使用 `signal_extractor.py` 的规则提取、轻量分类器或和主回复合并的一次结构化输出，避免双倍延迟

4. `RecallPatternMemory`
   - 读取同一主体最近几次已保存会话中的脱敏模式线索
   - 仅作为内部上下文使用，不直接曝光给用户

5. `EstablishFocus`
   - 锁定“此刻最值得跟住的一个模式入口”
   - 不等于议程设定，但要避免对话完全失焦

6. `DeterminePhase`
   - 判断本轮更适合继续材料展开、澄清防御、做模式链接、处理这里此刻关系，还是只维持收容

7. `SelectTechnique`
   - 从技术节点库中选择当前最合适的节点

8. `TechniqueExecution`
   - 执行一轮技术节点
   - 输出角色化回复和结构化 state_patch

9. `EvaluateInsight`
   - 判断本轮是否真的形成一点推进
   - 同时判断是否在空转、是否需要熔断

10. `NextStepDecision`
   - 决定继续当前节点、切换相位、回退 containment、进入 repair，或 wrap-up

11. `WrapUp`
   - 把“此刻看见了什么”整理成摘要素材
   - 不把解释做成绝对结论

## 7. 首批技术节点库设计

### 7.1 当前现实情况
与 CBT / Humanistic 一致，当前仓库已建立 `docs/moodpal/Psychoanalysis/` 的结构化 JSON 节点资产。

实现约束：
1. 节点资产继续维护在 JSON 中，不直接写死在 Graph 里。
2. `PsychoanalysisNodeRegistry` 负责加载这些节点。
3. Router / Executor / Evaluator 只消费节点 ID 与运行时状态，不直接依赖文档段落。

### 7.2 推荐的首批节点
建议第一版至少包含以下 10 个节点：

| 节点 ID | 类别 | 作用 | 说明 |
| --- | --- | --- | --- |
| `psa_entry_containment` | containment | 先稳住、收住、降低被分析感 | 用于开场、用户脆弱、节奏过快时 |
| `psa_association_invite` | association | 邀请用户把相关联的感受、画面、场景继续放出来 | 不做无边界自由联想，而是轻度关联展开 |
| `psa_defense_clarification` | defense | 温和指出回避、合理化、跳题、只讲道理等防御动作 | 必须用假设性语言 |
| `psa_pattern_linking` | pattern | 把“这一次”和“以前常见的相似场景”连起来 | 重点是重复，不是挖童年细节 |
| `psa_relational_here_now` | relational_reflection | 处理用户对当前对话关系的即时反应 | 是“这里此刻”反思，不直接做重型移情解释 |
| `psa_insight_integration` | integration | 把分散线索串成一个可接受的工作性假设 | 只整合一层，不给最终真相 |
| `psa_exception_resistance_soften` | repair | 阻抗升高时减压、退一步、重新建立可说性 | 不继续深挖 |
| `psa_exception_alliance_repair` | repair | 处理“你别分析我”“你根本没懂”一类联盟裂痕 | 与人本主义修复节点相似，但保留探索语境 |
| `psa_boundary_advice_pull` | boundary | 处理“别分析了，直接告诉我怎么办” | 承接急切，但不直接给命令式答案 |
| `psa_reflective_close` | closing | 用开放式、可带走的观察收束本轮对话 | 不布置作业，但留下一句可回看的自我观察锚点 |

### 7.3 一个关键设计决定
MVP 第一版不建议把“移情解释”做成单独的重型节点。

建议用 `psa_relational_here_now` 替代传统意义上的强移情解释，原因是：
1. AI 产品里最容易误伤用户的就是“你把我当成了某某人”这类判断。
2. 当前产品还没有足够的长期关系数据支撑高置信度移情解释。
3. “这里此刻你对我这句话的反应”更符合产品边界，也更容易做到假设性表达。

### 7.4 推荐的目录资产组织方式
当前目录资产组织方式：

`docs/moodpal/Psychoanalysis/`
1. `part1.json`
   - containment / association
2. `part2.json`
   - defense / pattern / relational_reflection
3. `part3.json`
   - integration / repair / boundary / closing

字段继续对齐现有两条线：
1. `node_id`
2. `name`
3. `category`
4. `book_reference`
5. `trigger_intent`
6. `prerequisites`
7. `system_instruction`
8. `examples`
9. `exit_criteria`

## 8. JSON 与 LangGraph 的映射方式

### 8.1 映射原则
精神分析节点也应沿用现有映射方式：
1. `node_id`
   - 技术节点唯一标识
2. `category`
   - 对应当前 phase 或修复轨道
3. `trigger_intent`
   - 作为候选信号，不直接等于硬编码布尔表达式
4. `prerequisites`
   - 作为进入候选集的门槛
5. `system_instruction`
   - 节点内核 Prompt
6. `examples`
   - few-shot 风格示例
7. `exit_criteria`
   - 由 `InsightEvaluator` 做结构化判定

### 8.2 不建议做成“解释模板直出”
精神分析最危险的做法，是把节点做成“命中某个模式 -> 直接解释一句标准答案”。

这里必须坚持：
1. 节点只提供观察框架和语言边界
2. 真正的回复仍然由 Executor 基于当前上下文组装
3. 节点只是帮助 AI 稳定地“看一眼什么”，不是替 AI 预设“真相”

## 9. 推荐的运行时状态设计

### 9.1 最小必要状态字段
建议在 `psychoanalysis/state.py` 中定义 `PsychoanalysisGraphState`，至少包含以下字段：

1. 基础字段
   - `session_id`
   - `subject_key`
   - `persona_id`
   - `therapy_mode`
   - `selected_model`
   - `session_phase`
   - `current_stage`
   - `current_phase`
   - `current_technique_id`

2. 会话上下文字段
   - `history_messages`
   - `last_user_message`
   - `last_assistant_message`
   - `last_summary`
   - `recalled_pattern_memory`

3. 分析推进字段
   - `focus_theme`
   - `association_openness`
   - `manifest_theme`
   - `repetition_theme_candidate`
   - `working_hypothesis`
   - `pattern_confidence`
   - `insight_score`
   - `insight_ready`
   - `interpretation_depth`

4. 动力学字段
   - `active_defense`
   - `resistance_level`
   - `alliance_strength`
   - `relational_pull`
   - `here_and_now_triggered`
   - `containment_needed`

5. 异常与边界字段
   - `safety_status`
   - `alliance_rupture_detected`
   - `resistance_spike_detected`
   - `advice_pull_detected`
   - `exception_flags`

6. 熔断字段
   - `technique_attempt_count`
   - `technique_stall_count`
   - `last_progress_marker`
   - `circuit_breaker_open`
   - `next_fallback_action`
   - `technique_trace`

### 9.2 为什么这些字段必要
精神分析流派比 CBT / Humanistic 更依赖“深度边界”判断，因此至少要能回答：
1. 现在是在展开材料，还是已经可以做链接？
2. 用户是在接近感受，还是在明显回避？
3. 当前是关系张力上升，还是只是内容复杂？
4. 这句解释是工作性假设，还是已经过深？

如果没有这些中间状态，路由会非常不稳定。

### 9.3 推荐的状态值草案
建议约束以下字段的枚举：
1. `association_openness`
   - `guarded`
   - `partial`
   - `open`
2. `resistance_level`
   - `low`
   - `medium`
   - `high`
3. `interpretation_depth`
   - `surface`
   - `linking`
   - `integration`
4. `relational_pull`
   - `approval_seeking`
   - `testing_authority`
   - `withdrawing`
   - `dependency_pull`
   - `''`

## 10. Router 设计

### 10.1 Pre-flight Check 必须前置
精神分析流派必须保留“前置检测”，不能先深挖再补救。

推荐优先级：
1. `safety_override`
2. `alliance_rupture_detected`
3. `resistance_spike_detected`
4. `advice_pull_detected`
5. 再进入普通分析相位选择

实现补充：
1. `PreFlightDynamicCheck` 的默认实现应与当前人本主义运行时一致，优先走本地 `signal_extractor.py`、规则匹配或极小模型。
2. MVP 不建议把“前置检测”和“正式回复生成”拆成两次串行的大模型调用。
3. 更稳妥的做法有两种：
   - 前置检测完全本地化
   - 由一次主模型调用同时返回 `reply + state_patch + 动力学分类信号`，后端再拆解
4. 这条约束需要直接纳入开发验收，否则精神分析流派会天然比另外两条线慢一倍。

### 10.2 相位选择原则
推荐的粗路由原则如下：
1. 当用户明显脆弱、被触发、被分析感过强时：
   - 进入 `containment`
2. 当用户还在叙述、材料较散、但愿意继续说时：
   - 进入 `association`
3. 当材料开始出现明显跳题、合理化、只讲道理时：
   - 进入 `defense_clarification`
4. 当当前困扰和历史重复模式出现较强相似性时：
   - 进入 `pattern_linking`
5. 当用户对当前对话关系本身产生明显反应时：
   - 进入 `relational_reflection`
6. 当已经形成足够材料，且用户承受得住时：
   - 进入 `insight_integration`

### 10.3 不做“无限深挖”
Router 必须控制一个硬边界：
1. 单轮只允许推进一个分析动作。
2. 连续两轮没有明确推进时，优先回退而不是继续追问。
3. 若 `resistance_level=high` 或 `alliance_strength=weak`，禁止进入 `insight_integration`。

### 10.4 推荐的 fallback 行为
建议沿用当前两条线的风格，定义：
1. `retry_same_technique`
2. `switch_same_phase`
3. `regress_to_containment`
4. `jump_to_repair`
5. `wrap_up_now`
6. `handoff_to_safety`

其中：
1. MVP 第一版不把“切到人本主义 Graph”作为标准 fallback。
2. 若确实需要更柔性的承接，应优先通过 `containment / repair` 节点在本 Graph 内解决。

## 11. Executor Prompt 组装逻辑

### 11.1 角色语气基线
“深挖派的心理学前辈”的回复基线建议为：
1. 语气稳、慢、少解释腔
2. 多使用“我注意到”“我有点好奇”“好像有一条线又出现了”
3. 避免“一针见血式揭露”
4. 避免直接给方案
5. 任何解释都用假设性表达，不把推测说成事实

### 11.2 Prompt 必须包含的上下文块
建议对齐现有 `executor.py` 风格，组装以下内容：
1. Persona 风格约束
2. 当前技术节点目标
3. 当前技术节点的 avoid rules
4. 当前状态相关字段
5. 最近一次保存摘要
6. `recalled_pattern_memory` 中的脱敏模式线索
7. 当前轮是否有阻抗、关系张力、边界拉扯
8. 当前允许的解释深度上限

### 11.3 特别的输出约束
精神分析流派应追加 4 条专属约束：
1. 不把假设说成诊断或事实。
2. 不直接下“你真正的问题是……”这类结论。
3. 不在用户尚未准备好时把对话拉向童年、创伤或家庭根源。
4. 如果用户要求立刻给方案，只能承接急切并帮助收束问题，不能假装自己不是建议型产品却又偷偷给命令。

### 11.4 收尾语气约束
精神分析流派的收尾不能做成“聊完就散”，也不能硬塞 homework。

推荐的收尾基调是：
1. 点出本轮刚刚浮现的一条线索
2. 不要求用户立刻改变
3. 留下一个轻量、开放式、可在现实里自我注意的观察点

也就是说，`wrap_up` 更像：
1. 一个可带走的工作性观察
2. 一句不会压迫用户的悬浮注意力提示
3. 一种“我们下次可以从这里继续”的收束感

建议在执行器与节点资产中，为 `psa_reflective_close` 单独定义这一语气，而不是复用 CBT 的行动式收尾。

## 12. Insight Evaluator 与熔断机制

### 12.1 为什么这一层尤其关键
精神分析流派比另外两条线更需要一个强 Evaluator，因为“没有推进”和“推进过度”都可能伤害体验。

因此 `insight_evaluator.py` 必须同时回答：
1. 这轮是否形成了一点新的可接受洞察？
2. 这轮是否只是重复追问或重复解释？
3. 当前是否已经把用户推到阻抗边缘？
4. 是否需要熔断并回退到 containment / repair？

### 12.2 推荐的 progress marker
第一版可以先定义以下 `progress_marker`：
1. `material_opened`
2. `defense_named_softly`
3. `repetition_pattern_glimpsed`
4. `here_and_now_named`
5. `insight_landed_lightly`
6. `resistance_softened`
7. `alliance_repaired`
8. `no_progress`

### 12.3 必须具备的熔断规则
必须显式加入：
1. 最大尝试次数限制
2. 最大 stall 次数限制
3. 若连续两轮 `no_progress`，默认回退
4. 若关系信任下降、阻抗升高，则禁止继续深层解释
5. 若已经进入 `integration` 但 `insight_score` 仍无提升，则直接 `wrap_up_now` 或 `regress_to_containment`

也就是说：
1. 不能无限追着一个模式问。
2. 不能把“用户没反应”误判成“需要再解释一次”。

## 13. 双轨记忆与阅后即焚的对齐方案

### 13.1 精神分析流派的特殊点
这条线天然希望保留“重复模式”的连续性，但产品又承诺：
1. 原始消息不长期保留
2. 用户可以全盘销毁

因此必须把长期记忆拆成两层：
1. 用户可见摘要
2. 系统可用的脱敏模式记忆

### 13.2 关键修正：模式记忆不能在用户销毁后继续保留
这是旧稿里最需要修正的一点。

推荐规则：
1. 在 `summary_pending` 阶段，可以生成临时的 `pattern_memory_candidate`。
2. 该 candidate 只存在于当前会话上下文中，不算长期保留。
3. 只有当用户执行“确认保存摘要”后，才把脱敏模式记忆写入可长期读取的存储。
4. 如果用户选择“全盘销毁”，则 `pattern_memory_candidate` 与摘要一起销毁，不得保留。

这样才能和产品承诺保持一致。

### 13.3 MVP v1 的存储落点建议
在不改大数据架构的前提下，建议：
1. 用户可见摘要继续保存在：
   - `summary_draft`
   - `summary_final`
2. 脱敏模式记忆保存在：
   - `session.metadata['psychoanalysis_memory_v1']`
3. 当前运行时状态保存在：
   - `session.metadata['psychoanalysis_state']`

### 13.4 脱敏模式记忆的建议 schema
建议第一版 schema 类似：

```json
{
  "schema_version": "v1",
  "repetition_themes": ["authority_tension", "approval_seeking"],
  "defense_patterns": ["intellectualization", "topic_shift"],
  "relational_pull": ["testing_authority"],
  "working_hypotheses": ["在被评价场景里容易先自我收紧"],
  "confidence": 0.72,
  "source_session_id": "<uuid>",
  "updated_at": "<iso-datetime>"
}
```

必须遵守：
1. 不出现用户原话
2. 不出现人名、地名、公司名等细节
3. 不出现可直接回指某次敏感事件的描述
4. `working_hypotheses` 必须保持抽象，不得是“事实认定”

### 13.5 召回策略
建议第一版召回方式：
1. 读取同一主体最近 3 次 `summary_action=saved` 的会话
2. 提取其中的 `psychoanalysis_memory_v1`
3. 合并成 `recalled_pattern_memory`
4. 在 Prompt 中只作为“背景线索”，而不是直接对用户宣告

### 13.6 后续演进：主体级全局模式画像
“最近 3 次”适合 MVP，但不够代表精神分析真正关心的长跨度重复模式。

因此建议在后续版本中演进到：
1. 以 `usage_subject` 为单位，而不是只以登录用户为单位
2. 通过异步任务周期性扫描该主体的多个已保存会话
3. 将多次 `psychoanalysis_memory_v1` 压缩、合并为一个轻量级 `subject_global_pattern_profile`
4. 新会话优先读取这个全局画像，再按需回看最近几次会话

这样做的好处是：
1. 匿名主体和登录主体都适用
2. 降低每轮 Prompt 的上下文负担
3. 更容易捕捉跨月度、跨季度的重复模式

但这一步不进入 MVP v1，原因是：
1. 当前还没有独立的数据模型承载主体级画像
2. 合并策略、置信度更新和销毁语义都需要单独设计
3. 先把单会话模式提取和最近几次召回做稳，比一开始追求“更深的长期画像”更重要

## 14. 与当前代码库的集成方式

### 14.1 message_service 接入
需要在 [message_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/message_service.py) 中新增：
1. `run_psychoanalysis_turn()` 的 dispatch
2. `merge_psychoanalysis_state_metadata()` 的 metadata 合并
3. 危机抢占后对 `psychoanalysis_state` 的安全态写入

### 14.2 session_service / debug 接入
当前 [session_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/session_service.py) 已补齐：
1. `runtime_state_key='psychoanalysis_state'`
2. `engine='psychoanalysis_graph'`
3. `current_path_key='current_phase'`

### 14.3 summary 与 burn 接入
当前 [summary_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/summary_service.py) 明显更偏 CBT 输出。

精神分析线落地时，建议至少做两件事：
1. 把摘要生成改成“基础摘要 + 流派补充字段”的策略，而不是只认 `cbt_state`
2. 在“确认保存摘要”时同步持久化 `psychoanalysis_memory_v1`

### 14.4 推荐的状态 merge 方式
应完全对齐现有两条线：
1. runtime service 输出 `persist_patch`
2. `message_service` 调用 `merge_psychoanalysis_state_metadata()`
3. 只 merge `psychoanalysis_state` 子 key，不覆盖 `metadata` 其他部分

## 15. 开发分阶段建议

### Phase 1：运行时骨架
目标：把第三条线接入现有系统，但先不追求复杂模式记忆。

状态：已完成 MVP 骨架。

内容：
1. 新建 `backend/moodpal/psychoanalysis/` 基本文件
2. 定义 `PsychoanalysisGraphState`
3. 定义 `PsychoanalysisGraph`
4. 定义第一版 `router_config.py`
5. 接入 `psychoanalysis_runtime_service.py`
6. 在 `message_service.py` 中完成 `insight_mentor` 到 `psychoanalysis_graph` 的运行时分发

### Phase 2：首批节点与执行器
目标：让“深挖派的心理学前辈”开始跑真实 LLM 驱动的探索型对话。

状态：已完成首批 JSON 节点、执行器、规则路由、本地信号提取、退出评估与基础测试。

内容：
1. 先用 Python 常量或最小 JSON 节点库定义首批 10 个节点
2. 补 `executor_prompt_config.py`
3. 补 `signal_extractor.py`
4. 补 `insight_evaluator.py` 与熔断规则
5. 补基础测试与回归样例

### Phase 3：脱敏模式记忆
目标：让跨会话的重复模式感知真正成立。

状态：MVP 闭环已完成。当前已支持在保存摘要时生成并写入 `psychoanalysis_memory_v1`，并在新会话开始时召回最近几次的脱敏模式记忆。

内容：
1. 增加 `pattern_memory.py`
2. 在保存摘要时写入 `psychoanalysis_memory_v1`
3. 在新会话开始时召回最近几次的抽象模式
4. 补隐私测试，确保销毁路径不留残余

### Phase 4：摘要与质量打磨
目标：让这条线的总结方式和另两条线拉开差异。

内容：
1. 摘要改成更适合探索型对话的结构
2. 调整“工作性假设”的语言强度
3. 加强阻抗、联盟裂痕、建议拉扯等边界案例测试

## 16. 不建议在 MVP 第一版就做的内容
以下内容建议明确延后：
1. 真正的向量数据库 / embedding 检索层
2. 高强度移情解释
3. 梦的深度分析、口误分析等高风险场景
4. 跨 Graph 自动切到 Humanistic Graph
5. 对童年/创伤根源的主动深挖

这些不是永远不做，而是当前项目阶段不适合先做。

## 17. 本文档对后续开发的直接指导结论
落地时应遵守以下 10 条：
1. 精神分析流派沿用现有两条线的运行时骨架，不单开新架构。
2. 先做 `psychoanalysis_state / router / executor / evaluator / runtime_service` 五件套。
3. 先做结构化节点库，不把“解释话术”硬编码到 Graph 里。
4. 把阻抗、联盟裂痕、建议拉扯做成前置抢占，而不是事后补救。
5. 单轮只推进一个分析动作，不连续深挖。
6. 所有解释都必须是工作性假设，不是事实宣判。
7. 长期记忆只保存脱敏抽象模式，不保存原文细节。
8. 用户若选择销毁，则抽象模式也不得保留。
9. 第一版用关系型 JSON 存储模式记忆，不急着上 Vector DB。
10. “深挖派的心理学前辈”在产品上表现为更会看见重复模式，但底层必须比其他两条线更保守、更可熔断。

## 18. 后续仍需补齐的内容
在本文档基础上，后续还需要继续细化：
1. `docs/moodpal/Psychoanalysis/` 的正式 JSON 节点资产
2. `router_config.py` 的常量与规则草案
3. `insight_rule_config.py` 的退出/熔断规则
4. `psychoanalysis_memory_v1` 的最终 schema
5. 精神分析流派专属摘要模板与回归样例集
