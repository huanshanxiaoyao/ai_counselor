# MoodPal CBT + LangGraph 设计草案（MVP v0.1）

## 1. 文档目的
本文件聚焦一个问题：

如何把 `docs/counselor/CBT/` 目录下的结构化 CBT 知识，与 MoodPal 的 LangGraph 状态机结合起来，完成 CBT 流派角色的对话实现。

本文档是 [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/counselor/tech_design.md) 的专题细化稿，重点解决：
1. CBT JSON 到 LangGraph 的映射方式
2. CBT 会话主状态机如何设计
3. 具体技术节点如何被路由、执行、退出
4. 哪些地方需要通用 Agent，哪些地方直接复用 JSON 片段

## 2. 当前 CBT JSON 的结构理解

### 2.1 现有资产不是“资料”，而是“节点库”
`docs/counselor/CBT/` 目录中的 4 个 JSON 文件已经接近可执行节点定义。每条记录都包含：
1. `node_id`
2. `name`
3. `category`
4. `book_reference`
5. `trigger_intent`
6. `prerequisites`
7. `system_instruction`
8. `examples`
9. `exit_criteria`

这意味着它们天然可以作为：
1. LangGraph 的候选技术节点库
2. Prompt 组装的结构化输入
3. 路由器进行节点选择的规则来源
4. 会话结果解释和审计的依据

### 2.2 当前节点总览
现有共 15 个节点，分为 5 类：

1. `会话控制与状态机`
   - `cbt_structure_agenda_setting`

2. `浅层认知干预`
   - `cbt_cog_identify_at_basic`
   - `cbt_cog_identify_at_telegraphic`
   - `cbt_cog_identify_at_imagery`
   - `cbt_cog_eval_socratic`
   - `cbt_cog_eval_distortion`
   - `cbt_cog_response_coping`

3. `深层个案概念化`
   - `cbt_core_downward_arrow`

4. `行为干预`
   - `cbt_beh_activation`
   - `cbt_beh_experiment`
   - `cbt_beh_graded_task`

5. `异常处理与联盟`
   - `cbt_exception_redirecting`
   - `cbt_exception_homework_obstacle`
   - `cbt_exception_alliance_rupture`
   - `cbt_exception_yes_but`

### 2.3 关键观察
这些节点并不处于同一抽象层级：
1. 有的是“主链路节点”，如议程设定、自动思维捕捉、苏格拉底评估。
2. 有的是“分支技术”，如行为激活、行为实验、任务拆解。
3. 有的是“异常中断节点”，如联盟破裂、温和打断、Yes-but。

所以不应直接把 15 个 JSON 节点平铺成一张硬连接的大图。那样图会很快失控。

## 3. 推荐总体方案

### 3.1 核心思想
不要把 JSON 直接等价为 LangGraph 的底层代码节点。

推荐采用“两层结构”：

1. 上层：LangGraph 宏状态机
   - 负责会话阶段推进
   - 负责安全抢占
   - 负责主分支选择
   - 负责异常分支与收尾

2. 下层：CBT 技术节点库
   - 由 JSON 定义
   - 在具体阶段被路由器选中
   - 作为 Prompt 组装与退出判定的输入

### 3.2 为什么这么做
这样设计有 4 个直接好处：
1. 图的复杂度可控，不会因为技术节点增加而爆炸。
2. CBT 方法库可持续扩展，只要增加 JSON，不必每次改图结构。
3. 不同流派未来可以复用同一套“宏状态机 + 技术节点库”框架。
4. 更贴近产品真实需求：用户感受到的是稳定阶段推进，而不是技术节点名字。

## 4. 推荐的 CBT Graph 结构

### 4.1 Graph 分层
CBT Graph 建议拆成三类状态：

1. 会话级状态
   - 新会话初始化
   - 安全检查
   - 情绪打卡
   - 议程设定
   - 干预进行中
   - 收尾总结

2. 干预级状态
   - 自动思维识别
   - 认知评估
   - 行为干预
   - 深层探索
   - 应对卡片生成

3. 中断级状态
   - 用户发散重定向
   - homework 阻抗处理
   - 联盟破裂修复
   - yes-but 分流
   - 危机安全抢占

补充要求：
1. 中断级状态不是“兜底补救层”，而是高优先级抢占层。
2. 每轮进入主链执行前，都必须先做异常与风险前置检测。

### 4.2 主链路
推荐的 CBT 主链路如下：

`SessionStart`
-> `SafetyCheck`
-> `PreFlightExceptionCheck`
-> `MoodCheck`
-> `AgendaSetting`
-> `SelectInterventionTrack`
-> `TechniqueExecution`
-> `EvaluateExit`
-> `NextStepDecision`
-> `WrapUp`

含义如下：
1. `SessionStart`
   - 初始化会话上下文
   - 读取最近摘要
   - 注入角色设定

2. `SafetyCheck`
   - 危机检测
   - 若命中高危，跳出普通 CBT 图

3. `PreFlightExceptionCheck`
   - 在每轮进入主链前检测高优先级异常
   - 包括联盟破裂、明显发散、行动阻抗、yes-but 等
   - 若命中，优先进入异常处理轨道，而不是继续原技术节点

4. `MoodCheck`
   - 获取当前情绪强度和主情绪标签
   - 为后续路径选择提供输入

5. `AgendaSetting`
   - 对应 `cbt_structure_agenda_setting`
   - 锁定 1 个主问题

6. `SelectInterventionTrack`
   - 在认知、行为、深层探索之间做路由

7. `TechniqueExecution`
   - 执行具体 CBT 技术节点

8. `EvaluateExit`
   - 判断该技术是否达成 `exit_criteria`
   - 同时判断是否需要熔断、降级或强制收尾

