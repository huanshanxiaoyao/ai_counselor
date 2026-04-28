from __future__ import annotations

from ..models import MoodPalMessage, MoodPalSession


PSYCHOANALYSIS_THEME_LABELS = {
    'authority_tension': '在被评价或面对权威时，你更容易先收紧自己',
    'self_blame_under_relationship_stress': '一感觉关系紧张，你更容易先把问题收到自己身上',
    'hiding_to_avoid_evaluation': '一感觉自己会被看见或被评价，你更容易往后缩',
    'rejection_alarm': '一感到可能被冷落或否定，你会很快警觉起来',
    'repetition_pattern_present': '某类相似情境会反复触发旧的紧张反应',
}

PSYCHOANALYSIS_DEFENSE_LABELS = {
    'intellectualization': '更容易先讲道理，把自己和感受拉开一点',
    'minimization': '更容易先把自己的受影响程度压小',
    'topic_shift': '一靠近难受处就会更想把话题转开',
    'withdrawal': '一感觉压力上来就会更想先把自己收回去',
}

PSYCHOANALYSIS_RELATIONAL_PULL_LABELS = {
    'approval_seeking': '更在意自己有没有被认可、被肯定',
    'testing_authority': '会先试探对方是不是在判断你、是不是值得信任',
    'withdrawing': '一觉得不安全就更容易退开',
    'dependency_pull': '焦虑升高时会更想立刻得到明确答案',
}


def _compact_text(value: str, limit: int = 42) -> str:
    text = ' '.join((value or '').split())
    if len(text) <= limit:
        return text
    return f'{text[:limit].rstrip()}...'


def _close_reason_text(reason: str) -> str:
    if reason == MoodPalSession.CloseReason.USER_ENDED:
        return '你主动结束了这次会话。'
    if reason == MoodPalSession.CloseReason.IDLE_TIMEOUT:
        return '你超过 30 分钟未继续回复，系统自动结束了会话。'
    return '本次会话已经结束。'


def _format_experiment_plan(plan: dict) -> str:
    if not isinstance(plan, dict):
        return ''
    action = str(plan.get('action') or '').strip()
    timepoint = str(plan.get('timepoint') or '').strip()
    metric = str(plan.get('metric') or '').strip()
    parts = [part for part in [action, timepoint, metric] if part]
    return '；'.join(parts)


def _build_focus_lines(user_messages: list[str]) -> list[str]:
    focus_lines = []
    seen = set()
    for text in user_messages:
        compact = _compact_text(text, limit=48)
        if compact and compact not in seen:
            seen.add(compact)
            focus_lines.append(compact)
        if len(focus_lines) >= 3:
            break
    return focus_lines


def _common_footer_lines(*, persona_id: str) -> list[str]:
    if persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        return [
            '',
            '建议保留到长期记忆的内容：',
            '- 哪种支持方式对你更有帮助',
            '- 这次开始清楚的现实卡点或重复模式',
            '- 下次最想继续推进的方向',
            '',
            '你可以直接编辑这份摘要，只保留真正希望未来继续记住的部分。',
        ]
    if persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        return [
            '',
            '建议保留到长期记忆的内容：',
            '- 哪类相似情境会反复触发你',
            '- 你更容易出现的保护动作或关系反应',
            '- 下次最想继续跟住的那条线索',
            '',
            '你可以直接编辑这份摘要，只保留真正希望未来继续记住的部分。',
        ]
    if persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        return [
            '',
            '建议保留到长期记忆的内容：',
            '- 哪些情绪最容易一下子把你淹没',
            '- 你最希望被怎样理解、被怎样接住',
            '- 下次还想继续说的那一点是什么',
            '',
            '你可以直接编辑这份摘要，只保留真正希望未来继续记住的部分。',
        ]
    return [
        '',
        '建议保留到长期记忆的内容：',
        '- 你现在最在意的情绪或问题是什么',
        '- 哪个触发场景最容易让你再次卡住',
        '- 下次希望继续聊的重点',
        '',
        '你可以直接编辑这份摘要，只保留真正希望未来继续记住的部分。',
    ]


