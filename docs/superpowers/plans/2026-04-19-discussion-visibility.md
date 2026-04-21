# 讨论可见性（公开/仅自己可见）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为圆桌讨论加入"公开 / 仅自己可见"开关：创建讨论时可选可见性；私密讨论仅在当前用户的历史列表里可见；其他用户访问别人创建的公开讨论时强制降为 observer；Restart 流程弹窗让用户为新讨论重新选择可见性，且新讨论默认进入 participant 模式。

**Architecture:** `Discussion` 新增 `owner`（FK User，nullable）、`visibility`（`public`/`private`，默认 `public`）两个字段。owner 在 Setup 创建 Discussion 时写入；visibility 在 Start 时根据前端选择写入。历史列表 API 用 `Q(visibility='public') | Q(owner=request.user)` 过滤；WebSocket connect 与 HTML 详情页均在非 owner 用户访问时把 `user_role` 内存降级为 `observer`，不改 DB。Restart API 接收 `visibility`、强制 `user_role='participant'`、记录当前用户为 owner；前端重启前弹窗选可见性。

**Tech Stack:** Django 4.2 + Channels（ASGI）、sqlite、原生 JS（无构建）、pytest。

---

## 背景 / 现有约束

- `Discussion` 模型当前**没有** owner/visibility 字段（`backend/roundtable/models.py:7`）。
- `HistoryListApiView`（`backend/roundtable/views.py:1013`）向每个登录用户返回**全部**讨论。
- Setup 两步流程：`DiscussionSetupView` 先创建 Discussion（`views.py:334` 附近）存 topic→status=setup；`DiscussionStartView`（`views.py:466` 附近）在角色配置好后把 status 置 active 并启动 AutoContinueService。owner 必须在第一步写入。
- `RestartApiView`（`views.py:1051`）目前复制 `user_role=original.user_role`——需改为强制 `participant`。
- `DiscussionConsumer`（`backend/roundtable/consumers.py`）connect 时会多处从 DB 读 discussion 的 `user_role`，需要确认所有 handler 走 `self.user_role`（在 connect 里统一被降级）。
- 认证：所有 HTTP 路径和 WS 要求 Django login；`settings_test` 禁用 auth。测试里 `Client()` 仍然走中间件→会碰 DB，需要 `@pytest.mark.django_db`。

---

## 文件结构

**新建/修改**：
- `backend/roundtable/models.py` — 新增 `owner`、`visibility` 字段
- `backend/roundtable/migrations/000X_discussion_visibility.py` — 由 makemigrations 生成
- `backend/roundtable/views.py` — Setup/Start/History/Restart 四处调整
- `backend/roundtable/consumers.py` — connect 内非 owner 降级
- `templates/roundtable/index.html` — 角色配置页加可见性单选
- `templates/roundtable/history.html`（或同效果模板）— 列表项加 🔒 + Restart 弹窗
- `tests/test_visibility.py` — 新测试文件
- 可能需要更新 `tests/test_api.py` 里已有的 Discussion 创建 fixture（如果它们依赖固定字段）

---

## Task 1: 数据模型 + 迁移

**Files:**
- Modify: `backend/roundtable/models.py:7`（Discussion class）
- Create: `backend/roundtable/migrations/000X_discussion_visibility.py`（由 makemigrations 产出）

- [ ] **Step 1: 写测试验证字段存在 + 默认值**

`tests/test_visibility.py`（新建）：
```python
import pytest
from django.contrib.auth import get_user_model
from backend.roundtable.models import Discussion


@pytest.mark.django_db
def test_discussion_has_owner_and_visibility_defaults():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    d = Discussion.objects.create(topic='t', owner=user)
    assert d.owner_id == user.id
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_discussion_owner_nullable_for_legacy_records():
    d = Discussion.objects.create(topic='legacy')
    assert d.owner is None
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_discussion_visibility_choices():
    d = Discussion.objects.create(topic='t', visibility='private')
    assert d.visibility == 'private'
```

