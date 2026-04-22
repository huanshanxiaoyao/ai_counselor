# MoodPal 人本主义 + LangGraph 设计（MVP v1）

## 1. 文档目的
本文件聚焦一个问题：

如何把 `docs/moodpal/Humanistic/` 目录下的人本主义结构化节点，与 MoodPal 的 LangGraph 状态机结合起来，完成“共情派的知心学姐”这一角色的对话实现。

本文档是 [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md) 的专题细化稿，重点解决：
1. 人本主义 JSON 节点如何映射到 LangGraph 运行时
2. 人本主义会话主状态机如何设计
3. 共情型对话如何做阶段推进、异常抢占和退出判定
4. 当前草稿里哪些内容可以直接落地，哪些需要改成后续补齐项

## 2. 当前 Humanistic JSON 的结构理解

### 2.1 现有资产不是“概念说明”，而是“节点库雏形”
`docs/moodpal/Humanistic/part1.json` 与 `docs/moodpal/Humanistic/part2.json` 里的记录已经具备结构化节点雏形，字段与 CBT 节点库保持一致：
1. `node_id`
2. `name`
3. `category`
4. `trigger_intent`
5. `prerequisites`
6. `system_instruction`
7. `examples`
8. `exit_criteria`

这意味着它们可以直接作为：
1. LangGraph 的候选技术节点库
2. Prompt 组装的结构化输入
3. 路由器的候选技术来源
4. 质量评估与人工回溯的依据

### 2.2 当前节点总览
当前 `Humanistic/` 目录下共有 7 个节点，分布在 2 个 JSON 文件中，分为 5 类：

1. `情绪抱持层`
   - `hum_validate_normalize`

2. `情感澄清层`
   - `hum_reflect_feeling`
   - `hum_body_focus`

3. `深层接纳层`
   - `hum_unconditional_regard`

4. `异常修复层`
   - `hum_exception_alliance_repair`
   - `hum_exception_numbness_unfreeze`

5. `边界修复层`
   - `hum_boundary_advice_pull`

### 2.3 关键修正
相较于原始草稿，这里有三个必须先校正的点：
1. 异常处理节点现已补齐第一版 JSON 资产，但仍属于待运行时验证的设计稿；当前目录中已经新增：
   - `hum_exception_alliance_repair`
   - `hum_exception_numbness_unfreeze`
   - `hum_boundary_advice_pull`
2. 人本主义主链不是“议程驱动”，而是“关系质量 + 情绪唤醒度 + 自我开放程度”共同驱动。
3. 人本主义的退出标准不是“任务完成”，而是“用户是否感到被接住、情绪是否更清晰、自我攻击是否松动、是否适合自然收尾”。

结论：
1. 目标架构应采用“宏状态机 + 节点库”的结构，异常处理也属于节点库资产的一部分。
2. 在运行时尚未完全消费这些异常节点前，可以临时由 Graph 层 repair handler 兜底，但接口与状态字段应对齐现有 JSON 节点形态。

## 3. 推荐总体方案

### 3.1 核心思想
不要把人本主义节点直接等价为“固定线性流程”。

推荐采用两层结构：
1. 上层：LangGraph 宏状态机
   - 负责风险抢占
   - 负责关系检测
   - 负责共情阶段推进
   - 负责收尾与摘要素材沉淀
2. 下层：Humanistic 技术节点库
   - 由 JSON 定义
   - 在具体阶段被路由器选中
   - 作为 Prompt 组装与退出判定的输入

### 3.2 为什么这么做
这样设计有 4 个直接好处：
1. 保持人本主义对话的自然性，不把对话做成伪问卷。
2. 节点库可扩展，未来增加“联盟修复”“麻木松动”等技术时不必重写整张图。
3. 人本主义和 CBT 能复用同一套 Supervisor Graph 框架，但保留不同的内部推进逻辑。
4. 有利于把“共情是否生效”做成结构化判定，而不是纯靠感觉。

## 4. 推荐的 Humanistic Graph 结构

### 4.1 Graph 分层
Humanistic Graph 建议拆成三类状态：

1. 会话级状态
   - 新会话初始化
   - 安全检查
   - 关系建立
   - 共情推进
   - 温和收尾

2. 共情级状态
   - 抱持与合法化
   - 情感反映
   - 躯体聚焦
   - 深层接纳

3. 中断级状态
   - 危机安全抢占
   - 联盟裂痕修复
   - 情感麻木/空白处理
   - 过强建议拉扯的边界修正

补充要求：
1. 中断级状态优先级高于普通共情推进。
2. 每轮进入主链执行前，都必须做异常与风险前置检测。
3. 人本主义不等于“永远顺着情绪流”，必要时要温和收束并守边界。

