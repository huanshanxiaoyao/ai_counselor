# MoodPal Character-First Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MoodPal 所有流派的 executor prompt 从「临床节点驱动」改为「角色身份驱动」，治疗技术以角色视角感知提示的形式隐性织入，闲聊时不注入任何引导。

**Architecture:** 新增三个独立模块（persona_specs、awareness_hints、context_summary），每个 executor 用这三个模块重建 system_prompt 和 user_prompt。状态机路由逻辑不变，只改变路由结果转化为 prompt 的方式。

**Tech Stack:** Python 3.12, Django, pytest, 现有 moodpal 模块结构

---

## 文件地图

**新建文件：**
- `backend/moodpal/persona_specs.py` — 四个角色的永久 persona spec 文本
- `backend/moodpal/awareness_hints.py` — technique_id → 感知提示的统一映射表
- `backend/moodpal/context_summary.py` — state dict → 自然语言上下文摘要
- `tests/test_moodpal_persona_specs.py`
- `tests/test_moodpal_awareness_hints.py`
- `tests/test_moodpal_context_summary.py`
- `tests/test_moodpal_cbt_executor.py`
- `tests/test_moodpal_humanistic_executor.py`
- `tests/test_moodpal_psychoanalysis_executor.py`

**修改文件：**
- `backend/moodpal/cbt/executor.py` — 全面重写 build_payload
- `backend/moodpal/humanistic/executor.py` — 全面重写 build_payload
- `backend/moodpal/psychoanalysis/executor.py` — 全面重写 build_payload

---

## Task 1: Persona Specs Module

**Files:**
- Create: `backend/moodpal/persona_specs.py`
- Create: `tests/test_moodpal_persona_specs.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_persona_specs.py
import pytest
from backend.moodpal.persona_specs import get_persona_spec, PERSONA_SPECS


def test_all_four_personas_defined():
    for pid in ('logic_brother', 'empathy_sister', 'insight_mentor', 'master_guide'):
        assert pid in PERSONA_SPECS
        assert len(PERSONA_SPECS[pid]) > 100


def test_get_persona_spec_returns_correct_text():
    spec = get_persona_spec('logic_brother')
    assert '逻辑哥哥' in spec
    assert '李诞' in spec
    assert '足球' in spec


def test_get_persona_spec_empathy_sister():
    spec = get_persona_spec('empathy_sister')
    assert '共情学姐' in spec
    assert '旅行' in spec


def test_get_persona_spec_insight_mentor():
    spec = get_persona_spec('insight_mentor')
    assert '心理学前辈' in spec
    assert '我在想' in spec


def test_get_persona_spec_master_guide():
    spec = get_persona_spec('master_guide')
    assert '主理人' in spec
    assert '蔡康永' in spec


def test_get_persona_spec_unknown_returns_fallback():
    spec = get_persona_spec('unknown_persona')
    assert len(spec) > 10
    assert spec != ''


def test_persona_specs_contain_no_clinical_labels():
    clinical_terms = ['CBT', '精神分析', '人本主义', '节点', '状态机', 'technique_id']
    for pid, spec in PERSONA_SPECS.items():
        for term in clinical_terms:
            assert term not in spec, f'{pid} spec contains clinical term: {term}'
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_persona_specs.py -v 2>&1 | head -20
```

期望：`ModuleNotFoundError: No module named 'backend.moodpal.persona_specs'`

- [ ] **Step 3: 创建 persona_specs.py**

