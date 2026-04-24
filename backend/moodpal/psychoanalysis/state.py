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
    'preflight_dynamic_check',
    'recall_pattern_memory',
    'establish_focus',
    'determine_phase',
    'select_technique',
    'execute_technique',
    'evaluate_insight',
    'handle_repair',
    'wrap_up',
)

PHASES = (
    'containment',
    'association',
    'defense_clarification',
    'pattern_linking',
    'relational_reflection',
    'insight_integration',
    'repair',
    'boundary',
    'closing',
    'safety_override',
    '',
)

FALLBACK_ACTIONS = (
    'retry_same_technique',
    'switch_same_phase',
    'regress_to_containment',
    'jump_to_repair',
    'wrap_up_now',
    'handoff_to_safety',
)


class PsychoanalysisGraphState(TypedDict, total=False):
    session_id: str
    subject_key: str
    persona_id: str
    therapy_mode: Literal['psychoanalysis']
    selected_model: str

    session_phase: Literal['starting', 'active', 'ending', 'summary_pending', 'closed']
    current_stage: Literal[
        'session_start',
        'safety_check',
        'preflight_dynamic_check',
        'recall_pattern_memory',
        'establish_focus',
        'determine_phase',
        'select_technique',
        'execute_technique',
        'evaluate_insight',
        'handle_repair',
        'wrap_up',
    ]
    current_phase: Literal[
        'containment',
        'association',
        'defense_clarification',
        'pattern_linking',
        'relational_reflection',
        'insight_integration',
        'repair',
        'boundary',
        'closing',
        'safety_override',
        '',
    ]
    current_technique_id: str

    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict
    recalled_pattern_memory: list[dict]

    focus_theme: str
    association_openness: Literal['guarded', 'partial', 'open']
    manifest_theme: str
    repetition_theme_candidate: str
    working_hypothesis: str
    pattern_confidence: float
    insight_score: int
    insight_ready: bool
    interpretation_depth: Literal['surface', 'linking', 'integration']

    active_defense: str
    resistance_level: Literal['low', 'medium', 'high']
    alliance_strength: Literal['weak', 'medium', 'strong']
    relational_pull: Literal['approval_seeking', 'testing_authority', 'withdrawing', 'dependency_pull', '']
    here_and_now_triggered: bool
    containment_needed: bool
    emotional_intensity: int

    safety_status: Literal['safe', 'crisis_override']
    alliance_rupture_detected: bool
    resistance_spike_detected: bool
    advice_pull_detected: bool
    exception_flags: dict
    last_route_reason: str
    recalled_pattern_memory_count: int
    recalled_pattern_memory_preview: list[dict]

    technique_attempt_count: int
    technique_stall_count: int
    last_progress_marker: str
    circuit_breaker_open: bool
    next_fallback_action: Literal[
        'retry_same_technique',
        'switch_same_phase',
        'regress_to_containment',
        'jump_to_repair',
        'wrap_up_now',
        'handoff_to_safety',
    ]
    technique_trace: list[dict]


def make_initial_psychoanalysis_state(
    *,
    session_id: str = '',
    subject_key: str = '',
    persona_id: str = '',
    selected_model: str = '',
    session_phase: str = 'active',
    history_messages: Optional[list[dict]] = None,
    last_summary: Optional[dict] = None,
    recalled_pattern_memory: Optional[list[dict]] = None,
) -> PsychoanalysisGraphState:
    return PsychoanalysisGraphState(
        session_id=session_id,
        subject_key=subject_key,
        persona_id=persona_id,
        therapy_mode='psychoanalysis',
        selected_model=selected_model,
        session_phase=session_phase,
        current_stage='session_start',
        current_phase='',
        current_technique_id='',
        history_messages=history_messages or [],
        last_user_message='',
        last_assistant_message='',
        last_summary=last_summary or {},
        recalled_pattern_memory=recalled_pattern_memory or [],
        focus_theme='',
        association_openness='partial',
        manifest_theme='',
        repetition_theme_candidate='',
        working_hypothesis='',
        pattern_confidence=0.0,
        insight_score=0,
        insight_ready=False,
        interpretation_depth='surface',
        active_defense='',
        resistance_level='low',
        alliance_strength='medium',
        relational_pull='',
        here_and_now_triggered=False,
        containment_needed=False,
        emotional_intensity=0,
        safety_status='safe',
        alliance_rupture_detected=False,
        resistance_spike_detected=False,
        advice_pull_detected=False,
        exception_flags={},
        last_route_reason='',
        recalled_pattern_memory_count=0,
        recalled_pattern_memory_preview=[],
        technique_attempt_count=0,
        technique_stall_count=0,
        last_progress_marker='',
        circuit_breaker_open=False,
        next_fallback_action='retry_same_technique',
        technique_trace=[],
    )


def build_psychoanalysis_state_from_session(
    *,
    session,
    history_messages: list[dict],
    last_summary: Optional[dict] = None,
    recalled_pattern_memory: Optional[list[dict]] = None,
) -> PsychoanalysisGraphState:
    state = make_initial_psychoanalysis_state(
        session_id=str(session.id),
        subject_key=session.usage_subject,
        persona_id=session.persona_id,
        selected_model=session.selected_model,
        session_phase=session.status,
        history_messages=history_messages,
        last_summary=last_summary or {},
        recalled_pattern_memory=recalled_pattern_memory or [],
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
