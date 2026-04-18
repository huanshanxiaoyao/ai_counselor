# 圆桌会谈 · 手动推荐嘉宾 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许用户在圆桌邀请嘉宾环节手动推荐最多 3 位人物，由 LLM 批量校验是否为真实名人或知名文学/影视人物，通过者与系统推荐等价进入配置。

**Architecture:** 新增一个 LLM 校验端点 `POST /roundtable/api/validate-guests/`，后端扩展 `DirectorAgent.validate_manual_characters()` 做批量校验；前端在 `index.html` 推荐卡片下方新增手动输入区，点「前往配置」时批量 POST 至校验端点，通过项与系统勾选项合并后进入 `/setup/`。

**Tech Stack:** Django 视图 + `LLMClient` + 原生 JS/HTML (无前端构建)。

**Spec:** `docs/superpowers/specs/2026-04-18-manual-guest-invitation-design.md`

---

## File Structure

- `backend/roundtable/services/director.py` — 扩展：新增 `validate_manual_characters()` 方法
- `backend/roundtable/views.py` — 扩展：新增 `ValidateGuestsView`
- `backend/roundtable/urls.py` — 扩展：新增一条 URL
- `templates/roundtable/index.html` — 扩展：新增手动输入区 UI + JS 分支
- `tests/test_agents.py` — 扩展：新增 `validate_manual_characters` 测试
- `tests/test_api.py` — 扩展：新增 `TestValidateGuestsAPI` 测试类

---

## Task 1: `DirectorAgent.validate_manual_characters()` — 单元测试先行

**Files:**
- Modify: `tests/test_agents.py` (append in `TestDirectorAgent` class)
- Modify: `backend/roundtable/services/director.py`

### 契约

```python
def validate_manual_characters(self, topic: str, names: list[str]) -> list[dict]:
    """
    Returns: [{"name": str, "valid": bool, "era": str|None,
               "reason": str|None, "rejection_reason": str|None}, ...]
    顺序与 names 一致。

    行为：
    - LLM 调用本身失败（LLMAPIError/LLMTimeoutError）→ 异常向上抛
    - JSON 解析失败 / 数组长度与 names 不等 / name 无法对齐 → 整体 fallback：
      所有项 {valid: False, era: None, reason: None, rejection_reason: <固定文案>}，并 log warning
    - 单条缺字段：valid=True 时 era/reason 缺失 → 填空字符串；整体仍保留
    - 固定驳回文案常量：DirectorAgent.DEFAULT_REJECTION = "评委会未能通过你推荐的人物"
    """
```

- [ ] **Step 1: 写失败测试 — 全部通过**

追加到 `tests/test_agents.py` 的 `TestDirectorAgent` 类末尾：

```python
    def test_validate_manual_characters_all_valid(self, director_agent):
        """全部通过场景"""
        director_agent.client.complete.return_value = '''[
            {"name": "王阳明", "valid": true, "era": "明代",
             "reason": "心学集大成者", "rejection_reason": null},
            {"name": "林黛玉", "valid": true, "era": "清代《红楼梦》",
             "reason": "贾府才女", "rejection_reason": null}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="项羽该不该渡江",
            names=["王阳明", "林黛玉"],
        )
        assert len(result) == 2
        assert result[0]["name"] == "王阳明"
        assert result[0]["valid"] is True
        assert result[0]["era"] == "明代"
        assert result[0]["reason"] == "心学集大成者"
        assert result[0]["rejection_reason"] is None
        assert result[1]["name"] == "林黛玉"
        assert result[1]["valid"] is True
```

- [ ] **Step 2: 运行并确认失败**

```bash
pytest tests/test_agents.py::TestDirectorAgent::test_validate_manual_characters_all_valid -v
```

预期：FAIL — `AttributeError: 'DirectorAgent' object has no attribute 'validate_manual_characters'`

- [ ] **Step 3: 添加其余测试（也应全部失败或报错）**

继续在同一类追加：

