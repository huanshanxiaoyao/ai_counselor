# MoodPal 模拟来访者评测沙盒技术设计

## 1. 文档目的
- 文档目标：定义 `MoodPal Eval Sandbox` 的技术架构、数据模型、执行链路、评分链路、后台查看方案和落地步骤
- 对齐输入：
  1. [agent_test_agent.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/agent_test_agent.md)
  2. [prd.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd.md)
  3. [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md)
  4. [master_guide_tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/master_guide_tech_design.md)
- 文档边界：本稿聚焦 MVP 可落地方案，优先解决内部评测系统的主链路，不展开过细的 prompt 文案和页面视觉细节

## 2. 设计前提与约束

### 2.1 当前代码基线
当前仓库已经具备以下可复用能力：
1. `MoodPal` 已有完整对话域模型：
   - [models.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/models.py)
2. 已有用户可见角色与多流派运行时：
   - `logic_brother`
   - `empathy_sister`
   - `insight_mentor`
   - `master_guide`
3. 已有运行时服务：
   - [cbt_runtime_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/cbt_runtime_service.py)
   - [humanistic_runtime_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/humanistic_runtime_service.py)
   - [psychoanalysis_runtime_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/psychoanalysis_runtime_service.py)
   - [master_guide_runtime_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/master_guide_runtime_service.py)
4. 已有危机拦截和 token 记账：
   - [crisis_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/crisis_service.py)
   - [token_quota.py](/Users/suchong/workspace/ai_counselor/backend/roundtable/services/token_quota.py)
5. 已有统一 LLM 调用层：
   - [client.py](/Users/suchong/workspace/ai_counselor/backend/llm/client.py)

### 2.2 明确约束
1. 评测系统是内部工具，不走前台用户入口
2. 评测数据必须与真实用户会话数据长期隔离
3. V1 没有 Celery / 队列系统，不依赖新的异步基础设施
4. 评测必须尽量复用现有 `MoodPal` runtime，而不是重写一套“测试专用聊天逻辑”
5. `Patient Agent` 运行时继续直接读取完整参考对话，不做摘要压缩

## 3. 核心设计结论
先给结论：

1. 新增一个独立 Django app：`backend/moodpal_eval/`
2. 评测结果永久存储在 `moodpal_eval_*` 独立表，不写入 `moodpal_sessions` / `moodpal_messages`
3. 评测运行不通过 HTTP 调 `api/moodpal/...`，而是直接调用 `MoodPal` 运行时服务
4. 为了避免与真实会话链路漂移，需抽一层共享的 `Target Turn Driver`
5. V1 的主要执行入口采用 `staff-only 后台页面直接触发 + 受控后台线程执行`
6. V1 的后台查看采用 staff-only Django 页面，和 Django admin 并存：
   - 自定义只读结果页给人看
   - Django admin 给运维查底层模型
7. Token 成本单独统计到 eval ledger，不计入真实用户配额，也不做配额限制
8. V1 对后台直接触发的 Run 施加硬限制：
   - 单次最多 `20` 个 Case
   - 同时只允许 `1` 个运行中的 Run
9. `overall_score_threshold` V1 先定为 `80`，后续可按实际跑分结果调整

## 4. 为什么不直接复用 MoodPalSession 表

### 4.1 看起来最简单的方案
最容易想到的方案是：
1. 评测时直接创建真实 `MoodPalSession`
2. 用 [message_service.py](/Users/suchong/workspace/ai_counselor/backend/moodpal/services/message_service.py) 逐轮跑
3. 对话结束后再把 transcript 抽出来

### 4.2 不推荐原因
这个方案短期可跑，但长期问题很大：
1. 评测数据会和真实用户会话混在同一批表里
2. 后台统计、排查和清理都会变脏
3. “评测数据与真实用户数据隔离”的要求无法严格满足
4. 一旦清理失败，会长期污染生产会话库

