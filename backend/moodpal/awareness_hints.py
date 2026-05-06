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