- [ ] **Step 2: 运行测试，预期失败**

```bash
pytest tests/test_visibility.py -v
```
Expected: 三条都失败，提示 `owner`/`visibility` 字段不存在。

- [ ] **Step 3: 修改模型**

在 `backend/roundtable/models.py` 顶部补：
```python
from django.conf import settings
```
在 `Discussion` 类里（现有字段之后、`class Meta` 之前）加：
```python
    class Visibility(models.TextChoices):
        PUBLIC = 'public', '公开'
        PRIVATE = 'private', '仅自己可见'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='discussions',
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
```

- [ ] **Step 4: 生成迁移**

```bash
cd backend && python manage.py makemigrations roundtable
```
Expected: 新增一个迁移文件，内容包含 `AddField` owner 与 visibility。现有行 `owner=NULL, visibility='public'`——由 default 覆盖，无需 RunPython。

- [ ] **Step 5: 测试通过**

```bash
pytest tests/test_visibility.py -v
```
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/roundtable/models.py backend/roundtable/migrations/ tests/test_visibility.py
git commit -m "feat(roundtable): add owner + visibility fields to Discussion"
```

---

## Task 2: Setup 时写入 owner

**Files:**
- Modify: `backend/roundtable/views.py`（`DiscussionSetupView` 内 `Discussion.objects.create(...)` 调用，约 `views.py:334`）
- Modify: `tests/test_visibility.py`

- [ ] **Step 1: 写测试**

追加到 `tests/test_visibility.py`：
```python
from django.test import Client


@pytest.mark.django_db
def test_setup_writes_owner():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/roundtable/api/setup/',
        data='{"topic":"hello","user_role":"host","max_rounds":3}',
        content_type='application/json',
    )
    assert resp.status_code == 200
    body = resp.json()
    d = Discussion.objects.get(id=body['discussion_id'])
    assert d.owner_id == user.id
    assert d.visibility == 'public'  # Start 前默认