### 4.2 主链路
推荐的人本主义主链路如下：

`SessionStart`
-> `SafetyCheck`
-> `PreFlightRelationalCheck`
-> `EntryAttunement`
-> `AffectAssessment`
-> `DetermineEmpathyPhase`
-> `SelectTechnique`
-> `TechniqueExecution`
-> `EvaluateResonance`
-> `NextStepDecision`
-> `WrapUp`

含义如下：
1. `SessionStart`
   - 初始化会话上下文
   - 读取最近一次确认摘要
   - 注入角色设定与模型选择

2. `SafetyCheck`
   - 危机检测
   - 若命中高危，直接跳出普通 Humanistic Graph

3. `PreFlightRelationalCheck`
   - 每轮进入主链前先检测高优先级关系异常
   - 包括联盟裂痕、明显麻木断联、强烈要求 AI 直接下指令等
   - 若命中，则先进入修复或边界处理轨道

4. `EntryAttunement`
   - 做自然开场与轻度承接
   - 如果存在历史摘要，只能用“随口关心”的方式柔和带出

5. `AffectAssessment`
   - 评估情绪强度、情绪清晰度、自我开放程度、是否存在自我攻击

6. `DetermineEmpathyPhase`
   - 决定当前更适合进入抱持、澄清、躯体聚焦还是深层接纳

7. `SelectTechnique`
   - 从节点库中选出当前最合适的人本主义技术

8. `TechniqueExecution`
   - 执行当前技术节点

9. `EvaluateResonance`
   - 判断是否真正产生“被理解”和“情感更可触达”的推进
   - 同时负责最大重试、stall 检测和熔断

10. `NextStepDecision`
   - 决定继续当前阶段、切换技术、回退抱持、转修复，还是收尾

11. `WrapUp`
   - 做温和收尾
   - 产出摘要素材，而不是硬性布置任务

## 5. JSON 与 LangGraph 的映射方式

### 5.1 推荐映射表
建议将 JSON 字段映射为以下运行时用途：

1. `node_id`
   - 技术节点唯一标识
   - 用于路由、日志、调试、回放

2. `category`
   - 决定它属于哪一类共情阶段
   - 用于阶段级粗路由

3. `trigger_intent`
   - 作为候选匹配信号
   - 不直接当硬编码布尔条件，需先转成结构化状态特征

4. `prerequisites`
   - 作为软门槛或硬门槛
   - 决定当前节点是否进入候选集

5. `system_instruction`
   - 当前技术的核心 Prompt 正文

6. `examples`
   - few-shot 参考示例
   - 需要裁剪后拼入 Prompt

7. `exit_criteria`
   - 用于判断当前技术是否完成
   - 由 `HumanisticResonanceEvaluator` 做结构化判定

### 5.2 关键建议
人本主义节点的 `trigger_intent` 多为情绪和关系描述，不适合在 MVP 阶段强行写成复杂 DSL。

推荐先用两步法：
1. 用规则与轻量评估器把当前会话映射到候选阶段
2. 在该阶段内选择最合适的具体节点

也就是说：
先选“此刻最需要的关系动作”，再选“具体技术节点”。

### 5.3 异常节点资产补齐策略
当前 JSON 资产已补齐 3 个关键异常节点草案：
1. `hum_exception_alliance_repair`
   - 处理“你根本没懂我”“别再套模板了”这类联盟裂痕
2. `hum_exception_numbness_unfreeze`
   - 处理“我什么都感觉不到”“脑子一片空白”这类情感麻木/断联
3. `hum_boundary_advice_pull`
   - 处理“别共情了，直接告诉我怎么办”这类强建议拉扯

接下来的技术策略应是：
1. 资产层
   - 这 3 类异常已经进入正式 JSON 节点库
2. 运行时过渡期
   - 在 Router / Executor / Evaluator 尚未完全接入前，保留 `GRAPH_EXCEPTION_HANDLERS` 作为临时兜底
   - 但 handler 的输入输出字段、退出判定、日志结构，要与现有 JSON 节点保持一致
3. 目标态
   - Router 统一从节点注册表中选取异常节点，而不是散落在分支逻辑里

这样做可以保证：
1. 异常处理资产已经结构化，不再停留在“口头设计”
2. 现阶段不阻塞后续运行时开发
3. 后续可以像普通技术节点一样复用、测试、调优

## 6. 推荐的运行时状态

### 6.1 会话状态字段
LangGraph 运行时至少需要这些字段：