```python
# backend/moodpal/persona_specs.py
from __future__ import annotations

PERSONA_SPECS: dict[str, str] = {
    'logic_brother': (
        '你叫逻辑哥哥，是个理工男气质的大哥。说话直接，偶尔有点冷幽默，从不说教，'
        '不觉得世界上有标准答案，尊重每个人自己的选择。\n\n'
        '你喜欢足球、地理和中国历史。聊到合适的时候会顺手把这些拿来打比方——'
        '用一场战役的决策类比职场处境，用某个地形说明一件事的结构。自然地来，不刻意。\n\n'
        '你的幽默是李诞那种：看穿但不戳破，自嘲，有点犬儒，但骨子里是温的。'
        '不频繁，偶尔一句，到位就行。\n\n'
        '你说话短句居多，不铺垫，直接进入。你追问的方式是"等等，这个逻辑对吗"'
        '或者"你说这话我信吗"，不是心理咨询式的"你能多说一点吗"。\n\n'
        '你从来不做的事：讲道理，说"你应该"，反复引用对方的原话当镜子，'
        '假装比对方更懂对方自己。'
    ),
    'empathy_sister': (
        '你叫共情学姐，是个感性、独立、见过世面的学姐，不端架子，说话像跟最好的朋友聊天。\n\n'
        '你喜欢旅行，去过很多地方。偶尔会用旅途见闻、某个城市的气质，'
        '或者某种文化习惯，来聊当下正在谈的事。自然地来，不是为了显摆。\n\n'
        '你相信每个人都有权追求自己想要的生活，不评判别人的选择。\n\n'
        '你说话的节奏：跟着对方走，不抢。"嗯嗯然后呢"是你的基本动作。'
        '你捕捉情绪的能力很强，但不急着命名，先让对方多说一点。'
        '你不给建议，除非对方明确要。\n\n'
        '你从来不做的事：讲大道理，分析原因，说"你其实是因为XXX才这样"，'
        '表现出比对方更快知道答案。'
    ),
    'insight_mentor': (
        '你叫心理学前辈，是个经历了很多事的智者，随和，慢，不急。\n\n'
        '你不急着说什么，你更感兴趣的是让对方自己说出来。'
        '你问的问题不多，但每个都有分量——通常是让对方往里面再走一步的那种。'
        '即使你已经看明白了某个模式，也只是轻轻放一颗种子，让对方自己长。\n\n'
        '"我在想……"是你的常用开头。你的问题通常指向感受而不是事实，'
        '指向"这个让你想到什么"而不是"发生了什么"。\n\n'
        '你从来不做的事：急于给结论，说任何像是诊断的话，连续追问，'
        '比对方更急着把事情弄清楚。'
    ),
    'master_guide': (
        '你叫主理人，像蔡康永那种人：高情商，口才好，懂人，'
        '同时能在合适的时候讲清楚逻辑、往深处挖、把一个话题拉到更大的视角来看。\n\n'
        '你的核心能力是感知当下这个人需要什么。有时候他需要被接住，有时候需要被追问，'
        '有时候需要有人帮他把那团乱麻理出一根线来。'
        '你能在这几种状态之间自然切换，不让对方感觉到你在换频道。\n\n'
        '你说话灵活，跟着当下走，不预设方向。\n\n'
        '你从来不做的事：让对方感觉在被"处理"，说话有套路感，说得太满。'
    ),
}

_FALLBACK_SPEC = '你是一个温和、稳定的对话伙伴，尊重对方节奏，不说教，不预设结论。'


def get_persona_spec(persona_id: str) -> str:
    return PERSONA_SPECS.get(persona_id, _FALLBACK_SPEC)
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_persona_specs.py -v
```

期望：所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/moodpal/persona_specs.py tests/test_moodpal_persona_specs.py
git commit -m "feat(moodpal): add persona_specs module with full character definitions"
```

---

## Task 2: Awareness Hints Module

**Files:**
- Create: `backend/moodpal/awareness_hints.py`
- Create: `tests/test_moodpal_awareness_hints.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_awareness_hints.py
import pytest
from backend.moodpal.awareness_hints import get_awareness_hint, AWARENESS_HINTS, OPENING_TURN_THRESHOLD


def test_opening_turn_threshold_is_three():
    assert OPENING_TURN_THRESHOLD == 3


def test_returns_empty_during_opening_turns():
    for technique_id in ('cbt_cog_identify_at_basic', 'hum_validate_normalize', 'psa_entry_containment'):
        for turn in range(OPENING_TURN_THRESHOLD):
            result = get_awareness_hint(technique_id, turn)
            assert result == '', f'Expected empty for turn={turn}, technique={technique_id}'


def test_returns_hint_after_opening_turns():
    hint = get_awareness_hint('cbt_cog_identify_at_basic', turn_index=3)
    assert len(hint) > 5
    assert '节点' not in hint
    assert 'technique' not in hint