```python
    def test_validate_manual_characters_all_rejected(self, director_agent):
        """全部驳回场景：rejection_reason 必须被上层覆盖为固定文案（agent 层保留原文案，view 层覆盖）"""
        director_agent.client.complete.return_value = '''[
            {"name": "xyz123", "valid": false, "era": null,
             "reason": null, "rejection_reason": "无法识别"}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="某话题", names=["xyz123"]
        )
        assert len(result) == 1
        assert result[0]["valid"] is False
        assert result[0]["era"] is None
        assert result[0]["reason"] is None
        assert result[0]["rejection_reason"] == "无法识别"

    def test_validate_manual_characters_partial(self, director_agent):
        """部分通过场景，保序"""
        director_agent.client.complete.return_value = '''[
            {"name": "王阳明", "valid": true, "era": "明代",
             "reason": "心学", "rejection_reason": null},
            {"name": "xyz", "valid": false, "era": null,
             "reason": null, "rejection_reason": "无法识别"},
            {"name": "林黛玉", "valid": true, "era": "清代",
             "reason": "才女", "rejection_reason": null}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="t", names=["王阳明", "xyz", "林黛玉"]
        )
        assert [r["name"] for r in result] == ["王阳明", "xyz", "林黛玉"]
        assert [r["valid"] for r in result] == [True, False, True]

    def test_validate_manual_characters_length_mismatch_falls_back(self, director_agent):
        """LLM 返回数组长度与入参不等 → 整体 fallback 为 invalid"""
        director_agent.client.complete.return_value = '''[
            {"name": "王阳明", "valid": true, "era": "明代",
             "reason": "x", "rejection_reason": null}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="t", names=["王阳明", "林黛玉"]
        )
        assert len(result) == 2
        for i, name in enumerate(["王阳明", "林黛玉"]):
            assert result[i]["name"] == name
            assert result[i]["valid"] is False
            assert result[i]["era"] is None
            assert result[i]["reason"] is None
            assert result[i]["rejection_reason"] == \
                DirectorAgent.DEFAULT_REJECTION

    def test_validate_manual_characters_invalid_json_falls_back(self, director_agent):
        """LLM 返回非法 JSON → 整体 fallback"""
        director_agent.client.complete.return_value = "not json at all"
        result = director_agent.validate_manual_characters(
            topic="t", names=["A", "B"]
        )
        assert len(result) == 2
        for r in result:
            assert r["valid"] is False
            assert r["rejection_reason"] == DirectorAgent.DEFAULT_REJECTION

    def test_validate_manual_characters_name_misaligned_falls_back(
        self, director_agent
    ):
        """LLM 返回了对的长度但 name 对不上 → 整体 fallback"""
        director_agent.client.complete.return_value = '''[
            {"name": "错名", "valid": true, "era": "x",
             "reason": "y", "rejection_reason": null},
            {"name": "另一个错名", "valid": true, "era": "x",
             "reason": "y", "rejection_reason": null}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="t", names=["王阳明", "林黛玉"]
        )
        assert all(r["valid"] is False for r in result)
        assert [r["name"] for r in result] == ["王阳明", "林黛玉"]

    def test_validate_manual_characters_valid_missing_fields(self, director_agent):
        """valid=true 但 era/reason 缺失 → 填空字符串，不 fallback"""
        director_agent.client.complete.return_value = '''[
            {"name": "王阳明", "valid": true}
        ]'''
        result = director_agent.validate_manual_characters(
            topic="t", names=["王阳明"]
        )
        assert len(result) == 1
        assert result[0]["valid"] is True
        assert result[0]["era"] == ""
        assert result[0]["reason"] == ""
```

测试类里 `director_agent` fixture 原本返回推荐角色 JSON；上面每个测试用 `director_agent.client.complete.return_value = ...` 重写返回值，即可复用。

同时在文件头部的 import 处补：

```python
from backend.roundtable.services.director import DirectorAgent
```

（若已存在可跳过；fixture 内部已有局部 import，但 `DEFAULT_REJECTION` 需要模块级访问）

- [ ] **Step 4: 运行所有新测试并确认失败**

```bash
pytest tests/test_agents.py::TestDirectorAgent -k validate_manual -v
```

预期：7 个测试全部 FAIL（方法未定义 / `DEFAULT_REJECTION` 未定义）

- [ ] **Step 5: 在 `DirectorAgent` 中添加类常量和新方法**

编辑 `backend/roundtable/services/director.py`。在类 `DirectorAgent` 定义的 `SYSTEM_PROMPT` 常量之后，`__init__` 之前，新增：

```python
    DEFAULT_REJECTION = "评委会未能通过你推荐的人物"

    VALIDATOR_SYSTEM_PROMPT = """你是圆桌会谈的"评委会"，负责审核用户推荐的嘉宾是否符合参会资格。

【参会资格】（满足任一即通过）
1. 真实存在的历史人物或当代知名人士（政治、科学、文学、艺术、商业等领域）
2. 知名文学作品、影视、戏剧、神话、宗教典籍中的角色（如林黛玉、孙悟空、福尔摩斯、哈姆雷特）

【拒绝条件】（满足任一即驳回）
- 名字无法识别为任何真实人物或知名虚构角色
- 明显是随机字符、键盘乱敲、或恶意输入
- 仅是普通职业/称谓（如"老师"、"医生"），不指向具体个人
- 网络梗、虚构博主、不知名作品中的小人物"""
```

在文件末尾（`analyze_topic` 之后）新增方法：