1. `session_id`
2. `subject_key`
3. `persona_id`
4. `therapy_mode`
5. `current_stage`
6. `current_phase`
7. `current_technique_id`
8. `history_messages`
9. `last_user_message`
10. `last_assistant_message`
11. `last_summary`
12. `emotional_intensity`
13. `dominant_emotions`
14. `emotional_clarity`
15. `openness_level`
16. `self_attack_flag`
17. `body_signal_present`
18. `body_focus_ready`
19. `felt_sense_description`
20. `resonance_score`
21. `being_understood_signal`
22. `relational_trust`
23. `alliance_rupture_detected`
24. `numbness_detected`
25. `advice_pull_detected`
26. `safety_status`
27. `homework_candidate`
28. `technique_attempt_count`
29. `technique_stall_count`
30. `last_progress_marker`
31. `circuit_breaker_open`
32. `next_fallback_action`
33. `technique_trace`

### 6.2 为什么这些字段必要
当前 Humanistic JSON 的 `prerequisites` 和 `exit_criteria` 都依赖这些中间状态。

例如：
1. `hum_validate_normalize` 需要识别情绪洪流或羞耻感。
2. `hum_reflect_feeling` 需要用户已经愿意持续倾诉。
3. `hum_body_focus` 需要用户处于模糊感受或躯体化焦虑，而不是危机状态。
4. `hum_unconditional_regard` 需要检测到显著自我攻击。

没有这些状态字段，就无法稳定路由，也无法判断共情是否真的起效。

### 6.3 推荐的 `HumanisticGraphState` 草案

```python
from typing import Literal, TypedDict


class HumanisticGraphState(TypedDict, total=False):
    # --- 基础身份 ---
    session_id: str
    subject_key: str
    persona_id: str
    therapy_mode: Literal["humanistic"]
    selected_model: str

    # --- 生命周期 ---
    session_phase: Literal[
        "starting",
        "active",
        "ending",
        "summary_pending",
        "closed",
    ]
    current_stage: Literal[
        "safety_check",
        "preflight_relational_check",
        "entry_attunement",
        "affect_assessment",
        "determine_phase",
        "select_technique",
        "execute_technique",
        "evaluate_resonance",
        "handle_repair",
        "wrap_up",
    ]
    current_phase: Literal[
        "holding",
        "clarifying",
        "body_focusing",
        "accepting",
        "repair",
        "wrap_up",
        "",
    ]
    current_technique_id: str

    # --- 历史与消息 ---
    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict

    # --- 情绪与关系 ---
    emotional_intensity: int
    dominant_emotions: list[str]
    emotional_clarity: Literal["diffuse", "emerging", "clear"]
    openness_level: Literal["guarded", "partial", "open"]
    self_attack_flag: bool
    shame_signal: bool
    body_signal_present: bool
    body_focus_ready: bool
    felt_sense_description: str
    resonance_score: int
    being_understood_signal: bool
    relational_trust: Literal["weak", "medium", "strong"]

    # --- 产出与沉淀 ---
    unmet_need_candidate: str
    self_compassion_shift: str
    homework_candidate: str

    # --- 异常与安全 ---
    safety_status: Literal["safe", "crisis_override"]
    alliance_rupture_detected: bool
    numbness_detected: bool
    advice_pull_detected: bool
    exception_flags: dict

    # --- 执行与熔断 ---
    technique_attempt_count: int
    technique_stall_count: int
    last_progress_marker: str
    circuit_breaker_open: bool
    next_fallback_action: str

    # --- 可观测性 ---
    technique_trace: list[dict]
```

### 6.4 最小必需字段（MVP）
如果第一版要压缩范围，至少不能少这些字段：
1. `session_id`
2. `subject_key`
3. `persona_id`
4. `therapy_mode`
5. `current_stage`
6. `current_phase`
7. `current_technique_id`
8. `history_messages`
9. `last_summary`
10. `emotional_intensity`
11. `dominant_emotions`
12. `emotional_clarity`
13. `openness_level`
14. `self_attack_flag`
15. `body_signal_present`
16. `resonance_score`
17. `being_understood_signal`
18. `relational_trust`
19. `alliance_rupture_detected`
20. `numbness_detected`
21. `advice_pull_detected`
22. `safety_status`
23. `technique_attempt_count`
24. `technique_stall_count`
25. `last_progress_marker`
26. `circuit_breaker_open`

### 6.5 状态流转约束
为了避免 Graph 出现不合法跳转，建议定义以下硬约束：
1. `safety_status="crisis_override"` 时
   - 禁止继续任何普通人本主义技术节点
