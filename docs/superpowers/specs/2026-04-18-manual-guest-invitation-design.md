# 圆桌会谈 · 手动推荐嘉宾 设计文档

- **日期：** 2026-04-18
- **范围：** Roundtable 应用 / 邀请嘉宾环节
- **状态：** 待实现

## 1. 背景与目标

当前圆桌会谈的邀请嘉宾环节完全由系统推荐（`DirectorAgent.suggest_characters`）提供候选。用户希望在系统推荐之外，**手动输入最多 3 位自己心仪的嘉宾**，由 LLM "评委会" 校验其是否为有效人物（真实名人或知名文学/影视/神话作品中的角色）。通过者与系统推荐人物等价地进入后续配置流程；未通过者统一反馈 **"评委会未能通过你推荐的人物"**。

## 2. 范围约束

- 手动输入名额与系统推荐 **共享** 3–8 位总额（不是额外追加）
- 手动输入最多 **3 位**
- 校验时机：**批量**，用户点击「前往配置 →」时一并提交
- 部分通过允许放行：通过者自动纳入选择，未通过者标红保留在输入区
- 校验通过时 LLM **一并返回** `era` 和 `reason`（30 字以内简介），避免后续再调用一次补全
- 同名严格去重（与系统推荐卡片、已有手动卡片比对）

## 3. UX 流程

在 `templates/roundtable/index.html` 的「为你推荐以下嘉宾」网格下方、「前往配置 →」按钮上方，新增「推荐你心仪的嘉宾（最多 3 位）」区块：

```
┌─────────────────────────────────────────────┐
│  为你推荐以下嘉宾（选择 3–8 位）             │
│  [系统推荐卡片网格]                          │
├─────────────────────────────────────────────┤
│  推荐你心仪的嘉宾（最多 3 位）               │
│  ┌───────────────────────┐ ┌──────┐          │
│  │ 输入人物名…           │ │ + 添加 │         │
│  └───────────────────────┘ └──────┘          │
│                                              │
│  ┌──────────────┐ ┌──────────────┐           │
│  │ 王阳明       x│ │ 林黛玉       x│ ← 已添加 │
│  │ ⏳ 待评审     │ │ ❌ 未通过     │           │
│  └──────────────┘ └──────────────┘           │
├─────────────────────────────────────────────┤
│  已选：3 位 (推荐 1 + 心仪 2)  [前往配置 →] │
└─────────────────────────────────────────────┘
```

### 3.1 交互规则

1. **添加：** 输入框 + 「添加」按钮。点击时前端依次做：非空、长度 ≤ 20、与系统卡片/已有手动卡片名不重复、总名额（推荐勾选 + 手动卡片）< 8、手动卡片数 < 3。通过则插入占位卡片，状态 `⏳ 待评审`。
2. **删除：** 卡片右上 `×` 按钮，任意状态均可删除。
3. **校验触发：** 点击「前往配置 →」时：
   - 若存在 `⏳ 待评审` 卡片，按钮改为"评审中…"并禁用
   - 一次 POST 到 `/roundtable/api/validate-guests/`，传所有待评审名字
   - 返回后按 name 匹配，每张卡片更新为 `✓ 已通过`（绿色，显示 era + reason）或 `❌ 评委会未能通过你推荐的人物`（红色）
4. **跳转条件：**
   - 无 `⏳ 待评审` 卡片
   - 无 `❌ 未通过` 卡片（用户必须手动删除）
   - 总数（系统勾选 + 通过的手动卡片）∈ [3, 8]
5. **通过即入选：** 通过的手动卡片自动计入 `selectedCharacters`，无需额外勾选动作。
6. **驳回卡片不能改名：** 驳回卡片只能删除；用户删除后重新输入同名/新名即重置为待评审状态。
7. **上限校验在添加时：** 避免无效 LLM 调用。总数 = 已勾选系统卡片 + 所有手动卡片（无论 待评审/已通过/未通过）。该约束需同时作用于两个方向：
   - 添加手动卡片时，若总数将达 8 → 拒绝
   - 勾选系统卡片时，若总数将达 8 → 拒绝（扩展现有 `toggleCharacter` 的 MAX_SELECT 判断）

## 4. API 契约

### 4.1 新增端点

`POST /roundtable/api/validate-guests/`

认证：沿用项目 auth 中间件，未登录 401。

### 4.2 请求

```json
{
  "topic": "项羽该不该渡江",
  "candidates": ["王阳明", "林黛玉", "xyz123"]
}
```

- `topic`：string，可选，传给 LLM 作语境（不影响通过与否）
- `candidates`：数组，1–3 个元素，每个非空字符串且 ≤ 20 字符，互不重复

### 4.3 响应（200）