```python
    def validate_manual_characters(
        self, topic: str, names: List[str]
    ) -> List[Dict]:
        """
        校验用户手动输入的人物是否为真实名人或知名文学/影视人物。

        Returns: 与 names 等长且保序的字典列表。
        LLM 返回不合法时整体 fallback 为 invalid（log warning）。
        """
        prompt = self._build_validator_prompt(topic, names)

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self.VALIDATOR_SYSTEM_PROMPT,
            json_mode=True,
        )

        parsed = self._parse_validator_response(response)
        if parsed is None or len(parsed) != len(names):
            logger.warning(
                "Validator response length mismatch or unparseable; "
                "falling back to all-invalid. names=%s response=%s",
                names, response[:500] if isinstance(response, str) else response,
            )
            return self._fallback_all_invalid(names)

        # 按入参顺序对齐；如果 name 对不上，整体 fallback
        by_name = {item.get("name"): item for item in parsed if isinstance(item, dict)}
        if set(by_name.keys()) != set(names):
            logger.warning(
                "Validator response names misaligned; falling back. "
                "expected=%s got=%s", names, list(by_name.keys()),
            )
            return self._fallback_all_invalid(names)

        normalized: List[Dict] = []
        for name in names:
            item = by_name[name]
            valid = bool(item.get("valid"))
            if valid:
                normalized.append({
                    "name": name,
                    "valid": True,
                    "era": item.get("era") or "",
                    "reason": item.get("reason") or "",
                    "rejection_reason": None,
                })
            else:
                normalized.append({
                    "name": name,
                    "valid": False,
                    "era": None,
                    "reason": None,
                    "rejection_reason": item.get("rejection_reason")
                        or self.DEFAULT_REJECTION,
                })
        return normalized

    def _build_validator_prompt(self, topic: str, names: List[str]) -> str:
        names_json = json.dumps(names, ensure_ascii=False)
        return f"""【讨论话题】（仅作语境参考，不影响是否通过）
{topic}

【待审核名单】
{names_json}

请严格按以下 JSON 数组格式返回，顺序与待审核名单一致，不要输出任何其他文字：

[
  {{
    "name": "原名字",
    "valid": true,
    "era": "时代/出处，如'明代'或'清代《红楼梦》'",
    "reason": "30 字以内的人物简介",
    "rejection_reason": null
  }},
  {{
    "name": "原名字",
    "valid": false,
    "era": null,
    "reason": null,
    "rejection_reason": "具体驳回原因"
  }}
]"""

    def _parse_validator_response(self, response: str):
        """解析 LLM 响应为列表；不合法返回 None。"""
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            try:
                start = response.find('[')
                end = response.rfind(']') + 1
                if start != -1 and end > start:
                    data = json.loads(response[start:end])
                else:
                    return None
            except Exception:
                return None
        if isinstance(data, dict) and 'results' in data:
            data = data['results']
        if not isinstance(data, list):
            return None
        return data

    def _fallback_all_invalid(self, names: List[str]) -> List[Dict]:
        return [
            {
                "name": name,
                "valid": False,
                "era": None,
                "reason": None,
                "rejection_reason": self.DEFAULT_REJECTION,
            }
            for name in names
        ]
```

- [ ] **Step 6: 运行测试并确认全部通过**

```bash
pytest tests/test_agents.py::TestDirectorAgent -k validate_manual -v
```

预期：7 passed

- [ ] **Step 7: 运行完整 agents 测试，确保未破坏现有**

```bash
pytest tests/test_agents.py -v
```

预期：全部 passed

- [ ] **Step 8: Commit**