2. `session_phase in ["summary_pending", "closed"]` 时
   - 禁止再执行 `execute_technique`
3. `relational_trust="weak"` 且 `alliance_rupture_detected=true` 时
   - 禁止进入 `hum_body_focus` 或 `hum_unconditional_regard`
   - 必须先走修复/再抱持
4. `emotional_intensity >= 9` 且情绪仍在失控时
   - 禁止直接进入 `hum_reflect_feeling` 的深层命名或 `hum_body_focus`
   - 优先回到 `hum_validate_normalize`
5. `self_attack_flag=false` 时
   - 默认不进入 `hum_unconditional_regard`

### 6.6 状态更新原则
每轮只允许做“小步更新”：
1. `TechniqueExecutor` 只写本轮直接得到的新信息
2. `ResonanceEvaluator` 负责写推进判定与熔断字段
3. `Router` 负责写 `current_phase`、`current_technique_id` 与 `next_fallback_action`

### 6.7 `technique_trace` 建议
建议每轮追加一条 trace，用于调试和质量复盘：

```json
{
  "turn_index": 5,
  "phase": "clarifying",
  "technique_id": "hum_reflect_feeling",
  "progress_marker": "deep_emotion_named",
  "done": true,
  "should_trip_circuit": false
}
```

## 7. 推荐的 Agent 分工

### 7.1 Agent 列表
对于 Humanistic Graph，建议至少有 6 个内部 Agent：
1. `SafetyAgent`
   - 危机检测与抢占
2. `AffectEvaluatorAgent`
   - 判断情绪强度、清晰度、自我开放程度、关系稳定度
3. `HumanisticStateSignalExtractor`
   - 先把当轮用户输入转成结构化状态信号
   - 例如：
     - `emotional_intensity`
     - `dominant_emotions`
     - `alliance_rupture_detected`
     - `numbness_detected`
     - `advice_pull_detected`
4. `HumanisticTechniqueRouter`
   - 从节点库中选出当前最合适的人本主义技术
5. `HumanisticTechniqueExecutor`
   - 根据选中的节点执行对应 Prompt
6. `HumanisticResonanceEvaluator`
   - 判断本轮共情是否产生了实质推进
7. `SummaryAgent`
   - 负责收尾、摘要素材沉淀与后续会话自然承接素材生成

### 7.2 职责边界
关键点：
1. `HumanisticStateSignalExtractor` 先做“原始文本 -> 结构化状态”的预处理，再交给 Router。
2. `HumanisticTechniqueRouter` 不直接对用户说话，只负责选阶段和技术。
3. `HumanisticTechniqueExecutor` 才负责生成“知心学姐”的最终回复。
4. `HumanisticResonanceEvaluator` 不做生成，只做判定。
5. 异常修复既可以由单独 repair handler 完成，也可以先作为 Router 输出的特殊动作处理。

## 8. Technique Router 的核心逻辑

### 8.1 粗路由：先选当前共情阶段
先根据当前状态决定进入哪一类阶段：
1. `holding`
   - 情绪洪流、强羞耻、明显崩溃时
2. `clarifying`
   - 用户已能叙述，但情绪仍混杂不清时
3. `body_focusing`
   - 用户说“不知道是什么感觉”，但身体信号明显时
4. `accepting`
   - 自我攻击、自我厌恶、自我否定明显时
5. `repair`
   - 出现联盟裂痕、麻木断联或强边界拉扯时

### 8.2 细路由：再选技术节点
在阶段内选具体节点：
1. 如果用户在剧烈发泄、羞耻或崩溃：
   - `hum_validate_normalize`
2. 如果用户讲了很多故事，但核心情绪仍模糊：
   - `hum_reflect_feeling`
3. 如果用户主要在描述躯体感受或“说不上来”：
   - `hum_body_focus`
4. 如果用户明显在攻击自己、否定自己的价值：
   - `hum_unconditional_regard`

### 8.3 异常优先级
异常处理必须高优先级抢占：
1. `safety override`
   - 高危内容直接跳出 Humanistic Graph
2. `alliance rupture`
   - 如“你根本不懂我”“别再套话了”
3. `numbness / disconnect`
   - 如“我什么都感觉不到”“脑子是空白的”
4. `advice pull`
   - 如“你别共情了，直接告诉我怎么办”

实现上建议：
1. 每轮进入主链前先做 `PreFlightRelationalCheck`。
2. `TechniqueExecution` 结束后，再做一次轻量复检。
3. 不能只在执行失败时才检查异常，否则会出现“明明已经失联，还在继续反映情绪”的错误体验。