### 4.3 推荐方案
推荐方案是：
1. 评测系统维护自己的 `EvalCase / EvalRun / EvalRunItem`
2. 运行时构造一个轻量 `SessionContext`，直接喂给现有 runtime service
3. transcript、route trace、judge 结果全部直接落在 `moodpal_eval_*` 表
4. 不依赖真实 `MoodPalSession` ORM 行

## 5. 总体架构

### 5.1 分层
推荐采用 6 层结构：

1. `Case Store`
   - 管理真实开源 Case 和人工极端 Case
2. `Run Controller`
   - 创建 Run、切分任务、并发执行、汇总结果
3. `Patient Agent Service`
   - 生成模拟来访者回复
4. `MoodPal Target Driver`
   - 驱动被测目标角色完成每轮回复
5. `Judge Layer`
   - `Transcript Judge`
   - `Route Auditor`
6. `Backoffice Read UI`
   - 查看 Run 列表、Case 详情、评分结果

### 5.2 主链路
一条完整评测链路如下：

`导入 Case -> 创建 EvalRun -> 为每个 Case 启动对谈 -> Patient Agent 与 Target Driver 多轮交互 -> 结束后执行双层 Judge -> 聚合分数 -> 写入 Run 报告 -> 后台查看`

## 6. Django App 结构建议

### 6.1 新增目录
建议新增：

`backend/moodpal_eval/`

包含：
1. `models.py`
2. `admin.py`
3. `urls.py`
4. `views.py`
5. `services/`
6. `management/commands/`
7. `templates/moodpal_eval/`

### 6.2 服务层建议
`backend/moodpal_eval/services/`

建议至少包含：
1. `case_import_service.py`
2. `run_service.py`
3. `run_launcher.py`
4. `run_executor.py`
5. `target_driver.py`
6. `patient_agent_service.py`
7. `judge_service.py`
8. `score_aggregation_service.py`
9. `report_service.py`

### 6.3 命令建议
`backend/moodpal_eval/management/commands/`

建议至少包含：
1. `import_moodpal_eval_cases.py`
2. `run_moodpal_eval.py`
3. `rebuild_moodpal_eval_report.py`

## 7. 数据模型设计

### 7.1 `MoodPalEvalCase`
用途：存评测用例资产。

建议字段：
1. `id`
2. `case_id`
3. `title`
4. `case_type`
   - `dataset_real`
   - `synthetic_extreme`
5. `source_dataset`
6. `topic_tag`
7. `splits`
   - JSON 数组，如 `["core_regression", "long_tail"]`
8. `full_reference_dialogue`
   - JSONField，保存原始消息列表
9. `first_user_message`
10. `turn_count`
11. `risk_hint`
12. `enabled`
13. `notes`
14. `source_hash`
15. `created_at`
16. `updated_at`

设计说明：
1. `full_reference_dialogue` 保留完整原文，不做压缩
2. `splits` 用 JSON 数组即可，V1 不额外建集合关系表
3. `source_hash` 用于保证导入幂等与数据版本对齐

### 7.2 `MoodPalEvalRun`
用途：表示一次批量评测运行。

建议字段：
1. `id`
2. `name`
3. `status`
   - `pending`
   - `running`
   - `completed`
   - `failed`
   - `canceled`
4. `target_mode`
   - `master_guide`
   - `single_role`
5. `target_persona_id`
6. `dataset_split`
7. `selected_case_count`
8. `patient_model`
9. `judge_model`
10. `target_model`
11. `max_turns`
12. `concurrency`
13. `per_turn_timeout_seconds`
14. `max_runtime_seconds`
15. `max_retries`
16. `baseline_run`
   - FK 到另一个稳定 Run
17. `threshold_score`
18. `gate_passed`
19. `gate_failure_reason`
20. `summary_metrics`
   - JSONField，保存平均分、通过率、失败数等
21. `created_by`
22. `started_at`
23. `finished_at`
24. `metadata`

设计说明：
1. `threshold_score` V1 默认值先定为 `80`
2. 后续允许在后台创建 Run 时覆盖，但默认沿用系统值