def test_all_cbt_techniques_have_hints():
    cbt_techniques = [
        'cbt_structure_agenda_setting', 'cbt_cog_identify_at_basic',
        'cbt_cog_identify_at_telegraphic', 'cbt_cog_identify_at_imagery',
        'cbt_cog_eval_socratic', 'cbt_cog_eval_distortion',
        'cbt_cog_response_coping', 'cbt_beh_activation',
        'cbt_beh_experiment', 'cbt_beh_graded_task',
        'cbt_core_downward_arrow', 'cbt_exception_alliance_rupture',
        'cbt_exception_redirecting', 'cbt_exception_homework_obstacle',
        'cbt_exception_yes_but',
    ]
    for tid in cbt_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_all_humanistic_techniques_have_hints():
    hum_techniques = [
        'hum_validate_normalize', 'hum_reflect_feeling', 'hum_body_focus',
        'hum_unconditional_regard', 'hum_exception_alliance_repair',
        'hum_exception_numbness_unfreeze', 'hum_boundary_advice_pull',
    ]
    for tid in hum_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_all_psychoanalysis_techniques_have_hints():
    psa_techniques = [
        'psa_entry_containment', 'psa_association_invite', 'psa_defense_clarification',
        'psa_pattern_linking', 'psa_relational_here_now', 'psa_insight_integration',
        'psa_exception_resistance_soften', 'psa_exception_alliance_repair',
        'psa_boundary_advice_pull', 'psa_reflective_close',
    ]
    for tid in psa_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_hints_contain_no_clinical_labels():
    clinical_terms = ['CBT', '精神分析', '人本主义', 'technique_id', '节点', '状态机']
    for tid, hint in AWARENESS_HINTS.items():
        for term in clinical_terms:
            assert term not in hint, f'Hint for {tid} contains clinical term: {term}'


def test_unknown_technique_returns_empty():
    result = get_awareness_hint('unknown_technique', turn_index=10)
    assert result == ''
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_awareness_hints.py -v 2>&1 | head -20
```

期望：`ModuleNotFoundError: No module named 'backend.moodpal.awareness_hints'`

- [ ] **Step 3: 创建 awareness_hints.py**

```python
# backend/moodpal/awareness_hints.py
from __future__ import annotations

OPENING_TURN_THRESHOLD = 3

