import pytest
from backend.moodpal.humanistic.executor import HumanisticTechniqueExecutor
from backend.moodpal.humanistic.state import make_initial_humanistic_state


def _make_state(persona_id='empathy_sister', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    state = make_initial_humanistic_state(history_messages=history)
    state['persona_id'] = persona_id
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.pop('last_user_message', '我感觉很难受')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_persona_spec():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '共情学姐' in payload.system_prompt
    assert '旅行' in payload.system_prompt


def test_system_prompt_contains_awareness_hint_after_opening():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '先慢下来' in payload.system_prompt


def test_system_prompt_no_awareness_hint_during_opening():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=1)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '先慢下来' not in payload.system_prompt


def test_system_prompt_has_no_clinical_labels():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_reflect_feeling')
    for label in ('本节点目标', '本轮聚焦', '避免事项', '回复契约', '节点前置条件', '工作约束', '语言约束'):
        assert label not in payload.system_prompt, f'Found clinical label: {label}'


def test_user_prompt_contains_last_message():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='我就是不想说话')
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '我就是不想说话' in payload.user_prompt


def test_user_prompt_has_no_backend_schema():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='测试')
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert '节点触发信号' not in payload.user_prompt
    assert '节点退出标准' not in payload.user_prompt
    assert '状态信号摘要' not in payload.user_prompt
    assert '严格按' not in payload.user_prompt
    assert '{' not in payload.user_prompt


def test_master_guide_persona_applied():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'hum_unconditional_regard')
    assert '主理人' in payload.system_prompt
    assert '蔡康永' in payload.system_prompt


def test_payload_metadata_preserved():
    executor = HumanisticTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'hum_validate_normalize')
    assert payload.metadata['node_name']
    assert payload.metadata['category']
    assert payload.technique_id == 'hum_validate_normalize'
