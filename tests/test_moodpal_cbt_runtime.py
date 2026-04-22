import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.moodpal.cbt import CBTGraph, CBTNodeRegistry, CBTTechniqueRouter
from backend.moodpal.cbt.exit_evaluator import CBTExitEvaluator
from backend.moodpal.cbt.executor import CBTTechniqueExecutor
from backend.moodpal.cbt.state import make_initial_cbt_state
from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.cbt_runtime_service import run_cbt_turn


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


def test_cbt_node_registry_loads_all_json_nodes():
    registry = CBTNodeRegistry()
    nodes = registry.all_nodes()
    node_ids = {node.node_id for node in nodes}

    assert len(nodes) == 15
    assert 'cbt_structure_agenda_setting' in node_ids
    assert 'cbt_cog_eval_socratic' in node_ids
    assert 'cbt_exception_alliance_rupture' in node_ids


def test_cbt_router_prioritizes_agenda_gate_before_other_tracks():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state(
        last_summary={},
        history_messages=[],
    )
    state['last_user_message'] = '我什么都不想干，整天都在床上。'
    state['energy_level'] = 'low'
    state['behavioral_shutdown'] = True

    selection = router.route(state)

    assert selection.track == 'agenda'
    assert selection.technique_id == 'cbt_structure_agenda_setting'


def test_cbt_router_uses_preflight_exception_override():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '老板没回消息'
    state['agenda_locked'] = True
    state['last_user_message'] = '你根本不懂，这些大道理没用。'

    selection = router.route(state)

    assert selection.track == 'exception'
    assert selection.technique_id == 'cbt_exception_alliance_rupture'


def test_cbt_router_selects_homework_obstacle_exception_on_hint():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '上周约好的小行动'
    state['agenda_locked'] = True
    state['last_user_message'] = '我没做，上周那件事还是做不到。'

    selection = router.route(state)

    assert selection.track == 'exception'
    assert selection.technique_id == 'cbt_exception_homework_obstacle'


def test_cbt_router_selects_redirecting_exception_on_hint():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '老板没回消息'
    state['agenda_locked'] = True
    state['last_user_message'] = '顺便我还想说下和家里的矛盾。'

    selection = router.route(state)

    assert selection.track == 'exception'
    assert selection.technique_id == 'cbt_exception_redirecting'
    assert selection.reason == 'topic_drift_detected'


def test_cbt_router_selects_telegraphic_identification_variant():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '明天要开会'
    state['agenda_locked'] = True
    state['last_user_message'] = '完了，如果我搞砸了怎么办？'

    selection = router.route(state)

    assert selection.track == 'cognitive_identification'
    assert selection.technique_id == 'cbt_cog_identify_at_telegraphic'


def test_cbt_router_selects_distortion_node_when_language_is_absolute():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '老板没回邮件'
    state['agenda_locked'] = True
    state['captured_automatic_thought'] = '老板没回我邮件，我这辈子全毁了。'

    selection = router.route(state)

    assert selection.track == 'cognitive_evaluation'
    assert selection.technique_id == 'cbt_cog_eval_distortion'


def test_cbt_router_selects_behavioral_activation_when_low_energy_after_agenda():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '下班后什么都做不了'
    state['agenda_locked'] = True
    state['last_user_message'] = '我现在什么都不想干，完全动不了。'
    state['energy_level'] = 'low'
    state['behavioral_shutdown'] = True

    selection = router.route(state)

    assert selection.track == 'behavioral_activation'
    assert selection.technique_id == 'cbt_beh_activation'


def test_cbt_router_selects_behavioral_experiment_from_prediction_thought():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '给同事发消息'
    state['agenda_locked'] = True
    state['captured_automatic_thought'] = '如果我主动发消息，他肯定会嫌我烦。'
    state['last_user_message'] = '我一想到要发消息就很慌。'
    state['emotion_stability'] = 'medium'

    selection = router.route(state)

    assert selection.track == 'behavioral_experiment'
    assert selection.technique_id == 'cbt_beh_experiment'


def test_cbt_router_prioritizes_existing_task_breakdown_before_prediction():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '给同事发消息'
    state['agenda_locked'] = True
    state['task_first_step'] = '先打开聊天窗口'
    state['captured_automatic_thought'] = '如果我主动发消息，他肯定会嫌我烦。'
    state['last_user_message'] = '我一想到要发消息就很慌。'

    selection = router.route(state)

    assert selection.track == 'graded_task'
    assert selection.technique_id == 'cbt_beh_graded_task'
    assert selection.reason == 'task_breakdown_already_in_progress'


def test_cbt_router_uses_same_track_fallback_after_behavioral_experiment_trip():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '给同事发消息'
    state['agenda_locked'] = True
    state['captured_automatic_thought'] = '如果我主动发消息，他肯定会嫌我烦。'
    state['current_technique_id'] = 'cbt_beh_experiment'
    state['circuit_breaker_open'] = True
    state['next_fallback_action'] = 'switch_same_track'

    selection = router.route(state)

    assert selection.track == 'graded_task'
    assert selection.technique_id == 'cbt_beh_graded_task'