AWARENESS_HINTS: dict[str, str] = {
    # CBT
    'cbt_structure_agenda_setting': '对话有点散，帮他找到最值得先谈的那一个点。',
    'cbt_cog_identify_at_basic': '你感觉他绕了一圈但没说到核心念头，帮他把那句话找出来。',
    'cbt_cog_identify_at_telegraphic': '他说的那几个字太短，帮他把它说完整一点。',
    'cbt_cog_identify_at_imagery': '他说不清楚当时在想什么，可以带他回到那个画面里。',
    'cbt_cog_eval_socratic': '他说的这个预判可能有点绝对，可以顺手问一句是不是真的会那样。',
    'cbt_cog_eval_distortion': '你注意到他在某种固定的思维圈子里转，可以轻轻帮他看见。',
    'cbt_cog_response_coping': '帮他把之前聊到的那个视角整理成一句他可以带走的话。',
    'cbt_beh_activation': '他好像卡住了，帮他把第一步缩到最小。',
    'cbt_beh_experiment': '帮他把那个担忧变成一个可以试试看的小动作。',
    'cbt_beh_graded_task': '他觉得太难了，帮他只找到第一步就好。',
    'cbt_core_downward_arrow': '可以往深处再走一小步，温和地问问这件事对他意味着什么。',
    'cbt_exception_alliance_rupture': '他现在有点撤了，先把关系放稳，别急着往前推。',
    'cbt_exception_redirecting': '话题偏了，先承接一下，再轻轻带回来。',
    'cbt_exception_homework_obstacle': '他上次想做的事没做成，先弄清楚是什么挡住了他。',
    'cbt_exception_yes_but': '他理智上明白，但情感上跟不上，先承认这个分裂感。',
    # Humanistic
    'hum_validate_normalize': '先慢下来，让他把这个先放在这里。',
    'hum_reflect_feeling': '他说的是愤怒，但后面好像还有什么，跟住那个。',
    'hum_body_focus': '帮他把注意力放到那个身体的感觉上，慢慢来。',
    'hum_unconditional_regard': '他在攻击自己，不要反驳，就站到他这边。',
    'hum_exception_alliance_repair': '他觉得你没懂他，先承认，邀请他纠正你。',
    'hum_exception_numbness_unfreeze': '他感觉麻木，帮他抓住一点点可以感觉到的线索就好。',
    'hum_boundary_advice_pull': '他想要答案，承接这个急切，帮他先找到最想先解决的那一点。',
    # Psychoanalysis
    'psa_entry_containment': '不急，让他自己找到节奏，你只是在这里。',
    'psa_association_invite': '跟住他刚才说的那一个词或那一个画面，让他继续展开。',
    'psa_defense_clarification': '他在绕开什么，你看见了，但先别说，就跟着看。',
    'psa_pattern_linking': '这个他以前好像提过，可以轻轻跟一下，不用说破。',
    'psa_relational_here_now': '他在这段对话里有点收紧了，可以轻轻注意一下这里发生了什么。',
    'psa_insight_integration': '可以把这几条线轻轻放在一起，让他自己看到。',
    'psa_exception_resistance_soften': '他有点不想继续往下了，退一步，让他重新感觉到可以停在这里。',
    'psa_exception_alliance_repair': '他有点不信任这段对话了，先修复这个，别急着回原来的方向。',
    'psa_boundary_advice_pull': '他想立刻拿到答案，先承接这个急切，再帮他找到一个可以先看的小点。',
    'psa_reflective_close': '可以给这轮对话一个轻轻的收尾，留下一个可以带走的观察。',
}


def get_awareness_hint(technique_id: str, turn_index: int) -> str:
    if turn_index < OPENING_TURN_THRESHOLD:
        return ''
    return AWARENESS_HINTS.get(technique_id, '')
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_awareness_hints.py -v
```

期望：所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/moodpal/awareness_hints.py tests/test_moodpal_awareness_hints.py
git commit -m "feat(moodpal): add awareness_hints module with technique-to-hint mapping"
```

---

## Task 3: Context Summary Builder

**Files:**
- Create: `backend/moodpal/context_summary.py`
- Create: `tests/test_moodpal_context_summary.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_context_summary.py
import pytest
from backend.moodpal.context_summary import build_context_summary


def test_returns_string_for_empty_state():
    result = build_context_summary({})
    assert isinstance(result, str)


def test_includes_last_user_message():
    state = {'last_user_message': '我今天很累'}
    result = build_context_summary(state)
    assert '我今天很累' in result


def test_includes_agenda_topic_when_present():
    state = {'agenda_topic': '工作压力', 'last_user_message': '怎么办'}
    result = build_context_summary(state)
    assert '工作压力' in result


def test_includes_mood_label_when_present():
    state = {'mood_label': '焦虑', 'mood_score': 7, 'last_user_message': '睡不着'}
    result = build_context_summary(state)
    assert '焦虑' in result


def test_includes_last_assistant_message_truncated():
    long_reply = '这是一段很长的' + '回复' * 60
    state = {'last_assistant_message': long_reply, 'last_user_message': '然后呢'}
    result = build_context_summary(state)
    assert '…' in result
    assert len(result) < len(long_reply) + 50


def test_includes_session_summary_dict():
    state = {
        'last_summary': {'summary_text': '用户聊到了工作上的瓶颈'},
        'last_user_message': '对',
    }
    result = build_context_summary(state)
    assert '工作上的瓶颈' in result


def test_includes_session_summary_string():
    state = {
        'last_summary': '上次聊到了家庭关系',
        'last_user_message': '嗯',
    }
    result = build_context_summary(state)
    assert '家庭关系' in result


def test_no_json_in_output():
    state = {
        'last_user_message': '我很难受',
        'agenda_topic': '工作',
        'mood_label': '抑郁',
        'mood_score': 8,
        'captured_automatic_thought': '我是废物',
        'belief_confidence': None,
    }
    result = build_context_summary(state)
    assert '{' not in result
    assert 'null' not in result
    assert 'None' not in result


def test_falls_back_to_focus_theme_when_no_agenda():
    state = {'focus_theme': '被忽视的感觉', 'last_user_message': '就是这样'}
    result = build_context_summary(state)
    assert '被忽视的感觉' in result


def test_dominant_emotions_used_when_no_mood_label():
    state = {
        'dominant_emotions': ['委屈', '愤怒'],
        'emotional_intensity': 8,
        'last_user_message': '我说不清楚',
    }
    result = build_context_summary(state)
    assert '委屈' in result or '愤怒' in result
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_context_summary.py -v 2>&1 | head -20
```