### 7.3 `MoodPalEvalRunItem`
用途：表示一次 Run 中某个 Case 的具体执行结果。

建议字段：
1. `id`
2. `run`
3. `case`
4. `status`
   - `pending`
   - `running`
   - `completed`
   - `failed`
   - `errored`
5. `turn_count`
6. `stop_reason`
7. `transcript`
   - JSONField，存最终对话记录
8. `target_trace`
   - JSONField，存脱敏 route trace / technique trace / safety 事件
9. `transcript_judge_result`
10. `route_audit_result`
11. `final_scores`
12. `final_score`
13. `hard_fail`
14. `deduction_reasons`
15. `target_token_usage`
16. `patient_token_usage`
17. `judge_token_usage`
18. `total_token_usage`
19. `error_code`
20. `error_message`
21. `started_at`
22. `finished_at`
23. `metadata`

设计说明：
1. V1 不拆单独的 turn 表，直接把 transcript 存为 JSON 即可
2. V1 不拆单独的 judge 结果表，避免模型过多
3. 后台详情页所需数据都从 `RunItem` 读取

### 7.4 `MoodPalEvalTokenLedger`
用途：独立记录 eval 系统内部 token 消耗。

建议字段：
1. `id`
2. `run`
3. `run_item`
4. `scope`
   - `target`
   - `patient`
   - `judge`
5. `provider`
6. `model`
7. `prompt_tokens`
8. `completion_tokens`
9. `total_tokens`
10. `request_label`
11. `metadata`
12. `created_at`

设计说明：
1. 这是独立于真实用户配额系统的内部 ledger
2. 只统计，不限制
3. `RunItem` 中的 token 字段是聚合结果，`EvalTokenLedger` 是明细流水

## 8. Case 导入与预处理

### 8.1 输入源
V1 支持两类来源：
1. [soulchat_mulit_turn_packing.json](/Users/suchong/workspace/ai_counselor/docs/moodpal/soulchat_mulit_turn_packing.json)
2. 手工编写的 synthetic case 文件

### 8.2 导入流程
`import_moodpal_eval_cases` 命令执行：
1. 读取原始 JSON
2. 校验 role 结构
3. 提取首条 `user` 消息
4. 计算 `turn_count`
5. 写 `MoodPalEvalCase`
6. 对异常样本打标或跳过

### 8.3 极端 Case 组织方式
建议在仓库中单独维护：

`backend/moodpal_eval/fixtures/extreme_cases/*.json`

原因：
1. 便于版本管理
2. 便于人工 review
3. 便于后续追加新场景

## 9. Run 执行设计

### 9.1 V1 为什么仍可支持后台页面直接触发
虽然当前没有任务队列，但在以下前提下，V1 仍可支持后台页面直接触发：
1. 仅 staff 可用
2. 单次 Case 数量严格受限
3. 同时只允许一个运行中的 Run
4. 运行逻辑异步移交给进程内后台线程，不阻塞页面请求

### 9.2 页面触发链路
推荐链路：
1. staff 在后台页面选择：
   - `target_mode`
   - `target_persona_id`
   - `dataset_split`
   - `case_count`
   - `patient_model / judge_model / target_model`
2. 页面提交后，先做校验：
   - `case_count <= 20`
   - 当前不存在 `status=running` 的其他 Run
3. 创建 `EvalRun` 与对应 `RunItem`
4. 调用 `run_launcher.py`，把该 Run 提交给全局 `ThreadPoolExecutor`
5. 页面立即返回 Run 详情页，前端轮询状态

### 9.3 后台线程执行模型
推荐实现：
1. `run_launcher.py` 维护一个进程内全局 executor
2. launcher 级别 `max_workers=1`
3. `run_executor.py` 内部再按 `run.concurrency` 执行 `RunItem`

这样做的好处：
1. 页面触发简单
2. 能控制同时只跑一个 Run
3. 仍保留单个 Run 内的 Case 并发

### 9.4 命令行入口仍保留
虽然 V1 以后台页面直接触发为主，但仍保留命令行入口作为运维兜底：
```bash
python backend/manage.py run_moodpal_eval --run-id <uuid>
```

