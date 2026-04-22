# MoodPal MVP 开发推进计划（v0.1）

## 1. 文档目标
本文件用于回答一个工程问题：

在 `prd.md`、`tech_design.md`、`cbt_langgraph_design.md` 都已经形成基线后，MoodPal 应该如何一步步推进开发，才能避免返工。

结论先行：
1. 不能先只写 CBT 代码。
2. 必须先把 MoodPal 的产品骨架、会话生命周期、Burn Pipeline 搭起来。
3. CBT 是第一条流派落地线，但不是整个产品的起点。

## 2. 四份文档的职责分工

### 2.1 `prd.md`
负责定义：
1. 产品定位
2. 用户主流程
3. 页面与体验要求
4. 隐私、危机、摘要、配额等产品边界

### 2.2 `tech_design.md`
负责定义：
1. Django + LangGraph 总架构
2. MoodPal 的共享能力
3. Session 生命周期
4. Burn Pipeline
5. 页面/API 的总边界

### 2.3 `cbt_langgraph_design.md`
负责定义：
1. CBT 流派如何接入总框架
2. CBT Graph 的状态机
3. CBT Router / Executor / ExitEvaluator
4. CBT JSON 节点库的消费方式

### 2.4 `humanistic_langgraph_design.md`
负责定义：
1. 人本主义流派如何接入总框架
2. Humanistic Graph 的状态机
3. Humanistic Router / Executor / ResonanceEvaluator
4. 人本主义 JSON 节点库与图层异常处理的协同方式

## 3. 总体推进原则
1. 先搭产品主链路，再做流派细节。
2. 先搭共享骨架，再做 CBT 专项。
3. 先把生命周期和数据流跑通，再做智能策略优化。
4. 每一步都应形成可验证的阶段成果，而不是“只补文档不落地”。

## 4. 推荐开发顺序

### 阶段 0：冻结设计基线
目标：
1. 冻结产品主流程
2. 冻结技术架构边界
3. 冻结 CBT 第一版实现方向

输入文档：
1. [prd.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/prd.md)
2. [tech_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/tech_design.md)
3. [cbt_langgraph_design.md](/Users/suchong/workspace/ai_counselor/docs/moodpal/cbt_langgraph_design.md)

产出：
1. 后续代码实现不再修改核心路线
2. 只允许补细节，不再改总方向

### 阶段 1：搭 MoodPal 模块骨架
目标：
先让 MoodPal 作为站内正式模块存在，而不是一堆零散实验代码。

需要落地：
1. `backend/moodpal/`
2. `backend/moodpal/urls.py`
3. `backend/moodpal/views.py`
4. `backend/moodpal/services/`
5. `templates/moodpal/`

页面骨架：
1. `/moodpal/`
   - 角色选择页
   - 非医疗建议声明
2. `/moodpal/session/<id>/`
   - 会话页
3. `/moodpal/session/<id>/summary/`
   - 摘要确认页

API 骨架：
1. `POST /api/moodpal/session/start`
2. `POST /api/moodpal/session/<id>/message`
3. `POST /api/moodpal/session/<id>/end`
4. `POST /api/moodpal/session/<id>/summary/save`
5. `POST /api/moodpal/session/<id>/summary/destroy`
6. `GET /api/moodpal/session/<id>`

阶段完成标准：
1. 页面可访问
2. 接口路由存在
3. 不要求智能逻辑已完成

### 阶段 2：实现 Session 生命周期
目标：
先把 MoodPal 从“页面壳”变成“有会话概念的产品”。

必须落实：
1. Session 生命周期状态
   - `starting`
   - `active`
   - `ending`
   - `summary_pending`
   - `closed`
2. 新会话创建
3. 会话进入 active
4. 主动结束
5. 自动结束
6. 终态不可恢复

关键约束：
1. 30 分钟无回复自动结束
2. 一旦进入 `summary_pending` 或 `closed`，不能继续普通对话

阶段完成标准：
1. 能创建会话
2. 能进入对话页
3. 能主动或自动结束
4. 结束后只能进入摘要流程

### 阶段 3：实现 Burn Pipeline 最小闭环
目标：
把产品最核心的“阅后即焚”做成真实链路，而不是文案承诺。

需要落地：
1. 短期消息存储层
   - 建议 Redis
2. 摘要草稿生成入口
3. 摘要确认页
4. 摘要保存
5. 摘要销毁
6. 原始消息销毁
7. 审计事件记录

最小规则：
1. 保存摘要时，仅保留确认后的摘要
2. 销毁摘要时，不保留原始消息和摘要
3. 自动结束也必须进入同一套摘要/Burn 流程

阶段完成标准：
1. 会话结束后能生成摘要
2. 用户能保存或销毁
3. 原始消息在流程结束后不再可恢复

### 阶段 4：接共享运行时接口
目标：
在正式接 CBT 之前，先把 Graph 运行时边界搭好。