def test_cbt_router_only_allows_deep_exploration_when_emotion_is_high():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '我总是害怕被否定'
    state['agenda_locked'] = True
    state['repeated_theme_detected'] = True
    state['emotion_stability'] = 'medium'
    state['alliance_strength'] = 'strong'
    state['captured_automatic_thought'] = '他们会觉得我很差劲。'

    selection = router.route(state)
    assert selection.technique_id != 'cbt_core_downward_arrow'

    state['emotion_stability'] = 'high'
    selection = router.route(state)

    assert selection.track == 'deep_exploration'
    assert selection.technique_id == 'cbt_core_downward_arrow'


def test_cbt_router_uses_exception_fallback_after_cognitive_trip():
    router = CBTTechniqueRouter()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '老板没回消息'
    state['agenda_locked'] = True
    state['captured_automatic_thought'] = '如果老板不回，我就完了。'
    state['current_technique_id'] = 'cbt_cog_eval_socratic'
    state['circuit_breaker_open'] = True
    state['next_fallback_action'] = 'jump_to_exception'

    selection = router.route(state)

    assert selection.track == 'exception'
    assert selection.technique_id == 'cbt_exception_yes_but'


def test_exit_evaluator_trips_circuit_after_stall_limit():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '开会发言'
    state['agenda_locked'] = True
    state['technique_attempt_count'] = 2
    state['technique_stall_count'] = 1
    state['last_progress_marker'] = ''

    result = evaluator.evaluate(state, 'cbt_cog_identify_at_basic')

    assert result.done is False
    assert result.should_trip_circuit is True
    assert result.trip_reason == 'attempt_limit_reached'
    assert result.next_fallback_action == 'switch_same_track'


def test_exit_evaluator_handoffs_cognitive_track_after_agenda_done():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '开会发言'
    state['agenda_locked'] = True

    result = evaluator.evaluate(state, 'cbt_structure_agenda_setting')

    assert result.done is True
    assert result.progress_marker == 'agenda_locked'
    assert result.next_fallback_action == 'handoff_to_cognitive_track'


def test_exit_evaluator_marks_balanced_response_ready():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['balanced_response'] = '虽然我现在很担心，但并没有证据证明事情已经完蛋。'
    state['balanced_response_confidence'] = 68

    result = evaluator.evaluate(state, 'cbt_cog_response_coping')

    assert result.done is True
    assert result.progress_marker == 'balanced_response_ready'
    assert result.next_fallback_action == 'wrap_up_now'


def test_exit_evaluator_marks_behavioral_activation_ready_with_activation_step():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['activation_step'] = '起身喝口水'

    result = evaluator.evaluate(state, 'cbt_beh_activation')

    assert result.done is True
    assert result.progress_marker == 'activation_step_committed'


def test_exit_evaluator_wraps_up_exception_after_stall_limit():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '老板没回消息'
    state['agenda_locked'] = True
    state['head_heart_split_detected'] = True
    state['technique_attempt_count'] = 1
    state['technique_stall_count'] = 1
    state['last_progress_marker'] = ''

    result = evaluator.evaluate(state, 'cbt_exception_yes_but')

    assert result.done is False
    assert result.should_trip_circuit is True
    assert result.trip_reason == 'stall_limit_reached'
    assert result.next_fallback_action == 'wrap_up_now'


def test_exit_evaluator_uses_jump_to_exception_for_imagery_identification_trip():
    evaluator = CBTExitEvaluator()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '工作失误'
    state['agenda_locked'] = True
    state['technique_attempt_count'] = 2
    state['technique_stall_count'] = 1
    state['last_progress_marker'] = ''

    result = evaluator.evaluate(state, 'cbt_cog_identify_at_imagery')

    assert result.done is False
    assert result.should_trip_circuit is True
    assert result.trip_reason == 'attempt_limit_reached'
    assert result.next_fallback_action == 'jump_to_exception'


def test_cbt_graph_builds_execution_payload_for_selected_node():
    graph = CBTGraph()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '工作失误'
    state['agenda_locked'] = True
    state['last_user_message'] = '我想不起来当时脑子里在想什么。'

    plan = graph.plan_turn(state)

    assert plan.selection.technique_id == 'cbt_cog_identify_at_imagery'
    assert plan.payload is not None
    assert '画面重现' in plan.payload.user_prompt
    assert '一次只推进一步' in plan.payload.system_prompt


