# MoodPal 聊天优先架构重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 MoodPal 从"每轮执行心理学步骤"改造为"默认自然聊天，后台静默分析，时机成熟时注入一句轻量方向提示"。

**Architecture:** 双层解耦——分析层（规则式信号提取 + 门控判断 → `hint_text: Optional[str]`）和响应层（`persona_spec` + `history_messages` + 可选 `hint_text` → LLM 纯文本回复）。不再有 `【本轮任务】` 注入，不再有 JSON 结构化响应，不再有 technique 状态机驱动输出。

**Tech Stack:** Python 3.10+, Django, `openai` SDK, `anthropic` SDK, existing `LLMClient`

**Design doc:** `docs/superpowers/specs/2026-05-06-moodpal-chat-first-architecture-design.md`

---

## File Map

| 动作 | 文件 |
|------|------|
| Modify | `backend/llm/client.py` — 新增 `complete_with_history()` |
| Create | `backend/moodpal/runtime/conversation_executor.py` — 响应层核心 |
| Create | `backend/moodpal/hint_generator.py` — 信号→提示映射 |
| Rewrite | `backend/moodpal/services/master_guide_runtime_service.py` |
| Rewrite | `backend/moodpal/services/cbt_runtime_service.py` |
| Rewrite | `backend/moodpal/services/humanistic_runtime_service.py` |
| Rewrite | `backend/moodpal/services/psychoanalysis_runtime_service.py` |
| Delete | `backend/moodpal/master_guide/graph.py` |
| Delete | `backend/moodpal/master_guide/router.py` |
| Delete | `backend/moodpal/master_guide/route_policy.py` |
| Delete | `backend/moodpal/master_guide/summary_projection.py` |
| Delete | `backend/moodpal/cbt/executor_prompt_config.py` |
| Delete | `backend/moodpal/humanistic/executor_prompt_config.py` |
| Delete | `backend/moodpal/psychoanalysis/executor_prompt_config.py` |
| Delete | `backend/moodpal/awareness_hints.py` |

---

## Task 1: 给 `LLMClient` 加多轮对话支持

当前 `complete()` 只接受单条 `prompt: str`，内部固定为 `[system, user]` 两条消息。新增 `complete_with_history()` 接受完整的 `messages: list[dict]`，让响应层可以直接传递对话历史。

**Files:**
- Modify: `backend/llm/client.py`

- [ ] **Step 1: 在 `OpenAIBackend` 里加 `complete_with_history()`**

在 `OpenAIBackend` 类的 `complete_with_usage` 方法之后插入：

```python
def complete_with_history(
    self,
    messages: list[dict],
    system_prompt: str | None = None,
    model: str | None = None,
) -> tuple[TokenUsage, str, str]:
    all_messages: list[dict] = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt})
    all_messages.extend(messages)
    try:
        response = self._client.chat.completions.create(
            model=model or self.provider.default_model,
            messages=all_messages,
        )
    except openai.APITimeoutError as e:
        raise LLMTimeoutError(str(e)) from e
    except openai.APIConnectionError as e:
        raise LLMTimeoutError(str(e)) from e
    except openai.APIStatusError as e:
        raise LLMAPIError(str(e), status_code=e.status_code) from e
    usage = TokenUsage(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
    )
    return usage, response.choices[0].message.content, response.model
```

- [ ] **Step 2: 在 `AnthropicBackend` 里加对应方法**

在 `AnthropicBackend` 类的 `complete_with_usage` 方法之后插入：

```python
def complete_with_history(
    self,
    messages: list[dict],
    system_prompt: str | None = None,
    model: str | None = None,
) -> tuple[TokenUsage, str, str]:
    params: dict = {
        "model": model or self.provider.default_model,
        "messages": messages,
        "max_tokens": 1024,
    }
    if system_prompt:
        params["system"] = system_prompt
    try:
        response = self._client.messages.create(**params)
    except anthropic.APITimeoutError as e:
        raise LLMTimeoutError(str(e)) from e
    except anthropic.APIConnectionError as e:
        raise LLMTimeoutError(str(e)) from e
    except anthropic.APIStatusError as e:
        raise LLMAPIError(str(e), status_code=e.status_code) from e
    text_parts = [block.text for block in response.content if isinstance(block, TextBlock)]
    usage = TokenUsage(
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
    )
    return usage, "\n".join(text_parts) if text_parts else "", response.model
```