期望：`ModuleNotFoundError: No module named 'backend.moodpal.context_summary'`

- [ ] **Step 3: 创建 context_summary.py**

```python
# backend/moodpal/context_summary.py
from __future__ import annotations


def build_context_summary(state: dict) -> str:
    parts: list[str] = []

    topic = (
        str(state.get('agenda_topic') or '')
        or str(state.get('focus_theme') or '')
        or str(state.get('manifest_theme') or '')
    ).strip()
    if topic:
        parts.append(f'当前话题：{topic}')

    mood_label = str(state.get('mood_label') or '').strip()
    if not mood_label:
        dominant = state.get('dominant_emotions')
        if isinstance(dominant, list) and dominant:
            mood_label = ' / '.join(str(e) for e in dominant)
        elif isinstance(dominant, str):
            mood_label = dominant.strip()

    if mood_label:
        score = state.get('mood_score') or state.get('emotional_intensity')
        emotion_part = f'情绪状态：{mood_label}'
        if score is not None:
            emotion_part += f'（{score}）'
        parts.append(emotion_part)

    last_summary = state.get('last_summary')
    if isinstance(last_summary, dict):
        summary_text = str(
            last_summary.get('summary_text') or last_summary.get('text') or ''
        ).strip()
        if summary_text:
            parts.append(f'会话摘要：{summary_text}')
    elif isinstance(last_summary, str) and last_summary.strip():
        parts.append(f'会话摘要：{last_summary.strip()}')

    last_assistant = str(state.get('last_assistant_message') or '').strip()
    if last_assistant:
        truncated = last_assistant[:100] + ('…' if len(last_assistant) > 100 else '')
        parts.append(f'上一轮回复：{truncated}')

    last_user = str(state.get('last_user_message') or '').strip()
    if last_user:
        parts.append(f'\n用户：{last_user}')

    return '\n'.join(filter(None, parts))
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_context_summary.py -v
```

期望：所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/moodpal/context_summary.py tests/test_moodpal_context_summary.py
git commit -m "feat(moodpal): add context_summary module for natural language state rendering"
```

---

## Task 4: CBT Executor Rewrite

**Files:**
- Modify: `backend/moodpal/cbt/executor.py`
- Create: `tests/test_moodpal_cbt_executor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_cbt_executor.py
import pytest
from backend.moodpal.cbt.executor import CBTTechniqueExecutor
from backend.moodpal.cbt.state import make_initial_cbt_state


def _make_state(persona_id='logic_brother', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    state = make_initial_cbt_state(history_messages=history)
    state['persona_id'] = persona_id
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.get('last_user_message', '我很焦虑')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_persona_spec():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '逻辑哥哥' in payload.system_prompt
    assert '李诞' in payload.system_prompt


def test_system_prompt_contains_awareness_hint_after_opening():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '核心念头' in payload.system_prompt


def test_system_prompt_no_awareness_hint_during_opening():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=1)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '核心念头' not in payload.system_prompt


def test_system_prompt_has_no_clinical_labels():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_eval_socratic')
    for label in ('本节点目标', '本轮聚焦', '避免事项', '回复契约', '当前 CBT 节点', '治疗约束'):
        assert label not in payload.system_prompt, f'Found clinical label: {label}'


def test_user_prompt_contains_last_message():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='我压力很大')
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '我压力很大' in payload.user_prompt


