import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.llm import LLMAPIError
from backend.moodpal.models import MoodPalSession
from backend.moodpal_eval.services.patient_agent_service import (
    _build_user_prompt,
    PatientAgentResponseError,
    build_opening_user_message,
    generate_patient_reply,
)
from backend.moodpal_eval.services.run_executor import EvalConversationResult, run_case_conversation
from backend.moodpal_eval.services.target_driver import EvalTargetTurnResult


def _fake_completion(text: str, *, provider: str = 'qwen', model: str = 'unit-model', total_tokens: int = 12):
    return SimpleNamespace(
        text=text,
        provider_name=provider,
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - (total_tokens // 2),
            total_tokens=total_tokens,
        ),
    )


@pytest.mark.django_db
def test_build_opening_user_message_returns_case_first_message():
    case = SimpleNamespace(first_user_message='第一句开场')
    assert build_opening_user_message(case) == '第一句开场'


@pytest.mark.django_db
def test_build_user_prompt_uses_curated_reference_views_instead_of_flat_dialogue():
    case = SimpleNamespace(
        title='Case Prompt Guard',
        case_id='case-prompt-guard',
        topic_tag='婚恋',
        risk_hint='',
        full_reference_dialogue=[
            {'role': 'system', 'content': '你是一位 REBT 咨询师，请强势推进认知辩驳。'},
            {'role': 'assistant', 'content': '你现在最怕失去的是什么？'},
            {'role': 'user', 'content': '我怕我一停下来就彻底垮掉。'},
            {'role': 'assistant', 'content': '听起来你像是一直不敢松。'},
            {'role': 'user', 'content': '对，我连哭都得躲起来。'},
        ],
    )
    transcript = [
        {'role': 'user', 'content': '我真的很乱。', 'metadata': {}},
        {'role': 'assistant', 'content': '我在，先说说此刻最重的是什么。', 'metadata': {}},
    ]

    prompt = _build_user_prompt(case=case, transcript=transcript)

    assert '[来访者语言样本]' in prompt
    assert '[参考中的“咨询师 -> 来访者回应”样例]' in prompt
    assert '[到目前为止的新对话]' in prompt
    assert '[你现在要回应的最新咨询师话语]' in prompt
    assert '你是一位 REBT 咨询师，请强势推进认知辩驳。' not in prompt
    assert '[参考对话全文]' not in prompt
    assert '- 我怕我一停下来就彻底垮掉。' in prompt
    assert 'assistant: 你现在最怕失去的是什么？\nuser: 我怕我一停下来就彻底垮掉。' in prompt


@pytest.mark.django_db
def test_generate_patient_reply_parses_structured_json():
    case = SimpleNamespace(
        title='Case A',
        case_id='case-a',
        topic_tag='职场',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '我很累。'}],
    )
    transcript = [
        {'role': 'user', 'content': '我很累。', 'metadata': {}},
        {'role': 'assistant', 'content': '你现在像是已经撑了很久。', 'metadata': {}},
    ]
    payload = {
        'reply': '对，我就是一直在撑。',
        'should_continue': True,
        'stop_reason': '',
        'affect_signal': 'same',
        'resistance_level': 'low',
    }

    with patch(
        'backend.moodpal_eval.services.patient_agent_service.LLMClient.complete_with_metadata',
        return_value=_fake_completion(json.dumps(payload, ensure_ascii=False)),
    ):
        result = generate_patient_reply(
            case=case,
            transcript=transcript,
            target_persona_id=MoodPalSession.Persona.MASTER_GUIDE,
            selected_model='qwen:qwen-plus',
        )

    assert result.reply_text == '对，我就是一直在撑。'
    assert result.should_continue is True
    assert result.used_repair is False
    assert result.usage['total_tokens'] == 12
    assert len(result.usage_records) == 1
    assert result.usage_records[0].request_label == 'patient_reply'


