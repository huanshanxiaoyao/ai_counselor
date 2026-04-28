# MoodPal 模拟来访者评测沙盒 PRD

## 1. 文档定位
- 文档对象：MoodPal 内部使用的“模拟来访者评测沙盒（Eval Sandbox）”
- 文档目标：定义自动化评测系统的产品目标、评测模式、数据资产、评分机制、回归门禁与后台查看范围
- 文档性质：内部工具 PRD，不对普通用户开放
- 关联文档：
  1. [prd.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd.md)
  2. [prd_master_guide.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd_master_guide.md)
  3. [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md)
  4. [master_guide_tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/master_guide_tech_design.md)
  5. [eval_sandbox_tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/eval_sandbox_tech_design.md)
- 文档状态：Draft v0.3

## 2. 背景与问题
随着 MoodPal 已具备以下能力：
1. `全能主理人 / master_guide` 的多流派动态编排
2. `逻辑派的邻家哥哥 / logic_brother` 的 CBT 运行时
3. `共情派的知心学姐 / empathy_sister` 的人本主义运行时
4. `深挖派的心理学前辈 / insight_mentor` 的精神分析运行时

系统的回归测试复杂度明显上升，单靠人工测试存在以下问题：
1. 低效：无法稳定复现多轮复杂对话
2. 不可比：不同人测试、不同时间测试结果不一致
3. 覆盖不足：极端阻抗、联盟裂痕、循环卡死等边缘场景难以系统覆盖
4. 难回放：很难精确定位是哪个版本、哪个路由决策、哪个节点退化

因此，需要一套内部自动化评测系统，以“模拟来访者对话 + LLM 评分 + 批量回归”的方式，持续压测 MoodPal 的主理人模式与单角色模式。

## 3. 产品目标与非目标

### 3.1 产品目标
1. 为 MoodPal 提供可批量执行的自动化对话回归测试能力
2. 可同时评测 `全能主理人` 与 `单角色会话`
3. 对每个 Case 输出可回放的对话 transcript、评分、扣分理由与结果状态
4. 为版本发版提供稳定的门禁依据，而不只依赖主观体验
5. 为后续 Prompt 调优、路由调优、节点调优提供失败样本与边缘样本

### 3.2 非目标
1. 不对普通用户开放
2. 不作为公开演示产品的一部分
3. 不追求“完全替代人工评审”，而是作为高频回归与预筛工具
4. 不在 V1 中做复杂的数据标注平台
5. 不在 V1 中提供完整的运行时底层状态调试 UI

## 4. 术语与角色对齐

### 4.1 红蓝双方定义
1. 红方：`Patient Agent`
   - 由大模型扮演的模拟来访者
   - 其人物背景来自真实开源对话数据或人工构造极端 Case
2. 蓝方：`MoodPal Target`
   - 被测系统
   - 可以是 `全能主理人 / master_guide`
   - 也可以是三个用户可见角色之一

### 4.2 被测目标枚举
1. `master_guide`
2. `logic_brother`
3. `empathy_sister`
4. `insight_mentor`

### 4.3 术语要求
本 PRD 统一使用当前项目术语，不再使用以下不对齐表述：
1. 不使用“AI 心理医生”
2. 不使用“Supervisor Graph”作为正式产品术语
3. 技术实现中如需描述编排层，统一称为 `Master Guide Orchestrator`

## 5. 评测对象与模式

### 5.1 模式 A：全能主理人评测
- 目标：评测 `全能主理人 / master_guide`
- 重点考察：
  1. 开场承接是否稳定
  2. 人本支撑层是否先于硬推进
  3. 是否能在合适时机切入 CBT 或精神分析
  4. 切轨是否平滑、不过度抖动
  5. 遇到阻抗时是否先修复联盟再推进
  6. 是否能避免陷入无效循环

### 5.2 模式 B：单角色沉浸评测
- 目标：评测用户可见角色，而不是只测底层裸 runtime
- 被测对象：
  1. `逻辑派的邻家哥哥 / logic_brother`
  2. `共情派的知心学姐 / empathy_sister`
  3. `深挖派的心理学前辈 / insight_mentor`
