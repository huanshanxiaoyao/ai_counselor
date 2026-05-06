import pytest
from backend.moodpal.cbt.executor import CBTTechniqueExecutor
from backend.moodpal.cbt.state import make_initial_cbt_state


def _make_state(persona_id='logic_brother', turn_count=0, **kwargs):
    history = []
    for i in range(turn_count):
        history.append({'role': 'user', 'content': f'用户消息{i}'})
        history.append({'role': 'assistant', 'content': f'助手回复{i}'})
    state = make_initial_cbt_state(history_messages=history)
    state['persona_id'] = persona_id
    state['surface_persona_id'] = persona_id
    state['last_user_message'] = kwargs.pop('last_user_message', '我很焦虑')
    for k, v in kwargs.items():
        state[k] = v
    return state


def test_system_prompt_contains_persona_spec():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '逻辑哥哥' in payload.system_prompt
    assert '李诞' in payload.system_prompt


def test_system_prompt_contains_awareness_hint_after_opening():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '核心念头' in payload.system_prompt


def test_system_prompt_no_awareness_hint_during_opening():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=1)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '核心念头' not in payload.system_prompt


def test_system_prompt_has_no_clinical_labels():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_eval_socratic')
    for label in ('本节点目标', '本轮聚焦', '避免事项', '回复契约', '当前 CBT 节点', '治疗约束'):
        assert label not in payload.system_prompt, f'Found clinical label: {label}'


def test_user_prompt_contains_last_message():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='我压力很大')
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '我压力很大' in payload.user_prompt


def test_user_prompt_has_no_backend_schema():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5, last_user_message='测试')
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert '节点触发信号' not in payload.user_prompt
    assert '节点前置条件' not in payload.user_prompt
    assert '节点退出标准' not in payload.user_prompt
    assert '严格按' not in payload.user_prompt
    assert '{' not in payload.user_prompt


def test_master_guide_persona_applied():
    executor = CBTTechniqueExecutor()
    state = _make_state(persona_id='master_guide', turn_count=5)
    payload = executor.build_payload(state, 'cbt_beh_activation')
    assert '主理人' in payload.system_prompt
    assert '蔡康永' in payload.system_prompt


def test_payload_metadata_preserved():
    executor = CBTTechniqueExecutor()
    state = _make_state(turn_count=5)
    payload = executor.build_payload(state, 'cbt_cog_identify_at_basic')
    assert payload.metadata['node_name']
    assert payload.metadata['category']
    assert payload.technique_id == 'cbt_cog_identify_at_basic'