```json
{
  "results": [
    {
      "name": "王阳明",
      "valid": true,
      "era": "明代",
      "reason": "明代心学集大成者，提出知行合一",
      "rejection_reason": null
    },
    {
      "name": "林黛玉",
      "valid": true,
      "era": "清代《红楼梦》",
      "reason": "曹雪芹笔下贾府才女，多愁善感，诗才横溢",
      "rejection_reason": null
    },
    {
      "name": "xyz123",
      "valid": false,
      "era": null,
      "reason": null,
      "rejection_reason": "评委会未能通过你推荐的人物"
    }
  ]
}
```

**字段规则：**

- `results` 顺序与入参 `candidates` 顺序一致（前端按 name 映射更稳）
- `valid=false` 的 `rejection_reason` **始终是固定文案 "评委会未能通过你推荐的人物"**；LLM 给出的真实原因只写入 server log，不返回前端
- `valid=true` 但 `era` / `reason` 为空字符串时：仍视为通过，前端字段做空值兜底

### 4.4 错误响应

| 状态 | 场景 | body |
|---|---|---|
| 400 | candidates 为空 / > 3 / 单条 > 20 字 / 重复 / JSON 格式错误 | `{"error": "..."}` |
| 401 | 未登录 | 中间件 |
| 500 | LLM 调用失败 / 解析失败 | `{"error": "评审服务暂时不可用，请稍后再试"}` |

### 4.5 与现有流程衔接

`/roundtable/api/configure/` 保持不变。前端在校验通过后，把通过的手动卡片 `{name, era, reason}` 直接合并进 `selectedCharacters`，跳转 `/setup/` 时它们与系统推荐卡片的字段格式完全等价。后续 `ConfigureView` 里的 `ensure_offline_profile()` 会自动为没有离线基础设定的手动人物生成并落盘。

## 5. 后端实现

### 5.1 `backend/roundtable/services/director.py` — 扩展

新增方法：

```python
def validate_manual_characters(
    self,
    topic: str,
    names: list[str],
) -> list[dict]:
    """
    校验用户手动输入的人物是否为真实名人或知名文学/影视人物。

    Returns: [
        {
          "name": str,
          "valid": bool,
          "era": str | None,
          "reason": str | None,
          "rejection_reason": str | None
        }, ...
    ]
    顺序与 names 一致。
    """
```

关键点：

- 复用 `self.llm` (LLMClient)，一次调用处理整批（1–3 个）
- 解析严格 JSON 数组，参考 `suggest_characters` 已有的 JSON 解析范式
- LLM 返回数组长度与 `names` 不一致，或 name 字段错位 → 整体走 fallback：所有项标 `valid=false`、`rejection_reason` 置固定文案；log warning
- 单条缺字段（如少 era）但 valid=true → 该字段置空字符串，不影响整体
- LLM 完全调用失败或 JSON 不可解析 → 抛 `LLMParseError`，由 view 捕获转 500

### 5.2 `backend/roundtable/views.py` — 新增 View

```python
class ValidateGuestsView(View):
    """API - 校验用户手动推荐的嘉宾"""

    def post(self, request):
        # 1) Content-Type 校验 + JSON 解析
        # 2) Payload 校验（candidates 1-3，每条非空且 ≤ 20 字，无重复）
        # 3) director = DirectorAgent()
        #    results = director.validate_manual_characters(topic, candidates)
        # 4) 对每个 valid=False 的项：
        #    - logger.info 记录 LLM 给出的真实 rejection_reason
        #    - 覆盖为固定文案 "评委会未能通过你推荐的人物"
        # 5) return JsonResponse({"results": results}, json_dumps_params={'ensure_ascii': False})
```

异常处理参照现有 `SuggestionsView`：

- `JSONDecodeError` → 400
- `LLMParseError` / LLM 相关异常 → 500 `"评审服务暂时不可用，请稍后再试"`
- 其他 `Exception` → `logger.exception` + 500 通用

### 5.3 `backend/roundtable/urls.py` — 新增路由

```python
path('api/validate-guests/', views.ValidateGuestsView.as_view(), name='validate_guests'),
```

### 5.4 离线基础设定

**不在 validate 阶段处理。** 手动通过的人物沿用 `ConfigureView.ensure_offline_profile()`，在下一步 `/api/configure/` 时自动识别"无离线设定"并生成落盘。validate 阶段仅做人物有效性判定。

## 6. LLM 提示词