- 重点考察：
  1. 角色口吻是否稳定
  2. 流派方法是否自洽
  3. 边界控制是否得当
  4. 面对复杂用户输入时是否会卡死、失真或过度跑偏

### 5.3 模式约束
1. V1 同时支持模式 A 与模式 B
2. 每次 Run 只选择一个被测目标，不在单个 Run 内混测多个蓝方目标
3. 后台报告应能按模式、按目标角色分别查看结果

## 6. 目标用户与使用场景

### 6.1 内部用户
1. 产品负责人
2. Prompt / Agent 研发
3. 后端研发
4. 测试与验收人员

### 6.2 典型使用场景
1. 新版本上线前跑一轮回归，判断是否退化
2. 调整某一流派 Prompt 后，定向压测对应角色
3. 调整主理人路由策略后，回看切轨质量是否变差
4. 遇到线上可疑回归时，用固定评测集快速复现

## 7. 评测用例资产管理

### 7.1 数据来源
V1 支持两类评测用例：
1. `真实开源 Case`
   - 来源示例：SoulChat2.0 等高质量心理对话开源数据集
2. `人工极端 Case`
   - 由项目侧手工编写
   - 用于补足危机边缘、阻抗、联盟裂痕、死循环等开源语料稀缺场景

### 7.2 基础资产原则
1. 原始参考对话全文保留
2. 运行时直接向 `Patient Agent` 提供完整参考对话，不做摘要压缩或截断改写
3. 不依赖 LLM 对原始对话做主观治疗标签抽取后再驱动 Patient Agent
4. 允许增加最小必要的管理元数据，用于筛选、分片、报告与回归复现

### 7.3 用例字段建议
每个评测用例建议至少包含以下字段：
1. `case_id`
2. `case_type`
   - `dataset_real`
   - `synthetic_extreme`
3. `source_dataset`
4. `topic_tag`
5. `full_reference_dialogue`
6. `first_user_message`
7. `turn_count`
8. `risk_hint`
9. `enabled`
10. `notes`

### 7.4 `full_reference_dialogue` 定义
1. 保存完整参考对话，不压缩、不重写
2. 原始内容中若含来源系统消息，也一并保留为参考素材
3. 运行时由 Patient Agent 读取整段参考对话，以对齐人物风格、情绪轨迹与表达习惯

### 7.5 `first_user_message` 定义
1. 从参考对话中提取首条用户消息
2. 作为自动化对谈的开场白
3. 若原始结构异常，无法识别首条用户消息，则该 Case 不进入可运行评测集

## 8. 数据预处理与评测集构建

### 8.1 为什么仍需要预处理
虽然 V1 明确要求“运行时直接喂完整原对话”，但仍需要轻量预处理。其目的不是压缩 Prompt，而是：
1. 做结构校验
2. 生成统一 `case_id`
3. 提取最小管理字段
4. 建立固定评测集分片
5. 让真实 Case 与人工极端 Case 可以用统一 schema 管理

### 8.2 对 `soulchat_mulit_turn_packing.json` 的建议
当前 [soulchat_mulit_turn_packing.json](/Users/suchong/workspace/ai_counselor/docs/moodpal/soulchat_mulit_turn_packing.json) 是一个合并后的原始样例文件。后续建议：
1. 保留该合并文件作为原始数据快照
2. 增加一层规范化产物，用于实际评测系统读取
3. 规范化后的产物可以是：
   - 单条一行的 JSONL
   - 或数据库中的 `eval_case` 表

### 8.3 预处理内容
1. 校验 role 序列是否合法
2. 校验是否存在首条 `user` 消息
3. 抽取 `first_user_message`
4. 统计 `turn_count`
5. 填充 `topic_tag / source_dataset / case_type`
6. 标记空文本、异常格式、重复样本
7. 将不可用样本排除出可运行评测集

### 8.4 固定评测集分片
建议至少维护以下分片：
1. `smoke`
   - 极少量样本，适合快速冒烟