def test_cbt_executor_builds_node_specific_prompt_template():
    executor = CBTTechniqueExecutor()
    state = make_initial_cbt_state()
    state['agenda_topic'] = '给同事发消息'
    state['agenda_locked'] = True
    state['captured_automatic_thought'] = '如果我主动发消息，他肯定会嫌我烦。'
    state['last_user_message'] = '我一想到要发消息就很慌。'
    state['experiment_plan'] = {'action': '', 'timepoint': '', 'metric': ''}
    state['homework_candidate'] = ''

    payload = executor.build_payload(state, 'cbt_beh_experiment')

    assert '本节点目标：把用户的负面预测转成一个小型、可验证的行为实验。' in payload.system_prompt
    assert '本轮聚焦：只明确实验动作、时间点和观察指标。' in payload.system_prompt
    assert '避免事项：' in payload.system_prompt
    assert '节点触发信号：' in payload.user_prompt
    assert '参考风格示例：' in payload.user_prompt
    assert '"captured_automatic_thought": "如果我主动发消息，他肯定会嫌我烦。"' in payload.user_prompt
    assert payload.metadata['prompt_template_id'] == 'cbt_beh_experiment'
    assert 'experiment_plan' in payload.metadata['relevant_context_keys']


def test_cbt_executor_limits_context_to_template_scope():
    executor = CBTTechniqueExecutor()
    state = make_initial_cbt_state()
    state['last_user_message'] = '你根本不懂，这些大道理没用。'
    state['alliance_strength'] = 'weak'
    state['alliance_rupture_detected'] = True
    state['homework_candidate'] = '不该出现在这个节点上下文里'

    payload = executor.build_payload(state, 'cbt_exception_alliance_rupture')

    assert '"alliance_rupture_detected": true' in payload.user_prompt
    assert '"alliance_strength": "weak"' in payload.user_prompt
    assert '"homework_candidate"' not in payload.user_prompt


@pytest.mark.django_db
def test_run_cbt_turn_resets_attempt_counter_when_switching_technique():
    session = MoodPalSession.objects.create(
        usage_subject='anon:cbt-counter-reset',
        anon_id='cbt-counter-reset',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '工作失误',
                'agenda_locked': True,
                'current_technique_id': 'cbt_structure_agenda_setting',
                'technique_attempt_count': 2,
                'technique_stall_count': 1,
                'last_progress_marker': 'agenda_locked',
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '完了，如果我搞砸了怎么办？'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps(
            {
                'reply': '我们先抓住那句最刺耳的话。',
                'state_patch': {
                    'thought_format': 'question',
                },
            },
            ensure_ascii=False,
        ),
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        model='fake-cbt-model',
    )

    with patch('backend.moodpal.services.cbt_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
        result = run_cbt_turn(session=session, history_messages=history_messages)

    assert result.reply_metadata['technique_id'] == 'cbt_cog_identify_at_telegraphic'
    assert result.state['technique_attempt_count'] == 1
    assert result.state['technique_stall_count'] == 1
    assert result.state['current_technique_id'] == 'cbt_cog_identify_at_telegraphic'


@pytest.mark.django_db
def test_run_cbt_turn_logs_local_fallback_application(caplog):
    session = MoodPalSession.objects.create(
        usage_subject='anon:cbt-fallback-log',
        anon_id='cbt-fallback-log',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '会议里的失误',
                'agenda_locked': True,
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '我想不起来当时脑子里在想什么。'},
    ]

    with _capture_named_logger(caplog, 'backend.moodpal.services.cbt_runtime_service'):
        with patch('backend.moodpal.services.cbt_runtime_service.LLMClient.complete_with_metadata', side_effect=RuntimeError('boom')):
            result = run_cbt_turn(session=session, history_messages=history_messages)

    assert result.used_fallback is True
    assert 'MoodPal CBT route selected' in caplog.text
    assert 'MoodPal CBT local fallback applied' in caplog.text
    assert 'MoodPal CBT trace appended' in caplog.text


@pytest.mark.django_db
def test_run_cbt_turn_logs_circuit_breaker_trip(caplog):
    session = MoodPalSession.objects.create(
        usage_subject='anon:cbt-circuit-trip',
        anon_id='cbt-circuit-trip',
        persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
        status=MoodPalSession.Status.ACTIVE,
        metadata={
            'cbt_state': {
                'agenda_topic': '开会发言',
                'agenda_locked': True,
                'current_technique_id': 'cbt_cog_identify_at_basic',
                'technique_attempt_count': 2,
                'technique_stall_count': 1,
                'last_progress_marker': '',
            }
        },
    )
    history_messages = [
        {'role': 'user', 'content': '我现在脑子很乱。'},
    ]
    llm_result = SimpleNamespace(
        text=json.dumps({'reply': '我们先慢一点，把那一瞬间最冒出来的话抓住。', 'state_patch': {}}, ensure_ascii=False),
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=4, total_tokens=6),
        model='fake-cbt-model',
    )

    with _capture_named_logger(caplog, 'backend.moodpal.services.cbt_runtime_service'):
        with patch('backend.moodpal.services.cbt_runtime_service.LLMClient.complete_with_metadata', return_value=llm_result):
            result = run_cbt_turn(session=session, history_messages=history_messages)

    assert result.state['circuit_breaker_open'] is True
    assert result.state['next_fallback_action'] == 'switch_same_track'
    assert 'MoodPal CBT circuit breaker opened' in caplog.text
    assert 'MoodPal CBT trace appended' in caplog.text