9. `NextStepDecision`
   - 决定继续深入、切换技术、收尾，还是进入异常修复

10. `WrapUp`
   - 生成平衡想法 / 微行动 / 摘要素材

## 5. JSON 与 LangGraph 的映射方式

### 5.1 推荐映射表
建议将 JSON 字段映射为以下运行时用途：

1. `node_id`
   - 技术节点唯一标识
   - 用于路由、日志、审计、回放

2. `category`
   - 决定它属于哪条干预轨道
   - 用于第一层粗路由

3. `trigger_intent`
   - 作为候选匹配信号
   - 不能直接当布尔条件，需要经过意图评估器转换

4. `prerequisites`
   - 作为硬约束或软约束
   - 决定当前节点能否进入候选集

5. `system_instruction`
   - 核心 Prompt 模板正文
   - 决定这项 CBT 技术如何执行

6. `examples`
   - few-shot 示例
   - 可以裁剪后拼入 Prompt

7. `exit_criteria`
   - 用于技术执行后的退出判定
   - 可由专门的 Exit Evaluator 做结构化判别

8. `book_reference`
   - 用于可解释性、人工回顾、文档追溯

### 5.2 关键建议
`trigger_intent` 和 `prerequisites` 当前是自然语言，不建议 MVP 直接做成硬编码规则 DSL。

推荐先用两步法：
1. 维护一份轻量 mapping，把状态字段映射到“候选节点集”
2. 再用 LLM 或规则打分器在候选集内二次选择最合适的技术节点

也就是说：
先缩小集合，再选择节点。

## 6. 推荐的运行时状态

### 6.1 会话状态字段
本轮不细化数据库模型，但 LangGraph 运行时至少需要这些字段：

1. `session_id`
2. `subject_key`
3. `persona_id`
4. `therapy_mode`
5. `current_stage`
6. `current_technique_id`
7. `agenda_topic`
8. `mood_label`
9. `mood_score`
10. `emotion_stability`
11. `captured_automatic_thought`
12. `belief_confidence`
13. `balanced_response`
14. `homework_candidate`
15. `last_summary`
16. `history_messages`
17. `exception_flags`
18. `safety_status`

### 6.2 为什么这些字段必要
当前 JSON 的 `prerequisites` 和 `exit_criteria` 都依赖这些中间状态。

例如：
1. `cbt_cog_eval_socratic` 需要已经捕获清晰自动思维。
2. `cbt_beh_activation` 需要识别活动水平下降。
3. `cbt_core_downward_arrow` 需要情绪稳定、关系建立良好。
4. `cbt_exception_yes_but` 需要刚完成认知重组但情绪仍未跟上。

没有这些状态字段，就无法稳定路由。

### 6.3 推荐的 `CBTGraphState` 草案
下面是一版面向 LangGraph 运行时的状态 schema。目标是：
1. 让 Router 有稳定输入
2. 让 Executor 有足够上下文
3. 让 ExitEvaluator 能做结构化判定