- [ ] **Step 3: 在 `LLMClient` 里加 `complete_with_history()`**

在 `LLMClient.complete_with_metadata()` 方法之后插入：

```python
def complete_with_history(
    self,
    messages: list[dict],
    system_prompt: str | None = None,
    model: str | None = None,
) -> CompletionResult:
    resolved_model = model or self.provider.default_model
    last_error: Exception | None = None
    for attempt in range(self.max_retries):
        try:
            start_time = time.time()
            usage, text, resp_model = self._client.complete_with_history(
                messages=messages,
                system_prompt=system_prompt,
                model=resolved_model,
            )
            elapsed = time.time() - start_time
            result = CompletionResult(
                text=text,
                model=resp_model or resolved_model,
                usage=usage,
                provider_name=self.provider.name,
                elapsed_seconds=round(elapsed, 3),
            )
            logger.info(
                f"LLM history call: provider={self.provider.name} model={result.model} "
                f"tokens={usage.total_tokens} ({usage.prompt_tokens}+{usage.completion_tokens}) "
                f"time={result.elapsed_seconds}s"
            )
            return result
        except LLMTimeoutError as e:
            last_error = e
            if attempt == self.max_retries - 1:
                raise
            time.sleep(2 ** attempt)
        except LLMAPIError as e:
            last_error = e
            if e.status_code in (400, 401, 403, 404):
                raise
            if attempt == self.max_retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise LLMMaxRetriesExceededError(
        f"LLM history call failed after {self.max_retries} attempts "
        f"(provider={self.provider.name}, model={resolved_model}): {last_error}"
    )
```

- [ ] **Step 4: 跑现有测试确认没有破坏**

```bash
pytest tests/ -v -x
```

期望：全部已有测试通过（新方法还没被调用，不会影响已有路径）

- [ ] **Step 5: Commit**

```bash
git add backend/llm/client.py
git commit -m "feat(llm): add complete_with_history() for multi-turn conversation support"
```

---

## Task 2: 创建 `ConversationExecutor`

响应层的核心：接收 `persona_id + hint_text + history_messages` → 组装 system prompt → 调 `LLMClient.complete_with_history()` → 返回纯文本回复。

**Files:**
- Create: `backend/moodpal/runtime/conversation_executor.py`

- [ ] **Step 1: 创建文件**

```python
# backend/moodpal/runtime/conversation_executor.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage
from ..persona_specs import get_persona_spec
from ..services.model_option_service import normalize_selected_model


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationTurnResult:
    reply_text: str
    provider: str
    model: str
    usage: dict
    used_fallback: bool = False


def execute_conversation_turn(
    *,
    persona_id: str,
    hint_text: Optional[str],
    history_messages: list[dict],
    selected_model: str,
    subject_key: str = '',
) -> ConversationTurnResult:
    system_prompt = _build_system_prompt(persona_id, hint_text)
    provider_name, model_name = _resolve_provider_and_model(selected_model)
    try:
        client = LLMClient(provider_name=provider_name)
        result = client.complete_with_history(
            messages=history_messages,
            system_prompt=system_prompt,
            model=model_name,
        )
        reply_text = result.text.strip()
        if not reply_text:
            raise ValueError('empty_reply')
        if result.usage.total_tokens > 0 and subject_key:
            record_token_usage(
                subject=parse_subject_key(subject_key),
                source='moodpal.conversation.turn',
                total_tokens=result.usage.total_tokens,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                provider=provider_name,
                model=result.model,
            )
        return ConversationTurnResult(
            reply_text=reply_text,
            provider=provider_name,
            model=result.model,
            usage={
                'prompt_tokens': result.usage.prompt_tokens,
                'completion_tokens': result.usage.completion_tokens,
                'total_tokens': result.usage.total_tokens,
            },
        )
    except Exception:
        logger.exception(
            'ConversationExecutor failed persona=%s provider=%s',
            persona_id,
            provider_name,
        )
        return ConversationTurnResult(
            reply_text='我在，可以继续说。',
            provider=provider_name,
            model=model_name or '',
            usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
            used_fallback=True,
        )


def _build_system_prompt(persona_id: str, hint_text: Optional[str]) -> str:
    parts = [get_persona_spec(persona_id)]
    if hint_text:
        parts.append(f'【背景觉察】\n{hint_text}')
    return '\n\n'.join(parts)


def _resolve_provider_and_model(selected_model: str) -> tuple[str, Optional[str]]:
    value = normalize_selected_model(selected_model)
    if ':' in value:
        provider_name, model_name = value.split(':', 1)
        provider_name = provider_name.strip() or getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
        return provider_name, model_name.strip() or None
    provider_name = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    return provider_name, value or None
```