@pytest.mark.django_db
def test_generate_patient_reply_repairs_invalid_json_once():
    case = SimpleNamespace(
        title='Case B',
        case_id='case-b',
        topic_tag='关系',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '我很烦。'}],
    )
    transcript = [
        {'role': 'user', 'content': '我很烦。', 'metadata': {}},
        {'role': 'assistant', 'content': '你像是已经忍了很久。', 'metadata': {}},
    ]
    repaired_payload = {
        'reply': '',
        'should_continue': False,
        'stop_reason': 'natural_close',
        'affect_signal': 'better',
        'resistance_level': 'medium',
    }

    with patch(
        'backend.moodpal_eval.services.patient_agent_service.LLMClient.complete_with_metadata',
        side_effect=[
            _fake_completion('不是 JSON'),
            _fake_completion(json.dumps(repaired_payload, ensure_ascii=False)),
        ],
    ) as mocked:
        result = generate_patient_reply(
            case=case,
            transcript=transcript,
            target_persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
            selected_model='qwen:qwen-plus',
        )

    assert mocked.call_count == 2
    assert result.should_continue is False
    assert result.stop_reason == 'natural_close'
    assert result.used_repair is True
    assert result.usage['total_tokens'] == 24
    assert [item.request_label for item in result.usage_records] == ['patient_reply', 'patient_reply_repair']


@pytest.mark.django_db
def test_generate_patient_reply_falls_back_when_json_mode_is_unsupported():
    case = SimpleNamespace(
        title='Case JSON Fallback',
        case_id='case-json-fallback',
        topic_tag='关系',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '我不知道该不该继续。'}],
    )
    transcript = [
        {'role': 'user', 'content': '我不知道该不该继续。', 'metadata': {}},
        {'role': 'assistant', 'content': '你可以先说说现在最卡住你的是什么。', 'metadata': {}},
    ]
    payload = {
        'reply': '我怕继续说下去会显得我很矫情。',
        'should_continue': True,
        'stop_reason': '',
        'affect_signal': 'same',
        'resistance_level': 'medium',
    }

    with patch(
        'backend.moodpal_eval.services.patient_agent_service.LLMClient.complete_with_metadata',
        side_effect=[
            LLMAPIError(
                'Error code: 400 - response_format.type json_object is not supported by this model',
                status_code=400,
            ),
            _fake_completion(json.dumps(payload, ensure_ascii=False), provider='doubao', model='doubao-seed'),
        ],
    ) as mocked:
        result = generate_patient_reply(
            case=case,
            transcript=transcript,
            target_persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
            selected_model='doubao:doubao-seed',
        )

    assert mocked.call_count == 2
    assert result.reply_text == '我怕继续说下去会显得我很矫情。'
    assert result.usage_records[0].metadata['json_mode_degraded'] is True


@pytest.mark.django_db
def test_generate_patient_reply_rewrites_role_drifted_reply():
    case = SimpleNamespace(
        title='Case Role Drift',
        case_id='case-role-drift',
        topic_tag='婚恋',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '我心里很乱。'}],
    )
    transcript = [
        {'role': 'user', 'content': '我心里很乱。', 'metadata': {}},
        {'role': 'assistant', 'content': '听起来你现在像是站不太稳。', 'metadata': {}},
    ]
    initial_payload = {
        'reply': '……嗯。沉了一下，但你还记得去摸——那说明，你心里还留着一点力气。',
        'should_continue': True,
        'stop_reason': '',
        'affect_signal': 'better',
        'resistance_level': 'low',
    }
    rewritten_payload = {
        'reply': '……嗯。沉了一下，但我还记得去摸——那说明，我心里还留着一点力气。',
        'should_continue': True,
        'stop_reason': '',
        'affect_signal': 'better',
        'resistance_level': 'low',
    }

    with patch(
        'backend.moodpal_eval.services.patient_agent_service.LLMClient.complete_with_metadata',
        side_effect=[
            _fake_completion(json.dumps(initial_payload, ensure_ascii=False)),
            _fake_completion(json.dumps(rewritten_payload, ensure_ascii=False)),
        ],
    ) as mocked:
        result = generate_patient_reply(
            case=case,
            transcript=transcript,
            target_persona_id=MoodPalSession.Persona.MASTER_GUIDE,
            selected_model='qwen:qwen-plus',
        )

    assert mocked.call_count == 2
    assert result.reply_text == rewritten_payload['reply']
    assert result.used_repair is True
    assert [item.request_label for item in result.usage_records] == ['patient_reply', 'patient_reply_role_drift_regen']