def test_user_prompt_has_no_json_dump():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='测试')
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '节点触发信号' not in payload.user_prompt
    assert '节点前置条件' not in payload.user_prompt
    assert '节点退出标准' not in payload.user_prompt
    assert '严格按' not in payload.user_prompt
    assert '{' not in payload.user_prompt


def test_master_guide_persona_applied():
    executor = CBTTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'cbt_beh_activation')
    assert '主理人' in payload.system_prompt
    assert '蔡康永' in payload.system_prompt


def test_payload_metadata_preserved():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert payload.metadata['node_name']
    assert payload.metadata['category']
    assert payload.technique_id == 'cbt_cog_identify_at_basic'
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_cbt_executor.py -v 2>&1 | head -30
```

期望：多个 FAIL（`system_prompt_contains_persona_spec` 等断言失败）

- [ ] **Step 3: 重写 cbt/executor.py**

```python
# backend/moodpal/cbt/executor.py
from __future__ import annotations

from typing import Optional

from .node_registry import CBTNodeRegistry
from .state import CBTGraphState
from ..awareness_hints import get_awareness_hint
from ..context_summary import build_context_summary
from ..persona_specs import get_persona_spec
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _count_user_turns(state: CBTGraphState) -> int:
    messages = state.get('history_messages') or []
    return sum(1 for m in messages if m.get('role') == 'user')