- [ ] **Step 2: Commit**

```bash
git add backend/moodpal/runtime/conversation_executor.py
git commit -m "feat(moodpal): add ConversationExecutor for chat-first response layer"
```

---

## Task 3: 创建 `hint_generator.py`

分析层的输出端：接收信号字典 → 判断门控条件 → 返回 `Optional[str]` hint。门控不通过则返回 `None`（纯聊天）。

**Files:**
- Create: `backend/moodpal/hint_generator.py`

- [ ] **Step 1: 创建文件**

```python
# backend/moodpal/hint_generator.py
from __future__ import annotations

from typing import Optional


_MIN_TURNS = 3          # 至少 3 轮才考虑注入提示
_MIN_HINT_GAP = 2       # 上次注入提示后至少再过 2 轮才再次注入


def generate_hint(
    signals: dict,
    turn_index: int,
    last_hint_turn_index: int = -99,
) -> Optional[str]:
    if not _passes_gate(signals, turn_index, last_hint_turn_index):
        return None
    return _select_hint(signals)


def _passes_gate(signals: dict, turn_index: int, last_hint_turn_index: int) -> bool:
    if turn_index < _MIN_TURNS:
        return False
    if signals.get('repair_needed'):
        return False
    if signals.get('alliance_status') == 'weak':
        return False
    distress = signals.get('distress_level', 'low')
    clarity = signals.get('problem_clarity', 'low')
    if distress == 'high' and clarity == 'low':
        return False
    if turn_index - last_hint_turn_index < _MIN_HINT_GAP:
        return False
    return (
        signals.get('cbt_readiness', 'low') in {'medium', 'high'}
        or signals.get('psychoanalysis_readiness', 'low') in {'medium', 'high'}
        or signals.get('action_readiness', 'low') in {'medium', 'high'}
        or signals.get('pattern_signal_strength', 'low') in {'medium', 'high'}
    )


def _select_hint(signals: dict) -> Optional[str]:
    pattern = signals.get('pattern_signal_strength', 'low')
    alliance = signals.get('alliance_status', 'medium')
    action = signals.get('action_readiness', 'low')
    cbt = signals.get('cbt_readiness', 'low')
    psycho = signals.get('psychoanalysis_readiness', 'low')
    distress = signals.get('distress_level', 'low')

    if pattern in {'medium', 'high'} and alliance == 'strong':
        return '用户的一些话里有重复的影子，有机会可以轻轻点一下，不用说透。'
    if pattern in {'medium', 'high'} and psycho in {'medium', 'high'}:
        return '用户似乎在绕圈子，可以帮他轻轻找到最想说的那根线。'
    if action in {'medium', 'high'} and cbt in {'medium', 'high'}:
        return '用户好像想往前走，可以帮他把第一步压到最小。'
    if distress == 'high' and cbt in {'medium', 'high'}:
        return '用户情绪还很满，先接住，等他自己松一点再说。'
    if cbt in {'medium', 'high'}:
        return '用户好像在找一个抓手，可以帮他把问题收束到一个具体的点上。'
    if psycho in {'medium', 'high'}:
        return '用户的话里有一些反复出现的感受，可以在合适的时候温和地映照一下。'
    return None
```

- [ ] **Step 2: Commit**

```bash
git add backend/moodpal/hint_generator.py
git commit -m "feat(moodpal): add hint_generator with gating logic and hint library"
```

---

## Task 4: 重写 `master_guide_runtime_service.py`

这是最核心的改动。把"路由→三track dispatch→结构化JSON"替换为"信号提取→门控→ConversationExecutor"。`merge_master_guide_state_metadata` 简化为只处理 `conversation_state`。

**Files:**
- Rewrite: `backend/moodpal/services/master_guide_runtime_service.py`

- [ ] **Step 1: 完整替换文件内容**

