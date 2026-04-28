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
    'extract_routing_signals',
    'support_gate',
    'select_main_track',
    'execute_selected_track',
    'persist_turn',
    'wrap_up',
)

TURN_MODES = (
    'support_only',
    'cbt',
    'psychoanalysis',
    '',
)

SUPPORT_MODES = (
    'opening',
    'repair',
    'handoff',
    'none',
)

MAIN_TRACKS = (
    'cbt',
    'psychoanalysis',
    '',
)

SIGNAL_LEVELS = (
    'low',
    'medium',
    'high',
)

ALLIANCE_STATUSES = (
    'weak',
    'medium',
    'strong',
)


class MasterGuideState(TypedDict, total=False):
    session_id: str
    subject_key: str
    persona_id: str
    therapy_mode: Literal['master_guide']
    selected_model: str
    session_phase: Literal['starting', 'active', 'ending', 'summary_pending', 'closed']

    current_stage: Literal[
        'session_start',
        'extract_routing_signals',
        'support_gate',
        'select_main_track',
        'execute_selected_track',
        'persist_turn',
        'wrap_up',
    ]
    current_turn_mode: Literal['support_only', 'cbt', 'psychoanalysis', '']
    active_main_track: Literal['cbt', 'psychoanalysis', '']
    last_main_track: Literal['cbt', 'psychoanalysis', '']
    support_mode: Literal['opening', 'repair', 'handoff', 'none']

    history_messages: list[dict]
    last_user_message: str
    last_assistant_message: str
    last_summary: dict

    alliance_status: Literal['weak', 'medium', 'strong']
    distress_level: Literal['low', 'medium', 'high']
    problem_clarity: Literal['low', 'medium', 'high']
    action_readiness: Literal['low', 'medium', 'high']
    pattern_signal_strength: Literal['low', 'medium', 'high']
    psychoanalysis_readiness: Literal['low', 'medium', 'high']
    cbt_readiness: Literal['low', 'medium', 'high']
    repair_needed: bool
    recent_track_progress: Literal['none', 'progress', 'stall']

    last_route_reason_code: str
    last_switch_reason_code: str
    switch_count: int
    turn_index: int
    stable_turns_on_current_track: int
    support_only_turn_count: int
    used_cbt: bool
    used_psychoanalysis: bool
    fallback_count: int

    route_trace: list[dict]
    summary_hints: list[str]


def make_initial_master_guide_state(
    *,
    session_id: str = '',
    subject_key: str = '',
    persona_id: str = '',
    selected_model: str = '',
    session_phase: str = 'active',
    history_messages: Optional[list[dict]] = None,
    last_summary: Optional[dict] = None,
) -> MasterGuideState:
    return MasterGuideState(
        session_id=session_id,
        subject_key=subject_key,
        persona_id=persona_id,
        therapy_mode='master_guide',
        selected_model=selected_model,
        session_phase=session_phase,
        current_stage='session_start',
        current_turn_mode='',
        active_main_track='',
        last_main_track='',
        support_mode='none',
        history_messages=history_messages or [],
        last_user_message='',
        last_assistant_message='',
        last_summary=last_summary or {},
        alliance_status='medium',
        distress_level='medium',
        problem_clarity='low',
        action_readiness='low',
        pattern_signal_strength='low',
        psychoanalysis_readiness='low',
        cbt_readiness='low',
        repair_needed=False,
        recent_track_progress='none',
        last_route_reason_code='',
        last_switch_reason_code='',
        switch_count=0,
        turn_index=0,
        stable_turns_on_current_track=0,
        support_only_turn_count=0,
        used_cbt=False,
        used_psychoanalysis=False,
        fallback_count=0,
        route_trace=[],
        summary_hints=[],
    )


def build_master_guide_state_from_session(*, session, history_messages: list[dict], last_summary: Optional[dict] = None) -> MasterGuideState:
    state = make_initial_master_guide_state(
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
    state['current_stage'] = 'extract_routing_signals' if history_messages else 'session_start'
    state['turn_index'] = sum(1 for message in history_messages if message.get('role') == 'assistant')
    return state
