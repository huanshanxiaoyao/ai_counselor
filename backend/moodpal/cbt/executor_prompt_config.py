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
    '优先使用短句和单问题推进，不要一次抛出多个任务。',
    '不暴露后台状态、节点名、schema 或状态机。',
)

PROMPT_TEMPLATES = (
    TechniquePromptTemplate(
        technique_id='cbt_structure_agenda_setting',
        objective='把当前对话收束到一个最值得先处理的议题，并让用户感到被跟上。',
        one_step_focus='只做议题收束与排序，不进入认知分析或建议环节。',
        avoid_rules=('不要直接给解决方案。', '不要一次扩展到多个新主题。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'mood_label', 'mood_score', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_identify_at_basic',
        objective='帮助用户抓住当时脑中最刺耳、最自动冒出来的那句话。',
        one_step_focus='只澄清自动想法，不进入证据评估。',
        avoid_rules=('不要提前纠正用户想法。', '不要直接给平衡想法。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'last_assistant_message', 'mood_label', 'mood_score', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_identify_at_telegraphic',
        objective='把用户的电报式、问句式、灾难式短念头翻译成更完整可观察的自动想法。',
        one_step_focus='只做澄清和补足，不解释对错。',
        avoid_rules=('不要长篇解释认知模型。', '不要跳到行为建议。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'thought_format', 'mood_label', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_identify_at_imagery',
        objective='帮助用户重建当时场景与脑内画面，从中抓出自动想法。',
        one_step_focus='只推进画面重现或情境具象化，不做认知重构。',
        avoid_rules=('不要追问过多细节导致负担过重。', '不要提前评估证据。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'last_assistant_message', 'thought_format', 'mood_score', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_eval_socratic',
        objective='帮助用户检视自动想法的证据、替代解释与确定性，而不是直接反驳。',
        one_step_focus='只做一轮苏格拉底式松动，不直接要求彻底想开。',
        avoid_rules=('不要说教。', '不要把结论强塞给用户。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'captured_automatic_thought', 'belief_confidence', 'last_user_message', 'alternative_explanation', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_eval_distortion',
        objective='在用户已经抓住自动想法后，帮助其看见可能存在的认知歪曲模式。',
        one_step_focus='只命名或对照一种最主要的歪曲，不展开完整教学。',
        avoid_rules=('不要一次列举多种歪曲。', '不要把命名变成评判。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'captured_automatic_thought', 'last_user_message', 'cognitive_distortion_label', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_cog_response_coping',
        objective='把前面得到的替代解释整理成更贴地、用户可带走的平衡想法或应对语句。',
        one_step_focus='只生成一个可接受、不过度乐观的平衡回应。',
        avoid_rules=('不要鸡汤化。', '不要给出明显超出用户当前接受度的安慰。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'captured_automatic_thought', 'alternative_explanation', 'balanced_response', 'belief_confidence', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_beh_activation',
        objective='在低能量和停滞状态下，帮用户找到一个几乎不需要意志力的最小起步动作。',
        one_step_focus='只把行动压缩到最小可执行单位。',
        avoid_rules=('不要布置大任务。', '不要使用命令式督促口吻。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'energy_level', 'behavioral_shutdown', 'activation_step', 'homework_candidate'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_beh_experiment',
        objective='把用户的负面预测转成一个小型、可验证的行为实验。',
        one_step_focus='只明确实验动作、时间点和观察指标。',
        avoid_rules=('不要让实验过大或高风险。', '不要把实验写成空泛建议。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'captured_automatic_thought', 'last_user_message', 'experiment_plan', 'homework_candidate', 'emotion_stability'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_beh_graded_task',
        objective='把“太难了”的任务拆成第一步，降低启动阻力。',
        one_step_focus='只锁定第一步，不追求完整计划。',
        avoid_rules=('不要一次拆出很多步。', '不要要求用户当场承诺超出能力范围的事。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'task_first_step', 'homework_candidate', 'energy_level'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_core_downward_arrow',
        objective='沿着自动想法继续下探，接近更深层的假设或核心信念。',
        one_step_focus='只往下探一层，保持关系稳定和节奏温和。',
        avoid_rules=('不要连续追问压迫用户。', '不要在情绪不稳时强行深挖。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'captured_automatic_thought', 'last_user_message', 'repeated_theme_detected', 'emotion_stability', 'alliance_strength', 'core_belief_candidate', 'intermediate_belief_candidate'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_exception_alliance_rupture',
        objective='优先修复用户被误解、被冒犯或不想继续的关系裂缝。',
        one_step_focus='只处理联盟问题，不推进原方法步骤。',
        avoid_rules=('不要为自己辩解。', '不要立即拉回原议题。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'alliance_strength', 'alliance_rupture_detected'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_exception_redirecting',
        objective='在不打断关系的前提下，把发散内容轻轻带回已锁定议题。',
        one_step_focus='先承接，再收束回当前主线。',
        avoid_rules=('不要生硬打断。', '不要否定用户新提到的话题价值。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'last_assistant_message', 'topic_drift_detected'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_exception_homework_obstacle',
        objective='把“没做/做不到”的阻抗变成可理解、可处理的信息。',
        one_step_focus='只澄清阻碍来源，不急着再次布置任务。',
        avoid_rules=('不要责备用户没完成。', '不要直接跳到更大行动。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'homework_candidate', 'task_first_step', 'homework_obstacle_detected', 'captured_automatic_thought'),
    ),
    TechniquePromptTemplate(
        technique_id='cbt_exception_yes_but',
        objective='处理“理智上知道，但情感上跟不上”的裂缝，降低用户的挫败感。',
        one_step_focus='先承认分裂感，再尝试缩小一点点差距。',
        avoid_rules=('不要重复讲道理。', '不要把用户的情绪当成不配合。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('agenda_topic', 'last_user_message', 'last_assistant_message', 'balanced_response', 'homework_candidate', 'head_heart_split_detected', 'emotion_stability'),
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