```python
# backend/moodpal/services/master_guide_runtime_service.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..hint_generator import generate_hint
from ..master_guide.routing_signal_extractor import extract_master_guide_routing_signals
from ..master_guide.state import build_master_guide_state_from_session
from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MasterGuideRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_master_guide_turn(*, session, history_messages: list[dict]) -> MasterGuideRuntimeTurnResult:
    metadata = dict(session.metadata or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    state['cbt_state'] = {}
    state['humanistic_state'] = {}
    state['psychoanalysis_state'] = {}

    conv_state = dict(metadata.get('conversation_state') or {})
    last_hint_turn_index = int(conv_state.get('last_hint_turn_index') or -99)

    signals = extract_master_guide_routing_signals(state)
    turn_index = int(state.get('turn_index') or 0)
    hint_text = generate_hint(signals, turn_index=turn_index, last_hint_turn_index=last_hint_turn_index)

    logger.info(
        'MoodPal conversation turn session=%s subject=%s persona=%s turn=%s hint=%s alliance=%s distress=%s',
        session.id,
        session.usage_subject,
        session.persona_id,
        turn_index,
        bool(hint_text),
        signals.get('alliance_status'),
        signals.get('distress_level'),
    )

    result = execute_conversation_turn(
        persona_id=session.persona_id,
        hint_text=hint_text,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )

    next_last_hint = turn_index if hint_text else last_hint_turn_index
    persist_patch = {
        'conversation_state': {
            'last_hint_turn_index': next_last_hint,
            'alliance_status': signals.get('alliance_status', 'medium'),
        }
    }

    reply_metadata = {
        'engine': 'conversation',
        'track': 'free_chat',
        'technique_id': '',
        'hint_injected': bool(hint_text),
        'fallback_used': result.used_fallback,
        'fallback_kind': 'llm_local_rule' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'usage': result.usage,
        'alliance_status': signals.get('alliance_status'),
        'distress_level': signals.get('distress_level'),
        'json_mode_degraded': False,
        'completion_mode': 'chat' if not result.used_fallback else 'rule_fallback',
        'llm_error_type': '',
        'debug_system_prompt': '',
        'debug_user_prompt': '',
    }

    return MasterGuideRuntimeTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=persist_patch,
        used_fallback=result.used_fallback,
    )


def merge_master_guide_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata
    if state_patch.get('conversation_state'):
        merged = dict(next_metadata.get('conversation_state') or {})
        merged.update(state_patch['conversation_state'])
        next_metadata['conversation_state'] = merged
    return next_metadata
```

- [ ] **Step 2: 跑测试（预期部分 master_guide 相关测试会 fail，先确认其他测试不受影响）**

```bash
pytest tests/ -v -k "not master_guide" 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add backend/moodpal/services/master_guide_runtime_service.py
git commit -m "refactor(moodpal): rewrite master_guide runtime to conversation-first architecture"
```

---

## Task 5: 重写 `cbt_runtime_service.py`（LOGIC_BROTHER）

同样模式：信号提取 → hint → ConversationExecutor。保留 `merge_cbt_state_metadata` 签名以兼容 `turn_driver`，但实现简化为 merge `conversation_state`。

**Files:**
- Rewrite: `backend/moodpal/services/cbt_runtime_service.py`

- [ ] **Step 1: 完整替换文件内容**