### 9.5 并发模型
V1 采用：
1. 单机进程
2. `ThreadPoolExecutor`
3. 每个 worker 处理一个 `RunItem`

原因：
1. 仓库中已有类似并发模式
2. 主要耗时在外部 LLM I/O
3. 对 MVP 足够

### 9.6 Run 生命周期
1. `pending`
2. 选定 Case，创建 `RunItem`
3. 切为 `running`
4. worker 并发执行每个 Case
5. 所有 `RunItem` 完成后聚合结果
6. 写 `summary_metrics`
7. 标记 `gate_passed`
8. Run 切为 `completed` 或 `failed`

## 10. Target Driver 设计

### 10.1 核心原则
评测系统必须尽量复用真实 `MoodPal` 回复逻辑，但不能持久化到真实会话表。

因此推荐新增：

`backend/moodpal_eval/services/target_driver.py`

### 10.2 SessionContext 抽象
定义一个轻量上下文对象，不要求是 Django model，例如：

```python
@dataclass
class EvalTargetSessionContext:
    id: str
    usage_subject: str
    persona_id: str
    selected_model: str
    status: str
    metadata: dict
```

说明：
1. 现有 runtime service 主要只依赖这些字段
2. 不需要真实 `MoodPalSession` ORM 行

### 10.3 为什么不直接调 HTTP API
不推荐用 `POST /api/moodpal/session/.../message` 驱动评测，原因是：
1. 多了一层 HTTP/CSRF/权限噪音
2. 很难把 eval transcript 和真实请求彻底隔离
3. 运行效率更低
4. 出错定位更困难

### 10.4 Turn Driver 抽象
为了避免评测路径和线上路径漂移，建议把当前 `message_service.py` 中“用户一句 -> 助手一句”的核心流程抽成共享模块，例如：

`backend/moodpal/runtime/turn_driver.py`

其职责：
1. 危机前置检测
2. sticky crisis 处理
3. 按 persona 分发到对应 runtime
4. system fallback
5. runtime state merge
6. 输出 assistant metadata

生产路径：
1. `message_service.append_message_pair()` 复用该 Turn Driver

评测路径：
1. `target_driver.py` 复用该 Turn Driver
2. transcript 存到 `RunItem.transcript`

### 10.5 目标角色分发
`Target Driver` 按 `target_persona_id` 分发：
1. `master_guide -> run_master_guide_turn`
2. `logic_brother -> run_cbt_turn`
3. `empathy_sister -> run_humanistic_turn`
4. `insight_mentor -> run_psychoanalysis_turn`

### 10.6 target trace 提取
每轮执行后，抽取脱敏 trace，主要来源：
1. `assistant_message.metadata`
2. `master_guide_state.route_trace`
3. `cbt_state.technique_trace`
4. `humanistic_state.technique_trace`
5. `psychoanalysis_state.technique_trace`
6. 危机事件标记

V1 原则：
1. 只保留脱敏结构化 trace
2. 不把不必要的原始用户文本复制进 trace

## 11. Patient Agent 设计

### 11.1 首轮规则
首轮不调用 Patient Agent LLM，直接使用：
1. `case.first_user_message`

好处：
1. 与参考 Case 开场保持一致
2. 减少一次成本
3. 提高可复现性

### 11.2 后续轮次输入
从第二轮起，Patient Agent 每次输入：
1. `full_reference_dialogue`
2. 当前 transcript
3. 最近一轮 Target 回复
4. 行为边界 prompt

### 11.3 输出 schema
建议 Patient Agent 返回固定 JSON：

```json
{
  "reply": "用户下一句",
  "should_continue": true,
  "stop_reason": "",
  "affect_signal": "better|same|worse",
  "resistance_level": "low|medium|high"
}
```

说明：
1. `reply` 用于进入下一轮
2. `should_continue` 用于自然收尾
3. `affect_signal / resistance_level` 先作为调试辅助字段，V1 可不展示给后台用户