```bash
git add backend/roundtable/services/director.py tests/test_agents.py
git commit -m "feat(roundtable): add DirectorAgent.validate_manual_characters for guest validation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `ValidateGuestsView` + URL 路由

**Files:**
- Modify: `tests/test_api.py` (append `TestValidateGuestsAPI`)
- Modify: `backend/roundtable/views.py` (append `ValidateGuestsView`)
- Modify: `backend/roundtable/urls.py` (append 一条 URL)

### 契约

- `POST /roundtable/api/validate-guests/`
- 请求 body: `{"topic": str, "candidates": [str, str, str]}`
- 响应 200: `{"results": [{name, valid, era, reason, rejection_reason}, ...]}`
- `valid=false` 项的 `rejection_reason` 在 view 层**强制覆写**为 `"评委会未能通过你推荐的人物"`（LLM 真实原因只写日志）
- 400: candidates 空 / > 3 / 单条 > 20 字 / 重复 / Content-Type 非 JSON / JSON 解析失败
- 500: LLM 调用失败（LLMAPIError/LLMTimeoutError/其他）→ `{"error": "评审服务暂时不可用，请稍后再试"}`

- [ ] **Step 1: 写失败的 API 测试**

追加到 `tests/test_api.py` 文件末尾：

```python
class TestValidateGuestsAPI:
    """Tests for /roundtable/api/validate-guests/ endpoint"""

    URL = '/roundtable/api/validate-guests/'

    def _post(self, body):
        return Client().post(
            self.URL,
            data=json.dumps(body),
            content_type='application/json',
        )

    def test_all_valid(self):
        """全部通过：返回原始 era/reason，rejection_reason 为 null"""
        with patch(
            'backend.roundtable.views.DirectorAgent.validate_manual_characters'
        ) as mock:
            mock.return_value = [
                {"name": "王阳明", "valid": True, "era": "明代",
                 "reason": "心学", "rejection_reason": None},
                {"name": "林黛玉", "valid": True, "era": "清代",
                 "reason": "才女", "rejection_reason": None},
            ]
            resp = self._post({
                "topic": "t", "candidates": ["王阳明", "林黛玉"]
            })
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert [r["name"] for r in data["results"]] == ["王阳明", "林黛玉"]
        assert all(r["valid"] for r in data["results"])
        assert all(r["rejection_reason"] is None for r in data["results"])

    def test_all_rejected_reason_is_overridden(self):
        """驳回项 rejection_reason 必须被覆盖为固定文案，原因只入日志"""
        with patch(
            'backend.roundtable.views.DirectorAgent.validate_manual_characters'
        ) as mock:
            mock.return_value = [
                {"name": "xyz", "valid": False, "era": None,
                 "reason": None, "rejection_reason": "LLM 的原始原因"},
            ]
            resp = self._post({"topic": "t", "candidates": ["xyz"]})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data["results"][0]["valid"] is False
        assert data["results"][0]["rejection_reason"] == \
            "评委会未能通过你推荐的人物"

    def test_partial_pass_preserves_order(self):
        with patch(
            'backend.roundtable.views.DirectorAgent.validate_manual_characters'
        ) as mock:
            mock.return_value = [
                {"name": "A", "valid": True, "era": "x",
                 "reason": "y", "rejection_reason": None},
                {"name": "B", "valid": False, "era": None,
                 "reason": None, "rejection_reason": "bad"},
                {"name": "C", "valid": True, "era": "x",
                 "reason": "y", "rejection_reason": None},
            ]
            resp = self._post({
                "topic": "t", "candidates": ["A", "B", "C"]
            })
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert [r["valid"] for r in data["results"]] == [True, False, True]
        assert data["results"][1]["rejection_reason"] == \
            "评委会未能通过你推荐的人物"

    def test_empty_candidates_returns_400(self):
        resp = self._post({"topic": "t", "candidates": []})
        assert resp.status_code == 400

    def test_too_many_candidates_returns_400(self):
        resp = self._post({
            "topic": "t", "candidates": ["A", "B", "C", "D"]
        })
        assert resp.status_code == 400

    def test_name_too_long_returns_400(self):
        resp = self._post({
            "topic": "t", "candidates": ["A" * 21]
        })
        assert resp.status_code == 400

    def test_empty_name_returns_400(self):
        resp = self._post({"topic": "t", "candidates": ["   "]})
        assert resp.status_code == 400

    def test_duplicate_candidates_returns_400(self):
        resp = self._post({
            "topic": "t", "candidates": ["王阳明", "王阳明"]
        })
        assert resp.status_code == 400

    def test_bad_content_type_returns_400(self):
        resp = Client().post(
            self.URL,
            data=json.dumps({"topic": "t", "candidates": ["x"]}),
            content_type='text/plain',
        )
        assert resp.status_code == 400

    def test_bad_json_returns_400(self):
        resp = Client().post(
            self.URL, data="not json",
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_llm_failure_returns_500(self):
        from backend.llm.exceptions import LLMAPIError
        with patch(
            'backend.roundtable.views.DirectorAgent.validate_manual_characters',
            side_effect=LLMAPIError("boom")
        ):
            resp = self._post({"topic": "t", "candidates": ["王阳明"]})
        assert resp.status_code == 500
        data = json.loads(resp.content)
        assert "评审服务" in data["error"]

    def test_topic_optional(self):
        """topic 可省略或为空字符串，仍能正常校验"""
        with patch(
            'backend.roundtable.views.DirectorAgent.validate_manual_characters'
        ) as mock:
            mock.return_value = [
                {"name": "王阳明", "valid": True, "era": "明代",
                 "reason": "x", "rejection_reason": None},
            ]
            resp = self._post({"candidates": ["王阳明"]})
        assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试并确认全部失败/404**

```bash
pytest tests/test_api.py::TestValidateGuestsAPI -v
```

预期：全部 FAIL（endpoint 404 或 view 不存在）

- [ ] **Step 3: 添加 URL**

编辑 `backend/roundtable/urls.py`，在 `api/configure/` 路由之后追加：

```python
    path('api/validate-guests/', views.ValidateGuestsView.as_view(), name='validate_guests'),
```

- [ ] **Step 4: 添加 View**

编辑 `backend/roundtable/views.py`，在顶部 imports 追加（如果尚未有）：

```python
from backend.llm.exceptions import LLMError
```

在 `ConfigureView` 之后新增：

```python
class ValidateGuestsView(View):
    """API endpoint - 校验用户手动推荐的嘉宾是否为有效人物"""

    MAX_CANDIDATES = 3
    MAX_NAME_LEN = 20
    FIXED_REJECTION = "评委会未能通过你推荐的人物"

    def post(self, request):
        content_type = request.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            return JsonResponse(
                {'error': 'Content-Type must be application/json'},
                status=400,
            )

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求格式'}, status=400)

        topic = (data.get('topic') or '').strip()
        candidates = data.get('candidates')

        if not isinstance(candidates, list) or len(candidates) == 0:
            return JsonResponse(
                {'error': 'candidates 不能为空'}, status=400,
            )
        if len(candidates) > self.MAX_CANDIDATES:
            return JsonResponse(
                {'error': f'最多支持 {self.MAX_CANDIDATES} 位手动推荐'},
                status=400,
            )

        cleaned: list[str] = []
        for raw in candidates:
            if not isinstance(raw, str):
                return JsonResponse(
                    {'error': '人物名必须为字符串'}, status=400,
                )
            name = raw.strip()
            if not name:
                return JsonResponse(
                    {'error': '人物名不能为空'}, status=400,
                )
            if len(name) > self.MAX_NAME_LEN:
                return JsonResponse(
                    {'error': f'单个人物名不能超过 {self.MAX_NAME_LEN} 字'},
                    status=400,
                )
            cleaned.append(name)

        if len(set(cleaned)) != len(cleaned):
            return JsonResponse({'error': '人物名不能重复'}, status=400)

        try:
            director = DirectorAgent()
            results = director.validate_manual_characters(topic, cleaned)
        except LLMError:
            logger.exception("Validator LLM call failed")
            return JsonResponse(
                {'error': '评审服务暂时不可用，请稍后再试'},
                status=500,
            )
        except Exception:
            logger.exception("Unexpected error in validate-guests")
            return JsonResponse(
                {'error': '评审服务暂时不可用，请稍后再试'},
                status=500,
            )

        # view 层覆写驳回文案；真实 LLM 原因仅留日志
        for item in results:
            if not item.get('valid'):
                original = item.get('rejection_reason')
                logger.info(
                    "Guest rejected: name=%s llm_reason=%s",
                    item.get('name'), original,
                )
                item['rejection_reason'] = self.FIXED_REJECTION

        return JsonResponse(
            {'results': results},
            json_dumps_params={'ensure_ascii': False},
        )
```

- [ ] **Step 5: 运行测试并确认全部通过**

```bash
pytest tests/test_api.py::TestValidateGuestsAPI -v
```

预期：12 passed

- [ ] **Step 6: 运行完整 API 测试**

```bash
pytest tests/test_api.py -v
```

预期：全部 passed（原有测试未被破坏）

- [ ] **Step 7: Django 系统检查**

```bash
cd backend && python manage.py check --settings=config.settings_test && cd ..
```

预期：System check identified no issues

- [ ] **Step 8: Lint**

```bash
ruff check backend/roundtable/views.py backend/roundtable/services/director.py backend/roundtable/urls.py
```

预期：无报错

- [ ] **Step 9: Commit**

```bash
git add backend/roundtable/views.py backend/roundtable/urls.py tests/test_api.py
git commit -m "feat(roundtable): add /api/validate-guests/ endpoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: 前端 `index.html` — 手动嘉宾输入区

**Files:**
- Modify: `templates/roundtable/index.html`

此 Task 无自动化测试（项目无前端构建/测试框架），依赖 Task 4 的手工验收。

### 设计要点

- 区块位置：`characters-grid` 之后、`selection-bar` 之前
- 状态机：每张手动卡片有 3 状态 `pending` / `valid` / `invalid`
- `selectedCharacters` 语义不变：依然是最终提交给 `/setup/` 的数组
- 手动卡片通过校验后自动 push 进 `selectedCharacters`（不点击勾选）
- 总数上限（MAX_SELECT=8）跨系统卡片 + 手动卡片统一约束

- [ ] **Step 1: 添加 CSS**

在 `templates/roundtable/index.html` 的 `<style>` 块末尾（`@media (max-width: 620px) { ... }` 之前）追加：

```css
/* ── manual guest section ── */
.manual-guests {
  margin-top: 22px;
  padding-top: 22px;
  border-top: 1px dashed var(--gold-border);
}

.manual-guests .section-divider { margin-bottom: 14px; }

.manual-input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.manual-input-row input {
  flex: 1;
  padding: 10px 14px;
  background: rgba(0,0,0,0.38);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  color: var(--text);
  font-size: 0.92rem;
}

.manual-input-row input:focus {
  outline: none;
  border-color: rgba(200,168,69,0.5);
}

.manual-input-row input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-add-guest {
  padding: 10px 18px;
  background: rgba(200,168,69,0.15);
  border: 1px solid var(--gold-border);
  border-radius: 8px;
  color: var(--gold-light);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.18s;
}
.btn-add-guest:hover:not(:disabled) { background: rgba(200,168,69,0.28); }
.btn-add-guest:disabled { opacity: 0.4; cursor: not-allowed; }

.manual-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}