```python
# backend/moodpal/services/cbt_runtime_service.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..hint_generator import generate_hint
from ..master_guide.routing_signal_extractor import extract_master_guide_routing_signals
from ..master_guide.state import build_master_guide_state_from_session
from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CBTRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_cbt_turn(
    *,
    session,
    history_messages: list[dict],
    state_overrides: dict | None = None,
) -> CBTRuntimeTurnResult:
    metadata = dict(session.metadata or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    state['cbt_state'] = {}
    state['humanistic_state'] = {}
    state['psychoanalysis_state'] = {}

    conv_state = dict(metadata.get('conversation_state') or {})
    last_hint_turn_index = int(conv_state.get('last_hint_turn_index') or -99)

    signals = extract_master_guide_routing_signals(state)
    turn_index = int(state.get('turn_index') or 0)

    persona_id = session.persona_id
    if isinstance(state_overrides, dict) and state_overrides.get('surface_persona_id'):
        persona_id = state_overrides['surface_persona_id']

    hint_text = generate_hint(signals, turn_index=turn_index, last_hint_turn_index=last_hint_turn_index)

    logger.info(
        'MoodPal CBT conversation turn session=%s subject=%s turn=%s hint=%s',
        session.id, session.usage_subject, turn_index, bool(hint_text),
    )

    result = execute_conversation_turn(
        persona_id=persona_id,
        hint_text=hint_text,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )

    next_last_hint = turn_index if hint_text else last_hint_turn_index
    persist_patch = {
        'conversation_state': {
            'last_hint_turn_index': next_last_hint,
            'alliance_status': signals.get('alliance_status', 'medium'),
        }
    }

    reply_metadata = {
        'engine': 'conversation',
        'track': 'free_chat',
        'technique_id': '',
        'hint_injected': bool(hint_text),
        'fallback_used': result.used_fallback,
        'fallback_kind': 'llm_local_rule' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'usage': result.usage,
        'json_mode_degraded': False,
        'completion_mode': 'chat' if not result.used_fallback else 'rule_fallback',
        'llm_error_type': '',
        'debug_system_prompt': '',
        'debug_user_prompt': '',
    }

    return CBTRuntimeTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=persist_patch,
        used_fallback=result.used_fallback,
    )


def merge_cbt_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata
    if state_patch.get('conversation_state'):
        merged = dict(next_metadata.get('conversation_state') or {})
        merged.update(state_patch['conversation_state'])
        next_metadata['conversation_state'] = merged
    return next_metadata
```

- [ ] **Step 2: Commit**

```bash
git add backend/moodpal/services/cbt_runtime_service.py
git commit -m "refactor(moodpal): rewrite CBT runtime to conversation-first architecture"
```

---

## Task 6: 重写 `humanistic_runtime_service.py`（EMPATHY_SISTER）

与 Task 5 完全同样的模式，只是返回类型名不同。

**Files:**
- Rewrite: `backend/moodpal/services/humanistic_runtime_service.py`

- [ ] **Step 1: 完整替换文件内容**

```python
# backend/moodpal/services/humanistic_runtime_service.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..hint_generator import generate_hint
from ..master_guide.routing_signal_extractor import extract_master_guide_routing_signals
from ..master_guide.state import build_master_guide_state_from_session
from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HumanisticRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_humanistic_turn(
    *,
    session,
    history_messages: list[dict],
    state_overrides: dict | None = None,
) -> HumanisticRuntimeTurnResult:
    metadata = dict(session.metadata or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    state['cbt_state'] = {}
    state['humanistic_state'] = {}
    state['psychoanalysis_state'] = {}

    conv_state = dict(metadata.get('conversation_state') or {})
    last_hint_turn_index = int(conv_state.get('last_hint_turn_index') or -99)

    signals = extract_master_guide_routing_signals(state)
    turn_index = int(state.get('turn_index') or 0)

    persona_id = session.persona_id
    if isinstance(state_overrides, dict) and state_overrides.get('surface_persona_id'):
        persona_id = state_overrides['surface_persona_id']

    hint_text = generate_hint(signals, turn_index=turn_index, last_hint_turn_index=last_hint_turn_index)

    logger.info(
        'MoodPal humanistic conversation turn session=%s subject=%s turn=%s hint=%s',
        session.id, session.usage_subject, turn_index, bool(hint_text),
    )

    result = execute_conversation_turn(
        persona_id=persona_id,
        hint_text=hint_text,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )

    next_last_hint = turn_index if hint_text else last_hint_turn_index
    persist_patch = {
        'conversation_state': {
            'last_hint_turn_index': next_last_hint,
            'alliance_status': signals.get('alliance_status', 'medium'),
        }
    }

    reply_metadata = {
        'engine': 'conversation',
        'track': 'free_chat',
        'technique_id': '',
        'hint_injected': bool(hint_text),
        'fallback_used': result.used_fallback,
        'fallback_kind': 'llm_local_rule' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'usage': result.usage,
        'json_mode_degraded': False,
        'completion_mode': 'chat' if not result.used_fallback else 'rule_fallback',
        'llm_error_type': '',
        'debug_system_prompt': '',
        'debug_user_prompt': '',
    }

    return HumanisticRuntimeTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=persist_patch,
        used_fallback=result.used_fallback,
    )


def merge_humanistic_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata
    if state_patch.get('conversation_state'):
        merged = dict(next_metadata.get('conversation_state') or {})
        merged.update(state_patch['conversation_state'])
        next_metadata['conversation_state'] = merged
    return next_metadata
```