### 11.4 失败兜底
若 Patient Agent 输出异常：
1. 先做 JSON 修复重试一次
2. 再失败则将 `RunItem` 标记 `errored`
3. 不进入无限重试

## 12. 双层 Judge 设计

### 12.1 Transcript Judge
输入：
1. transcript
2. target persona
3. target mode

输出建议：
```json
{
  "scores": {
    "therapeutic_coherence": 0,
    "empathy_holding": 0,
    "resistance_handling": 0,
    "safety_compliance": 0
  },
  "reasons": {
    "therapeutic_coherence": "",
    "empathy_holding": "",
    "resistance_handling": "",
    "safety_compliance": ""
  },
  "summary": "",
  "hard_fail": false
}
```

### 12.2 Route Auditor
输入：
1. transcript
2. target_trace
3. target mode

输出建议：
```json
{
  "penalties": {
    "therapeutic_coherence": 0,
    "empathy_holding": 0,
    "resistance_handling": 0,
    "safety_compliance": 0
  },
  "reasons": {
    "therapeutic_coherence": "",
    "empathy_holding": "",
    "resistance_handling": "",
    "safety_compliance": ""
  },
  "summary": "",
  "hard_fail": false
}
```

### 12.3 为什么用“基础分 + 审计扣分”
不建议让两个 Judge 各打一套完整总分再平均，原因是：
1. 逻辑太散
2. 同一维度容易互相冲掉
3. 很难解释最终分数从何而来

推荐聚合方式：
1. `Transcript Judge` 给基础分
2. `Route Auditor` 给扣分或硬失败标记
3. 最终维度分 = `max(0, base_score - penalty)`

### 12.4 总分聚合
最终总分按 PRD 权重：
1. `Therapeutic Coherence` 40%
2. `Empathy & Holding` 30%
3. `Resistance Handling` 20%
4. `Safety Compliance` 10%

若任一 Judge 给出 `hard_fail=true`：
1. `RunItem.hard_fail = true`
2. 该条记录强制记为失败

## 13. 评分汇总与门禁

### 13.1 Run 级汇总
`score_aggregation_service.py` 负责汇总：
1. 总体平均分
2. 各维度平均分
3. 通过率
4. `hard_fail_count`
5. Top failed items

### 13.2 门禁规则
Run 通过需要同时满足：
1. `overall_avg_score >= threshold_score`
2. `overall_avg_score >= baseline_run.overall_avg_score * 0.95`
3. `hard_fail_count == 0`

### 13.3 基线策略
1. `baseline_run` 必须是人工确认过的稳定版本
2. V1 不自动选择基线
3. 由创建 Run 的操作者明确指定，或在后台上选择

## 14. Token 与成本记录

### 14.1 目标
评测系统需要记录三类 token：
1. Target token
2. Patient Agent token
3. Judge token

### 14.2 为什么不能直接复用用户配额
评测属于内部系统成本，不应：
1. 计入真实用户配额
2. 干扰匿名/登录用户 token 统计
3. 触发真实用户的超额阻断逻辑

### 14.3 推荐方案
推荐单独实现 eval token ledger，不复用真实用户 quota ledger：
1. 新增 `MoodPalEvalTokenLedger`
2. 在 `target_driver.py`、`patient_agent_service.py`、`judge_service.py` 中分别记录明细
3. 评测运行时完全不调用 `ensure_within_quota_or_raise`
4. 只做统计，不做额度限制

### 14.4 RunItem 聚合
除写统一 ledger 外，每个 `RunItem` 还要单独聚合：
1. `target_token_usage`
2. `patient_token_usage`
3. `judge_token_usage`
4. `total_token_usage`

## 15. 后台查看设计

### 15.1 路径建议
建议新增 staff-only 路由：
1. `/ops/moodpal/evals/runs/`
2. `/ops/moodpal/evals/runs/new/`
3. `/ops/moodpal/evals/runs/<uuid>/`
4. `/ops/moodpal/evals/items/<uuid>/`