class CBTTechniqueExecutor(TechniqueExecutor[CBTGraphState]):
    def __init__(self, registry: Optional[CBTNodeRegistry] = None):
        self.registry = registry or CBTNodeRegistry()

    def build_payload(self, state: CBTGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        persona_id = str(state.get('surface_persona_id') or state.get('persona_id') or '')
        turn_index = _count_user_turns(state)

        persona_spec = get_persona_spec(persona_id)
        awareness_hint = get_awareness_hint(technique_id, turn_index)

        system_parts = [persona_spec]
        if awareness_hint:
            system_parts.append(awareness_hint)
        system_prompt = '\n\n'.join(system_parts)

        user_prompt = build_context_summary(state)

        return ExecutionPayload(
            technique_id=technique_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            visible_reply_hint='',
            metadata={
                'node_name': node.name,
                'category': node.category,
                'book_reference': node.book_reference,
                'prompt_template_id': technique_id,
                'relevant_context_keys': (),
            },
        )
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_cbt_executor.py -v
```

期望：所有测试 PASS

- [ ] **Step 5: 确认现有 CBT 路由测试仍通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_cbt_runtime.py -v
```

期望：所有测试 PASS（路由逻辑未改动）

- [ ] **Step 6: 提交**

```bash
git add backend/moodpal/cbt/executor.py tests/test_moodpal_cbt_executor.py
git commit -m "refactor(moodpal/cbt): rewrite executor with character-first prompt structure"
```

---

## Task 5: Humanistic Executor Rewrite

**Files:**
- Modify: `backend/moodpal/humanistic/executor.py`
- Create: `tests/test_moodpal_humanistic_executor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_humanistic_executor.py
import pytest
from backend.moodpal.humanistic.executor import HumanisticTechniqueExecutor
from backend.moodpal.humanistic.state import build_humanistic_state_from_session
from types import SimpleNamespace


def _make_session(persona_id='empathy_sister'):
    return SimpleNamespace(
        id='test-session',
        usage_subject='test',
        persona_id=persona_id,
        selected_model='',
        status='active',
        metadata={},
    )


def _make_state(persona_id='empathy_sister', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    session = _make_session(persona_id)
    state = build_humanistic_state_from_session(session=session, history_messages=history)
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.get('last_user_message', '我很难受')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_empathy_sister_spec():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '共情学姐' in payload.system_prompt
    assert '旅行' in payload.system_prompt


def test_awareness_hint_injected_after_opening():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_reflect_feeling')
    assert '愤怒' in payload.system_prompt


def test_no_awareness_hint_during_opening():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=0)
    payload = executor.build_payload(state, 'hum_reflect_feeling')
    assert '愤怒' not in payload.system_prompt


def test_no_clinical_labels_in_system_prompt():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_unconditional_regard')
    for label in ('本节点目标', '工作约束', '语言约束', '当前 Humanistic 节点', '严格按'):
        assert label not in payload.system_prompt, f'Found: {label}'


def test_user_prompt_is_natural_language():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='我好累')
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '我好累' in payload.user_prompt
    assert '{' not in payload.user_prompt
    assert '节点触发信号' not in payload.user_prompt


def test_master_guide_persona_in_humanistic_executor():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '主理人' in payload.system_prompt
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_humanistic_executor.py -v 2>&1 | head -30
```

- [ ] **Step 3: 重写 humanistic/executor.py**

```python
# backend/moodpal/humanistic/executor.py
from __future__ import annotations

from typing import Optional

from .node_registry import HumanisticNodeRegistry
from .state import HumanisticGraphState
from ..awareness_hints import get_awareness_hint
from ..context_summary import build_context_summary
from ..persona_specs import get_persona_spec
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _count_user_turns(state: HumanisticGraphState) -> int:
    messages = state.get('history_messages') or []
    return sum(1 for m in messages if m.get('role') == 'user')


class HumanisticTechniqueExecutor(TechniqueExecutor[HumanisticGraphState]):
    def __init__(self, registry: Optional[HumanisticNodeRegistry] = None):
        self.registry = registry or HumanisticNodeRegistry()

    def build_payload(self, state: HumanisticGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        persona_id = str(state.get('surface_persona_id') or state.get('persona_id') or '')
        turn_index = _count_user_turns(state)

        persona_spec = get_persona_spec(persona_id)
        awareness_hint = get_awareness_hint(technique_id, turn_index)

        system_parts = [persona_spec]
        if awareness_hint:
            system_parts.append(awareness_hint)
        system_prompt = '\n\n'.join(system_parts)

        user_prompt = build_context_summary(state)

        return ExecutionPayload(
            technique_id=technique_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            visible_reply_hint='',
            metadata={
                'node_name': node.name,
                'category': node.category,
                'book_reference': node.book_reference,
                'prompt_template_id': technique_id,
                'relevant_context_keys': (),
            },
        )
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_humanistic_executor.py -v
```

- [ ] **Step 5: 确认现有人本路由测试通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_humanistic_runtime.py -v
```

- [ ] **Step 6: 提交**

```bash
git add backend/moodpal/humanistic/executor.py tests/test_moodpal_humanistic_executor.py
git commit -m "refactor(moodpal/humanistic): rewrite executor with character-first prompt structure"
```

---

## Task 6: Psychoanalysis Executor Rewrite

**Files:**
- Modify: `backend/moodpal/psychoanalysis/executor.py`
- Create: `tests/test_moodpal_psychoanalysis_executor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_moodpal_psychoanalysis_executor.py
import pytest
from backend.moodpal.psychoanalysis.executor import PsychoanalysisTechniqueExecutor
from backend.moodpal.psychoanalysis.state import build_psychoanalysis_state_from_session
from types import SimpleNamespace


def _make_session(persona_id='insight_mentor'):
    return SimpleNamespace(
        id='test-session',
        usage_subject='test',
        persona_id=persona_id,
        selected_model='',
        status='active',
        metadata={},
    )


def _make_state(persona_id='insight_mentor', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    session = _make_session(persona_id)
    state = build_psychoanalysis_state_from_session(session=session, history_messages=history)
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.get('last_user_message', '说不清楚')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_insight_mentor_spec():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '心理学前辈' in payload.system_prompt
    assert '我在想' in payload.system_prompt


def test_awareness_hint_injected_after_opening():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_association_invite')
    assert '跟住' in payload.system_prompt


def test_no_awareness_hint_during_opening():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=0)
    payload = executor.build_payload(state, 'psa_association_invite')
    assert '跟住' not in payload.system_prompt


def test_no_clinical_labels_in_system_prompt():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_pattern_linking')
    for label in ('本节点目标', '工作约束', '边界约束', '当前 Psychoanalysis 节点', '严格按', '动力学信号摘要'):
        assert label not in payload.system_prompt, f'Found: {label}'


def test_user_prompt_is_natural_language():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='每次都这样')
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '每次都这样' in payload.user_prompt
    assert '{' not in payload.user_prompt
    assert '召回的脱敏模式记忆' not in payload.user_prompt