### 8.4 MVP 路由表（第一版）
下面这张表不是最终代码实现，而是 `HumanisticTechniqueRouter` 的首版业务规则基线。

1. `holding`
   - 进入条件：
     - `emotional_intensity >= 8`
     - 或 `shame_signal=true`
     - 或用户仍在情绪洪流中
   - 候选节点：
     - `hum_validate_normalize`
   - 成功产出：
     - 情绪被承接
     - `emotional_intensity` 略下降
     - `relational_trust` 上升

2. `clarifying`
   - 进入条件：
     - `emotional_intensity` 不再失控
     - 用户愿意继续倾诉
     - `emotional_clarity in ["diffuse", "emerging"]`
   - 候选节点：
     - `hum_reflect_feeling`
   - 成功产出：
     - 更具体的情绪标签
     - `being_understood_signal=true` 或 `resonance_score` 上升

3. `body_focusing`
   - 进入条件：
     - `body_signal_present=true`
     - `emotional_clarity="diffuse"`
     - 用户尚可停下来感受身体
   - 候选节点：
     - `hum_body_focus`
   - 成功产出：
     - `felt_sense_description`
     - 更清晰的情绪命名

4. `accepting`
   - 进入条件：
     - `self_attack_flag=true`
     - 或出现明显“我很糟糕/不配/废物”表达
   - 候选节点：
     - `hum_unconditional_regard`
   - 成功产出：
     - 自我攻击强度下降
     - `self_compassion_shift`

5. `repair`
   - 进入条件：
     - `alliance_rupture_detected=true`
     - 或 `numbness_detected=true`
     - 或 `advice_pull_detected=true`
   - 候选处理：
     - 目标态：
       - `hum_exception_alliance_repair`
       - `hum_exception_numbness_unfreeze`
       - `hum_boundary_advice_pull`
     - 过渡期：
       - 图层 repair handler 兜底，直到对应 JSON 节点补齐
   - 成功产出：
     - `relational_trust` 恢复
     - 或回退到 `holding`
     - 或直接 `wrap_up_now`

### 8.5 路由优先级
MVP 建议按以下顺序判定：
1. `safety override`
2. `repair override`
3. `holding gate`
4. `accepting gate`
5. `body_focusing gate`
6. `clarifying default`

### 8.6 同阶段替代策略
当一个节点熔断时，路由器应优先尝试同阶段替代或更保守的回退：
1. `hum_reflect_feeling`
   - 若用户一直说“不是这个感觉”，可回退到 `hum_validate_normalize`
2. `hum_body_focus`
   - 若用户更困惑或更不安，可回退到 `hum_validate_normalize`
3. `hum_unconditional_regard`
   - 若用户对深层接纳感到不适，可退回 `hum_reflect_feeling` 或 `hum_validate_normalize`
4. `repair handler`
   - 若修复失败，直接 `wrap_up_now`

## 9. Technique Executor 的实现建议

### 9.1 Prompt 组装
执行单个节点时，Prompt 由以下部分组成：
1. Persona 设定
   - “知心学姐”的语气、节奏、边界、亲和感
2. 人本主义共通约束
   - 不争辩
   - 不说教
   - 不诊断
   - 不一口气抛多个问题
   - 尽量避免使用“为什么”
3. 当前会话状态
   - 当前情绪强度
   - 当前共情阶段
   - 是否存在自我攻击
   - 之前已经命中过哪些情绪
4. 当前 JSON 节点的 `system_instruction`
5. 当前 JSON 节点的 `examples`
6. 输出格式要求
   - 只输出一轮用户可见的回复
   - 最多推进一步
   - 不提前切换到下一种技术

### 9.2 重要约束
执行器必须遵守“单步推进”原则：
1. 每轮只做一个关系动作。
2. 不允许一条回复里同时完成“抱持 + 深层命名 + 自我接纳 + 任务建议”。
3. 历史摘要只能柔和带出，不能像盘问进度。
4. 只有在用户情绪稳定时，才允许把 `homework_candidate` 作为轻提示带出。

## 10. Resonance Evaluator 的实现建议

### 10.1 作用
`HumanisticResonanceEvaluator` 是人本主义图里的关键判定器。

它决定：
1. 当前技术是否产生了实质共鸣
2. 是否继续停留在该节点
3. 是否切换到更深或更浅的阶段
4. 是否已经出现停滞，需要熔断或收尾

### 10.2 实现方式
推荐采用“结构化判定器”：

输入：
1. 当前节点的 `exit_criteria`
2. 最近 1-2 轮用户输入
3. 当前状态字段

输出：
1. `done: true/false`
2. `confidence: 0-1`
3. `reason`
4. `state_patch`
5. `should_trip_circuit: true/false`
6. `trip_reason`

