import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.moodpal.humanistic import HumanisticGraph, HumanisticNodeRegistry, HumanisticTechniqueRouter
from backend.moodpal.humanistic.executor import HumanisticTechniqueExecutor
from backend.moodpal.humanistic.executor_prompt_config import PROMPT_TEMPLATE_BY_TECHNIQUE
from backend.moodpal.humanistic.resonance_evaluator import HumanisticResonanceEvaluator
from backend.moodpal.humanistic.signal_extractor import extract_humanistic_turn_signals
from backend.moodpal.humanistic.state import make_initial_humanistic_state
from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.humanistic_runtime_service import run_humanistic_turn


@contextmanager
def _capture_named_logger(caplog, logger_name: str, level: int = logging.INFO):
    target_logger = logging.getLogger(logger_name)
    previous_level = target_logger.level
    target_logger.addHandler(caplog.handler)
    target_logger.setLevel(level)
    try:
        yield
    finally:
        target_logger.removeHandler(caplog.handler)
        target_logger.setLevel(previous_level)


def test_humanistic_node_registry_loads_all_json_nodes():
    registry = HumanisticNodeRegistry()
    nodes = registry.all_nodes()
    node_ids = {node.node_id for node in nodes}

    assert len(nodes) == 7
    assert 'hum_validate_normalize' in node_ids
    assert 'hum_exception_alliance_repair' in node_ids
    assert 'hum_boundary_advice_pull' in node_ids


def test_humanistic_router_prioritizes_repair_override():
    router = HumanisticTechniqueRouter()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '你根本没懂我，别再套模板了。'
    state['emotional_intensity'] = 9

    selection = router.route(state)

    assert selection.track == 'repair'
    assert selection.technique_id == 'hum_exception_alliance_repair'


def test_humanistic_router_selects_holding_on_high_intensity():
    router = HumanisticTechniqueRouter()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '我现在真的快崩溃了。'
    state['emotional_intensity'] = 9

    selection = router.route(state)

    assert selection.track == 'holding'
    assert selection.technique_id == 'hum_validate_normalize'


def test_humanistic_router_selects_accepting_for_self_attack():
    router = HumanisticTechniqueRouter()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '我就是个废物。'
    state['self_attack_flag'] = True
    state['emotional_intensity'] = 6

    selection = router.route(state)

    assert selection.track == 'accepting'
    assert selection.technique_id == 'hum_unconditional_regard'


def test_humanistic_router_selects_body_focus_for_diffuse_body_signal():
    router = HumanisticTechniqueRouter()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '我就是胸口闷，说不上来。'
    state['emotional_intensity'] = 6
    state['body_signal_present'] = True
    state['emotional_clarity'] = 'diffuse'

    selection = router.route(state)

    assert selection.track == 'body_focusing'
    assert selection.technique_id == 'hum_body_focus'


def test_humanistic_resonance_evaluator_trips_on_stall_limit():
    evaluator = HumanisticResonanceEvaluator()
    state = make_initial_humanistic_state()
    state['advice_pull_detected'] = True
    state['technique_attempt_count'] = 2
    state['technique_stall_count'] = 0
    state['last_progress_marker'] = 'boundary_negotiation_in_progress'

    result = evaluator.evaluate(state, 'hum_boundary_advice_pull')

    assert result.done is False
    assert result.should_trip_circuit is True
    assert result.trip_reason == 'attempt_limit_reached'
    assert result.next_fallback_action == 'wrap_up_now'


def test_humanistic_graph_builds_execution_payload_for_repair_node():
    graph = HumanisticGraph()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '你根本没懂我。'
    state['alliance_rupture_detected'] = True
    state['relational_trust'] = 'weak'

    plan = graph.plan_turn(state)

    assert plan.selection.technique_id == 'hum_exception_alliance_repair'
    assert plan.payload is not None
    assert '修复刚刚受损的关系' in plan.payload.system_prompt
    assert '节点退出标准：' in plan.payload.user_prompt


def test_humanistic_signal_extractor_derives_structured_turn_signals():
    state = make_initial_humanistic_state()
    state['last_user_message'] = '我胸口闷得慌，说不上来，就是堵着很难受。'

    patch = extract_humanistic_turn_signals(state)

    assert patch['body_signal_present'] is True
    assert patch['body_focus_ready'] is True
    assert patch['emotional_intensity'] >= 6
    assert patch['emotional_clarity'] == 'diffuse'
    assert patch['dominant_emotions'] == []


