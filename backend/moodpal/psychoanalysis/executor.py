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
