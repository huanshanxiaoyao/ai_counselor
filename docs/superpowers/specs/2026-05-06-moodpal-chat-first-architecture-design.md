# MoodPal 架构重构设计：聊天优先 + 条件触发心理学提示

**日期**: 2026-05-06  
**状态**: 已批准，待实现

---

## 背景与问题

当前架构每一轮都强制执行：`MasterGuide 路由 → 选 track → 选 technique → 注入【本轮任务】`。这个流水线让每条回复都带着"我在执行一个步骤"的气味，即使 persona spec 包装得再好，用户仍然感受到被"处理"的催促感与空洞感。

根本矛盾：系统是"带聊天包装的治疗"，而目标应是"带可选治疗能力的聊天"。

---

## 设计目标

- 表层：自然聊天，绝大多数 turn 无任何心理学任务框注入
- 底层：静默分析对话状态，在时机成熟时给响应层注入一句轻量方向提示
- 用户感知：像在和一个高水平的朋友聊天，对方懂你，偶尔帮你找到点

---

## 核心架构：双层解耦

每个 turn 分两个独立操作：

```
用户消息
    │
    ├── 分析层（静默）
    │       三条 track 信号提取 + 状态更新
    │       门控判断：是否注入提示 + 注入什么
    │       输出：hint_text: Optional[str]
    │
    └── 响应层（用户可见）
            persona_spec + 对话历史 + hint_text（可选）
            → LLM 生成回复
```

### 响应层 prompt 结构

**无提示时**（默认，大多数 turn）：
```
[persona_spec]

[完整对话历史]
```

**有提示时**（时机成熟，条件触发）：
```
[persona_spec]

[背景觉察]
{hint_text}  ← 一句自然语言，如"用户似乎在几个话题里绕，可以帮他找到最想说的那根线，轻轻问一句。"

[完整对话历史]
```

`hint_text` 永远是口语化的情境觉察句，不暴露任何技术名词、节点名、状态机概念。

---

## 门控机制（Gating）

满足以下所有条件才注入提示：

| 条件 | 说明 |
|------|------|
| `turn_index >= 3` | 至少有一定对话积累 |
| `alliance_status in {medium, strong}` | 信任基础存在 |
| `NOT repair_needed` | 没有关系裂缝需要先修复 |
| `distress_level != high OR problem_clarity != low` | 不在纯情绪崩溃状态 |
| `readiness_score >= threshold` | CBT / 精神分析 / 人本中至少一条准备度达标 |

**默认态**：不满足门控 → `hint_text = None` → 纯聊天。

---

## hint_generator 模块

新增 `moodpal/hint_generator.py`，职责：输入信号字典，输出 `Optional[str]`。

提示按信号模式分组，而非按 technique ID 分类。示例映射：

| 信号模式 | hint_text |
|----------|-----------|
| `pattern_signal=high, alliance=strong` | 用户的一些话里有重复的影子，有机会可以轻轻点一下，不用说透。 |
| `action_readiness=high, cbt_readiness=high` | 用户好像想往前走，可以帮他把第一步压到最小。 |
| `emotional_intensity=high, advice_pull=detected` | 用户想要抓手，但情绪还很满，先接住，等他自己松一点再说。 |
| `agenda_locked=True, topic_drift=detected` | 用户跑题了，可以顺着他说，然后轻轻带回来。 |

---

## 各层职责变化

### 分析层（原三条 track）

- **保留**：信号提取逻辑、各 track 的状态结构（CBT state、humanistic state、psychoanalysis state）
- **移除**：executor 的 prompt 构建职责（`_build_technique_section` 等）
- 三个 executor 文件退化为"分析执行器"，只负责运行状态机、提取信号、输出状态 patch

### MasterGuide Router

- **原输出**：`RouteSelection(mode: str, reason_code: str, ...)`
- **新输出**：`TurnPlan(hint_text: Optional[str], analysis_patch: dict)`

### 响应层（新增）

- 新文件：`moodpal/runtime/conversation_executor.py`
- 职责：接收 `persona_id + hint_text + history_messages`，构建 prompt，调用 LLM

### 废弃/大幅简化

- 各 track 的 `executor_prompt_config.py`（technique 模板不再用于 prompt 构建）
- `awareness_hints.py`（功能合并进 hint_generator）
- 各 track 内部的 graph-level 路由（只保留状态更新，不再"选节点执行"）

---

## 关键文件清单

### 新建
- `backend/moodpal/hint_generator.py`
- `backend/moodpal/runtime/conversation_executor.py`

### 改动
- `backend/moodpal/master_guide/router.py`
- `backend/moodpal/master_guide/route_policy.py`
- `backend/moodpal/master_guide/routing_signal_extractor.py`（轻微调整）
- `backend/moodpal/services/master_guide_runtime_service.py`
- `backend/moodpal/cbt/executor.py` → 退化为分析执行器
- `backend/moodpal/humanistic/executor.py` → 退化为分析执行器
- `backend/moodpal/psychoanalysis/executor.py` → 退化为分析执行器

### 废弃（可保留但不再被调用）
- `backend/moodpal/cbt/executor_prompt_config.py`
- `backend/moodpal/humanistic/executor_prompt_config.py`
- `backend/moodpal/psychoanalysis/executor_prompt_config.py`
- `backend/moodpal/awareness_hints.py`

---

## 不变的部分

- `persona_specs.py` — persona 人设定义完全不变
- 三条 track 的状态定义（`state.py`）
- 三条 track 的信号提取逻辑（`signal_extractor.py`、routing_signal_extractor）
- DB 模型、session service、前端模板
- LLM client 层（`backend/llm/`）
