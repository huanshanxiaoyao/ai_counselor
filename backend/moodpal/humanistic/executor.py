from __future__ import annotations

import json
from typing import Optional

from .executor_prompt_config import get_prompt_template
from .node_registry import HumanisticNodeRegistry
from .state import HumanisticGraphState
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _persona_style(persona_id: str) -> str:
    if persona_id == 'empathy_sister':
        return '角色语气：像温暖、稳、慢节奏、有边界感的知心学姐。'
    if persona_id == 'logic_brother':
        return '角色语气：自然、稳定，但此轮仍以人本主义承接为主。'
    if persona_id == 'insight_mentor':
        return '角色语气：自然、稳重，但此轮避免深挖式追问。'
    return '角色语气：自然、温和、不过度表演。'


class HumanisticTechniqueExecutor(TechniqueExecutor[HumanisticGraphState]):
    def __init__(self, registry: Optional[HumanisticNodeRegistry] = None):
        self.registry = registry or HumanisticNodeRegistry()

    def build_payload(self, state: HumanisticGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        template = get_prompt_template(technique_id)
        context = self._build_context(state, template.relevant_context_keys)
        signal_summary = self._build_signal_summary(state)
        example = node.examples[0] if node.examples and template.include_example else None
        example_block = self._build_example_block(example)
        visible_reply_hint = str((example or {}).get('ai', '')).strip()

        system_prompt = '\n'.join(
            [
                _persona_style(state.get('persona_id', '')),
                '工作约束：一次只推进一个关系动作，不说教，不诊断，不提前切到别的技术。',
                '语言约束：尽量避免“为什么”，多用陪伴式、低压迫、可停顿的表达。',
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
                '当前 Humanistic 节点：' + node.name,
                '节点触发信号：' + ' / '.join(node.trigger_intent),
                '节点前置条件：' + ' / '.join(node.prerequisites),
                '节点退出标准：' + node.exit_criteria,
                '本轮相关上下文：',
                json.dumps(context, ensure_ascii=False, indent=2),
                signal_summary,
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

    def _build_context(self, state: HumanisticGraphState, relevant_context_keys: tuple[str, ...]) -> dict:
        return {key: state.get(key) for key in relevant_context_keys}

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

    def _build_signal_summary(self, state: HumanisticGraphState) -> str:
        emotions = ' / '.join(state.get('dominant_emotions') or []) or '未明确'
        exception_flags = []
        if state.get('alliance_rupture_detected'):
            exception_flags.append('alliance_rupture')
        if state.get('numbness_detected'):
            exception_flags.append('numbness')
        if state.get('advice_pull_detected'):
            exception_flags.append('advice_pull')
        flags_text = ', '.join(exception_flags) if exception_flags else 'none'
        return '\n'.join(
            [
                '状态信号摘要：',
                f'- 情绪强度：{int(state.get("emotional_intensity") or 0)}/10',
                f'- 主情绪：{emotions}',
                f'- 情绪清晰度：{state.get("emotional_clarity", "diffuse")}',
                f'- 开放程度：{state.get("openness_level", "partial")}',
                f'- 关系信任：{state.get("relational_trust", "medium")}',
                f'- 当前异常标记：{flags_text}',
                f'- 被理解信号：{bool(state.get("being_understood_signal"))}',
                f'- 未满足需要候选：{state.get("unmet_need_candidate", "") or "未明确"}',
            ]
        )