def _build_cbt_summary_lines(metadata: dict) -> list[str]:
    lines: list[str] = []
    cbt_state = dict(metadata.get('cbt_state') or {})

    if (cbt_state.get('agenda_topic') or '').strip():
        lines.append(f"本次锁定的议题：{cbt_state.get('agenda_topic', '').strip()}")

    if (cbt_state.get('balanced_response') or '').strip():
        lines.append(f"当前形成的平衡想法：{cbt_state.get('balanced_response', '').strip()}")

    if (cbt_state.get('activation_step') or '').strip():
        lines.append(f"行为激活起步动作：{cbt_state.get('activation_step', '').strip()}")

    if (cbt_state.get('homework_candidate') or '').strip():
        lines.append(f"建议带走的微行动：{cbt_state.get('homework_candidate', '').strip()}")

    if (cbt_state.get('task_first_step') or '').strip():
        lines.append(f"拆出来的第一步行动：{cbt_state.get('task_first_step', '').strip()}")

    experiment_plan_text = _format_experiment_plan(cbt_state.get('experiment_plan') or {})
    if experiment_plan_text:
        lines.append(f"可继续验证的行为实验：{experiment_plan_text}")

    if (cbt_state.get('core_belief_candidate') or '').strip():
        lines.append(f"可能触及的底层信念：{cbt_state.get('core_belief_candidate', '').strip()}")
    elif (cbt_state.get('intermediate_belief_candidate') or '').strip():
        lines.append(f"可能触及的中间信念：{cbt_state.get('intermediate_belief_candidate', '').strip()}")
    return lines


def _build_psychoanalysis_summary_lines(metadata: dict, *, latest_user: str, latest_assistant: str) -> list[str]:
    lines: list[str] = []
    state = dict(metadata.get('psychoanalysis_state') or {})

    focus_theme = str(state.get('focus_theme') or state.get('manifest_theme') or '').strip()
    if focus_theme:
        lines.append(f"这次最值得继续跟住的一条线索：{focus_theme}")
    else:
        lines.append(f"这次最值得继续跟住的一条线索：{latest_user}")

    repetition_theme = str(state.get('repetition_theme_candidate') or '').strip()
    repetition_line = PSYCHOANALYSIS_THEME_LABELS.get(repetition_theme, '')
    if repetition_line:
        lines.append(f"当前浮现的重复模式线索：{repetition_line}")

    defense = str(state.get('active_defense') or '').strip()
    defense_line = PSYCHOANALYSIS_DEFENSE_LABELS.get(defense, '')
    if defense_line:
        lines.append(f"对话里出现的一种保护动作：{defense_line}")

    relational_pull = str(state.get('relational_pull') or '').strip()
    relational_line = PSYCHOANALYSIS_RELATIONAL_PULL_LABELS.get(relational_pull, '')
    if relational_line:
        lines.append(f"关系里更容易出现的反应：{relational_line}")

    working_hypothesis = str(state.get('working_hypothesis') or '').strip()
    if working_hypothesis:
        lines.append(f"当前形成的一种工作性理解：{working_hypothesis}")
    else:
        lines.append(f"当前阶段的陪伴方向：{latest_assistant}")

    return lines


def _build_humanistic_summary_lines(metadata: dict, *, latest_user: str, latest_assistant: str) -> list[str]:
    lines: list[str] = []
    state = dict(metadata.get('humanistic_state') or {})

    dominant_emotions = [str(item).strip() for item in (state.get('dominant_emotions') or []) if str(item).strip()]
    if dominant_emotions:
        lines.append(f"这次更清楚被看见的情绪：{'、'.join(dominant_emotions)}")

    felt_sense_description = str(state.get('felt_sense_description') or '').strip()
    if felt_sense_description:
        lines.append(f"身体或感受层面冒出来的线索：{felt_sense_description}")

    unmet_need_candidate = str(state.get('unmet_need_candidate') or '').strip()
    if unmet_need_candidate:
        lines.append(f"这份情绪背后更在意的需要：{unmet_need_candidate}")

    self_compassion_shift = str(state.get('self_compassion_shift') or '').strip()
    if self_compassion_shift:
        lines.append(f"这次慢慢长出来的一点自我允许：{self_compassion_shift}")

    if not lines:
        lines.append(f"这次最想被接住的一部分：{latest_user}")
        lines.append(f"当前阶段的陪伴方向：{latest_assistant}")
    elif not self_compassion_shift:
        lines.append(f"当前阶段的陪伴方向：{latest_assistant}")

    return lines


