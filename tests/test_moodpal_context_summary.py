import pytest
from backend.moodpal.context_summary import build_context_summary


def test_returns_string_for_empty_state():
    result = build_context_summary({})
    assert isinstance(result, str)


def test_includes_last_user_message():
    state = {'last_user_message': '我今天很累'}
    result = build_context_summary(state)
    assert '我今天很累' in result


def test_includes_agenda_topic_when_present():
    state = {'agenda_topic': '工作压力', 'last_user_message': '怎么办'}
    result = build_context_summary(state)
    assert '工作压力' in result


def test_includes_mood_label_when_present():
    state = {'mood_label': '焦虑', 'mood_score': 7, 'last_user_message': '睡不着'}
    result = build_context_summary(state)
    assert '焦虑' in result


def test_includes_last_assistant_message_truncated():
    long_reply = '这是一段很长的' + '回复' * 60
    state = {'last_assistant_message': long_reply, 'last_user_message': '然后呢'}
    result = build_context_summary(state)
    assert '…' in result
    assert len(result) < len(long_reply) + 50


def test_includes_session_summary_dict():
    state = {
        'last_summary': {'summary_text': '用户聊到了工作上的瓶颈'},
        'last_user_message': '对',
    }
    result = build_context_summary(state)
    assert '工作上的瓶颈' in result


def test_includes_session_summary_string():
    state = {
        'last_summary': '上次聊到了家庭关系',
        'last_user_message': '嗯',
    }
    result = build_context_summary(state)
    assert '家庭关系' in result


def test_no_json_in_output():
    state = {
        'last_user_message': '我很难受',
        'agenda_topic': '工作',
        'mood_label': '抑郁',
        'mood_score': 8,
        'captured_automatic_thought': '我是废物',
        'belief_confidence': None,
    }
    result = build_context_summary(state)
    assert '{' not in result
    assert 'null' not in result
    assert 'None' not in result


def test_falls_back_to_focus_theme_when_no_agenda():
    state = {'focus_theme': '被忽视的感觉', 'last_user_message': '就是这样'}
    result = build_context_summary(state)
    assert '被忽视的感觉' in result


def test_dominant_emotions_used_when_no_mood_label():
    state = {
        'dominant_emotions': ['委屈', '愤怒'],
        'emotional_intensity': 8,
        'last_user_message': '我说不清楚',
    }
    result = build_context_summary(state)
    assert '委屈' in result or '愤怒' in result