.manual-card {
  position: relative;
  padding: 12px 30px 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(255,255,255,0.07);
  font-size: 0.88rem;
}

.manual-card.pending {
  border-color: rgba(200,168,69,0.4);
  background: rgba(200,168,69,0.06);
}

.manual-card.valid {
  border-color: rgba(126,201,126,0.55);
  background: rgba(126,201,126,0.09);
}

.manual-card.invalid {
  border-color: rgba(217,96,96,0.55);
  background: rgba(217,96,96,0.08);
}

.manual-card .mc-name {
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}
.manual-card .mc-era {
  font-size: 0.76rem;
  color: var(--gold);
  margin-bottom: 4px;
}
.manual-card .mc-status {
  font-size: 0.78rem;
  color: var(--muted);
}
.manual-card.valid   .mc-status { color: #7ec97e; }
.manual-card.invalid .mc-status { color: var(--red); }

.manual-card .mc-remove {
  position: absolute;
  top: 8px;
  right: 10px;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255,255,255,0.15);
  color: var(--text);
  font-size: 11px;
  cursor: pointer;
  user-select: none;
}
.manual-card .mc-remove:hover { background: rgba(255,255,255,0.3); }

.manual-hint {
  font-size: 0.74rem;
  color: var(--muted);
  margin-top: 8px;
  min-height: 1em;
}
.manual-hint.error { color: var(--red); }
```

- [ ] **Step 2: 添加 HTML（在 characters-grid 与 selection-bar 之间）**

在 `templates/roundtable/index.html` 中找到这一段：

```html
      <div id="characters-grid" class="characters-grid"></div>
      <div class="selection-bar">