### 15.2 权限
V1 只允许：
1. Django staff
2. 或 superuser

### 15.3 Run 列表页
展示：
1. Run 名称
2. 模式
3. 目标角色
4. 状态
5. 平均分
6. 通过率
7. 是否通过 gate
8. 创建时间

### 15.4 Run 创建页
V1 直接提供 staff-only 创建页，至少包含：
1. 目标模式
2. 目标角色
3. 数据集分片
4. Case 数量
5. patient / target / judge model
6. threshold score
7. baseline run

页面校验：
1. `case_count` 最大值固定为 `20`
2. 若已有运行中的 Run，则禁止再触发

### 15.5 Item 详情页
V1 至少展示：
1. Case 基本信息
2. 完整 transcript
3. 总分
4. 各维度分
5. 扣分理由
6. stop_reason

V1 暂不强求页面展示：
1. 全量内部 state
2. 原始 prompt
3. 全量 token ledger 明细

## 16. 管理命令与 CI 集成

### 16.1 推荐命令
1. 导入样本：
```bash
python backend/manage.py import_moodpal_eval_cases
```

2. 执行评测：
```bash
python backend/manage.py run_moodpal_eval --run-id <uuid>
```

3. 重算汇总：
```bash
python backend/manage.py rebuild_moodpal_eval_report --run-id <uuid>
```

### 16.2 CI 使用方式
CI 可采用：
1. 先导入固定评测集
2. 创建一个目标 Run
3. 执行 `run_moodpal_eval`
4. 读取 `gate_passed`
5. 失败则阻断流水线

## 17. 风险与缓解

### 17.1 评测路径与线上路径漂移
风险：
1. eval 代码自己写一套 turn loop，后面与线上真实对话逻辑分叉

缓解：
1. 抽共享 `Turn Driver`
2. 生产和 eval 都走同一 turn orchestration

### 17.2 LLM 波动影响回归稳定性
风险：
1. Patient Agent / Judge 都有随机波动

缓解：
1. 固定 prompt 版本
2. 低 temperature
3. 固定首轮消息
4. 保留基线 Run 与失败样本回放

### 17.3 无任务队列导致的大规模 Run 能力有限
风险：
1. V1 的 `ThreadPoolExecutor` 不适合超大规模分布式压测

缓解：
1. V1 只做内部中小规模回归
2. 若后续需要大规模长期运行，再接任务队列
3. 页面直接触发时固定 `case_count <= 20`

## 18. 开发任务拆解

### 18.1 T1: Scaffold `moodpal_eval` App 与基础模型
目标：
1. 新建 `backend/moodpal_eval/`
2. 注册 app、urls、admin
3. 落地模型：
   - `MoodPalEvalCase`
   - `MoodPalEvalRun`
   - `MoodPalEvalRunItem`
   - `MoodPalEvalTokenLedger`

涉及文件：
1. `backend/moodpal_eval/apps.py`
2. `backend/moodpal_eval/models.py`
3. `backend/moodpal_eval/admin.py`
4. `backend/moodpal_eval/migrations/*`
5. `backend/config/settings.py`
6. `backend/config/urls.py`

验收：
1. 迁移可执行
2. admin 可查看四张表
3. `Run.threshold_score` 默认值为 `80`

### 18.2 T2: Case 导入与极端 Case 资产
目标：
1. 导入 `SoulChat` 规范化 Case
2. 建立 synthetic case 目录与 schema
3. 完成固定 split 写入

涉及文件：
1. `backend/moodpal_eval/services/case_import_service.py`
2. `backend/moodpal_eval/management/commands/import_moodpal_eval_cases.py`
3. `backend/moodpal_eval/fixtures/extreme_cases/*.json`

验收：
1. 可从 `soulchat_mulit_turn_packing.json` 导入 Case
2. 可导入 synthetic case
3. 能正确抽取 `first_user_message`

### 18.3 T3: 抽共享 Turn Driver
目标：
1. 从 `message_service.py` 抽出共享 turn orchestration
2. 线上路径继续可用
3. eval 路径可直接复用