def test_humanistic_executor_limits_context_to_template_scope():
    executor = HumanisticTechniqueExecutor()
    state = make_initial_humanistic_state()
    state['last_user_message'] = '别安慰我了，直接告诉我怎么办。'
    state['advice_pull_detected'] = True
    state['openness_level'] = 'guarded'
    state['homework_candidate'] = '先决定一个最想处理的小点'
    state['self_attack_flag'] = True

    payload = executor.build_payload(state, 'hum_boundary_advice_pull')

    assert '节点触发信号：' in payload.user_prompt
    assert '"advice_pull_detected": true' in payload.user_prompt
    assert '"self_attack_flag"' not in payload.user_prompt
    assert payload.metadata['prompt_template_id'] == 'hum_boundary_advice_pull'


def test_humanistic_executor_includes_signal_summary_block():
    executor = HumanisticTechniqueExecutor()
    state = make_initial_humanistic_state()
    state.update(
        {
            'last_user_message': '你根本没懂我。',
            'alliance_rupture_detected': True,
            'relational_trust': 'weak',
            'emotional_intensity': 7,
            'dominant_emotions': ['委屈'],
            'unmet_need_candidate': '被理解',
        }
    )

    payload = executor.build_payload(state, 'hum_exception_alliance_repair')

    assert '状态信号摘要：' in payload.user_prompt
    assert '未满足需要候选：被理解' in payload.user_prompt
    assert '当前异常标记：alliance_rupture' in payload.user_prompt


def test_all_humanistic_nodes_have_prompt_templates():
    registry_ids = {node.node_id for node in HumanisticNodeRegistry().all_nodes()}
    assert set(PROMPT_TEMPLATE_BY_TECHNIQUE.keys()) == registry_ids


@pytest.mark.django_db
def test_run_humanistic_turn_resets_attempt_counter_when_switching_technique():
    session = MoodPalSession.objects.create(
        usage_subject='anon:humanistic-counter-reset',
        anon_id='humanistic-counter-reset',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'humanistic_state': {
                'current_technique_id': 'hum_validate_normalize',
                'technique_attempt_count': 2,
                'technique_stall_count': 1,
                'last_progress_marker': 'holding_stabilized',
                'emotional_intensity': 6,
                'body_signal_present': True,
                'emotional_clarity': 'diffuse',
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '我就是胸口闷，说不上来。'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我们先不急着解释，只看看这份闷更像卡在胸口还是喉咙。',
                'state_patch': {
                    'felt_sense_description': '胸口发紧',
                    'body_signal_present': True,
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        model='fake-humanistic-model',
    )

    with patch('backend.moodpal.services.humanistic_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        result = run_humanistic_turn(session=session, history_messages=history_messages)

    assert result.reply_metadata['technique_id'] == 'hum_body_focus'
    assert result.state['technique_attempt_count'] == 1
    assert result.state['current_technique_id'] == 'hum_body_focus'


@pytest.mark.django_db
def test_run_humanistic_turn_logs_local_fallback_application(caplog):
    session = MoodPalSession.objects.create(
        usage_subject='anon:humanistic-fallback-log',
        anon_id='humanistic-fallback-log',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'humanistic_state': {
                'emotional_intensity': 9,
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '我现在真的快崩溃了。'},
    ]

    with _capture_named_logger(caplog, 'backend.moodpal.services.humanistic_runtime_service'):
        with patch('backend.moodpal.services.humanistic_runtime_service.LLMClient.complete_with_metadata', side_effect=RuntimeError('boom')):
            result = run_humanistic_turn(session=session, history_messages=history_messages)

    assert result.used_fallback is True
    assert 'MoodPal Humanistic route selected' in caplog.text
    assert 'MoodPal Humanistic local fallback applied' in caplog.text
    assert 'MoodPal Humanistic trace appended' in caplog.text


@pytest.mark.django_db
def test_run_humanistic_turn_uses_extracted_body_signal_without_persisted_state():
    session = MoodPalSession.objects.create(
        usage_subject='anon:humanistic-signal-extraction',
        anon_id='humanistic-signal-extraction',
        persona_id=MoodPalSession.Persona.EMPATHY_SISTER,
        status=MoodPalSession.Status.ACTIVE,
    )
    history_messages = [
        {'role': 'user', 'content': '我就是胸口闷，说不上来。'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我们先不急着解释，只看看这份闷更像卡在胸口还是喉咙。',
                'state_patch': {
                    'felt_sense_description': '胸口发紧',
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        model='fake-humanistic-model',
    )

    with patch('backend.moodpal.services.humanistic_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        result = run_humanistic_turn(session=session, history_messages=history_messages)

    assert result.reply_metadata['technique_id'] == 'hum_body_focus'
    assert result.state['body_signal_present'] is True
