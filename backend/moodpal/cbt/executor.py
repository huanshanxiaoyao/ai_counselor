from __future__ import annotations

from typing import Optional

from .executor_prompt_config import get_prompt_template
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


def _build_technique_section(technique_id: str) -> str:
    try:
        t = get_prompt_template(technique_id)
    except KeyError:
        return ''
    lines = [f'【本轮任务】{t.objective}', f'只做这一步：{t.one_step_focus}']
    if t.avoid_rules:
        lines.append('注意：' + ' '.join(t.avoid_rules))
    if t.response_contract:
        lines.append('回复规范：' + ' '.join(t.response_contract))
    return '\n'.join(lines)


class CBTTechniqueExecutor(TechniqueExecutor[CBTGraphState]):
    def __init__(self, registry: Optional[CBTNodeRegistry] = None):
        self.registry = registry or CBTNodeRegistry()

    def build_payload(self, state: CBTGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        persona_id = str(state.get('surface_persona_id') or state.get('persona_id') or '')
        turn_index = _count_user_turns(state)

        persona_spec = get_persona_spec(persona_id)
        technique_section = _build_technique_section(technique_id)
        awareness_hint = get_awareness_hint(technique_id, turn_index)

        system_parts = [persona_spec]
        if technique_section:
            system_parts.append(technique_section)
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