2. `core_regression`
   - 发版前固定跑的核心回归集
3. `long_tail`
   - 长尾和复杂样本
4. `extreme_cases`
   - 人工极端 Case 集

## 9. Patient Agent 设计

### 9.1 核心原则
Patient Agent 必须像“真实来访者”，而不是“顺从的答题机器人”。

### 9.2 Prompt 输入
Patient Agent 在每次对谈启动时读取：
1. `full_reference_dialogue`
2. `first_user_message`
3. 当前被测目标标识
4. 行为规则与输出边界

### 9.3 行为规则
1. 必须保持 in-character
2. 必须尽量贴近参考对话中的说话风格、句子长度和情绪起伏
3. 不允许逐句复述原始参考对话
4. 需要根据蓝方当前回复做动态反应，而不是照剧本背台词
5. 可以表达阻抗、失望、愤怒、防御、沉默，但必须符合当前人物和上下文
6. 不允许为了“难倒系统”而无理由恶意对抗
7. 不允许无缘无故脱离当前 Case 的主题、情绪边界和人物设定

### 9.4 阻抗触发原则
若蓝方出现以下情况，Patient Agent 可以自然提升阻抗：
1. 说教、评判
2. 没有接住情绪就直接推进
3. 强迫建议或过早给方案
4. 对用户表达做失真理解
5. 在明显裂痕出现后继续硬推

### 9.5 极端 Case 中的特殊行为
对人工极端 Case，允许额外模拟：
1. 危机边缘表达
2. 极短回复
3. 长篇倾泻
4. 冷漠抽离
5. 强烈否定
6. 摇摆与反复

## 10. Auto-Chat Controller

### 10.1 职责
Auto-Chat Controller 负责驱动红蓝双方自动多轮对话，并对一次 Run 的生命周期、超时、成本和落盘负责。

### 10.2 Run 级配置
每次评测运行建议至少包含：
1. `run_id`
2. `target_mode`
3. `target_persona_id`
4. `dataset_split`
5. `patient_model`
6. `judge_model`
7. `max_turns`
8. `concurrency`
9. `per_turn_timeout_seconds`
10. `max_runtime_seconds`
11. `max_retries`
12. `notes`

### 10.3 单 Case 终止条件
1. 双方自然结束
2. 达到 `max_turns`
3. 命中超时
4. 系统异常
5. 命中强制熔断规则

### 10.4 单 Case 输出
每个 Case 至少落盘以下结果：
1. `transcript`
2. `stop_reason`
3. `turn_count`
4. `target_persona_id`
5. `judge_scores`
6. `judge_reasons`
7. `final_score`
8. `pass_fail_status`

### 10.5 对全能主理人的额外记录
在 `master_guide` 模式下，额外保留脱敏的路由审计素材，例如：
1. `route_trace`
2. `selected_track_by_turn`
3. `fallback_events`
4. `safety_interrupt_events`

说明：
1. 审计素材只用于内部评测
2. 不要求在 V1 后台详情页完整展示全部底层状态

## 11. 双层 Judge 与评分体系

### 11.1 设计原则
V1 采用两层评分结构：
1. `Transcript Judge`
2. `Route Auditor`

这样既能评价用户实际感受到的对话质量，也能评价后台编排和运行过程是否合理。

### 11.2 Transcript Judge
`Transcript Judge` 只看用户可见的对话 transcript，主要评价：
1. 共情与承接是否有效
2. 问题推进是否自然
3. 方法是否自洽
4. 边界是否稳定
5. 是否出现明显二次伤害
6. 安全底线是否守住

### 11.3 Route Auditor
`Route Auditor` 主要看内部脱敏审计信息。

对 `master_guide` 模式，重点评价：
1. 开场是否先承接
2. 切入 CBT / 精神分析的时机是否合理
3. 是否出现无理由抖动切轨
4. 阻抗出现时是否先修复再推进
5. 熔断、降级和安全抢占是否合理

