from __future__ import annotations

import json
from typing import Optional

from .executor_prompt_config import get_prompt_template
from .node_registry import CBTNodeRegistry
from .state import CBTGraphState
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _persona_style(persona_id: str) -> str:
    if persona_id == 'master_guide':
        return '角色语气：像沉稳、灵活、可靠的全能主理人，先接住情绪，再温和地把问题理清。'
    if persona_id == 'logic_brother':
        return '角色语气：像逻辑清晰、可靠、不说教的邻家哥哥。'
    if persona_id == 'empathy_sister':
        return '角色语气：像温柔、有边界、先接住情绪的知心学姐。'
    if persona_id == 'insight_mentor':
        return '角色语气：像稳重、善于追问模式的心理学前辈。'
    return '角色语气：自然、稳定、不过度表演。'


def _support_directive_lines(state: CBTGraphState) -> list[str]:
    directive = str(state.get('support_directive', '') or '').strip()
    if directive == 'repair_softened':
        return ['支撑约束：这一轮先放低推进力度，保持修复后的温和衔接。']
    if directive == 'soft_handoff':
        return ['支撑约束：这一轮先用一句柔和承接，再进入问题拆解，不要显得像突然换了个人。']
    if directive == 'gentle_focus':
        return ['支撑约束：保持被接住的感觉，但主干仍要清楚落在现实问题推进上。']
    return []


class CBTTechniqueExecutor(TechniqueExecutor[CBTGraphState]):
    def __init__(self, registry: Optional[CBTNodeRegistry] = None):
        self.registry = registry or CBTNodeRegistry()

    def build_payload(self, state: CBTGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        template = get_prompt_template(technique_id)
        context = self._build_context(state, template.relevant_context_keys)
        example = node.examples[0] if node.examples and template.include_example else None
        example_block = self._build_example_block(example)
        visible_reply_hint = str((example or {}).get('ai', '')).strip()

        system_prompt = '\n'.join(
            [
                _persona_style(state.get('surface_persona_id') or state.get('persona_id', '')),
                *_support_directive_lines(state),
                '治疗约束：一次只推进一步，不说教，不提前跳到下一个技术。',
                '输出要求：只输出一轮对用户可见的自然中文回复，不暴露后台状态机。',
                '本节点目标：' + template.objective,
                '本轮聚焦：' + template.one_step_focus,
                '避免事项：',
                *[f'- {item}' for item in template.avoid_rules],
                '回复契约：',
                *[f'- {item}' for item in template.response_contract],
                '',
                node.system_instruction,
            ]
        ).strip()

        user_prompt = '\n'.join(
            [
                '当前 CBT 节点：' + node.name,
                '节点触发信号：' + ' / '.join(node.trigger_intent),
                '节点前置条件：' + ' / '.join(node.prerequisites),
                '节点退出标准：' + node.exit_criteria,
                '本轮相关上下文：',
                json.dumps(context, ensure_ascii=False, indent=2),
                example_block,
                '请基于以上信息，严格按当前技术节点推进一步。',
            ]
        ).strip()

        return ExecutionPayload(
            technique_id=technique_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            visible_reply_hint=visible_reply_hint,
            metadata={
                'node_name': node.name,
                'category': node.category,
                'book_reference': node.book_reference,
                'prompt_template_id': template.technique_id,
                'relevant_context_keys': template.relevant_context_keys,
            },
        )

    def _build_context(self, state: CBTGraphState, relevant_context_keys: tuple[str, ...]) -> dict:
        return {
            key: state.get(key)
            for key in relevant_context_keys
        }

    def _build_example_block(self, example: dict | None) -> str:
        if not example:
            return ''
        return '\n'.join(
            [
                '参考风格示例：',
                '用户：' + str(example.get('user', '')).strip(),
                '助手：' + str(example.get('ai', '')).strip(),
            ]
        )