- [ ] **Step 2: Commit**

```bash
git add backend/moodpal/services/humanistic_runtime_service.py
git commit -m "refactor(moodpal): rewrite humanistic runtime to conversation-first architecture"
```

---

## Task 7: 重写 `psychoanalysis_runtime_service.py`（INSIGHT_MENTOR）

**Files:**
- Rewrite: `backend/moodpal/services/psychoanalysis_runtime_service.py`

- [ ] **Step 1: 完整替换文件内容**

```python
# backend/moodpal/services/psychoanalysis_runtime_service.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..hint_generator import generate_hint
from ..master_guide.routing_signal_extractor import extract_master_guide_routing_signals
from ..master_guide.state import build_master_guide_state_from_session
from ..runtime.conversation_executor import execute_conversation_turn


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PsychoanalysisRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_psychoanalysis_turn(
    *,
    session,
    history_messages: list[dict],
    state_overrides: dict | None = None,
) -> PsychoanalysisRuntimeTurnResult:
    metadata = dict(session.metadata or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    state['cbt_state'] = {}
    state['humanistic_state'] = {}
    state['psychoanalysis_state'] = {}

    conv_state = dict(metadata.get('conversation_state') or {})
    last_hint_turn_index = int(conv_state.get('last_hint_turn_index') or -99)

    signals = extract_master_guide_routing_signals(state)
    turn_index = int(state.get('turn_index') or 0)

    persona_id = session.persona_id
    if isinstance(state_overrides, dict) and state_overrides.get('surface_persona_id'):
        persona_id = state_overrides['surface_persona_id']

    hint_text = generate_hint(signals, turn_index=turn_index, last_hint_turn_index=last_hint_turn_index)

    logger.info(
        'MoodPal psychoanalysis conversation turn session=%s subject=%s turn=%s hint=%s',
        session.id, session.usage_subject, turn_index, bool(hint_text),
    )

    result = execute_conversation_turn(
        persona_id=persona_id,
        hint_text=hint_text,
        history_messages=history_messages,
        selected_model=session.selected_model,
        subject_key=session.usage_subject,
    )

    next_last_hint = turn_index if hint_text else last_hint_turn_index
    persist_patch = {
        'conversation_state': {
            'last_hint_turn_index': next_last_hint,
            'alliance_status': signals.get('alliance_status', 'medium'),
        }
    }

    reply_metadata = {
        'engine': 'conversation',
        'track': 'free_chat',
        'technique_id': '',
        'hint_injected': bool(hint_text),
        'fallback_used': result.used_fallback,
        'fallback_kind': 'llm_local_rule' if result.used_fallback else '',
        'provider': result.provider,
        'model': result.model,
        'usage': result.usage,
        'json_mode_degraded': False,
        'completion_mode': 'chat' if not result.used_fallback else 'rule_fallback',
        'llm_error_type': '',
        'debug_system_prompt': '',
        'debug_user_prompt': '',
    }

    return PsychoanalysisRuntimeTurnResult(
        reply_text=result.reply_text,
        reply_metadata=reply_metadata,
        persist_patch=persist_patch,
        used_fallback=result.used_fallback,
    )


def merge_psychoanalysis_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata
    if state_patch.get('conversation_state'):
        merged = dict(next_metadata.get('conversation_state') or {})
        merged.update(state_patch['conversation_state'])
        next_metadata['conversation_state'] = merged
    return next_metadata
```

- [ ] **Step 2: Commit**

```bash
git add backend/moodpal/services/psychoanalysis_runtime_service.py
git commit -m "refactor(moodpal): rewrite psychoanalysis runtime to conversation-first architecture"
```

---

## Task 8: 修正受影响的测试

Tasks 4-7 的重写会导致依赖旧 runtime 行为的测试失败。逐一修正，不要删测试，改为匹配新行为。

**Files:**
- Modify: 所有 `tests/` 下引用旧 runtime 行为的测试文件（运行后确认哪些 fail）

- [ ] **Step 1: 找出 failing 测试**

```bash
pytest tests/ -v 2>&1 | grep -E "FAILED|ERROR"
```

- [ ] **Step 2: 针对每个 failing 测试，检查它断言的内容**