建议先定义：
1. `GraphState` 抽象
2. `NodeRegistry` 抽象
3. `TechniqueRouter` 抽象
4. `TechniqueExecutor` 抽象
5. `ExitEvaluator` 抽象

要求：
1. 接口先抽象，不只为 CBT 服务
2. CBT 是第一种实现，不是唯一实现

阶段完成标准：
1. MoodPal 已具备接入任意流派 Graph 的技术骨架

### 阶段 5：实现 CBT 第一版运行时
目标：
把 CBT 作为第一条可运行流派接进 MoodPal。

建议优先实现：
1. `CBTGraphState`
2. `CBTNodeRegistry`
3. `CBTTechniqueRouter`
4. `CBTTechniqueExecutor`
5. `CBTExitEvaluator`
6. `CBTGraph`

首版节点白名单：
1. `cbt_structure_agenda_setting`
2. `cbt_cog_identify_at_basic`
3. `cbt_cog_identify_at_telegraphic`
4. `cbt_cog_identify_at_imagery`
5. `cbt_cog_eval_socratic`
6. `cbt_cog_eval_distortion`
7. `cbt_cog_response_coping`
8. `cbt_exception_alliance_rupture`

必须同时支持：
1. `PreFlightExceptionCheck`
2. `ExitEvaluator` 熔断
3. 同轨替代

阶段完成标准：
1. CBT 主链可跑通
2. 不会在单节点死循环
3. 能在结尾形成平衡想法或摘要素材

### 阶段 6：接入站内共享能力
目标：
让 MoodPal 真正成为站内产品，而不是独立实验模块。

需要接入：
1. 匿名主体识别
   - `anon_usage_id`
2. 登录用户主体识别
3. token 配额检查
4. token 使用记录
5. 模型选择
6. 联系管理员反馈
7. 危机检测前置抢占

阶段完成标准：
1. 匿名和登录用户都能使用
2. 超额能阻断
3. 模型选择能生效
4. 危机内容能跳出普通 Graph

### 阶段 7：页面联调
目标：
把前端页面与后端主链路串起来。

联调顺序：
1. 角色选择 -> 创建会话
2. 隐私契约 -> 进入会话
3. 发消息 -> Graph 回复
4. 主动结束 -> 摘要确认
5. 自动结束 -> 摘要确认
6. 保存/销毁摘要
7. 配额超额提示
8. 危机切换提示

阶段完成标准：
1. 用户主流程全链可走通
2. 没有裸 500

### 阶段 8：补第二批 CBT 能力
目标：
在主链稳定后再扩展行为分支和深层探索。

第二批：
1. `cbt_beh_activation`
2. `cbt_beh_experiment`
3. `cbt_beh_graded_task`
4. `cbt_exception_homework_obstacle`

第三批：
1. `cbt_core_downward_arrow`
2. `cbt_exception_yes_but`
3. `cbt_exception_redirecting`

原因：
1. 行为分支复杂度适中，可在主链稳定后补充
2. 深层探索和复杂异常最容易造成状态判断漂移，必须后置

### 阶段 9：测试与可观测性
目标：
让 MoodPal 可维护、可定位问题、可灰度。

至少补 4 类测试：
1. Router 规则测试
2. ExitEvaluator 判定测试
3. Session / Burn Pipeline 流程测试
4. API 集成测试

至少补 5 类日志/追踪：
1. 技术节点 trace
2. 熔断日志
3. 危机抢占日志
4. 摘要生成/销毁日志
5. 配额阻断日志

## 5. 现在最推荐的“下一步”
从整体顺序看，下一步不应该直接开始写完整 CBT Router 代码。

最合理的优先级是：
1. 先搭 `backend/moodpal/` 模块和页面/API 骨架
2. 先实现 Session 生命周期
3. 先实现 Burn Pipeline 最小闭环
4. 再进入 CBT 第一版实现

这一步做好后，后续写 CBT 代码就不会因为产品主链路不完整而返工。

## 6. 对应到代码任务的推荐顺序
建议按下面顺序开工：

1. `backend/moodpal/urls.py`
2. `backend/moodpal/views.py`
3. `templates/moodpal/index.html`
4. `templates/moodpal/session.html`
5. `templates/moodpal/summary.html`
6. `backend/moodpal/services/session_service.py`
7. `backend/moodpal/services/summary_service.py`
8. `backend/moodpal/services/burn_service.py`
9. `backend/moodpal/cbt/state.py`
10. `backend/moodpal/cbt/node_registry.py`
11. `backend/moodpal/cbt/router_config.py`
12. `backend/moodpal/cbt/router.py`
13. `backend/moodpal/cbt/exit_evaluator.py`
14. `backend/moodpal/cbt/executor.py`
15. `backend/moodpal/cbt/graph.py`

## 7. 当前不建议做的事
1. 不建议一开始就做 15 个 CBT 节点全量上线
2. 不建议一开始就做共情流派和深挖流派同时实现
3. 不建议在 Session/Burn Pipeline 还没稳定前先做大量 Prompt 微调
4. 不建议先做复杂前端动画和高级 UI 打磨