### 10.2.1 推荐输出 schema
建议 `HumanisticResonanceEvaluator` 输出一个固定结构：

```json
{
  "done": false,
  "confidence": 0.84,
  "reason": "用户仍在讲事件经过，但还没有明确认领更深层的情绪体验",
  "state_patch": {
    "emotional_intensity": 72,
    "dominant_emotions": ["委屈", "失落"],
    "being_understood_signal": false
  },
  "progress_marker": "deeper_emotion_candidate_named",
  "stall_detected": false,
  "technique_attempt_count": 2,
  "technique_stall_count": 0,
  "should_trip_circuit": false,
  "trip_reason": "",
  "next_fallback_action": "retry_same_technique"
}
```

### 10.3 工程价值
如果没有 Resonance Evaluator，人本主义图会出现三个问题：
1. 在“重复共情措辞”里打转，用户觉得空泛。
2. 太早下潜，用户尚未被接住就被要求说更深感受。
3. 缺少熔断时，会卡在“你是不是很委屈/对，不只是委屈吗”的死循环。

因此，最大重试、stall 检测和熔断降级必须内建在该判定器里，而不是后补。

### 10.4 熔断与最大重试机制
建议增加以下运行时控制字段：
1. `technique_attempt_count`
2. `technique_stall_count`
3. `last_progress_marker`
4. `circuit_breaker_open`

建议的 MVP 规则：
1. 单一技术节点连续执行超过 3 轮仍未满足 `exit_criteria`，进入熔断判定。
2. 如果连续 2 轮没有新的情绪颗粒度、关系改善或自我攻击松动，视为 `stall`。
3. 若满足“轮数过多”或“持续 stall”，则 `should_trip_circuit=true`。

### 10.5 熔断后的处理策略
熔断后不能简单报错退出，必须降级：
1. 先尝试切换同阶段替代或更保守阶段
2. 如果关系已经变脆，转 repair handler
3. 如果当前轮明显疲劳或用户不想继续，直接进入 `WrapUp`

### 10.5.1 `next_fallback_action` 枚举建议
MVP 先约束成少量固定值：
1. `retry_same_technique`
2. `switch_same_phase`
3. `regress_to_holding`
4. `jump_to_repair`
5. `wrap_up_now`

### 10.5.2 节点级退出判定样例
为了让实现更具体，MVP 可以先为 4 个主链核心节点定义首版判定规则：

1. `hum_validate_normalize`
   - `done=true` 条件：
     - 用户从情绪洪流转向可叙述状态
     - 或明确表示“你这样说让我没那么紧绷了”

2. `hum_reflect_feeling`
   - `done=true` 条件：
     - 用户认领了更准确的情绪命名
     - 或情绪颗粒度明显变细
   - `stall=true` 信号：
     - 用户连续两轮表示“不是这个感觉”

3. `hum_body_focus`
   - `done=true` 条件：
     - 用户能够描述身体感受的形状、位置、重量、颜色，或从中触达更明确情绪
   - `trip=true` 信号：
     - 用户明显更慌、更乱，难以继续停留在身体感受上

4. `hum_unconditional_regard`
   - `done=true` 条件：
     - 用户的自我攻击明显松动
     - 或首次出现自我保护、自我许可的表达

## 11. MVP 推荐的人本主义推进方式

### 11.1 第一版只做最稳的主链
MVP 第一版建议优先做 2 个最稳的节点：
1. `hum_validate_normalize`
2. `hum_reflect_feeling`

原因：
1. 能覆盖最多的“先接住我”场景。
2. 最符合“知心学姐”的首版角色体验。
3. 风险低，容易验证是否产生共鸣。

### 11.2 第二版补躯体与深层接纳
第二批引入：
1. `hum_body_focus`
2. `hum_unconditional_regard`

原因：
1. 这两类技术更强，也更容易用错。
2. 需要先把关系评估和熔断机制跑稳。

### 11.3 第三版接入异常节点
第三批把以下结构化 JSON 节点正式接入运行时：
1. `hum_exception_alliance_repair`
2. `hum_exception_numbness_unfreeze`
3. `hum_boundary_advice_pull`

原因：
1. 这三类异常资产已经准备好，下一步重点是运行时接入与验证。
2. 接入后，异常处理才能与普通技术节点共用路由、执行、评估、测试体系。
3. 这一步不影响前两阶段先把主链跑通，但应作为明确 backlog。

## 12. 与产品体验的连接

