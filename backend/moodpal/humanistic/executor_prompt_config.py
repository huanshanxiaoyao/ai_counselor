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
    '优先使用短句、慢节奏和单问题推进。',
    '不暴露后台状态、节点名、schema 或状态机。',
)

PROMPT_TEMPLATES = (
    TechniquePromptTemplate(
        technique_id='hum_validate_normalize',
        objective='先把用户接住，降低羞耻或情绪洪流的失控感。',
        one_step_focus='只做合法化与承接，不给建议。',
        avoid_rules=('不要分析原因。', '不要急着问很多问题。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'emotional_intensity', 'dominant_emotions', 'shame_signal', 'openness_level', 'last_summary'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_reflect_feeling',
        objective='帮助用户从事件叙述转向更贴近当下的情绪体验。',
        one_step_focus='只命中一层更深的情绪，不抢着总结。',
        avoid_rules=('不要复述过多故事细节。', '不要一次命名很多情绪。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'emotional_intensity', 'dominant_emotions', 'emotional_clarity', 'being_understood_signal', 'relational_trust', 'unmet_need_candidate'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_body_focus',
        objective='帮助用户从麻团般的难受感里抓住一点可感的身体线索。',
        one_step_focus='只邀请用户停留在一个微小的身体感受上。',
        avoid_rules=('不要做深度解释。', '不要把身体感觉说成病理。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'emotional_intensity', 'body_signal_present', 'body_focus_ready', 'felt_sense_description', 'emotional_clarity'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_unconditional_regard',
        objective='在用户强烈自我攻击时，提供稳定、非反驳式的接纳。',
        one_step_focus='只站到用户这边，不争论对错。',
        avoid_rules=('不要列优点反驳。', '不要讲道理说用户没那么糟。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'emotional_intensity', 'self_attack_flag', 'dominant_emotions', 'relational_trust', 'self_compassion_shift'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_exception_alliance_repair',
        objective='优先修复用户对 AI 的不信任或被误解感。',
        one_step_focus='只承认偏差并邀请纠正，不回原话题。',
        avoid_rules=('不要自我辩解。', '不要马上证明你其实懂。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'last_assistant_message', 'openness_level', 'relational_trust', 'alliance_rupture_detected'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_exception_numbness_unfreeze',
        objective='帮助用户从情感麻木或空白里松动出一点点感觉。',
        one_step_focus='只抓一丝可感线索，不逼着命名完整情绪。',
        avoid_rules=('不要追问原因。', '不要催用户立刻说清。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'emotional_intensity', 'numbness_detected', 'body_signal_present', 'felt_sense_description', 'openness_level'),
    ),
    TechniquePromptTemplate(
        technique_id='hum_boundary_advice_pull',
        objective='承接用户想立刻获得抓手的急切，同时守住非命令式边界。',
        one_step_focus='只把问题收束到一个最想先处理的小点。',
        avoid_rules=('不要直接下命令。', '不要把对话强拉回纯共情循环。'),
        response_contract=COMMON_RESPONSE_CONTRACT,
        relevant_context_keys=('last_user_message', 'emotional_intensity', 'advice_pull_detected', 'openness_level', 'relational_trust', 'unmet_need_candidate', 'homework_candidate'),
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