def _build_master_guide_summary_lines(metadata: dict, *, latest_user: str, latest_assistant: str) -> list[str]:
    lines: list[str] = []
    master_state = dict(metadata.get('master_guide_state') or {})
    summary_hints = [str(item).strip() for item in (master_state.get('summary_hints') or []) if str(item).strip()]
    active_main_track = str(master_state.get('active_main_track') or '').strip()
    used_cbt = bool(master_state.get('used_cbt'))
    used_psychoanalysis = bool(master_state.get('used_psychoanalysis'))

    if summary_hints:
        lines.append(f"这次支持方式的推进：{'；'.join(summary_hints[:3])}")

    if active_main_track == 'cbt':
        lines.append('当前更适合继续的方向：先把现实里的问题拆清楚，再看最小可行的一步。')
    elif active_main_track == 'psychoanalysis':
        lines.append('当前更适合继续的方向：沿着已经浮现的重复模式，再稳一点往下看。')
    elif used_cbt and not used_psychoanalysis:
        lines.append('当前更适合继续的方向：继续用更清楚的现实问题拆解往前推。')
    elif used_psychoanalysis and not used_cbt:
        lines.append('当前更适合继续的方向：继续沿着重复模式和触发线索慢慢看清。')

    if used_cbt:
        cbt_lines = _build_cbt_summary_lines(metadata)
        if cbt_lines:
            lines.append(cbt_lines[0])
    if used_psychoanalysis:
        psychoanalysis_lines = _build_psychoanalysis_summary_lines(
            metadata,
            latest_user=latest_user,
            latest_assistant=latest_assistant,
        )
        if psychoanalysis_lines:
            lines.append(psychoanalysis_lines[0])
    if not lines:
        lines.append(f"这次最值得继续跟住的一点：{latest_user}")
        lines.append(f"当前阶段的陪伴方向：{latest_assistant}")
    return lines


def build_summary_draft(session: MoodPalSession) -> str:
    messages = list(session.messages.order_by('created_at', 'id'))
    user_messages = [item.content.strip() for item in messages if item.role == MoodPalMessage.Role.USER and item.content.strip()]
    assistant_messages = [
        item.content.strip()
        for item in messages
        if item.role == MoodPalMessage.Role.ASSISTANT and item.content.strip()
    ]

    lines = [
        f"角色：{session.get_persona_id_display()}",
        _close_reason_text(session.close_reason),
        '',
    ]

    if not user_messages:
        lines.extend(
            [
                '本次会话没有形成实质对话，暂时没有可留存的长期记忆。',
                '如果你下次想继续，可以从当前最困扰你的情绪、触发事件或担心的后果开始说起。',
                '',
                '你可以直接编辑这份摘要，只保留愿意留给下一次会话的内容。',
            ]
        )
        return '\n'.join(lines)

    focus_lines = _build_focus_lines(user_messages)

    latest_user = _compact_text(user_messages[-1], limit=64)
    latest_assistant = _compact_text(assistant_messages[-1], limit=64) if assistant_messages else '本次还没有形成明确的回应结论。'
    metadata = dict(session.metadata or {})

    lines.extend(
        [
            f"本次你主要提到了：{'；'.join(focus_lines)}",
            f"此刻最需要继续处理的点：{latest_user}",
            f"当前阶段的陪伴方向：{latest_assistant}",
            '',
        ]
    )

    if metadata.get('crisis_active'):
        lines.append('本次会话触发过安全干预，普通角色化对话已被中止。')

    if session.persona_id == MoodPalSession.Persona.MASTER_GUIDE:
        lines.extend(
            _build_master_guide_summary_lines(
                metadata,
                latest_user=latest_user,
                latest_assistant=latest_assistant,
            )
        )
    elif session.persona_id == MoodPalSession.Persona.LOGIC_BROTHER:
        lines.extend(_build_cbt_summary_lines(metadata))
    elif session.persona_id == MoodPalSession.Persona.EMPATHY_SISTER:
        lines.extend(
            _build_humanistic_summary_lines(
                metadata,
                latest_user=latest_user,
                latest_assistant=latest_assistant,
            )
        )
    elif session.persona_id == MoodPalSession.Persona.INSIGHT_MENTOR:
        lines.extend(
            _build_psychoanalysis_summary_lines(
                metadata,
                latest_user=latest_user,
                latest_assistant=latest_assistant,
            )
        )

    lines.extend(_common_footer_lines(persona_id=session.persona_id))
    return '\n'.join(lines)