### 12.1 用户看到什么
用户看到的是：
1. 一个温暖、慢节奏、有耐心的学姐角色
2. 不是马上给建议，而是先把人接住
3. 在合适时机，帮自己听懂自己的情绪
4. 结束时得到一句可带走的自我理解，而不是硬任务

### 12.2 系统实际上做了什么
系统实际上做的是：
1. 先做风险与关系前置检测
2. 判断当前更需要抱持、澄清、躯体聚焦还是接纳
3. 从节点库中选技术
4. 只推进一步
5. 判断共鸣是否真的发生
6. 再决定下一步

这正是 LangGraph 在人本主义场景下的工程价值。

## 13. 当前最推荐的工程落地方式

### 13.1 代码层建议
不要为每个 JSON 节点各写一个独立 Python 类。

推荐写四类通用组件：
1. `HumanisticNodeRegistry`
   - 负责加载 JSON 节点库
2. `HumanisticStateSignalExtractor`
   - 负责提取当轮情绪、关系和异常信号
3. `HumanisticTechniqueRouter`
   - 负责基于状态挑选候选节点
4. `HumanisticTechniqueExecutor`
   - 负责用选中的 JSON 片段组装 Prompt 并调用 LLM
5. `HumanisticResonanceEvaluator`
   - 负责根据 `exit_criteria` 判定是否退出
   - 同时负责最大重试、stall 检测和熔断决策

再加：
6. `HumanisticRepairHandlers`
   - 负责联盟裂痕、麻木断联、边界拉扯等异常处理的过渡实现
   - 对应 JSON 节点补齐后，可收缩为兼容层或删除

### 13.2 LangGraph 层建议
LangGraph 中保留少量通用节点：
1. `safety_check`
2. `preflight_relational_check`
3. `entry_attunement`
4. `affect_assessment`
5. `determine_phase`
6. `select_technique`
7. `execute_technique`
8. `evaluate_resonance`
9. `handle_repair`
10. `wrap_up`

也就是说：
LangGraph 管流程，JSON 管技术；SignalExtractor 负责预结构化输入；repair handler 只作为异常节点补齐前的临时兼容层。

## 14. `HumanisticTechniqueRouter` 配置草案

### 14.1 配置目标
Router 配置的目标不是替代 LangGraph，而是把“如何从状态选出候选技术”固定成一套可维护常量。

建议 Router 只做 4 件事：
1. 判断是否需要安全抢占
2. 判断是否需要 repair 抢占
3. 选择当前共情阶段
4. 在阶段内选择候选技术节点与降级路径

### 14.2 推荐配置分层
建议 Router 配置拆成以下 6 组常量：
1. `PHASE_PRIORITY`
2. `PHASE_GATE_RULES`
3. `PHASE_CANDIDATES`
4. `TECHNIQUE_RULES`
5. `SAME_PHASE_FALLBACKS`
6. `GRAPH_EXCEPTION_HANDLERS`

补充：
当前异常节点已经资产化，因此 `GRAPH_EXCEPTION_HANDLERS` 更适合作为兼容映射层：
1. 负责把异常 flag / hint 映射到对应的异常 JSON 节点
2. 让过渡期 handler 和正式节点共享同一套 technique id
3. 长期看，主路由仍应以 `PHASE_CANDIDATES`、`TECHNIQUE_RULES` 和显式 repair route rules 为主

### 14.3 推荐代码形态
建议最终代码侧先做成 Python 常量模块，例如：

`backend/moodpal/humanistic/router_config.py`

首版可以写成如下形态：

```python
PHASE_PRIORITY = [
    "safety_override",
    "repair",
    "holding",
    "accepting",
    "body_focusing",
    "clarifying",
]
```

### 14.4 阶段级规则草案

```python
PHASE_GATE_RULES = {
    "holding": {
        "any": [
            ("emotional_intensity", ">=", 8),
            ("shame_signal", "==", True),
            ("last_user_message", "contains_pattern", "崩溃"),
        ],
    },
    "accepting": {
        "any": [
            ("self_attack_flag", "==", True),
            ("last_user_message", "contains_pattern", "我很糟糕"),
            ("last_user_message", "contains_pattern", "不配"),
        ],
    },
    "body_focusing": {
        "all": [
            ("body_signal_present", "==", True),
            ("emotional_clarity", "==", "diffuse"),
        ],
        "block_if": [
            ("emotional_intensity", ">=", 9),
            ("alliance_rupture_detected", "==", True),
        ],
    },
    "clarifying": {
        "all": [
            ("relational_trust", "in", ["medium", "strong"]),
        ],
    },
    "repair": {
        "any": [
            ("alliance_rupture_detected", "==", True),
            ("numbness_detected", "==", True),
            ("advice_pull_detected", "==", True),
        ],
    },
}
```

