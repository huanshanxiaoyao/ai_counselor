from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.moodpal.models import MoodPalSession
from backend.moodpal_eval.services.run_executor import EvalConversationState, append_target_turn
from backend.moodpal_eval.services.target_driver import EvalTargetSessionContext, run_target_turn


@pytest.mark.django_db
def test_target_driver_merges_runtime_state_for_logic_brother():
    session_context = EvalTargetSessionContext(
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        usage_subject='system_eval:test-run',
    )
    child_result = SimpleNamespace(
        reply_text='我们先把工作里最卡的那个场景放在这里。',
        reply_metadata={
            'engine': 'conversation',
            'track': 'free_chat',
            'technique_id': '',
            'fallback_used': False,
            'fallback_kind': '',
            'provider': 'qwen',
            'model': 'qwen-plus',
            'usage': {'prompt_tokens': 30, 'completion_tokens': 10, 'total_tokens': 40},
            'json_mode_degraded': False,
            'completion_mode': 'chat',
        },
        persist_patch={'conversation_state': {'last_hint_turn_index': -99, 'alliance_status': 'medium'}},
        used_fallback=False,
    )

    with patch('backend.moodpal.runtime.turn_driver.run_cbt_turn', return_value=child_result):
        result = run_target_turn(
            session_context=session_context,
            transcript=[],
            user_content='我最近工作压力特别大。',
        )

    assert result.assistant_message['metadata']['engine'] == 'conversation'
    assert session_context.metadata['conversation_state']['alliance_status'] == 'medium'
    assert result.target_trace[0]['assistant_engine'] == 'conversation'
    assert result.target_trace[0]['fallback_kind'] == ''
    assert result.target_trace[0]['json_mode_degraded'] is False
    assert result.transcript[-1]['content'] == '我们先把工作里最卡的那个场景放在这里。'
    assert len(result.usage_records) == 1
    assert result.usage_records[0].total_tokens == 40


@pytest.mark.django_db
def test_target_driver_handles_crisis_without_real_session_row():
    session_context = EvalTargetSessionContext(
        persona_id=MoodPalSession.Persona.MASTER_GUIDE,
        usage_subject='system_eval:test-run',
    )

    result = run_target_turn(
        session_context=session_context,
        transcript=[],
        user_content='我不想活了，感觉没必要再撑下去。',
    )

    assert result.safety_override is True
    assert result.stop_reason == 'safety_override'
    assert result.assistant_message['metadata']['engine'] == 'crisis_guard'
    assert session_context.metadata['crisis_active'] is True
    assert result.target_trace[0]['safety_override'] is True
    assert result.target_trace[0]['fallback_kind'] == 'safety_override'


@pytest.mark.django_db
def test_run_executor_appends_target_turn_and_trace():
    session_context = EvalTargetSessionContext(
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        usage_subject='system_eval:test-run',
    )
    child_result = SimpleNamespace(
        reply_text='我听见你现在已经很累了。',
        reply_metadata={
            'engine': 'conversation',
            'track': 'free_chat',
            'technique_id': '',
            'fallback_used': False,
            'fallback_kind': '',
            'provider': '',
            'model': '',
            'json_mode_degraded': False,
            'completion_mode': 'chat',
        },
        persist_patch={'conversation_state': {'last_hint_turn_index': -99, 'alliance_status': 'medium'}},
        used_fallback=False,
    )
    state = EvalConversationState(session_context=session_context)

    with patch('backend.moodpal.runtime.turn_driver.run_humanistic_turn', return_value=child_result):
        turn_result = append_target_turn(state, user_content='我今天真的很崩溃。')

    assert len(state.transcript) == 2
    assert len(state.target_trace) == 1
    assert turn_result.assistant_message['content'] == '我听见你现在已经很累了。'
    assert session_context.metadata['conversation_state']['alliance_status'] == 'medium'