```

在 `</div>` 和 `<div class="selection-bar">` 之间插入：

```html
      <div id="manual-guests" class="manual-guests">
        <div class="section-divider"><span>推荐你心仪的嘉宾（最多 3 位）</span></div>
        <div class="manual-input-row">
          <input
            type="text"
            id="manual-input"
            placeholder="输入人物名，如：王阳明"
            maxlength="20"
          >
          <button type="button" id="btn-add-guest" class="btn-add-guest">+ 添加</button>
        </div>
        <div id="manual-cards" class="manual-cards"></div>
        <div id="manual-hint" class="manual-hint"></div>
      </div>
```

- [ ] **Step 3: 修改 JS — 新增状态与函数**

在 `<script>` 块顶部，在 `const MIN_SELECT = 3;` 一行之后、`let selectedCharacters` 之前插入常量与状态：

```javascript
  const MAX_MANUAL = 3;
  const FIXED_REJECTION = '评委会未能通过你推荐的人物';

  // manual guest state: [{name, status, era, reason}]
  // status: 'pending' | 'valid' | 'invalid'
  let manualGuests = [];
```

在 `const errorMessage = ...` 一行之后追加：

```javascript
  const manualInput    = document.getElementById('manual-input');
  const btnAddGuest    = document.getElementById('btn-add-guest');
  const manualCards    = document.getElementById('manual-cards');
  const manualHint     = document.getElementById('manual-hint');
```

- [ ] **Step 4: 修改 toggleCharacter（系统卡片勾选上限需跨手动卡片）**

找到现有 `toggleCharacter` 函数：

```javascript
  function toggleCharacter(card, character) {
    const idx = selectedCharacters.findIndex(c => c.name === character.name);
    if (idx >= 0) {
      selectedCharacters.splice(idx, 1);
      card.classList.remove('selected');
    } else if (selectedCharacters.length < MAX_SELECT) {
      selectedCharacters.push(character);
      card.classList.add('selected');
    }
    updateSelectionUI();
  }
```

替换为（总数跨系统勾选 + 所有手动卡片）：

```javascript
  function toggleCharacter(card, character) {
    const idx = selectedCharacters.findIndex(c => c.name === character.name);
    if (idx >= 0) {
      selectedCharacters.splice(idx, 1);
      card.classList.remove('selected');
    } else if (totalCount() < MAX_SELECT) {
      selectedCharacters.push(character);
      card.classList.add('selected');
    }
    updateSelectionUI();
  }

  function totalCount() {
    // selectedCharacters 已包含 valid 状态的手动卡片；pending/invalid 手动卡片单独计数
    const extraManual = manualGuests.filter(g => g.status !== 'valid').length;
    return selectedCharacters.length + extraManual;
  }