```python
from typing import Literal, Optional, TypedDict


class CBTGraphState(TypedDict, total=False):
    # --- 基础身份 ---
    session_id: str
    subject_key: str
    persona_id: str
    therapy_mode: Literal["cbt"]
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
        "preflight_exception_check",
        "mood_check",
        "agenda_setting",
        "route_track",
        "select_technique",
        "execute_technique",
        "evaluate_exit",
        "handle_exception",
        "wrap_up",
    ]
    current_track: Literal[
        "agenda",
        "cognitive_identification",
        "cognitive_evaluation",
        "cognitive_response",
        "behavioral_activation",
        "behavioral_experiment",
        "graded_task",
        "deep_exploration",
        "exception",
        "",
    ]
    current_technique_id: str

    # --- 历史与消息 ---
    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict

    # --- 情绪与议程 ---
    mood_label: str
    mood_score: int
    emotion_stability: Literal["low", "medium", "high"]
    agenda_topic: str
    agenda_locked: bool

    # --- 认知路径状态 ---
    captured_automatic_thought: str
    thought_format: Literal["statement", "telegraphic", "question", "imagery", ""]
    belief_confidence: int
    alternative_explanation: str
    cognitive_distortion_label: str
    balanced_response: str
    balanced_response_confidence: int

    # --- 行为路径状态 ---
    energy_level: Literal["low", "medium", "high"]
    behavioral_shutdown: bool
    experiment_plan: dict
    task_first_step: str
    homework_candidate: str

    # --- 深层探索状态 ---
    repeated_theme_detected: bool
    core_belief_candidate: str
    intermediate_belief_candidate: str
    alliance_strength: Literal["weak", "medium", "strong"]

    # --- 异常与安全 ---
    safety_status: Literal["safe", "crisis_override"]
    alliance_rupture_detected: bool
    topic_drift_detected: bool
    homework_obstacle_detected: bool
    head_heart_split_detected: bool
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

### 6.4 字段分组说明
建议按以下原则组织状态：

1. 基础身份字段
   - 不随单轮对话频繁变化
   - 主要用于主体识别、模型选择、Persona/流派绑定

2. 生命周期字段
   - 决定当前 Graph 在哪一个宏阶段
   - 由 LangGraph 主节点推进

3. 对话内容字段
   - 保存最近消息、历史消息和摘要上下文
   - 主要服务于 Executor 和 Summary Agent

4. 认知 / 行为 / 深层状态字段
   - 分别对应不同轨道
   - Router 不需要所有字段都非空，只读取当前轨相关字段

5. 异常与安全字段
   - 为 `PreFlightExceptionCheck` 和 `SafetyCheck` 提供输入
   - 这类字段优先级高于主轨字段

6. 熔断与调试字段
   - 服务 ExitEvaluator 和技术追踪
   - 不直接面向用户，但对稳定性非常关键

### 6.5 最小必需字段（MVP）
如果第一版要压缩范围，至少不能少这些字段：

1. `session_id`
2. `subject_key`
3. `persona_id`
4. `therapy_mode`
5. `current_stage`
6. `current_track`
7. `current_technique_id`
8. `history_messages`
9. `last_summary`
10. `mood_label`
11. `mood_score`
12. `emotion_stability`
13. `agenda_topic`
14. `agenda_locked`
15. `captured_automatic_thought`
16. `belief_confidence`
17. `balanced_response`
18. `homework_candidate`
19. `safety_status`
20. `alliance_rupture_detected`
21. `topic_drift_detected`
22. `head_heart_split_detected`
23. `technique_attempt_count`
24. `technique_stall_count`
25. `last_progress_marker`
26. `circuit_breaker_open`

### 6.6 状态流转约束
为了避免 Graph 出现不合法跳转，建议定义以下硬约束：

1. `agenda_locked=false` 时
   - 禁止进入：
     - `cognitive_evaluation`
     - `cognitive_response`
     - `behavioral_experiment`
     - `deep_exploration`

2. `captured_automatic_thought=""` 时
   - 禁止进入：
     - `cbt_cog_eval_socratic`
     - `cbt_cog_eval_distortion`
     - `cbt_cog_response_coping`

3. `emotion_stability="low"` 或 `alliance_strength="weak"` 时
   - 禁止进入：
     - `cbt_core_downward_arrow`

4. `safety_status="crisis_override"` 时
   - 禁止继续任何普通 CBT 技术节点

5. `session_phase in ["summary_pending", "closed"]` 时
   - 禁止再执行 `execute_technique`

### 6.7 状态更新原则
每轮只允许做“小步更新”，不要大面积覆盖状态。

推荐规则：
1. `TechniqueExecutor` 只写本轮直接得到的内容
   - 例如：
     - 新捕获的自动思维
     - 新的平衡想法
     - 新的行为实验方案

2. `ExitEvaluator` 负责写判定相关字段
   - 例如：
     - `done`
     - `last_progress_marker`
     - `technique_attempt_count`
     - `technique_stall_count`
     - `circuit_breaker_open`

3. `Router` 负责写路径选择字段
   - 例如：
     - `current_track`
     - `current_technique_id`
     - `next_fallback_action`

### 6.8 `technique_trace` 建议
建议每轮追加一条 trace，用于后续调试和质量评估：

```json
{
  "turn_index": 4,
  "track": "cognitive_evaluation",
  "technique_id": "cbt_cog_eval_socratic",
  "progress_marker": "alternative_explanation_found",
  "done": true,
  "should_trip_circuit": false
}
```

这样后续出现问题时，可以回看：
1. 路由是否选错
2. 技术是否打转
3. 哪些节点最容易熔断

## 7. 推荐的 Agent 分工

### 7.1 Agent 列表
对于 CBT Graph，建议至少有 6 个内部 Agent：

1. `SafetyAgent`
   - 危机检测和抢占

2. `StateEvaluatorAgent`
   - 判断情绪强度、会话阶段、是否发散、是否适合深挖

3. `TechniqueRouterAgent`
   - 从 JSON 节点库中选出当前最合适的 CBT 技术

4. `TechniqueExecutorAgent`
   - 根据选中的节点执行对应 Prompt

5. `ExitEvaluatorAgent`
   - 判断当前节点是否达到退出标准

6. `SummarizerAgent`
   - 负责收尾、平衡想法沉淀、摘要素材生成

### 7.2 职责边界
关键点：
1. `TechniqueRouterAgent` 不直接对用户说话，只负责选技术。
2. `TechniqueExecutorAgent` 才负责生成用户可见的角色化回复。
3. `ExitEvaluatorAgent` 不做生成，只做判定。

这种拆分会让图更稳定，也更容易测试。

## 8. Technique Router 的核心逻辑

### 8.1 粗路由：先选轨道
先根据当前状态决定进入哪条轨道：

1. `agenda track`
   - 会话刚开始且议程未锁定

2. `cognitive track`
   - 已有具体情境，且适合识别和评估自动思维

3. `behavioral track`
   - 用户低能量、强拖延、明显反刍，或有可验证预测

4. `deep track`
   - 同主题反复出现，且用户情绪稳定，适合向下箭头

5. `exception track`
   - 发散、联盟破裂、行动阻抗、yes-but

### 8.2 细路由：再选技术节点
在轨道内选具体节点：

1. 如果还没有自动思维：
   - `cbt_cog_identify_at_basic`
   - 如果想法过短：`cbt_cog_identify_at_telegraphic`
   - 如果想不起来：`cbt_cog_identify_at_imagery`

2. 如果已有自动思维，且确信度高：
   - 优先 `cbt_cog_eval_socratic`

3. 如果逻辑谬误明显，或苏格拉底推进受阻：
   - 转 `cbt_cog_eval_distortion`

4. 如果认知评估已有松动，接近收尾：
   - 转 `cbt_cog_response_coping`

5. 如果低活跃、高无力感：
   - 转 `cbt_beh_activation`

6. 如果存在具体可测试预测：
   - 转 `cbt_beh_experiment`

7. 如果任务过大、拖延明显：
   - 转 `cbt_beh_graded_task`

8. 如果多轮反复触及同一底层主题：
   - 转 `cbt_core_downward_arrow`

### 8.3 异常优先级
异常节点必须高优先级抢占：

1. `cbt_exception_alliance_rupture`
   - 最高优先级

2. `cbt_exception_redirecting`

3. `cbt_exception_homework_obstacle`

4. `cbt_exception_yes_but`

实现上建议：
1. 每轮用户输入进入主链前，先做一次 `PreFlightExceptionCheck`。
2. `TechniqueExecution` 结束后、进入下一轮前，再做一次轻量异常复检。
3. 不能只在主链路失败时才检查异常，否则会出现“错误技术继续推进 1-2 轮”的体验偏差。

结论：
异常抢占必须首先是前置检测（Pre-flight Check），其次才是执行后的复检与兜底。

### 8.4 MVP 路由表（第一版）
下面这张表不是最终代码实现，而是 `CBTTechniqueRouter` 的首版业务规则基线。

1. `agenda track`
   - 进入条件：
     - `agenda_topic` 为空
     - 会话刚开始，且尚未锁定一个具体问题
   - 候选节点：
     - `cbt_structure_agenda_setting`
   - 成功产出：
     - `agenda_topic`
     - `agenda_locked=true`

2. `cognitive_identification track`
   - 进入条件：
     - 已有 `agenda_topic`
     - `captured_automatic_thought` 为空
     - 用户正在描述具体情境或情绪
   - 候选节点：
     - 默认：`cbt_cog_identify_at_basic`
     - 如果用户表达是电报式词语或问句：`cbt_cog_identify_at_telegraphic`
     - 如果用户表示“想不起来/脑子空白”：`cbt_cog_identify_at_imagery`
   - 成功产出：
     - `captured_automatic_thought`

3. `cognitive_evaluation track`
   - 进入条件：
     - 已捕获 `captured_automatic_thought`
     - 当前重点仍是认知评估，而非行为执行
   - 候选节点：
     - 默认：`cbt_cog_eval_socratic`
     - 如果语言中有明显绝对化、灾难化、读心术模式：`cbt_cog_eval_distortion`
   - 成功产出：
     - `belief_confidence` 下降
     - 或出现 `alternative_explanation`

4. `cognitive_response track`
   - 进入条件：
     - 已出现替代解释
     - 或会话临近收尾，需要形成带走的平衡想法
   - 候选节点：
     - `cbt_cog_response_coping`
   - 成功产出：
     - `balanced_response`
     - `balanced_response_confidence`

5. `behavioral_activation track`
   - 进入条件：
     - `energy_level` 很低
     - `behavioral_shutdown=true`
     - 用户陷入“什么都不想做/完全动不了”
   - 候选节点：
     - `cbt_beh_activation`
   - 成功产出：
     - `homework_candidate`
     - `activation_step`

6. `behavioral_experiment track`
   - 进入条件：
     - 存在清晰的负面预测
     - 该预测可在现实中安全验证
   - 候选节点：
     - `cbt_beh_experiment`
   - 成功产出：
     - `experiment_plan`
     - `homework_candidate`

7. `graded_task track`
   - 进入条件：
     - 用户面对具体任务
     - 明显使用“太难了/做不到/无法开始”表述
   - 候选节点：
     - `cbt_beh_graded_task`
   - 成功产出：
     - `task_first_step`
     - `homework_candidate`

8. `deep_exploration track`
   - 进入条件：
     - 同主题反复出现
     - `emotion_stability` 达到可探索阈值
     - 关系稳定，且非危机时刻
   - 候选节点：
     - `cbt_core_downward_arrow`
   - 成功产出：
     - `core_belief_candidate`
     - `intermediate_belief_candidate`

9. `exception track`
   - 进入条件：
     - `alliance_rupture_detected=true`
     - 或 `topic_drift_detected=true`
     - 或 `homework_obstacle_detected=true`
     - 或 `head_heart_split_detected=true`
   - 候选节点：
     - 联盟破裂：`cbt_exception_alliance_rupture`
     - 话题发散：`cbt_exception_redirecting`
     - 行动阻抗：`cbt_exception_homework_obstacle`
     - 理智情感分裂：`cbt_exception_yes_but`
   - 成功产出：
     - `repair_done`
     - 或 `agenda_relocked`
     - 或新的 `captured_automatic_thought`

### 8.5 路由优先级
为了避免路由冲突，MVP 建议按以下顺序判定：

1. `safety override`
   - 高危内容直接跳出 CBT Graph

2. `exception override`
   - 联盟破裂、强发散、明显阻抗优先于主干预路径

3. `agenda gate`
   - 议程未锁定时，不允许进入认知/行为深层技术

4. `deep exploration guard`
   - 未满足情绪稳定与关系稳定条件时，禁止进入 `cbt_core_downward_arrow`

5. `main track routing`
   - 在认知、行为两条主轨中择一推进

### 8.6 同轨替代策略
当一个节点熔断时，路由器应优先尝试同轨替代，而不是立刻跳轨：

1. `cbt_cog_identify_at_basic`
   - 替代到 `cbt_cog_identify_at_telegraphic` 或 `cbt_cog_identify_at_imagery`

2. `cbt_cog_eval_socratic`
   - 替代到 `cbt_cog_eval_distortion`

3. `cbt_beh_experiment`
   - 若执行门槛太高，可降级到 `cbt_beh_graded_task`

4. `cbt_core_downward_arrow`
   - 若用户承受不了，回退到 `cbt_exception_yes_but` 或直接 `WrapUp`

## 9. Technique Executor 的实现建议

### 9.1 Prompt 组装
执行单个 JSON 节点时，Prompt 由以下部分组成：

1. Persona 设定
   - 例如“邻家哥哥”的语气、边界、风格

2. CBT 共通约束
   - 不说教
   - 不一次抛太多问题
   - 不脱离当前议程
   - 保持自然口语化

3. 当前会话状态
   - 议程
   - 当前情绪
   - 已捕获自动思维
   - 之前问到哪里

4. 当前 JSON 节点的 `system_instruction`

5. 当前 JSON 节点的 `examples`

6. 输出格式要求
   - 只输出一轮对用户可见的回复
   - 最多推进一步
   - 不提前进入下一个技术

### 9.2 重要约束
执行器必须遵守“单步推进”原则：
1. 每一轮只完成当前技术节点的一小步。
2. 不允许一条回复中同时完成“自动思维捕捉 + 认知歪曲识别 + 行为实验布置”。
3. 这样才能让状态机真正发挥作用，而不是又退化成大一统 Prompt。

## 10. Exit Evaluator 的实现建议

### 10.1 作用
`exit_criteria` 是当前 JSON 节点最重要的工程价值之一。

它决定：
1. 当前技术是否完成
2. 是否继续停留在该节点
3. 是否进入下一个技术
4. 是否已经进入无效循环，需要熔断

### 10.2 实现方式
推荐采用“结构化判定器”：

输入：
1. 当前 JSON 节点的 `exit_criteria`
2. 最近 1-2 轮用户输入
3. 当前状态字段

输出：
1. `done: true/false`
2. `confidence: 0-1`
3. `reason`
4. `state_patch`
5. `should_trip_circuit: true/false`
6. `trip_reason`

例如：
1. 对 `cbt_cog_identify_at_basic`
   - 是否已捕获具体自动思维字句

2. 对 `cbt_cog_eval_socratic`
   - 是否已出现替代解释
   - 是否原始确信度下降

3. 对 `cbt_beh_experiment`
   - 是否已形成具体行动、时间点、观察指标

### 10.2.1 推荐输出 schema
建议 `CBTExitEvaluator` 输出一个固定结构，避免不同节点各自返回随意格式。

```json
{
  "done": false,
  "confidence": 0.86,
  "reason": "用户仍未明确说出自动思维，只描述了情绪体验",
  "state_patch": {
    "mood_label": "anxious",
    "mood_score": 78,
    "captured_automatic_thought": ""
  },
  "progress_marker": "emotion_labeled",
  "stall_detected": false,
  "technique_attempt_count": 2,
  "technique_stall_count": 0,
  "should_trip_circuit": false,
  "trip_reason": "",
  "next_fallback_action": "retry_same_technique"
}
```

字段说明：
1. `done`
   - 当前技术是否已达到退出标准
2. `confidence`
   - 判定器对本次判断的信心
3. `reason`
   - 给路由器和调试日志使用的人类可读解释
4. `state_patch`
   - 本轮新增或更新的状态字段
5. `progress_marker`
   - 用于判断是否有实质推进
6. `stall_detected`
   - 本轮是否缺少推进
7. `technique_attempt_count`
   - 当前节点累计尝试数
8. `technique_stall_count`
   - 连续卡住轮数
9. `should_trip_circuit`
   - 是否熔断
10. `trip_reason`
   - 熔断原因
11. `next_fallback_action`
   - 建议的后续动作

### 10.3 工程价值
如果没有 Exit Evaluator，图会出现两个问题：
1. 停不下来，在一个节点里反复打转
2. 停得太早，尚未达到方法上的完成标准

如果没有熔断与最大重试机制，还会出现第三个更严重的问题：
3. 状态机卡死在“技术未完成 -> 继续追问 -> 仍未完成”的闭环里，导致用户体验崩坏，甚至破坏治疗联盟。

### 10.4 熔断与最大重试机制
这是 Exit Evaluator 的必要补充，不应作为可选增强。

建议增加以下运行时控制字段：
1. `technique_attempt_count`
   - 当前技术节点已尝试轮数
2. `technique_stall_count`
   - 连续多少轮没有实质状态推进
3. `last_progress_marker`
   - 上一轮是否产生了关键进展，例如捕获到自动思维、生成了替代解释、明确了行为实验
4. `circuit_breaker_open`
   - 当前节点是否已熔断

建议的 MVP 规则：
1. 单一技术节点连续执行超过 3 轮仍未满足 `exit_criteria`，进入熔断判定。
2. 如果连续 2 轮没有新的状态推进，视为 `stall`。
3. 若同时满足“轮数过多”或“持续 stall”，则 `should_trip_circuit=true`。

### 10.5 熔断后的处理策略
熔断后不能简单报错退出，必须降级。

推荐顺序：
1. 先尝试切换同轨道替代技术
   - 例如从 `cbt_cog_eval_socratic` 切到 `cbt_cog_eval_distortion`
2. 如果同轨道也不适合，切到异常处理节点
   - 例如 `cbt_exception_yes_but` 或 `cbt_exception_alliance_rupture`
3. 若当前轮已明显疲劳或阻抗升高，则直接进入 `WrapUp`
   - 生成一个轻量收尾与更保守的下一步建议

### 10.5.1 `next_fallback_action` 枚举建议
MVP 先约束成少量固定值：

1. `retry_same_technique`
   - 允许在原节点再推进一轮

2. `switch_same_track`
   - 切换到同轨道替代技术

3. `jump_to_exception`
   - 转异常处理节点

4. `wrap_up_now`
   - 直接进入收尾

5. `handoff_to_behavioral_track`
   - 从认知轨切到行为轨

6. `handoff_to_cognitive_track`
   - 从行为轨切到认知轨

### 10.5.2 节点级退出判定样例
为了让实现更具体，MVP 可以先为核心节点定义首版判定规则：

1. `cbt_structure_agenda_setting`
   - `done=true` 条件：
     - `agenda_topic` 非空
     - `agenda_locked=true`

2. `cbt_cog_identify_at_basic`
   - `done=true` 条件：
     - `captured_automatic_thought` 是一句可引用的陈述
   - `stall=true` 信号：
     - 用户连续两轮只重复“我就是难受/不知道”

3. `cbt_cog_eval_socratic`
   - `done=true` 条件：
     - 出现 `alternative_explanation`
     - 或 `belief_confidence` 明显下降
   - `trip=true` 信号：
     - 连续多轮只回到原断言，无任何松动

4. `cbt_cog_response_coping`
   - `done=true` 条件：
     - 生成 `balanced_response`
     - 用户对其有基本接受度

5. `cbt_beh_experiment`
   - `done=true` 条件：
     - 具备明确行动、时间点、观察指标三要素

6. `cbt_beh_graded_task`
   - `done=true` 条件：
     - 任务已拆到一个用户愿意承诺的第一步

### 10.6 为什么熔断必须放在 Exit Evaluator
因为是否“该继续当前技术”本质上就是退出判定的一部分。

换句话说：
1. `ExitEvaluator` 不只负责“完成了没有”
2. 还负责“虽然没完成，但已经不适合继续了”

这两种判断都应该由同一个判定器输出，避免路由逻辑分裂。

## 11. MVP 推荐的 CBT 图谱推进方式

### 11.1 第一版只做最稳的主链
MVP 不建议 15 个节点一次全上。

建议优先做 8 个核心节点：
1. `cbt_structure_agenda_setting`
2. `cbt_cog_identify_at_basic`
3. `cbt_cog_identify_at_telegraphic`
4. `cbt_cog_identify_at_imagery`
5. `cbt_cog_eval_socratic`
6. `cbt_cog_eval_distortion`
7. `cbt_cog_response_coping`
8. `cbt_exception_alliance_rupture`

### 11.2 第二版再补行为分支
第二批引入：
1. `cbt_beh_activation`
2. `cbt_beh_experiment`
3. `cbt_beh_graded_task`
4. `cbt_exception_homework_obstacle`

### 11.3 第三版再补深层探索
最后引入：
1. `cbt_core_downward_arrow`
2. `cbt_exception_yes_but`
3. `cbt_exception_redirecting`

原因：
1. 主链先跑稳，能覆盖最多场景。
2. 行为分支次之，适合补充无力感和拖延场景。
3. 深层探索风险更高，必须等状态判定更稳后再放开。

## 12. 与产品体验的连接

### 12.1 用户看到什么
用户看到的是：
1. 一个稳定的人设角色
2. 自然、轻松、被理解的对话
3. 偶尔被温和拉回重点
4. 在结尾得到平衡想法或微行动

### 12.2 系统实际上做了什么
系统实际上做的是：
1. 先锁议程
2. 判断进入认知还是行为路径
3. 从 CBT 节点库里选择当前最合适的技术
4. 只推进一步
5. 判断是否达成退出标准
6. 再决定下一步

这正是 LangGraph 的价值所在。

## 13. 当前最推荐的工程落地方式

### 13.1 代码层建议
不要为每个 JSON 节点各写一个独立 Python 类。

推荐写三类通用组件：
1. `CBTNodeRegistry`
   - 负责加载 JSON 节点库

2. `CBTTechniqueRouter`
   - 负责基于状态挑选候选节点

3. `CBTTechniqueExecutor`
   - 负责用选中的 JSON 片段组装 Prompt 并调用 LLM

再加：
4. `CBTExitEvaluator`
   - 负责根据 `exit_criteria` 判定是否退出
   - 同时负责最大重试、stall 检测和熔断决策

### 13.2 LangGraph 层建议
LangGraph 中保留少量通用节点：
1. `safety_check`
2. `mood_check`
3. `agenda_setting`
4. `route_track`
5. `select_technique`
6. `execute_technique`
7. `evaluate_exit`
8. `handle_exception`
9. `wrap_up`

也就是说：
LangGraph 管流程，JSON 管技术。

补充：
1. `handle_exception` 的进入条件不能只来自执行失败，也必须来自 `PreFlightExceptionCheck`。
2. `evaluate_exit` 必须内建熔断判断，避免单技术节点无限循环。

## 14. `CBTTechniqueRouter` 配置草案

### 14.1 配置目标
Router 配置的目标不是替代 LangGraph，而是把“如何从状态选出候选技术”固定成一套可维护常量。

建议 Router 只做 4 件事：
1. 判断是否需要安全抢占
2. 判断是否需要异常抢占
3. 选择当前轨道
4. 在轨道内选择候选技术节点与降级路径

### 14.2 推荐配置分层
建议 Router 配置拆成以下 6 组常量：

1. `TRACK_PRIORITY`
   - 轨道判定顺序

2. `TRACK_GATE_RULES`
   - 每条轨道的进入条件

3. `TRACK_CANDIDATES`
   - 每条轨道允许出现的节点

4. `TECHNIQUE_RULES`
   - 每个节点自己的适用条件、阻断条件、成功产出

5. `SAME_TRACK_FALLBACKS`
   - 熔断后同轨替代关系

6. `CROSS_TRACK_HANDOFFS`
   - 必须跨轨切换时的允许关系

### 14.3 推荐代码形态
建议最终代码侧先做成 Python 常量模块，例如：

`backend/moodpal/cbt/router_config.py`

首版可以写成如下形态：

```python
TRACK_PRIORITY = [
    "safety_override",
    "exception",
    "agenda",
    "cognitive_identification",
    "cognitive_evaluation",
    "cognitive_response",
    "behavioral_activation",
    "behavioral_experiment",
    "graded_task",
    "deep_exploration",
]
```

### 14.4 轨道级规则草案
下面是建议直接转成配置的数据结构。

```python
TRACK_GATE_RULES = {
    "agenda": {
        "all": [
            ("agenda_locked", "==", False),
        ],
    },
    "cognitive_identification": {
        "all": [
            ("agenda_locked", "==", True),
            ("captured_automatic_thought", "empty", True),
        ],
        "any": [
            ("mood_score", ">=", 40),
            ("last_user_message", "contains_situation", True),
        ],
    },
    "cognitive_evaluation": {
        "all": [
            ("agenda_locked", "==", True),
            ("captured_automatic_thought", "empty", False),
        ],
    },
    "cognitive_response": {
        "any": [
            ("alternative_explanation", "empty", False),
            ("session_phase", "==", "ending"),
        ],
    },
    "behavioral_activation": {
        "all": [
            ("energy_level", "==", "low"),
        ],
        "any": [
            ("behavioral_shutdown", "==", True),
            ("last_user_message", "contains_pattern", "什么都不想做"),
            ("last_user_message", "contains_pattern", "完全动不了"),
        ],
    },
    "behavioral_experiment": {
        "all": [
            ("agenda_locked", "==", True),
        ],
        "any": [
            ("last_user_message", "contains_prediction", True),
            ("captured_automatic_thought", "contains_prediction", True),
        ],
    },
    "graded_task": {
        "all": [
            ("agenda_locked", "==", True),
        ],
        "any": [
            ("last_user_message", "contains_pattern", "做不到"),
            ("last_user_message", "contains_pattern", "太难了"),
            ("last_user_message", "contains_pattern", "无法开始"),
        ],
    },
    "deep_exploration": {
        "all": [
            ("repeated_theme_detected", "==", True),
            ("emotion_stability", "==", "high"),
            ("alliance_strength", "in", ["medium", "strong"]),
        ],
    },
    "exception": {
        "any": [
            ("alliance_rupture_detected", "==", True),
            ("topic_drift_detected", "==", True),
            ("homework_obstacle_detected", "==", True),
            ("head_heart_split_detected", "==", True),
        ],
    },
}
```

### 14.5 轨道候选节点草案
```python
TRACK_CANDIDATES = {
    "agenda": [
        "cbt_structure_agenda_setting",
    ],
    "cognitive_identification": [
        "cbt_cog_identify_at_basic",
        "cbt_cog_identify_at_telegraphic",
        "cbt_cog_identify_at_imagery",
    ],
    "cognitive_evaluation": [
        "cbt_cog_eval_socratic",
        "cbt_cog_eval_distortion",
    ],
    "cognitive_response": [
        "cbt_cog_response_coping",
    ],
    "behavioral_activation": [
        "cbt_beh_activation",
    ],
    "behavioral_experiment": [
        "cbt_beh_experiment",
    ],
    "graded_task": [
        "cbt_beh_graded_task",
    ],
    "deep_exploration": [
        "cbt_core_downward_arrow",
    ],
    "exception": [
        "cbt_exception_alliance_rupture",
        "cbt_exception_redirecting",
        "cbt_exception_homework_obstacle",
        "cbt_exception_yes_but",
    ],
}
```

### 14.6 节点级规则草案
节点级规则负责解决“同一轨道里到底选谁”的问题。

```python
TECHNIQUE_RULES = {
    "cbt_structure_agenda_setting": {
        "track": "agenda",
        "priority": 100,
        "require": [
            ("agenda_locked", "==", False),
        ],
        "block_if": [],
        "produces": ["agenda_topic", "agenda_locked"],
    },
    "cbt_cog_identify_at_basic": {
        "track": "cognitive_identification",
        "priority": 100,
        "require": [
            ("captured_automatic_thought", "empty", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_situation", True),
        ],
        "block_if": [],
        "produces": ["captured_automatic_thought", "thought_format"],
    },
    "cbt_cog_identify_at_telegraphic": {
        "track": "cognitive_identification",
        "priority": 110,
        "require": [
            ("captured_automatic_thought", "empty", True),
        ],
        "prefer_if": [
            ("last_user_message", "telegraphic_or_question", True),
        ],
        "block_if": [],
        "produces": ["captured_automatic_thought", "thought_format"],
    },
    "cbt_cog_identify_at_imagery": {
        "track": "cognitive_identification",
        "priority": 120,
        "require": [
            ("captured_automatic_thought", "empty", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_pattern", "想不起来"),
            ("last_user_message", "contains_pattern", "脑子一片空白"),
        ],
        "block_if": [],
        "produces": ["captured_automatic_thought", "thought_format"],
    },
    "cbt_cog_eval_socratic": {
        "track": "cognitive_evaluation",
        "priority": 100,
        "require": [
            ("captured_automatic_thought", "empty", False),
        ],
        "prefer_if": [
            ("belief_confidence", ">=", 70),
        ],
        "block_if": [],
        "produces": ["belief_confidence", "alternative_explanation"],
    },
    "cbt_cog_eval_distortion": {
        "track": "cognitive_evaluation",
        "priority": 110,
        "require": [
            ("captured_automatic_thought", "empty", False),
        ],
        "prefer_if": [
            ("last_user_message", "contains_distortion_pattern", True),
        ],
        "block_if": [],
        "produces": ["cognitive_distortion_label", "belief_confidence"],
    },
    "cbt_cog_response_coping": {
        "track": "cognitive_response",
        "priority": 100,
        "require": [],
        "prefer_if": [
            ("alternative_explanation", "empty", False),
            ("session_phase", "==", "ending"),
        ],
        "block_if": [],
        "produces": ["balanced_response", "balanced_response_confidence"],
    },
    "cbt_beh_activation": {
        "track": "behavioral_activation",
        "priority": 100,
        "require": [
            ("energy_level", "==", "low"),
        ],
        "prefer_if": [
            ("behavioral_shutdown", "==", True),
        ],
        "block_if": [],
        "produces": ["homework_candidate"],
    },
    "cbt_beh_experiment": {
        "track": "behavioral_experiment",
        "priority": 100,
        "require": [
            ("agenda_locked", "==", True),
        ],
        "prefer_if": [
            ("captured_automatic_thought", "contains_prediction", True),
        ],
        "block_if": [
            ("emotion_stability", "==", "low"),
        ],
        "produces": ["experiment_plan", "homework_candidate"],
    },
    "cbt_beh_graded_task": {
        "track": "graded_task",
        "priority": 100,
        "require": [
            ("agenda_locked", "==", True),
        ],
        "prefer_if": [
            ("last_user_message", "contains_pattern", "太难了"),
            ("last_user_message", "contains_pattern", "做不到"),
        ],
        "block_if": [],
        "produces": ["task_first_step", "homework_candidate"],
    },
    "cbt_core_downward_arrow": {
        "track": "deep_exploration",
        "priority": 100,
        "require": [
            ("repeated_theme_detected", "==", True),
            ("emotion_stability", "==", "high"),
        ],
        "prefer_if": [
            ("alliance_strength", "in", ["medium", "strong"]),
        ],
        "block_if": [
            ("safety_status", "==", "crisis_override"),
            ("alliance_strength", "==", "weak"),
        ],
        "produces": ["core_belief_candidate", "intermediate_belief_candidate"],
    },
    "cbt_exception_alliance_rupture": {
        "track": "exception",
        "priority": 1000,
        "require": [
            ("alliance_rupture_detected", "==", True),
        ],
        "block_if": [],
        "produces": ["repair_done"],
    },
    "cbt_exception_redirecting": {
        "track": "exception",
        "priority": 900,
        "require": [
            ("topic_drift_detected", "==", True),
        ],
        "block_if": [],
        "produces": ["agenda_relocked"],
    },
    "cbt_exception_homework_obstacle": {
        "track": "exception",
        "priority": 800,
        "require": [
            ("homework_obstacle_detected", "==", True),
        ],
        "block_if": [],
        "produces": ["captured_automatic_thought", "homework_candidate"],
    },
    "cbt_exception_yes_but": {
        "track": "exception",
        "priority": 700,
        "require": [
            ("head_heart_split_detected", "==", True),
        ],
        "block_if": [],
        "produces": ["belief_confidence", "core_belief_candidate"],
    },
}
```

### 14.7 同轨降级映射草案
```python
SAME_TRACK_FALLBACKS = {
    "cbt_cog_identify_at_basic": [
        "cbt_cog_identify_at_telegraphic",
        "cbt_cog_identify_at_imagery",
    ],
    "cbt_cog_eval_socratic": [
        "cbt_cog_eval_distortion",
    ],
    "cbt_beh_experiment": [
        "cbt_beh_graded_task",
    ],
    "cbt_core_downward_arrow": [
        "cbt_exception_yes_but",
    ],
}
```

### 14.8 跨轨切换映射草案
```python
CROSS_TRACK_HANDOFFS = {
    "cognitive_identification": {
        "on_low_energy": "behavioral_activation",
    },
    "cognitive_evaluation": {
        "on_repeated_theme_and_stable": "deep_exploration",
        "on_prediction_ready": "behavioral_experiment",
    },
    "behavioral_experiment": {
        "on_too_hard": "graded_task",
    },
    "exception": {
        "on_repair_complete": "previous_active_track",
    },
}
```

### 14.9 Router 执行顺序建议
首版 Router 每轮只做以下步骤：

1. `safety override`
   - 危机则直接退出 CBT Graph

2. `exception override`
   - 根据异常标志优先命中异常节点

3. `track selection`
   - 按 `TRACK_PRIORITY` 依次检查 `TRACK_GATE_RULES`

4. `candidate filtering`
   - 从 `TRACK_CANDIDATES` 中取候选节点
   - 用 `TECHNIQUE_RULES.require` / `block_if` 过滤

5. `candidate ranking`
   - 按 `priority`
   - 再结合 `prefer_if` 打分

6. `fallback application`
   - 若当前节点熔断，优先查 `SAME_TRACK_FALLBACKS`
   - 再考虑 `CROSS_TRACK_HANDOFFS`

### 14.10 MVP 代码实现建议
Router 第一版建议不要做成全自动“规则解释器”。

更稳的方式是：
1. 先把上面这组常量写成 Python dict
2. 只实现少量固定 operator：
   - `==`
   - `!=`
   - `in`
   - `>=`
   - `empty`
   - `contains_pattern`
   - `contains_prediction`
   - `contains_distortion_pattern`
   - `contains_situation`
   - `telegraphic_or_question`
3. Router 主函数根据这些 operator 执行判断

这样做的好处是：
1. 比完全硬编码更可维护
2. 比上来就做 DSL 更稳

## 15. 当前仍需继续细化的点
1. `trigger_intent` 如何从自然语言整理成可机器判定的标签体系
2. `prerequisites` 如何映射到运行时状态字段
3. `exit_criteria` 的结构化判定 schema
4. CBT 角色 Persona Prompt 的正式版本
5. 认知路径与行为路径的切换阈值
6. 哪些情形禁止进入 `向下箭头技术`

## 16. 下一步建议
建议下一轮直接补以下内容：

1. `CBTGraphState` 草案
   - 本稿已完成首版 schema、字段分组和流转约束

2. `CBTTechniqueRouter` 路由表
   - 把 15 个 JSON 节点映射到候选条件
   - 本稿已给出 MVP 首版业务规则，下一轮可转成代码侧常量/配置

3. `CBTTechniqueExecutor` Prompt 模板
   - 形成可落地的 Prompt 组装规范

4. `CBTExitEvaluator` 输出 schema
   - 本稿已给出首版 schema
   - 下一轮需要补成节点级判定模板和测试样例

5. MVP 第一版的节点白名单
   - 明确先上线哪 8 个节点

推荐执行顺序：
1. 先把 Router 路由表转成配置
2. 接着定义 `ExitEvaluator` 的节点级判定模板
3. 再落 `TechniqueExecutor` Prompt 规范
4. 最后再开始代码骨架实现