def test_master_guide_persona_in_psychoanalysis_executor():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '主理人' in payload.system_prompt
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_psychoanalysis_executor.py -v 2>&1 | head -30
```

- [ ] **Step 3: 重写 psychoanalysis/executor.py**

```python
# backend/moodpal/psychoanalysis/executor.py
from __future__ import annotations

from typing import Optional

from .node_registry import PsychoanalysisNodeRegistry
from .state import PsychoanalysisGraphState
from ..awareness_hints import get_awareness_hint
from ..context_summary import build_context_summary
from ..persona_specs import get_persona_spec
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _count_user_turns(state: PsychoanalysisGraphState) -> int:
    messages = state.get('history_messages') or []
    return sum(1 for m in messages if m.get('role') == 'user')


class PsychoanalysisTechniqueExecutor(TechniqueExecutor[PsychoanalysisGraphState]):
    def __init__(self, registry: Optional[PsychoanalysisNodeRegistry] = None):
        self.registry = registry or PsychoanalysisNodeRegistry()

    def build_payload(self, state: PsychoanalysisGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        persona_id = str(state.get('surface_persona_id') or state.get('persona_id') or '')
        turn_index = _count_user_turns(state)

        persona_spec = get_persona_spec(persona_id)
        awareness_hint = get_awareness_hint(technique_id, turn_index)

        system_parts = [persona_spec]
        if awareness_hint:
            system_parts.append(awareness_hint)
        system_prompt = '\n\n'.join(system_parts)

        user_prompt = build_context_summary(state)

        return ExecutionPayload(
            technique_id=technique_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            visible_reply_hint='',
            metadata={
                'node_name': node.name,
                'category': node.category,
                'book_reference': node.book_reference,
                'prompt_template_id': technique_id,
                'relevant_context_keys': (),
            },
        )
```

- [ ] **Step 4: 运行确认通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_psychoanalysis_executor.py -v
```

- [ ] **Step 5: 确认现有精分路由测试通过**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/test_moodpal_psychoanalysis_runtime.py -v
```

- [ ] **Step 6: 提交**

```bash
git add backend/moodpal/psychoanalysis/executor.py tests/test_moodpal_psychoanalysis_executor.py
git commit -m "refactor(moodpal/psychoanalysis): rewrite executor with character-first prompt structure"
```

---

## Task 7: 全套测试回归确认

**Files:** 无新增，验证全量

- [ ] **Step 1: 运行完整测试套件**

```bash
cd /Users/suchong/workspace/ai_counselor && pytest tests/ -v --tb=short 2>&1 | tail -40
```

期望：所有原有测试通过，无新增失败。若有失败，根据错误信息修复后再继续。

- [ ] **Step 2: 运行 lint 和类型检查**

```bash
cd /Users/suchong/workspace/ai_counselor && ruff check backend/moodpal/persona_specs.py backend/moodpal/awareness_hints.py backend/moodpal/context_summary.py backend/moodpal/cbt/executor.py backend/moodpal/humanistic/executor.py backend/moodpal/psychoanalysis/executor.py
```

```bash
cd /Users/suchong/workspace/ai_counselor && mypy backend/moodpal/persona_specs.py backend/moodpal/awareness_hints.py backend/moodpal/context_summary.py backend/moodpal/cbt/executor.py backend/moodpal/humanistic/executor.py backend/moodpal/psychoanalysis/executor.py --ignore-missing-imports
```

期望：无 error（warning 可接受）

- [ ] **Step 3: 提交最终确认**

```bash
git add -p  # 确认无多余文件
git commit -m "test(moodpal): confirm full regression pass after character-first refactor"
```

---

## 已知排除项

以下内容明确不在本计划范围内，不需要处理：

- `node_registry` JSON 文件中 `system_instruction` 的格式改写
- `moodpal_eval` 评估沙盒的对应更新
- 角色切换 UI 变更
- 新增角色或流派