```

- [ ] **Step 5: 添加手动卡片渲染与增删函数**

在 `escapeHtml` 函数之前（或之后，位置不影响）新增：

```javascript
  function renderManualCards() {
    manualCards.innerHTML = manualGuests.map((g, i) => {
      let statusText, statusEmoji;
      if (g.status === 'pending') { statusEmoji = '⏳'; statusText = '待评审'; }
      else if (g.status === 'valid') { statusEmoji = '✓'; statusText = '已通过'; }
      else { statusEmoji = '❌'; statusText = FIXED_REJECTION; }

      const eraLine = (g.status === 'valid' && g.era)
        ? `<div class="mc-era">${escapeHtml(g.era)}</div>` : '';
      const reasonLine = (g.status === 'valid' && g.reason)
        ? `<div class="mc-status">${escapeHtml(g.reason)}</div>`
        : `<div class="mc-status">${statusEmoji} ${escapeHtml(statusText)}</div>`;

      return `
        <div class="manual-card ${g.status}" data-index="${i}">
          <div class="mc-remove" data-index="${i}" title="删除">×</div>
          <div class="mc-name">${escapeHtml(g.name)}</div>
          ${eraLine}
          ${reasonLine}
        </div>
      `;
    }).join('');

    manualCards.querySelectorAll('.mc-remove').forEach(btn => {
      btn.addEventListener('click', () => removeManualGuest(parseInt(btn.dataset.index, 10)));
    });
  }

  function updateManualControls() {
    const atManualCap = manualGuests.length >= MAX_MANUAL;
    const atTotalCap = totalCount() >= MAX_SELECT;
    btnAddGuest.disabled = atManualCap || atTotalCap;
    manualInput.disabled = atManualCap || atTotalCap;

    if (atManualCap) {
      manualHint.textContent = `已达手动推荐上限（${MAX_MANUAL} 位）`;
      manualHint.classList.remove('error');
    } else if (atTotalCap) {
      manualHint.textContent = `嘉宾已达上限 ${MAX_SELECT} 位`;
      manualHint.classList.remove('error');
    } else {
      manualHint.textContent = '';
      manualHint.classList.remove('error');
    }
  }

  function setManualError(msg) {
    manualHint.textContent = msg;
    manualHint.classList.add('error');
  }

  function allSystemNames() {
    return Array.from(document.querySelectorAll('#characters-grid .char-name'))
      .map(el => el.textContent.trim());
  }

  function addManualGuest() {
    const raw = manualInput.value.trim();
    if (!raw) return;
    if (raw.length > 20) { setManualError('人物名不能超过 20 字'); return; }
    if (manualGuests.length >= MAX_MANUAL) { setManualError(`最多 ${MAX_MANUAL} 位`); return; }
    if (totalCount() >= MAX_SELECT) { setManualError(`嘉宾已达上限 ${MAX_SELECT} 位`); return; }

    const sysNames = allSystemNames();
    if (sysNames.includes(raw) || manualGuests.some(g => g.name === raw)) {
      setManualError('该嘉宾已在列表中');
      return;
    }

    manualGuests.push({ name: raw, status: 'pending', era: '', reason: '' });
    manualInput.value = '';
    renderManualCards();
    updateManualControls();
    updateSelectionUI();
  }

  function removeManualGuest(index) {
    const removed = manualGuests[index];
    if (!removed) return;
    manualGuests.splice(index, 1);
    // 若被移除的是 valid，同步从 selectedCharacters 移除
    if (removed.status === 'valid') {
      const idx = selectedCharacters.findIndex(c => c.name === removed.name);
      if (idx >= 0) selectedCharacters.splice(idx, 1);
    }
    renderManualCards();
    updateManualControls();
    updateSelectionUI();
  }

  btnAddGuest.addEventListener('click', addManualGuest);
  manualInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); addManualGuest(); }
  });
```

- [ ] **Step 6: 修改 updateSelectionUI — 纳入手动卡片约束**

找到现有 `updateSelectionUI` 函数：

```javascript
  function updateSelectionUI() {
    const count = selectedCharacters.length;
    selectedCount.textContent = count;
    if (count >= MIN_SELECT && count <= MAX_SELECT) {
      btnStart.classList.add('active');
      btnStart.disabled = false;
    } else {
      btnStart.classList.remove('active');
      btnStart.disabled = true;
    }
  }
```

替换为：

```javascript
  function updateSelectionUI() {
    const count = totalCount();
    const hasPending = manualGuests.some(g => g.status === 'pending');
    const hasInvalid = manualGuests.some(g => g.status === 'invalid');
    selectedCount.textContent = count;

    const canProceed = count >= MIN_SELECT
      && count <= MAX_SELECT
      && !hasInvalid;  // pending 允许，点按钮时触发校验
    if (canProceed) {
      btnStart.classList.add('active');
      btnStart.disabled = false;
    } else {
      btnStart.classList.remove('active');
      btnStart.disabled = true;
    }

    if (hasInvalid) {
      btnStart.textContent = '请先处理未通过的嘉宾';
    } else if (hasPending) {
      btnStart.textContent = '前往配置 →';  // 点击会先校验
    } else {
      btnStart.textContent = '前往配置 →';
    }

    updateManualControls();
  }
```

- [ ] **Step 7: 修改 btnStart 点击逻辑 — 加入校验阶段**

找到现有：

```javascript
  btnStart.addEventListener('click', () => {
    if (selectedCharacters.length < MIN_SELECT) return;
    const params = new URLSearchParams({
      topic: currentTopic,
      characters: JSON.stringify(selectedCharacters),
      user_role: userRoleSelect.value
    });
    window.location.href = '/roundtable/setup/?' + params.toString();
  });
