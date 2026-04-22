from __future__ import annotations

from ..models import MoodPalMessage, MoodPalSession


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

    focus_lines = []
    seen = set()
    for text in user_messages:
        compact = _compact_text(text, limit=48)
        if compact and compact not in seen:
            seen.add(compact)
            focus_lines.append(compact)
        if len(focus_lines) >= 3:
            break

    latest_user = _compact_text(user_messages[-1], limit=64)
    latest_assistant = _compact_text(assistant_messages[-1], limit=64) if assistant_messages else '本次还没有形成明确的回应结论。'
    cbt_state = dict((session.metadata or {}).get('cbt_state') or {})

    lines.extend(
        [
            f"本次你主要提到了：{'；'.join(focus_lines)}",
            f"此刻最需要继续处理的点：{latest_user}",
            f"当前阶段的陪伴方向：{latest_assistant}",
            '',
        ]
    )

    if (session.metadata or {}).get('crisis_active'):
        lines.append('本次会话触发过安全干预，普通角色化对话已被中止。')

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

    lines.extend(
        [
            '',
            '建议保留到长期记忆的内容：',
            '- 你现在最在意的情绪或问题是什么',
            '- 哪个触发场景最容易让你再次卡住',
            '- 下次希望继续聊的重点',
            '',
            '你可以直接编辑这份摘要，只保留真正希望未来继续记住的部分。',
        ]
    )
    return '\n'.join(lines)