对于 mock 了旧 technique_id / engine / track 的测试：把 `assert metadata['technique_id'] == 'cbt_structure_agenda_setting'` 改成 `assert metadata['technique_id'] == ''`，`assert metadata['engine'] == 'cbt_graph'` 改成 `assert metadata['engine'] == 'conversation'`。

对于 mock 了 `run_cbt_turn` 返回旧 `CBTRuntimeTurnResult` 字段（如 `state`）的测试：更新 mock 返回值，去掉 `state` 字段，只保留 `reply_text`, `reply_metadata`, `persist_patch`, `used_fallback`。

- [ ] **Step 3: 确认所有测试通过**

```bash
pytest tests/ -v
```

期望：全部通过

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update moodpal tests to match conversation-first runtime"
```

---

## Task 9: 删除死代码

把不再调用的文件清理掉，避免未来维护者困惑。

**Files:**
- Delete: 见下方列表

- [ ] **Step 1: 删除旧 master_guide 路由文件**

```bash
git rm backend/moodpal/master_guide/graph.py \
       backend/moodpal/master_guide/router.py \
       backend/moodpal/master_guide/route_policy.py \
       backend/moodpal/master_guide/summary_projection.py
```

- [ ] **Step 2: 删除旧 executor_prompt_config 文件**

```bash
git rm backend/moodpal/cbt/executor_prompt_config.py \
       backend/moodpal/humanistic/executor_prompt_config.py \
       backend/moodpal/psychoanalysis/executor_prompt_config.py
```

- [ ] **Step 3: 删除旧 executor 文件（它们的 prompt 构建职责已被 ConversationExecutor 取代）**

```bash
git rm backend/moodpal/cbt/executor.py \
       backend/moodpal/humanistic/executor.py \
       backend/moodpal/psychoanalysis/executor.py
```

- [ ] **Step 4: 删除不再需要的辅助模块**

```bash
git rm backend/moodpal/awareness_hints.py \
       backend/moodpal/context_summary.py
```

- [ ] **Step 5: 确认删除后测试仍然全部通过**

```bash
pytest tests/ -v
```

期望：全部通过（这些文件已不再被任何测试 import）

- [ ] **Step 6: Commit**

```bash
git commit -m "chore(moodpal): remove deprecated technique routing and executor modules"
```

---

## Task 10: 手动冒烟测试

代码改完，起服务，用浏览器走一遍 4 个 persona 的对话，验证没有套路感、没有 `【本轮任务】`。

- [ ] **Step 1: 启动开发服务器**

```bash
cd backend && daphne -p 8000 backend.config.asgi:application
```

- [ ] **Step 2: 访问 MoodPal session 页面，分别测试以下 persona**

打开 `http://localhost:8000/moodpal/`，依次选择：
- 逻辑哥哥（LOGIC_BROTHER）
- 共情学姐（EMPATHY_SISTER）
- 心理学前辈（INSIGHT_MENTOR）
- 主理人（MASTER_GUIDE）

- [ ] **Step 3: 每个 persona 发 5 条以上消息，验证以下行为**

✅ 前 3 条消息：纯闲聊，回复没有任何任务式框架  
✅ 第 4 条起：部分情况下回复带有隐含方向感，但绝不出现 `【本轮任务】` 字样  
✅ 说"你根本不懂"：AI 不继续推进，先接住  
✅ 说"怎么办"：AI 顺着说，不立即变成诊断式追问  
✅ 切换话题：AI 跟上，不强拉回旧议题

- [ ] **Step 4: 检查 Django 日志确认 `hint_injected` 字段正常出现**

```bash
grep "MoodPal conversation turn" /tmp/django.log | tail -20
```

期望日志里出现 `hint=False` 和偶发 `hint=True` 的记录。

---

## 注意事项

- **Crisis 路径不受影响**：`turn_driver._apply_crisis_runtime_state` 写 `master_guide_state` / `cbt_state` 等字段，这些字段在新架构下不再被读取，但写操作本身无害，可以保留不动。
- **旧 session 兼容**：已有 session 的 `metadata` 里有 `master_guide_state` / `cbt_state` 等，新代码忽略这些字段，只读 `conversation_state`；不需要迁移脚本。
- **`session_service.py` 和前端模板不需要改动**：所有变化都在 runtime services 层。