```

替换为：

```javascript
  btnStart.addEventListener('click', async () => {
    if (totalCount() < MIN_SELECT) return;
    if (manualGuests.some(g => g.status === 'invalid')) return;

    const pending = manualGuests.filter(g => g.status === 'pending');
    if (pending.length > 0) {
      await validatePendingGuests(pending);
      // 校验后若仍有 invalid，不跳转
      if (manualGuests.some(g => g.status === 'invalid')) return;
      // 总数校验（通过后可能减少，若 < MIN_SELECT 不跳转）
      if (totalCount() < MIN_SELECT) return;
    }

    const params = new URLSearchParams({
      topic: currentTopic,
      characters: JSON.stringify(selectedCharacters),
      user_role: userRoleSelect.value
    });
    window.location.href = '/roundtable/setup/?' + params.toString();
  });

  async function validatePendingGuests(pending) {
    const names = pending.map(g => g.name);
    btnStart.disabled = true;
    btnStart.textContent = '评审中…';
    try {
      const resp = await fetch('/roundtable/api/validate-guests/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: currentTopic, candidates: names }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      const byName = {};
      (data.results || []).forEach(r => { byName[r.name] = r; });

      manualGuests.forEach(g => {
        if (g.status !== 'pending') return;
        const r = byName[g.name];
        if (!r) return;
        if (r.valid) {
          g.status = 'valid';
          g.era = r.era || '';
          g.reason = r.reason || '';
          // 自动纳入 selectedCharacters（幂等）
          if (!selectedCharacters.some(c => c.name === g.name)) {
            selectedCharacters.push({
              name: g.name, era: g.era, reason: g.reason,
            });
          }
        } else {
          g.status = 'invalid';
        }
      });
    } catch (err) {
      setManualError('评审服务暂时不可用，请稍后再试');
    } finally {
      renderManualCards();
      updateSelectionUI();
    }
  }
```

- [ ] **Step 8: 初始化渲染一次**

在 `loadHistory();` 一行之前追加：

```javascript
  renderManualCards();
  updateManualControls();
```

- [ ] **Step 9: Django 系统检查（模板语法）**

```bash
cd backend && python manage.py check --settings=config.settings_test && cd ..
```

预期：System check identified no issues

- [ ] **Step 10: Commit**

```bash
git add templates/roundtable/index.html
git commit -m "feat(roundtable): add manual guest invitation UI with batch LLM validation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 手工验收

**Files:** 无代码改动，仅人工/浏览器验证。

- [ ] **Step 1: 启动开发服务器**

```bash
cd backend && daphne -p 8000 backend.config.asgi:application
```

- [ ] **Step 2: 打开 http://localhost:8000/roundtable/ （登录后），依次验证：**

  1. **输入话题 + 召集嘉宾**：系统推荐列表正常出现
  2. **手动输入空值**：按「添加」无反应（不弹错误也不调接口）
  3. **输入 21 字：** `maxlength` 拦截；若强行粘贴 21 字后添加，提示"人物名不能超过 20 字"
  4. **输入「孔子」（与系统推荐同名）**：提示"该嘉宾已在列表中"
  5. **输入合法 3 位**：卡片显示 `⏳ 待评审`；添加按钮与输入框禁用；提示"已达手动推荐上限（3 位）"
  6. **系统勾选 5 位 + 手动 3 位 = 8**：再点任何系统卡片无效；任何按钮禁用文本"嘉宾已达上限 8 位"
  7. **无系统勾选 + 3 张待评审卡片，点「前往配置」**：按钮变"评审中…"；完成后各卡片变绿（已通过）或红（未通过）；若有未通过按钮文案"请先处理未通过的嘉宾"
  8. **全部通过 + 总数 ≥ 3**：自动跳转 `/setup/`；setup 页面显示手动嘉宾与系统嘉宾合在一起
  9. **配置完成 + 开始讨论**：手动嘉宾在讨论页面正常发言
  10. **网络中断（DevTools 关网）再点前往配置**：红字提示"评审服务暂时不可用，请稍后再试"；卡片状态保持 `pending` 可重试

- [ ] **Step 3: 完整测试套件**

```bash
pytest tests/ -v
```

预期：全部通过

```bash
pytest backend/ -v
```

预期：全部通过

- [ ] **Step 4: Lint + mypy**

```bash
ruff check backend llm
mypy backend llm --ignore-missing-imports
```

预期：ruff 无新增错误；mypy 无新增错误

- [ ] **Step 5: 最终 commit（如有改动）**

若 Step 2 的验收需要微调（如样式小修），统一做一次 commit：

```bash
git add -A
git commit -m "chore(roundtable): manual guest invitation acceptance tweaks

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

若无改动则跳过。

---

## Self-Review 备忘

- Spec §1–§10 均有对应 Task 覆盖：UX → Task 3；API → Task 2；后端实现 → Task 1/2；LLM 提示词 → Task 1 Step 5；错误处理 → Task 1/2/3；测试 → Task 1/2 + Task 4 人工
- 所有步骤含可执行代码与具体命令，无 TBD
- 类型一致性：`validate_manual_characters` / `ValidateGuestsView.FIXED_REJECTION` / `DirectorAgent.DEFAULT_REJECTION` / 前端 `FIXED_REJECTION` 四处文案一致