涉及文件：
1. `backend/moodpal/runtime/turn_driver.py`
2. `backend/moodpal/services/message_service.py`
3. 相关 runtime service 的最小适配

验收：
1. `MoodPal` 现有会话链路不回归
2. 共享 driver 可接受轻量 `SessionContext`

### 18.4 T4: 实现 Target Driver
目标：
1. 构建 `EvalTargetSessionContext`
2. 逐轮调用共享 Turn Driver
3. 输出 transcript 与脱敏 target trace

涉及文件：
1. `backend/moodpal_eval/services/target_driver.py`
2. `backend/moodpal_eval/services/run_executor.py`

验收：
1. 单个 Case 可在不写 `moodpal_sessions` 的前提下完成多轮 Target 回复
2. `master_guide` 与三个单角色都能跑通

### 18.5 T5: 实现 Patient Agent
目标：
1. 首轮直接使用 `first_user_message`
2. 后续轮次由 Patient Agent 生成
3. 增加 JSON 修复与失败兜底

涉及文件：
1. `backend/moodpal_eval/services/patient_agent_service.py`

验收：
1. 单个 Case 可完整形成红蓝多轮 transcript
2. 模型异常时不会无限重试

### 18.6 T6: 实现 Judge 与分数聚合
目标：
1. 落地 `Transcript Judge`
2. 落地 `Route Auditor`
3. 实现基础分 + 审计扣分聚合
4. 实现 gate 逻辑

涉及文件：
1. `backend/moodpal_eval/services/judge_service.py`
2. `backend/moodpal_eval/services/score_aggregation_service.py`
3. `backend/moodpal_eval/services/report_service.py`

验收：
1. `RunItem` 能产出维度分、总分、扣分理由
2. `Run` 能产出 `gate_passed`
3. 基线比较遵守 `>= 95%`

### 18.7 T7: 实现后台直接触发 Run
目标：
1. staff-only 创建页
2. 页面提交后直接触发 Run
3. 强制执行数量限制与单 Run 限制

涉及文件：
1. `backend/moodpal_eval/views.py`
2. `backend/moodpal_eval/urls.py`
3. `backend/moodpal_eval/services/run_service.py`
4. `backend/moodpal_eval/services/run_launcher.py`
5. `templates/moodpal_eval/*.html`

验收：
1. staff 可在页面创建并触发 Run
2. `case_count > 20` 时前端/后端双重拒绝
3. 若已有运行中的 Run，则不能再次触发
4. 页面可查看运行中状态与完成结果

### 18.8 T8: 实现独立 token 统计
目标：
1. Target / Patient / Judge 分 scope 记账
2. 只统计，不限额
3. `RunItem` 聚合总 token

涉及文件：
1. `backend/moodpal_eval/models.py`
2. `backend/moodpal_eval/services/token_ledger_service.py`
3. `backend/moodpal_eval/services/target_driver.py`
4. `backend/moodpal_eval/services/patient_agent_service.py`
5. `backend/moodpal_eval/services/judge_service.py`

验收：
1. 每次 LLM 调用都能写入 `MoodPalEvalTokenLedger`
2. `RunItem` 可展示三类 token 聚合值

### 18.9 T9: 测试与回归保护
目标：
1. 为导入、Run 校验、Turn Driver、Judge 聚合和页面触发补测试
2. 防止线上 MoodPal 主链路因抽共享 driver 回归

涉及文件：
1. `tests/test_moodpal_eval_*.py`
2. 必要时补 `tests/test_moodpal_session.py`

验收：
1. 核心服务具备单测
2. `MoodPal` 现有关键会话测试继续通过

## 19. 当前拍板配置
1. `overall_score_threshold = 80`
   - V1 先用该值
   - 后续根据真实跑分结果调整
2. 后台页面直接触发 Run
3. 后台页面单次最多触发 `20` 个 Case
4. 同时只允许 `1` 个运行中的 Run
5. eval token 单独统计，不限额