### 14.5 阶段候选节点草案

```python
PHASE_CANDIDATES = {
    "holding": [
        "hum_validate_normalize",
    ],
    "clarifying": [
        "hum_reflect_feeling",
    ],
    "body_focusing": [
        "hum_body_focus",
    ],
    "accepting": [
        "hum_unconditional_regard",
    ],
    "repair": [
        "hum_exception_alliance_repair",
        "hum_exception_numbness_unfreeze",
        "hum_boundary_advice_pull",
    ],
}
```

### 14.5.1 同阶段降级与异常映射草案

```python
SAME_PHASE_FALLBACKS = {
    "hum_validate_normalize": (),
    "hum_reflect_feeling": ("hum_validate_normalize",),
    "hum_body_focus": ("hum_validate_normalize",),
    "hum_unconditional_regard": ("hum_reflect_feeling", "hum_validate_normalize"),
    "hum_exception_alliance_repair": ("hum_validate_normalize",),
    "hum_exception_numbness_unfreeze": ("hum_validate_normalize",),
    "hum_boundary_advice_pull": ("hum_validate_normalize",),
}

GRAPH_EXCEPTION_HANDLERS = {
    "alliance_rupture_detected": "hum_exception_alliance_repair",
    "numbness_detected": "hum_exception_numbness_unfreeze",
    "advice_pull_detected": "hum_boundary_advice_pull",
}
```

### 14.6 节点级规则草案

```python
TECHNIQUE_RULES = {
    "hum_validate_normalize": {
        "phase": "holding",
        "priority": 100,
        "require": [],
        "prefer_if": [
            ("emotional_intensity", ">=", 8),
            ("shame_signal", "==", True),
        ],
        "block_if": [],
        "produces": ["relational_trust", "emotional_intensity"],
    },
    "hum_reflect_feeling": {
        "phase": "clarifying",
        "priority": 100,
        "require": [
            ("relational_trust", "in", ["medium", "strong"]),
        ],
        "prefer_if": [
            ("emotional_clarity", "in", ["diffuse", "emerging"]),
        ],
        "block_if": [
            ("emotional_intensity", ">=", 9),
        ],
        "produces": ["dominant_emotions", "being_understood_signal"],
    },
    "hum_body_focus": {
        "phase": "body_focusing",
        "priority": 90,
        "require": [
            ("body_signal_present", "==", True),
        ],
        "prefer_if": [
            ("emotional_clarity", "==", "diffuse"),
        ],
        "block_if": [
            ("alliance_rupture_detected", "==", True),
            ("emotional_intensity", ">=", 9),
        ],
        "produces": ["felt_sense_description", "dominant_emotions"],
    },
    "hum_unconditional_regard": {
        "phase": "accepting",
        "priority": 100,
        "require": [
            ("self_attack_flag", "==", True),
        ],
        "prefer_if": [
            ("relational_trust", "in", ["medium", "strong"]),
        ],
        "block_if": [
            ("alliance_rupture_detected", "==", True),
        ],
        "produces": ["self_compassion_shift", "resonance_score"],
    },
    "hum_exception_alliance_repair": {
        "phase": "repair",
        "priority": 100,
        "require": [
            ("alliance_rupture_detected", "==", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_pattern", "你根本没懂"),
            ("last_user_message", "contains_pattern", "别套模板"),
        ],
        "block_if": [],
        "produces": ["relational_trust", "being_understood_signal"],
    },
    "hum_exception_numbness_unfreeze": {
        "phase": "repair",
        "priority": 95,
        "require": [
            ("numbness_detected", "==", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_pattern", "什么都感觉不到"),
            ("last_user_message", "contains_pattern", "脑子一片空白"),
        ],
        "block_if": [
            ("emotional_intensity", ">=", 9),
        ],
        "produces": ["openness_level", "body_signal_present"],
    },
    "hum_boundary_advice_pull": {
        "phase": "repair",
        "priority": 90,
        "require": [
            ("advice_pull_detected", "==", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_pattern", "直接告诉我怎么办"),
        ],
        "block_if": [],
        "produces": ["relational_trust", "openness_level"],
    },
}
```

## 15. 当前仍需继续讨论的问题
1. `advice_pull` 的边界策略是否允许在人本主义模式下给极轻量、非指令式建议。
2. 人本主义摘要是否需要增加专属字段，例如“被命中的情绪命名”或“出现的自我接纳句”。
3. 人本主义后续是否独立引入二级安全判定模型，复用 MoodPal 通用危机链路。
