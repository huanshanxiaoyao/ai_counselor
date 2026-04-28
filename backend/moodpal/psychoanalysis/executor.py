from __future__ import annotations

import json
from typing import Optional

from .executor_prompt_config import get_prompt_template
from .node_registry import PsychoanalysisNodeRegistry
from .state import PsychoanalysisGraphState
from ..runtime.interfaces import TechniqueExecutor
from ..runtime.types import ExecutionPayload


def _persona_style(persona_id: str) -> str:
    if persona_id == 'master_guide':
        return '角色语气：像沉稳、灵活、可靠的全能主理人，用观察和假设性的方式陪用户慢慢看见重复模式。'
    if persona_id == 'insight_mentor':
        return '角色语气：像稳重、慢节奏、善于看见重复模式的心理学前辈。'
    if persona_id == 'empathy_sister':
        return '角色语气：自然、稳，但此轮保持探索式观察，而不是纯共情承接。'
    if persona_id == 'logic_brother':
        return '角色语气：自然、清晰，但此轮以探索式、假设性表达为主。'
    return '角色语气：自然、稳、不过度表演。'


def _support_directive_lines(state: PsychoanalysisGraphState) -> list[str]:
    directive = str(state.get('support_directive', '') or '').strip()
    if directive == 'repair_softened':
        return ['支撑约束：这一轮即使进入探索，也要保持修复后的低压迫和安全感。']
    if directive == 'soft_handoff':
        return ['支撑约束：这一轮先用一句柔和承接，再进入模式探索，不要显得突然深挖。']
    if directive == 'gentle_focus':
        return ['支撑约束：保持被接住的感觉，但主干要明确落在模式观察上。']
    return []


class PsychoanalysisTechniqueExecutor(TechniqueExecutor[PsychoanalysisGraphState]):
    def __init__(self, registry: Optional[PsychoanalysisNodeRegistry] = None):
        self.registry = registry or PsychoanalysisNodeRegistry()

    def build_payload(self, state: PsychoanalysisGraphState, technique_id: str) -> ExecutionPayload:
        node = self.registry.get_node(technique_id)
        template = get_prompt_template(technique_id)
        context = self._build_context(state, template.relevant_context_keys)
        dynamic_summary = self._build_dynamic_summary(state)
        pattern_summary = self._build_pattern_memory_summary(state)
        example = node.examples[0] if node.examples and template.include_example else None
        example_block = self._build_example_block(example)
        visible_reply_hint = str((example or {}).get('ai', '')).strip()

        system_prompt = '\n'.join(
            [
                _persona_style(state.get('surface_persona_id') or state.get('persona_id', '')),
                *_support_directive_lines(state),
                '工作约束：一次只推进一个分析动作，不连续深挖。',
                '语言约束：多用观察、好奇和假设性表达，避免武断解释。',
                '边界约束：不诊断，不说教，不主动追到童年或创伤根源。',
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
                '当前 Psychoanalysis 节点：' + node.name,
                '节点触发信号：' + ' / '.join(node.trigger_intent),
                '节点前置条件：' + ' / '.join(node.prerequisites),
                '节点退出标准：' + node.exit_criteria,
                '本轮相关上下文：',
                json.dumps(context, ensure_ascii=False, indent=2),
                dynamic_summary,
                pattern_summary,
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

    def _build_context(self, state: PsychoanalysisGraphState, relevant_context_keys: tuple[str, ...]) -> dict:
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

    def _build_dynamic_summary(self, state: PsychoanalysisGraphState) -> str:
        return '\n'.join(
            [
                '动力学信号摘要：',
                f'- 当前焦点：{state.get("focus_theme", "") or "未锁定"}',
                f'- 显性主题：{state.get("manifest_theme", "") or "未明确"}',
                f'- 关联开放度：{state.get("association_openness", "partial")}',
                f'- 阻抗水平：{state.get("resistance_level", "low")}',
                f'- 当前防御：{state.get("active_defense", "") or "未明确"}',
                f'- 联盟强度：{state.get("alliance_strength", "medium")}',
                f'- 关系拉扯：{state.get("relational_pull", "") or "未明确"}',
                f'- 模式候选：{state.get("repetition_theme_candidate", "") or "未明确"}',
                f'- 工作性假设：{state.get("working_hypothesis", "") or "未形成"}',
                f'- insight_score：{int(state.get("insight_score") or 0)}/10',
                f'- 当前异常标记：{self._format_exception_flags(state)}',
            ]
        )

    def _build_pattern_memory_summary(self, state: PsychoanalysisGraphState) -> str:
        recalled = list(state.get('recalled_pattern_memory') or [])
        if not recalled:
            return '召回的脱敏模式记忆：none'

        items: list[str] = []
        for entry in recalled[:3]:
            themes = ', '.join(entry.get('repetition_themes') or []) or 'none'
            defenses = ', '.join(entry.get('defense_patterns') or []) or 'none'
            pulls = ', '.join(entry.get('relational_pull') or []) or 'none'
            hypothesis = '; '.join(entry.get('working_hypotheses') or []) or 'none'
            items.append(
                f'- themes={themes}; defenses={defenses}; relational_pull={pulls}; hypotheses={hypothesis}'
            )
        return '\n'.join(['召回的脱敏模式记忆：', *items])

    def _format_exception_flags(self, state: PsychoanalysisGraphState) -> str:
        flags = []
        if state.get('alliance_rupture_detected'):
            flags.append('alliance_rupture')
        if state.get('resistance_spike_detected'):
            flags.append('resistance_spike')
        if state.get('advice_pull_detected'):
            flags.append('advice_pull')
        return ', '.join(flags) if flags else 'none'
