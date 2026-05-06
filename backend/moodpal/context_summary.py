from __future__ import annotations


def build_context_summary(state: dict) -> str:
    parts: list[str] = []

    topic = (
        str(state.get('agenda_topic') or '')
        or str(state.get('focus_theme') or '')
        or str(state.get('manifest_theme') or '')
    ).strip()
    if topic:
        parts.append(f'当前话题：{topic}')

    mood_label = str(state.get('mood_label') or '').strip()
    if not mood_label:
        dominant = state.get('dominant_emotions')
        if isinstance(dominant, list) and dominant:
            mood_label = ' / '.join(str(e) for e in dominant)
        elif isinstance(dominant, str):
            mood_label = dominant.strip()

    if mood_label:
        score = state.get('mood_score') or state.get('emotional_intensity')
        emotion_part = f'情绪状态：{mood_label}'
        if score is not None:
            emotion_part += f'（{score}）'
        parts.append(emotion_part)

    last_summary = state.get('last_summary')
    if isinstance(last_summary, dict):
        summary_text = str(
            last_summary.get('summary_text') or last_summary.get('text') or ''
        ).strip()
        if summary_text:
            parts.append(f'会话摘要：{summary_text}')
    elif isinstance(last_summary, str) and last_summary.strip():
        parts.append(f'会话摘要：{last_summary.strip()}')

    last_assistant = str(state.get('last_assistant_message') or '').strip()
    if last_assistant:
        truncated = last_assistant[:100] + ('…' if len(last_assistant) > 100 else '')
        parts.append(f'上一轮回复：{truncated}')

    last_user = str(state.get('last_user_message') or '').strip()
    if last_user:
        parts.append(f'\n用户：{last_user}')

    return '\n'.join(filter(None, parts))