```
你是圆桌会谈的"评委会"，负责审核用户推荐的嘉宾是否符合参会资格。

【参会资格】（满足任一即通过）
1. 真实存在的历史人物或当代知名人士（政治、科学、文学、艺术、商业等领域）
2. 知名文学作品、影视、戏剧、神话、宗教典籍中的角色（如林黛玉、孙悟空、福尔摩斯、哈姆雷特）

【拒绝条件】（满足任一即驳回）
- 名字无法识别为任何真实人物或知名虚构角色
- 明显是随机字符、键盘乱敲、或恶意输入
- 仅是普通职业/称谓（如"老师"、"医生"），不指向具体个人
- 网络梗、虚构博主、不知名作品中的小人物

【讨论话题】（仅作语境参考，不影响是否通过）
{topic}

【待审核名单】
{names_json}

请严格按以下 JSON 数组格式返回，顺序与待审核名单一致，不要输出任何其他文字：

[
  {
    "name": "原名字",
    "valid": true | false,
    "era": "时代/出处，如'明代'或'清代《红楼梦》'，valid=false 时为 null",
    "reason": "30 字以内的人物简介，valid=false 时为 null",
    "rejection_reason": "valid=false 时填具体驳回原因（仅记日志），valid=true 时为 null"
  },
  ...
]
```

**注入：** `names_json = json.dumps(names, ensure_ascii=False)`。

**Provider：** 复用 `LLMClient` 的默认 provider；超时与重试由 `LLMClient` 统一处理（`LLM_MAX_RETRIES`）。

## 7. 错误处理与边界用例

| 场景 | 处理 |
|---|---|
| 输入空字符串/纯空格点添加 | 前端拒绝，不调接口 |
| 输入超 20 字符 | 前端 `maxlength="20"` 限制 |
| 已添加 3 张手动卡片 | 输入框 + 添加按钮禁用，提示"最多 3 位" |
| 系统勾选 + 手动已添加 ≥ 8 | 添加按钮禁用，提示"嘉宾已达上限 8 位" |
| 与系统卡片或已有手动卡片同名 | 前端拒绝，提示"该嘉宾已在列表中" |
| 删除待评审卡片后再添加新名 | 直接覆盖，无需调接口 |
| 改名驳回卡片 | UX 禁止；只能先删除再重新添加 |
| `/api/validate-guests/` 网络失败或 500 | 前端 toast "评审服务暂时不可用，请稍后再试"；保留所有卡片为待评审状态，可再次点「前往配置」重试 |
| LLM 返回非法 JSON | 后端抛 `LLMParseError` → 500 |
| LLM 返回数组长度错位 / name 对不上 | 后端整体 fallback：所有项 valid=false；log warning |
| 校验通过后用户又删除通过卡片 | 前端从 `selectedCharacters` 移除，不影响其他 |

## 8. 测试计划

### 8.1 后端单元测试

文件：`tests/test_validate_guests.py`

- `test_all_valid`：mock LLM 返回全部 valid=true
- `test_all_rejected`：mock LLM 返回全部 valid=false，断言 rejection_reason 被改写为固定文案
- `test_partial_pass`：部分通过部分驳回，断言顺序、字段、文案
- `test_llm_returns_wrong_length`：LLM 返回数组长度与入参不符 → 整体 fallback 全 invalid
- `test_llm_returns_invalid_json`：LLM 返回非 JSON → 500
- `test_payload_validation`：candidates 空 / > 3 / 超长 / 重复 → 400
- `test_unauthenticated`：未登录 → 401
- `test_lm_reason_not_leaked`：LLM 给出具体驳回原因，响应体中只含固定文案

### 8.2 前端手工验收

- 输入框超 20 字不可输入
- 系统推荐 8 位全勾后，添加按钮禁用
- 已添加 3 位手动卡片后，输入框禁用
- 手动输入与系统推荐同名 → 拒绝
- 点前往配置：全通过 → 跳转 `/setup/` 且总数包含手动卡片；部分通过 → 驳回卡片标红、按钮仍禁用；全驳回 → 所有卡片标红、按钮禁用
- 校验期间网络断开 → toast 提示，卡片回到待评审，可重试

## 9. 实现变更清单

| 文件 | 变更 |
|---|---|
| `backend/roundtable/services/director.py` | 新增 `validate_manual_characters()` 方法 |
| `backend/roundtable/views.py` | 新增 `ValidateGuestsView` |
| `backend/roundtable/urls.py` | 新增 `api/validate-guests/` 路由 |
| `templates/roundtable/index.html` | 新增「推荐你心仪的嘉宾」区块 HTML/CSS/JS；扩展提交逻辑，点击跳转前先调用校验接口 |
| `tests/test_validate_guests.py` | 新增测试文件 |

## 10. 不在本次范围内

- 手动输入人物的昵称归一化（如"王阳明" vs "王守仁"）——一律按原字符串处理
- 记录手动通过人物到候选队列（候选队列仅追踪系统推荐）
- 手动输入的历史校验复用缓存（每次都实时 LLM 调用，3 条以内成本可接受）
- 多语言/英文名支持（当前 LLM 与前端都以中文为主）