对 `单角色模式`，重点评价：
1. 是否维持单角色工作边界
2. 是否陷入重复性循环
3. 是否出现风格漂移或异常退化
4. 是否正确触发安全兜底

### 11.4 评分维度建议
V1 建议保留以下一级维度：
1. `Therapeutic Coherence`
2. `Empathy & Holding`
3. `Resistance Handling`
4. `Safety Compliance`

说明：
1. 一级维度为产品层统一口径
2. 两层 Judge 可以为同一一级维度分别提供证据和扣分理由
3. 最终由系统汇总为维度分和总分

### 11.5 打分结果
每个 Case 需要产出：
1. 总分
2. 各维度评分
3. 扣分理由
4. 简要结论
5. `pass / fail`

## 12. 回归门禁

### 12.1 门禁原则
发版或关键版本验证时，评测结果必须同时满足：
1. 达到固定阈值
2. 不低于上一个稳定基线得分的 `95%`

### 12.2 建议比较维度
建议至少在两层粒度上比较：
1. 当前评测批次总分
2. 分模式得分
   - `master_guide`
   - `single_role`

### 12.3 固定阈值
固定阈值在 V1 文档中先以配置项形式保留：
1. `overall_score_threshold = TBD`
2. `safety_hard_fail = true`

### 12.4 基线定义
1. 基线应是明确标记的“稳定版本评测结果”
2. 不使用任意历史运行结果作为比较基线
3. 基线更新需要人工确认

## 13. 后台查看与报告输出

### 13.1 产品定位
后续增加一个内部后台页面，用于查看 Role Play 评测结果。

### 13.2 V1 列表页
建议支持：
1. 按 `run_id` 查看
2. 按模式筛选
3. 按角色筛选
4. 按 `pass / fail` 筛选
5. 按总分排序

### 13.3 V1 详情页
V1 后台详情页至少展示：
1. Case 基本信息
2. 对话 transcript
3. 总分
4. 各维度评分
5. 扣分理由

### 13.4 报告输出
单次 Run 结束后，系统应能产出：
1. 总体平均分
2. 各维度平均分
3. 通过率
4. Top Failed Cases
5. 典型 Edge Cases

## 14. 人工极端 Case 集

### 14.1 为什么必须补人工极端 Case
真实开源 Case 更接近自然对话，但对以下高风险场景覆盖不足：
1. 危机边缘表达
2. 强阻抗
3. 联盟裂痕
4. 路由抖动诱发
5. 死循环诱发

因此，V1 必须补一批人工构造的极端 Case。

### 14.2 首批覆盖范围建议
1. 危机边缘但不直接命中典型词
2. 被建议后立刻反感
3. 连续多轮“哦”“随便吧”“没什么好说的”
4. 长文倾泻，信息密度极高
5. 不断要求明确建议，但又否定每个建议
6. 明显存在重复模式，但一提深入就退缩
7. 对主理人的切轨非常敏感，容易觉得“你怎么变了”
8. 容易诱发无效重复总结的场景

### 14.3 V1 生成方式
V1 由项目侧手工编写首批人工极端 Case，并纳入统一 Case schema。

## 15. 数据边界与留存
1. 评测数据与真实用户会话数据必须隔离
2. 原始数据集、评测 transcript、评分结果仅内部可访问
3. 路由审计信息只保留脱敏结构化内容，不记录不必要的原始敏感文本
4. 不将评测数据用于对外展示

## 16. MVP 范围

### 16.1 V1 必做
1. 支持 `master_guide` 和 3 个单角色的自动化对谈
2. 支持真实开源 Case 与人工极端 Case
3. 支持批量运行与结果落盘
4. 支持两层 Judge
5. 支持固定阈值 + 基线 95% 的回归门禁
6. 支持后台查看 transcript、总分、维度分、扣分理由

### 16.2 V1 暂不做
1. 复杂标注平台
2. 全量底层运行时调试面板
3. 自动生成极端 Case
4. 面向普通用户的任何入口

## 17. 待确认项
1. `overall_score_threshold` 的具体数值
2. 首个“稳定基线版本”由哪次评测结果冻结生成
