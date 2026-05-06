import pytest
from backend.moodpal.psychoanalysis.executor import PsychoanalysisTechniqueExecutor
from backend.moodpal.psychoanalysis.state import make_initial_psychoanalysis_state


def _make_state(persona_id='insight_mentor', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    state = make_initial_psychoanalysis_state(history_messages=history)
    state['persona_id'] = persona_id
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.pop('last_user_message', '我不知道为什么总是这样')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_persona_spec():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '心理学前辈' in payload.system_prompt
    assert '我在想' in payload.system_prompt


def test_system_prompt_contains_awareness_hint_after_opening():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '你只是在这里' in payload.system_prompt


def test_system_prompt_no_awareness_hint_during_opening():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=1)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert '你只是在这里' not in payload.system_prompt


def test_system_prompt_has_no_clinical_labels():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_association_invite')
    for label in ('本节点目标', '本轮聚焦', '边界约束', '动力学', '节点前置条件', '工作约束'):
        assert label not in payload.system_prompt, f'Found clinical label: {label}'


def test_user_prompt_contains_last_message():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='我又失控了')
    payload = executor.build_payload(state, 'psa_association_invite')
    assert '我又失控了' in payload.user_prompt


def test_user_prompt_has_no_backend_schema():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='测试')
    payload = executor.build_payload(state, 'psa_pattern_linking')
    assert '节点触发信号' not in payload.user_prompt
    assert '动力学信号摘要' not in payload.user_prompt
    assert '召回的脱敏模式记忆' not in payload.user_prompt
    assert '严格按' not in payload.user_prompt
    assert '{' not in payload.user_prompt


def test_master_guide_persona_applied():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'psa_insight_integration')
    assert '主理人' in payload.system_prompt
    assert '蔡康永' in payload.system_prompt


def test_payload_metadata_preserved():
    executor = PsychoanalysisTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'psa_entry_containment')
    assert payload.metadata['node_name']
    assert payload.metadata['category']
    assert payload.technique_id == 'psa_entry_containment'
