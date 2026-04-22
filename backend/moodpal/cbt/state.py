from __future__ import annotations

from typing import Literal, Optional, TypedDict


SESSION_PHASES = (
    'starting',
    'active',
    'ending',
    'summary_pending',
    'closed',
)

STAGES = (
    'session_start',
    'safety_check',
    'preflight_exception_check',
    'mood_check',
    'agenda_setting',
    'route_track',
    'select_technique',
    'execute_technique',
    'evaluate_exit',
    'handle_exception',
    'wrap_up',
)

TRACKS = (
    'agenda',
    'cognitive_identification',
    'cognitive_evaluation',
    'cognitive_response',
    'behavioral_activation',
    'behavioral_experiment',
    'graded_task',
    'deep_exploration',
    'exception',
    'safety_override',
    '',
)

FALLBACK_ACTIONS = (
    'retry_same_technique',
    'switch_same_track',
    'jump_to_exception',
    'wrap_up_now',
    'handoff_to_behavioral_track',
    'handoff_to_cognitive_track',
    'handoff_to_safety',
)


class CBTGraphState(TypedDict, total=False):
    session_id: str
    subject_key: str
    persona_id: str
    therapy_mode: Literal['cbt']
    selected_model: str

    session_phase: Literal['starting', 'active', 'ending', 'summary_pending', 'closed']
    current_stage: Literal[
        'session_start',
        'safety_check',
        'preflight_exception_check',
        'mood_check',
        'agenda_setting',
        'route_track',
        'select_technique',
        'execute_technique',
        'evaluate_exit',
        'handle_exception',
        'wrap_up',
    ]
    current_track: Literal[
        'agenda',
        'cognitive_identification',
        'cognitive_evaluation',
        'cognitive_response',
        'behavioral_activation',
        'behavioral_experiment',
        'graded_task',
        'deep_exploration',
        'exception',
        'safety_override',
        '',
    ]
    current_technique_id: str

    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict

    mood_label: str
    mood_score: int
    emotion_stability: Literal['low', 'medium', 'high']
    agenda_topic: str
    agenda_locked: bool

    captured_automatic_thought: str
    thought_format: Literal['statement', 'telegraphic', 'question', 'imagery', '']
    belief_confidence: int
    alternative_explanation: str
    cognitive_distortion_label: str
    balanced_response: str
    balanced_response_confidence: int

    energy_level: Literal['low', 'medium', 'high']
    behavioral_shutdown: bool
    activation_step: str
    experiment_plan: dict
    task_first_step: str
    homework_candidate: str

    repeated_theme_detected: bool
    core_belief_candidate: str
    intermediate_belief_candidate: str
    alliance_strength: Literal['weak', 'medium', 'strong']

    safety_status: Literal['safe', 'crisis_override']
    alliance_rupture_detected: bool
    topic_drift_detected: bool
    homework_obstacle_detected: bool
    head_heart_split_detected: bool
    exception_flags: dict

    technique_attempt_count: int
    technique_stall_count: int
    last_progress_marker: str
    circuit_breaker_open: bool
    next_fallback_action: Literal[
        'retry_same_technique',
        'switch_same_track',
        'jump_to_exception',
        'wrap_up_now',
        'handoff_to_behavioral_track',
        'handoff_to_cognitive_track',
        'handoff_to_safety',
    ]
    technique_trace: list[dict]


def make_initial_cbt_state(
    *,
    session_id: str = '',
    subject_key: str = '',
    persona_id: str = '',
    selected_model: str = '',
    session_phase: str = 'active',
    history_messages: Optional[list[dict]] = None,
    last_summary: Optional[dict] = None,
) -> CBTGraphState:
    return CBTGraphState(
        session_id=session_id,
        subject_key=subject_key,
        persona_id=persona_id,
        therapy_mode='cbt',
        selected_model=selected_model,
        session_phase=session_phase,
        current_stage='session_start',
        current_track='',
        current_technique_id='',
        history_messages=history_messages or [],
        last_user_message='',
        last_assistant_message='',
        last_summary=last_summary or {},
        mood_label='',
        mood_score=0,
        emotion_stability='medium',
        agenda_topic='',
        agenda_locked=False,
        captured_automatic_thought='',
        thought_format='',
        belief_confidence=0,
        alternative_explanation='',
        cognitive_distortion_label='',
        balanced_response='',
        balanced_response_confidence=0,
        energy_level='medium',
        behavioral_shutdown=False,
        activation_step='',
        experiment_plan={},
        task_first_step='',
        homework_candidate='',
        repeated_theme_detected=False,
        core_belief_candidate='',
        intermediate_belief_candidate='',
        alliance_strength='medium',
        safety_status='safe',
        alliance_rupture_detected=False,
        topic_drift_detected=False,
        homework_obstacle_detected=False,
        head_heart_split_detected=False,
        exception_flags={},
        technique_attempt_count=0,
        technique_stall_count=0,
        last_progress_marker='',
        circuit_breaker_open=False,
        next_fallback_action='retry_same_technique',
        technique_trace=[],
    )


def build_cbt_state_from_session(*, session, history_messages: list[dict], last_summary: Optional[dict] = None) -> CBTGraphState:
    state = make_initial_cbt_state(
        session_id=str(session.id),
        subject_key=session.usage_subject,
        persona_id=session.persona_id,
        selected_model=session.selected_model,
        session_phase=session.status,
        history_messages=history_messages,
        last_summary=last_summary or {},
    )

    last_user_message = ''
    last_assistant_message = ''
    for message in history_messages:
        if message.get('role') == 'user':
            last_user_message = message.get('content', '')
        elif message.get('role') == 'assistant':
            last_assistant_message = message.get('content', '')

    state['last_user_message'] = last_user_message
    state['last_assistant_message'] = last_assistant_message
    state['current_stage'] = 'route_track' if history_messages else 'session_start'
    return state
