from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TechniquePromptTemplate:
    technique_id: str
    objective: str
    one_step_focus: str
    avoid_rules: tuple[str, ...]
    response_contract: tuple[str, ...]
    relevant_context_keys: tuple[str, ...]
    include_example: bool = True


COMMON_RESPONSE_CONTRACT = (
    '只输出一轮对用户可见的自然中文回复。',
    '一次只推进一个分析动作，不连续深挖。',
    '不暴露后台状态、节点名、schema 或状态机。',
    '所有理解都必须保持工作性假设口吻，不下诊断。',
)

PROMPT_TEMPLATES = (
    TechniquePromptTemplate(
        technique_id='psa_entry_containment',
        objective='先稳住用户的承载力，让对话重新变得可待、可说。',
        one_step_focus='只做收容与放慢节奏，不做模式解释。',
        avoid_rules=('不要急着下结论。', '不要推进童年、创伤或关系根源解释。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'association_openness', 'emotional_intensity', 'containment_needed', 'alliance_strength', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_association_invite',
        objective='帮助用户围绕刚刚浮现的一条线索继续展开材料。',
        one_step_focus='只跟住一个词、一个场景或一种熟悉感，不做整合。',
        avoid_rules=('不要同时打开多个方向。', '不要把关联展开变成盘问。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'focus_theme', 'manifest_theme', 'association_openness', 'alliance_strength', 'recalled_pattern_memory', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_defense_clarification',
        objective='温和照亮一个可能的回避动作，让用户开始看见自己的防御。',
        one_step_focus='只指出一处回避或抽离动作，不做评价。',
        avoid_rules=('不要拆穿用户。', '不要一次命名多个防御机制。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'active_defense', 'resistance_level', 'alliance_strength', 'focus_theme'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_pattern_linking',
        objective='把当前困扰和反复出现的相似模式轻轻连起来。',
        one_step_focus='只连一条线，不做完整理论。',
        avoid_rules=('不要直接追溯童年根源。', '不要把模式说成宿命。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'manifest_theme', 'repetition_theme_candidate', 'pattern_confidence', 'working_hypothesis', 'recalled_pattern_memory', 'alliance_strength', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_relational_here_now',
        objective='照亮用户在这里此刻对当前对话关系的即时反应。',
        one_step_focus='只处理此刻互动里的收紧、试探或退开，不做重型移情解释。',
        avoid_rules=('不要武断地说用户把你当成某个人。', '不要夸大当前关系反应。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'here_and_now_triggered', 'relational_pull', 'alliance_strength', 'resistance_level'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_insight_integration',
        objective='把已经浮现的几条线整合成一条轻量、可工作的理解。',
        one_step_focus='只整合一层，留下可讨论的工作性假设。',
        avoid_rules=('不要做终极解释。', '不要把理解直接变成改变任务。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'manifest_theme', 'repetition_theme_candidate', 'working_hypothesis', 'pattern_confidence', 'insight_score', 'alliance_strength', 'resistance_level', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_exception_resistance_soften',
        objective='在阻抗升高时降低探索压力，让用户重新感觉自己可以停留。',
        one_step_focus='只做减压和收回一步，不继续解释。',
        avoid_rules=('不要追问原因。', '不要把撤退理解成不配合。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'resistance_level', 'active_defense', 'association_openness', 'alliance_strength'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_exception_alliance_repair',
        objective='修复刚刚受损的关系，让用户重新感到自己被贴近地听见。',
        one_step_focus='只修复联盟，不回到原分析主线。',
        avoid_rules=('不要辩解。', '不要急着证明自己其实懂。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'alliance_rupture_detected', 'alliance_strength', 'relational_pull'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_boundary_advice_pull',
        objective='承接用户想立刻得到抓手的急切，同时守住探索式对话边界。',
        one_step_focus='只帮助收束一个最值得先看的小点，不直接下命令。',
        avoid_rules=('不要突然变成建议清单。', '不要嘲讽或否定用户想要抓手的需要。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'advice_pull_detected', 'focus_theme', 'manifest_theme', 'association_openness', 'alliance_strength'),
    ),
    TechniquePromptTemplate(
        technique_id='psa_reflective_close',
        objective='以一条可以带走的观察线索自然收束本轮对话。',
        one_step_focus='只留下一个轻量观察锚点，不布置作业。',
        avoid_rules=('不要给行动清单。', '不要做人生结论式总结。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'focus_theme', 'repetition_theme_candidate', 'working_hypothesis', 'insight_score', 'last_summary'),
    ),
)

PROMPT_TEMPLATE_BY_TECHNIQUE = {
    template.technique_id: template
    for template in PROMPT_TEMPLATES
}


def get_prompt_template(technique_id: str) -> TechniquePromptTemplate:
    try:
        return PROMPT_TEMPLATE_BY_TECHNIQUE[technique_id]
    except KeyError as exc:
        raise KeyError(f'unknown_prompt_template:{technique_id}') from exc
