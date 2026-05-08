from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.moodpal.services.spirit_companion_runtime_service import (
    SpiritCompanionTurnResult,
    run_spirit_companion_turn,
)

_MODULE = 'backend.moodpal.services.spirit_companion_runtime_service'


def _make_session(**kwargs):
    defaults = dict(
        id=1,
        persona_id='spirit_companion',
        selected_model='qwen-max',
        usage_subject='test_subject',
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_executor_result(*, reply_text='橘来了', used_fallback=False, provider='qwen', model='qwen-max'):
    return SimpleNamespace(
        reply_text=reply_text,
        used_fallback=used_fallback,
        provider=provider,
        model=model,
    )


def test_run_spirit_companion_turn_calls_executor_with_session_kwargs():
    session = _make_session()
    history = [{'role': 'user', 'content': '嗨'}]
    mock_result = _make_executor_result()

    with patch(f'{_MODULE}.execute_conversation_turn', return_value=mock_result) as mock_exec:
        run_spirit_companion_turn(session=session, history_messages=history)

    mock_exec.assert_called_once_with(
        persona_id='spirit_companion',
        hint_text=None,
        history_messages=history,
        selected_model='qwen-max',
        subject_key='test_subject',
    )


def test_run_spirit_companion_turn_persist_patch_is_always_none():
    session = _make_session()
    mock_result = _make_executor_result()

    with patch(f'{_MODULE}.execute_conversation_turn', return_value=mock_result):
        result = run_spirit_companion_turn(session=session, history_messages=[])

    assert result.persist_patch is None


def test_run_spirit_companion_turn_fallback_kind_when_used():
    session = _make_session()
    mock_result = _make_executor_result(used_fallback=True)

    with patch(f'{_MODULE}.execute_conversation_turn', return_value=mock_result):
        result = run_spirit_companion_turn(session=session, history_messages=[])

    assert result.reply_metadata['fallback_used'] is True
    assert result.reply_metadata['fallback_kind'] == 'system_fallback'


def test_run_spirit_companion_turn_fallback_kind_when_not_used():
    session = _make_session()
    mock_result = _make_executor_result(used_fallback=False)

    with patch(f'{_MODULE}.execute_conversation_turn', return_value=mock_result):
        result = run_spirit_companion_turn(session=session, history_messages=[])

    assert result.reply_metadata['fallback_used'] is False
    assert result.reply_metadata['fallback_kind'] == ''


def test_run_spirit_companion_turn_reply_metadata_shape():
    session = _make_session()
    mock_result = _make_executor_result(reply_text='喵', provider='anthropic', model='claude-3')

    with patch(f'{_MODULE}.execute_conversation_turn', return_value=mock_result):
        result = run_spirit_companion_turn(session=session, history_messages=[])

    assert isinstance(result, SpiritCompanionTurnResult)
    assert result.reply_text == '喵'
    assert result.reply_metadata['engine'] == 'spirit_companion'
    assert result.reply_metadata['provider'] == 'anthropic'
    assert result.reply_metadata['model'] == 'claude-3'
    assert result.reply_metadata['json_mode_degraded'] is False
    assert result.reply_metadata['completion_mode'] == 'chat'