```

> **实施者注意**：先读一下 `backend/roundtable/views.py` 的 `DiscussionSetupView` 和 `backend/roundtable/urls.py`，确认 URL 路径和请求体字段名与此测试一致；如不一致请调整测试，而不是改动 URL。

- [ ] **Step 2: 测试失败**

```bash
pytest tests/test_visibility.py::test_setup_writes_owner -v
```
Expected: FAIL — owner 为 None。

- [ ] **Step 3: 在 Setup create 调用里加 `owner=request.user`**

`backend/roundtable/views.py` DiscussionSetupView 的 `Discussion.objects.create(...)`，新增一行：
```python
owner=request.user,
```

- [ ] **Step 4: 测试通过**

```bash
pytest tests/test_visibility.py -v
```
Expected: all passed。

- [ ] **Step 5: Commit**

```bash
git add backend/roundtable/views.py tests/test_visibility.py
git commit -m "feat(roundtable): record owner at discussion setup"
```

---

## Task 3: Start 时根据前端 payload 更新 visibility

**Files:**
- Modify: `backend/roundtable/views.py`（`DiscussionStartView`，约 `views.py:466`）
- Modify: `templates/roundtable/index.html`（开始讨论按钮上方插入单选）
- Modify: `tests/test_visibility.py`

- [ ] **Step 1: 写测试**

```python
@pytest.mark.django_db
def test_start_accepts_visibility_private():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    d = Discussion.objects.create(topic='t', user_role='observer', owner=user)
    # 简化：走 start API；假定有一个 character 已配置（如果测试路径要求角色，在 fixture 里补）
    from backend.roundtable.models import Character
    Character.objects.create(discussion=d, name='c1', viewpoints={}, language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(user)
    resp = client.post(
        f'/roundtable/api/discussions/{d.id}/start/',
        data='{"visibility":"private"}',
        content_type='application/json',
    )
    assert resp.status_code == 200
    d.refresh_from_db()
    assert d.visibility == 'private'


@pytest.mark.django_db
def test_start_default_visibility_public_when_missing():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    d = Discussion.objects.create(topic='t', user_role='observer', owner=user)
    from backend.roundtable.models import Character
    Character.objects.create(discussion=d, name='c1', viewpoints={}, language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(user)
    resp = client.post(
        f'/roundtable/api/discussions/{d.id}/start/',
        data='{}',
        content_type='application/json',
    )
    assert resp.status_code == 200
    d.refresh_from_db()
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_start_rejects_invalid_visibility():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    d = Discussion.objects.create(topic='t', user_role='observer', owner=user)
    from backend.roundtable.models import Character
    Character.objects.create(discussion=d, name='c1', viewpoints={}, language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(user)
    resp = client.post(
        f'/roundtable/api/discussions/{d.id}/start/',
        data='{"visibility":"secret"}',
        content_type='application/json',
    )
    assert resp.status_code == 400
```

> **实施者注意**：
> - URL/字段名以代码为准；读一下 `DiscussionStartView` 本身的 request body parsing 和 URL 配置。
> - Character 需要的必填字段同样以实际模型为准；如果 `viewpoints`/`language_style`/`temporal_constraints` 不是 JSONField 或有其他默认值，请改为真实的构造方式。
> - 这些测试写的是**行为契约**；如需要辅助 fixture 提取到 conftest，照做即可。

- [ ] **Step 2: 测试失败**

```bash
pytest tests/test_visibility.py -v
```
Expected: 三条与 visibility 相关的都 FAIL。

- [ ] **Step 3: 修改 DiscussionStartView**

在 `DiscussionStartView.post` 里，读取完 body（现有代码里已有 json.loads 的位置）后加：
```python
visibility = data.get('visibility', 'public')
if visibility not in ('public', 'private'):
    return JsonResponse({'error': '无效的可见性参数'}, status=400)
```
在把 status 改为 active 的同一处 save/update 里一并存 `visibility=visibility`（如果该处用 `.update(...)`，加 kwarg；如果是 `discussion.save()` 先赋值属性再 save）。

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_visibility.py -v
```
Expected: 全部通过。

- [ ] **Step 5: 前端改动 — index.html 增加单选**

在 `templates/roundtable/index.html` 的"开始讨论"按钮（搜索 `btnStart` 或对应中文按钮文案）所在 section，**按钮上方**插入：
```html
<div class="field visibility-field" style="margin:12px 0;">
    <label style="font-weight:600;">会谈可见性：</label>
    <label style="margin-right:16px;">
        <input type="radio" name="visibility" value="public" checked> 公开
    </label>
    <label>
        <input type="radio" name="visibility" value="private"> 仅自己可见
    </label>
</div>
```
在 `btnStart` 的 click handler 里，POST body 构造处（目前应向 `/api/discussions/<id>/start/` 发请求）读取并带上：
```javascript
const visibility = document.querySelector('input[name="visibility"]:checked').value;
// ... body: JSON.stringify({ ..., visibility })
```

- [ ] **Step 6: Commit**

```bash
git add backend/roundtable/views.py templates/roundtable/index.html tests/test_visibility.py
git commit -m "feat(roundtable): persist visibility selection at start"
```

---

## Task 4: 历史列表过滤 + is_mine/visibility 元数据

**Files:**
- Modify: `backend/roundtable/views.py:1013`（HistoryListApiView）
- Modify: 历史列表模板（先读代码确认是哪一个；可能在 `templates/roundtable/history.html` 或 `index.html` 的某一段 JS）
- Modify: `tests/test_visibility.py`

- [ ] **Step 1: 写后端测试**

```python
@pytest.mark.django_db
def test_history_hides_others_private():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    mine_public = Discussion.objects.create(topic='mp', owner=alice, visibility='public')
    mine_private = Discussion.objects.create(topic='mpr', owner=alice, visibility='private')
    bob_public = Discussion.objects.create(topic='bp', owner=bob, visibility='public')
    bob_private = Discussion.objects.create(topic='bpr', owner=bob, visibility='private')
    legacy = Discussion.objects.create(topic='leg')  # owner=None, public by default
    client = Client()
    client.force_login(alice)
    resp = client.get('/roundtable/api/history/')
    ids = {item['id'] for item in resp.json()['history']}
    assert mine_public.id in ids
    assert mine_private.id in ids
    assert bob_public.id in ids
    assert legacy.id in ids
    assert bob_private.id not in ids


@pytest.mark.django_db
def test_history_marks_is_mine_and_visibility():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    mine = Discussion.objects.create(topic='m', owner=alice, visibility='private')
    bobs = Discussion.objects.create(topic='b', owner=bob, visibility='public')
    client = Client()
    client.force_login(alice)
    resp = client.get('/roundtable/api/history/')
    by_id = {item['id']: item for item in resp.json()['history']}
    assert by_id[mine.id]['is_mine'] is True
    assert by_id[mine.id]['visibility'] == 'private'
    assert by_id[bobs.id]['is_mine'] is False
    assert by_id[bobs.id]['visibility'] == 'public'
```

- [ ] **Step 2: 测试失败**

```bash
pytest tests/test_visibility.py -v
```
Expected: 两条新测试 FAIL。

- [ ] **Step 3: 修改 HistoryListApiView**

```python
from django.db.models import Q

class HistoryListApiView(View):
    def get(self, request):
        try:
            discussions = (
                Discussion.objects
                .filter(Q(visibility='public') | Q(owner=request.user))
                .prefetch_related('characters')
                .order_by('-created_at')
            )
            history_list = []
            for d in discussions:
                characters = list(d.characters.all())
                character_count = len(characters)
                char_names = ', '.join(c.name for c in characters[:3])
                if character_count > 3:
                    char_names += f' 等{character_count}人'
                history_list.append({
                    'id': d.id,
                    'topic': d.topic,
                    'status': d.status,
                    'user_role': d.user_role,
                    'character_names': char_names,
                    'character_count': character_count,
                    'current_round': d.current_round,
                    'max_rounds': d.max_rounds,
                    'created_at': d.created_at.strftime('%Y-%m-%d %H:%M'),
                    'visibility': d.visibility,
                    'is_mine': d.owner_id == request.user.id,
                })
            return JsonResponse({'history': history_list, 'count': len(history_list)},
                                json_dumps_params={'ensure_ascii': False})
        except Exception:
            logger.exception("Error getting history list")
            return JsonResponse({'error': '服务器内部错误，请稍后重试'}, status=500)
```

- [ ] **Step 4: 前端渲染 🔒**

找到历史列表渲染 JS（可能在 `templates/roundtable/index.html` 或独立模板），在条目标题后根据 `item.visibility === 'private' && item.is_mine` 渲染 `🔒`。只对 `is_mine` 才显示私密图标——公开的讨论全部无图标。

- [ ] **Step 5: 测试通过**

```bash
pytest tests/test_visibility.py -v
```
Expected: all passed。

- [ ] **Step 6: Commit**

```bash
git add backend/roundtable/views.py templates/ tests/test_visibility.py
git commit -m "feat(roundtable): filter history by visibility + owner"
```

---

## Task 5: 非 owner 访问时降级为 observer

**Files:**
- Modify: `backend/roundtable/consumers.py` — `DiscussionConsumer.connect`
- Modify: `backend/roundtable/views.py` — 渲染详情页的 view（先 grep `discussion.html` 找对应 view 名）
- Modify: `templates/roundtable/discussion.html` — 依据模板上下文里的 `user_role` 隐藏发言/令牌 UI（目前应该已经有条件分支；检查是否足够）
- Modify: `tests/test_visibility.py`

- [ ] **Step 1: 写测试**

```python
@pytest.mark.django_db
def test_detail_view_downgrades_non_owner_to_observer():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(bob)
    resp = client.get(f'/roundtable/discussion/{d.id}/')
    assert resp.status_code == 200
    # 渲染上下文里的 user_role 应被降级
    assert resp.context['user_role'] == 'observer'


@pytest.mark.django_db
def test_detail_view_keeps_owner_role():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    d = Discussion.objects.create(topic='t', user_role='participant', owner=alice,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(alice)
    resp = client.get(f'/roundtable/discussion/{d.id}/')
    assert resp.context['user_role'] == 'participant'


@pytest.mark.django_db
def test_detail_view_legacy_no_owner_uses_original_role():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=None,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(alice)
    resp = client.get(f'/roundtable/discussion/{d.id}/')
    assert resp.context['user_role'] == 'host'
```

> **实施者注意**：详情页 URL/view 的确切名字请以 `backend/roundtable/urls.py` 为准。如果目前模板直接从 `discussion` 对象读 `user_role`，改为渲染时传 effective `user_role` 到 context。

- [ ] **Step 2: 测试失败**

- [ ] **Step 3: 修改详情页 view**

读出 discussion 后：
```python
effective_user_role = discussion.user_role
if discussion.owner_id and discussion.owner_id != request.user.id:
    effective_user_role = 'observer'
context = {..., 'user_role': effective_user_role, 'discussion': discussion, ...}
```
如果模板里当前是 `{{ discussion.user_role }}`，改为 `{{ user_role }}`（同步调整模板）。

- [ ] **Step 4: 修改 DiscussionConsumer.connect**

在 `connect` 里取 discussion 后，计算 `self.user_role`：
```python
if discussion.owner_id and discussion.owner_id != self.user.id:
    self.user_role = 'observer'
else:
    self.user_role = discussion.user_role
```

**关键审查**：grep `consumers.py` 里所有使用 `discussion.user_role`（特别是 send_message / 抢令牌 / 参与者相关 handler）的位置，改为读 `self.user_role`。connect 里初始下发到前端的 `initial_data.user_role` 也必须是 `self.user_role`，让前端隐藏相应 UI。

- [ ] **Step 5: 测试通过**

```bash
pytest tests/test_visibility.py -v
```

- [ ] **Step 6: 手测**

启动 daphne（`cd /Users/suchong/workspace/ai_counselor && daphne -p 8000 -b 127.0.0.1 backend.config.asgi:application`），用两个账号验证：
1. alice 新建 `host` 模式公开讨论
2. bob 登录→打开 alice 的讨论→UI 只允许旁观，发言按钮隐藏
3. alice 自己打开→保持 host 模式

- [ ] **Step 7: Commit**

```bash
git add backend/roundtable/consumers.py backend/roundtable/views.py templates/roundtable/discussion.html tests/test_visibility.py
git commit -m "feat(roundtable): downgrade non-owner viewers to observer"
```

---

## Task 6: Restart 强制 participant + 可见性弹窗

**Files:**
- Modify: `backend/roundtable/views.py:1051`（RestartApiView）
- Modify: 前端历史页或含 Restart 按钮的模板
- Modify: `tests/test_visibility.py`

- [ ] **Step 1: 写测试**

```python
@pytest.mark.django_db
def test_restart_forces_participant_and_sets_owner():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    original = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                         visibility='public', status='finished')
    from backend.roundtable.models import Character
    Character.objects.create(discussion=original, name='c1', viewpoints={},
                             language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(bob)
    resp = client.post(
        f'/roundtable/api/discussions/{original.id}/restart/',
        data='{"visibility":"private"}',
        content_type='application/json',
    )
    assert resp.status_code == 200
    new_id = resp.json()['discussion_id']
    new_d = Discussion.objects.get(id=new_id)
    assert new_d.user_role == 'participant'
    assert new_d.owner_id == bob.id
    assert new_d.visibility == 'private'


@pytest.mark.django_db
def test_restart_default_visibility_public():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    original = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                         visibility='private', status='finished')
    from backend.roundtable.models import Character
    Character.objects.create(discussion=original, name='c1', viewpoints={},
                             language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(alice)
    resp = client.post(
        f'/roundtable/api/discussions/{original.id}/restart/',
        data='{}',
        content_type='application/json',
    )
    new_id = resp.json()['discussion_id']
    assert Discussion.objects.get(id=new_id).visibility == 'public'


@pytest.mark.django_db
def test_restart_rejects_invalid_visibility():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    original = Discussion.objects.create(topic='t', owner=alice, status='finished')
    from backend.roundtable.models import Character
    Character.objects.create(discussion=original, name='c1', viewpoints={},
                             language_style={}, temporal_constraints={})
    client = Client()
    client.force_login(alice)
    resp = client.post(
        f'/roundtable/api/discussions/{original.id}/restart/',
        data='{"visibility":"secret"}',
        content_type='application/json',
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: 测试失败**

- [ ] **Step 3: 修改 RestartApiView**

```python
def post(self, request, discussion_id):
    try:
        import json
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            data = {}
        visibility = data.get('visibility', 'public')
        if visibility not in ('public', 'private'):
            return JsonResponse({'error': '无效的可见性参数'}, status=400)

        original = Discussion.objects.get(id=discussion_id)
        original_chars = original.characters.all()
        if not original_chars:
            return JsonResponse({'error': '原讨论没有角色配置'}, status=400)

        new_discussion = Discussion.objects.create(
            topic=original.topic,
            user_role='participant',  # 强制参与者
            status='active',
            max_rounds=original.max_rounds,
            character_limit=original.character_limit,
            owner=request.user,
            visibility=visibility,
            # …保留原有其它字段复制
        )
        # …其余角色复制 + 启动 AutoContinueService 的逻辑保持不变
```
（实施者：按现有文件的实际结构细致 patch，不要一次性大块替换；保留角色复制、token 启动等逻辑。）

- [ ] **Step 4: 前端弹窗**

找到 Restart 按钮对应的 JS handler（历史列表里的"重新开始"按钮），改写成：
```javascript
async function onRestartClick(discussionId) {
    const choice = await showVisibilityDialog();  // 返回 'public' | 'private' | null(取消)
    if (!choice) return;
    const resp = await fetch(`/roundtable/api/discussions/${discussionId}/restart/`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrf()},
        body: JSON.stringify({ visibility: choice }),
    });
    // …跳转到新讨论
}

function showVisibilityDialog() {
    return new Promise(resolve => {
        // 简单的 modal：两个单选 + 确认/取消按钮
        // 或复用 window.confirm 风格：两个按钮，公开 / 仅自己可见；取消返回 null
    });
}
```
可以用现有项目里已有的弹窗风格（如果有）；没有就写一个最小 HTML + CSS 的 modal（参照 `index.html` 里已有的 confirm 元素）。

- [ ] **Step 5: 测试通过**

```bash
pytest tests/test_visibility.py -v
pytest tests/ -v  # 确认现有测试不回归
```

- [ ] **Step 6: 手测**

- alice 完成一个讨论
- alice 在历史列表点"重新开始"→弹窗→选私密→进入新讨论是 participant 模式、历史列表里只有 alice 看得到新讨论
- bob 点 alice 的公开讨论的"重新开始"→弹窗选公开→新讨论 owner=bob、participant 模式、alice 也能在列表里看到（公开）

- [ ] **Step 7: Commit**

```bash
git add backend/roundtable/views.py templates/ tests/test_visibility.py
git commit -m "feat(roundtable): restart prompts for visibility and forces participant"
```

---

## 最终验收

- [ ] `pytest tests/ -v` 与 `pytest backend/ -v` 全绿
- [ ] `cd backend && python manage.py check --settings=config.settings_test` 通过
- [ ] 手测五大路径：创建公开 / 创建私密 / 他人看公开被降级 / 他人看私密（URL）也被降级 / Restart 弹窗正确
- [ ] 没有新遗留 `print`/调试日志；commit 消息风格与 `git log --oneline -10` 一致