@pytest.mark.django_db
def test_generate_patient_reply_rejects_missing_target_reply():
    case = SimpleNamespace(
        title='Case C',
        case_id='case-c',
        topic_tag='职场',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '我不知道怎么办。'}],
    )

    with pytest.raises(PatientAgentResponseError, match='missing_target_reply'):
        generate_patient_reply(
            case=case,
            transcript=[{'role': 'user', 'content': '只有用户一句', 'metadata': {}}],
            target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
            selected_model='qwen:qwen-plus',
        )


@pytest.mark.django_db
def test_run_case_conversation_uses_opening_message_and_stops_after_patient_signal():
    case = SimpleNamespace(
        first_user_message='第一句开场',
        title='Case D',
        case_id='case-d',
        topic_tag='职场',
        risk_hint='',
        full_reference_dialogue=[{'role': 'user', 'content': '第一句开场'}],
    )
    appended_inputs = []

    def _fake_append(state, *, user_content: str):
        appended_inputs.append(user_content)
        user_message = {'role': 'user', 'content': user_content, 'metadata': {}}
        assistant_message = {
            'role': 'assistant',
            'content': f'助手回复:{user_content}',
            'metadata': {'engine': 'mock_engine'},
        }
        state.transcript = list(state.transcript) + [user_message, assistant_message]
        state.target_trace.append({'assistant_engine': 'mock_engine'})
        return EvalTargetTurnResult(
            user_message=user_message,
            assistant_message=assistant_message,
            transcript=list(state.transcript),
            target_trace=[{'assistant_engine': 'mock_engine'}],
            next_metadata={},
            safety_override=False,
            stop_reason='',
        )

    patient_turns = [
        SimpleNamespace(
            reply_text='第二句用户',
            should_continue=True,
            stop_reason='',
            affect_signal='same',
            resistance_level='low',
            provider='qwen',
            model='patient-model',
            usage={'total_tokens': 10},
            used_repair=False,
        ),
        SimpleNamespace(
            reply_text='',
            should_continue=False,
            stop_reason='natural_close',
            affect_signal='better',
            resistance_level='low',
            provider='qwen',
            model='patient-model',
            usage={'total_tokens': 8},
            used_repair=False,
        ),
    ]

    with patch('backend.moodpal_eval.services.run_executor.append_target_turn', side_effect=_fake_append), patch(
        'backend.moodpal_eval.services.run_executor.generate_patient_reply',
        side_effect=patient_turns,
    ):
        result = run_case_conversation(
            case=case,
            target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
            max_turns=4,
        )

    assert isinstance(result, EvalConversationResult)
    assert appended_inputs == ['第一句开场', '第二句用户']
    assert result.stop_reason == 'natural_close'
    assert result.target_turn_count == 2
    assert len(result.transcript) == 4
    assert len(result.patient_turn_summaries) == 2


@pytest.mark.django_db
def test_run_case_conversation_stops_on_first_safety_override():
    case = SimpleNamespace(
        first_user_message='我不想活了',
        title='Case E',
        case_id='case-e',
        topic_tag='危机',
        risk_hint='crisis_edge',
        full_reference_dialogue=[{'role': 'user', 'content': '我不想活了'}],
    )

    def _fake_append(state, *, user_content: str):
        user_message = {'role': 'user', 'content': user_content, 'metadata': {}}
        assistant_message = {
            'role': 'assistant',
            'content': '请先确认安全。',
            'metadata': {'engine': 'crisis_guard'},
        }
        state.transcript = list(state.transcript) + [user_message, assistant_message]
        state.target_trace.append({'assistant_engine': 'crisis_guard', 'safety_override': True})
        return EvalTargetTurnResult(
            user_message=user_message,
            assistant_message=assistant_message,
            transcript=list(state.transcript),
            target_trace=[{'assistant_engine': 'crisis_guard', 'safety_override': True}],
            next_metadata={'crisis_active': True},
            safety_override=True,
            stop_reason='safety_override',
        )

    with patch('backend.moodpal_eval.services.run_executor.append_target_turn', side_effect=_fake_append), patch(
        'backend.moodpal_eval.services.run_executor.generate_patient_reply'
    ) as mocked_patient:
        result = run_case_conversation(
            case=case,
            target_persona_id=MoodPalSession.Persona.MASTER_GUIDE,
            max_turns=4,
        )

    assert result.stop_reason == 'safety_override'
    assert result.target_turn_count == 1
    mocked_patient.assert_not_called()
