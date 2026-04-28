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
    'preflight_relational_check',
    'entry_attunement',
    'affect_assessment',
    'determine_phase',
    'select_technique',
    'execute_technique',
    'evaluate_resonance',
    'handle_repair',
    'wrap_up',
)

PHASES = (
    'holding',
    'clarifying',
    'body_focusing',
    'accepting',
    'repair',
    'safety_override',
    '',
)

FALLBACK_ACTIONS = (
    'retry_same_technique',
    'switch_same_phase',
    'regress_to_holding',
    'jump_to_repair',
    'wrap_up_now',
    'handoff_to_safety',
)


class HumanisticGraphState(TypedDict, total=False):
    session_id: str
    subject_key: str
    persona_id: str
    surface_persona_id: str
    therapy_mode: Literal['humanistic']
    selected_model: str
    support_directive: str

    session_phase: Literal['starting', 'active', 'ending', 'summary_pending', 'closed']
    current_stage: Literal[
        'session_start',
        'safety_check',
        'preflight_relational_check',
        'entry_attunement',
        'affect_assessment',
        'determine_phase',
        'select_technique',
        'execute_technique',
        'evaluate_resonance',
        'handle_repair',
        'wrap_up',
    ]
    current_phase: Literal[
        'holding',
        'clarifying',
        'body_focusing',
        'accepting',
        'repair',
        'safety_override',
        '',
    ]
    current_technique_id: str

    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict

    emotional_intensity: int
    dominant_emotions: list[str]
    emotional_clarity: Literal['diffuse', 'emerging', 'clear']
    openness_level: Literal['guarded', 'partial', 'open']
    self_attack_flag: bool
    shame_signal: bool
    body_signal_present: bool
    body_focus_ready: bool
    felt_sense_description: str
    resonance_score: int
    being_understood_signal: bool
    relational_trust: Literal['weak', 'medium', 'strong']

    unmet_need_candidate: str
    self_compassion_shift: str
    homework_candidate: str

    safety_status: Literal['safe', 'crisis_override']
    alliance_rupture_detected: bool
    numbness_detected: bool
    advice_pull_detected: bool
    exception_flags: dict

    technique_attempt_count: int
    technique_stall_count: int
    last_progress_marker: str
    circuit_breaker_open: bool
    next_fallback_action: Literal[
        'retry_same_technique',
        'switch_same_phase',
        'regress_to_holding',
        'jump_to_repair',
        'wrap_up_now',
        'handoff_to_safety',
    ]
    technique_trace: list[dict]


def make_initial_humanistic_state(
    *,
    session_id: str = '',
    subject_key: str = '',
    persona_id: str = '',
    selected_model: str = '',
    session_phase: str = 'active',
    history_messages: Optional[list[dict]] = None,
    last_summary: Optional[dict] = None,
) -> HumanisticGraphState:
    return HumanisticGraphState(
        session_id=session_id,
        subject_key=subject_key,
        persona_id=persona_id,
        surface_persona_id=persona_id,
        therapy_mode='humanistic',
        selected_model=selected_model,
        support_directive='',
        session_phase=session_phase,
        current_stage='session_start',
        current_phase='',
        current_technique_id='',
        history_messages=history_messages or [],
        last_user_message='',
        last_assistant_message='',
        last_summary=last_summary or {},
        emotional_intensity=0,
        dominant_emotions=[],
        emotional_clarity='diffuse',
        openness_level='partial',
        self_attack_flag=False,
        shame_signal=False,
        body_signal_present=False,
        body_focus_ready=False,
        felt_sense_description='',
        resonance_score=0,
        being_understood_signal=False,
        relational_trust='medium',
        unmet_need_candidate='',
        self_compassion_shift='',
        homework_candidate='',
        safety_status='safe',
        alliance_rupture_detected=False,
        numbness_detected=False,
        advice_pull_detected=False,
        exception_flags={},
        technique_attempt_count=0,
        technique_stall_count=0,
        last_progress_marker='',
        circuit_breaker_open=False,
        next_fallback_action='retry_same_technique',
        technique_trace=[],
    )


def build_humanistic_state_from_session(*, session, history_messages: list[dict], last_summary: Optional[dict] = None) -> HumanisticGraphState:
    state = make_initial_humanistic_state(
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
    state['current_stage'] = 'determine_phase' if history_messages else 'session_start'
    return state
