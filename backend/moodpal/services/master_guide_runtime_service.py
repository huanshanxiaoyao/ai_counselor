from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..master_guide import MasterGuideGraph
from ..master_guide.state import MasterGuideState, build_master_guide_state_from_session
from ..master_guide.summary_projection import append_summary_hint
from .cbt_runtime_service import merge_cbt_state_metadata, run_cbt_turn
from .humanistic_runtime_service import merge_humanistic_state_metadata, run_humanistic_turn
from .psychoanalysis_runtime_service import merge_psychoanalysis_state_metadata, run_psychoanalysis_turn


logger = logging.getLogger(__name__)


MASTER_GUIDE_STATE_KEYS = {
    'therapy_mode',
    'selected_model',
    'session_phase',
    'current_stage',
    'current_turn_mode',
    'active_main_track',
    'last_main_track',
    'support_mode',
    'alliance_status',
    'distress_level',
    'problem_clarity',
    'action_readiness',
    'pattern_signal_strength',
    'psychoanalysis_readiness',
    'cbt_readiness',
    'repair_needed',
    'recent_track_progress',
    'last_route_reason_code',
    'last_switch_reason_code',
    'switch_count',
    'turn_index',
    'stable_turns_on_current_track',
    'support_only_turn_count',
    'used_cbt',
    'used_psychoanalysis',
    'fallback_count',
    'route_trace',
    'summary_hints',
}


@dataclass(frozen=True)
class MasterGuideRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    state: MasterGuideState
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


@dataclass(frozen=True)
class _ChildRuntimeResult:
    state_key: str
    reply_text: str
    reply_metadata: dict
    persist_patch: dict
    used_fallback: bool = False
    state: dict = field(default_factory=dict)


def run_master_guide_turn(*, session, history_messages: list[dict]) -> MasterGuideRuntimeTurnResult:
    state = _load_state(session=session, history_messages=history_messages)
    graph = MasterGuideGraph()
    plan = graph.plan_turn(state)
    logger.info(
        'MoodPal Master Guide route selected session=%s subject=%s mode=%s reason=%s active_track=%s',
        session.id,
        session.usage_subject,
        plan.selection.mode,
        plan.selection.reason_code,
        state.get('active_main_track', ''),
    )

    child_result = _execute_child_runtime(
        session=session,
        history_messages=history_messages,
        selection=plan.selection,
    )
    next_state = _build_next_state(
        previous_state=state,
        selection=plan.selection,
        signals=plan.signals,
        child_result=child_result,
    )

    persist_patch = {'master_guide_state': _build_master_guide_persist_patch(state, next_state)}
    if child_result.persist_patch:
        persist_patch[child_result.state_key] = child_result.persist_patch

    reply_metadata = {
        'engine': 'master_guide_orchestrator',
        'selected_mode': plan.selection.mode,
        'reason_code': plan.selection.reason_code,
        'support_mode': plan.selection.support_mode,
        'support_directive': plan.selection.support_directive,
        'switch_from': plan.selection.switch_from,
        'switch_to': plan.selection.switch_to,
        'child_engine': child_result.reply_metadata.get('engine', ''),
        'track': child_result.reply_metadata.get('track', ''),
        'technique_id': child_result.reply_metadata.get('technique_id', ''),
        'fallback_action': child_result.reply_metadata.get('fallback_action', ''),
        'fallback_used': child_result.used_fallback,
        'fallback_kind': child_result.reply_metadata.get('fallback_kind', 'llm_local_rule' if child_result.used_fallback else ''),
        'provider': child_result.reply_metadata.get('provider', ''),
        'model': child_result.reply_metadata.get('model', ''),
        'usage': child_result.reply_metadata.get('usage', {}),
        'json_mode_degraded': bool(child_result.reply_metadata.get('json_mode_degraded')),
        'completion_mode': child_result.reply_metadata.get('completion_mode', ''),
        'llm_error_type': child_result.reply_metadata.get('llm_error_type', ''),
    }
    return MasterGuideRuntimeTurnResult(
        reply_text=child_result.reply_text,
        reply_metadata=reply_metadata,
        state=next_state,
        persist_patch=persist_patch,
        used_fallback=child_result.used_fallback,
    )


def merge_master_guide_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    if not isinstance(state_patch, dict):
        return next_metadata

    if state_patch.get('master_guide_state'):
        merged_master_state = dict(next_metadata.get('master_guide_state') or {})
        merged_master_state.update(_sanitize_master_guide_state_patch(state_patch.get('master_guide_state')))
        next_metadata['master_guide_state'] = merged_master_state
    if state_patch.get('humanistic_state'):
        next_metadata = merge_humanistic_state_metadata(next_metadata, state_patch.get('humanistic_state'))
    if state_patch.get('cbt_state'):
        next_metadata = merge_cbt_state_metadata(next_metadata, state_patch.get('cbt_state'))
    if state_patch.get('psychoanalysis_state'):
        next_metadata = merge_psychoanalysis_state_metadata(next_metadata, state_patch.get('psychoanalysis_state'))
    return next_metadata


def _load_state(*, session, history_messages: list[dict]) -> MasterGuideState:
    metadata = dict(session.metadata or {})
    persisted_state = dict(metadata.get('master_guide_state') or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_master_guide_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    for key, value in persisted_state.items():
        if key in MASTER_GUIDE_STATE_KEYS:
            state[key] = value
    state['session_id'] = str(session.id)
    state['subject_key'] = session.usage_subject
    state['persona_id'] = session.persona_id
    state['selected_model'] = session.selected_model
    state['session_phase'] = session.status
    state['cbt_state'] = dict(metadata.get('cbt_state') or {})
    state['humanistic_state'] = dict(metadata.get('humanistic_state') or {})
    state['psychoanalysis_state'] = dict(metadata.get('psychoanalysis_state') or {})
    if history_messages:
        state['current_stage'] = 'extract_routing_signals'
    return state


def _execute_child_runtime(*, session, history_messages: list[dict], selection) -> _ChildRuntimeResult:
    state_overrides = {
        'surface_persona_id': session.persona_id,
        'support_directive': selection.support_directive,
    }
    if selection.mode == 'support_only':
        result = run_humanistic_turn(session=session, history_messages=history_messages, state_overrides=state_overrides)
        return _ChildRuntimeResult(
            state_key='humanistic_state',
            reply_text=result.reply_text,
            reply_metadata=result.reply_metadata,
            persist_patch=result.persist_patch,
            used_fallback=result.used_fallback,
            state=result.state,
        )
    if selection.mode == 'psychoanalysis':
        result = run_psychoanalysis_turn(session=session, history_messages=history_messages, state_overrides=state_overrides)
        return _ChildRuntimeResult(
            state_key='psychoanalysis_state',
            reply_text=result.reply_text,
            reply_metadata=result.reply_metadata,
            persist_patch=result.persist_patch,
            used_fallback=result.used_fallback,
            state=result.state,
        )
    result = run_cbt_turn(session=session, history_messages=history_messages, state_overrides=state_overrides)
    return _ChildRuntimeResult(
        state_key='cbt_state',
        reply_text=result.reply_text,
        reply_metadata=result.reply_metadata,
        persist_patch=result.persist_patch,
        used_fallback=result.used_fallback,
        state=result.state,
    )


def _build_next_state(*, previous_state: MasterGuideState, selection, signals: dict, child_result: _ChildRuntimeResult) -> MasterGuideState:
    next_state = dict(previous_state)
    previous_track = str(previous_state.get('active_main_track') or '')
    next_state.update(
        {
            'current_stage': 'persist_turn',
            'current_turn_mode': selection.mode,
            'support_mode': selection.support_mode,
            'alliance_status': signals.get('alliance_status', 'medium'),
            'distress_level': signals.get('distress_level', 'medium'),
            'problem_clarity': signals.get('problem_clarity', 'low'),
            'action_readiness': signals.get('action_readiness', 'low'),
            'pattern_signal_strength': signals.get('pattern_signal_strength', 'low'),
            'psychoanalysis_readiness': signals.get('psychoanalysis_readiness', 'low'),
            'cbt_readiness': signals.get('cbt_readiness', 'low'),
            'repair_needed': bool(signals.get('repair_needed')),
            'recent_track_progress': signals.get('recent_track_progress', 'none'),
            'last_route_reason_code': selection.reason_code,
            'turn_index': int(previous_state.get('turn_index') or 0) + 1,
        }
    )

    if selection.mode in {'cbt', 'psychoanalysis'}:
        next_state['last_main_track'] = previous_track
        next_state['active_main_track'] = selection.mode
        if previous_track and previous_track != selection.mode:
            next_state['switch_count'] = int(previous_state.get('switch_count') or 0) + 1
            next_state['last_switch_reason_code'] = selection.reason_code
            next_state['stable_turns_on_current_track'] = 1
        elif previous_track == selection.mode:
            next_state['stable_turns_on_current_track'] = int(previous_state.get('stable_turns_on_current_track') or 0) + 1
        else:
            next_state['stable_turns_on_current_track'] = 1
    else:
        next_state['last_main_track'] = previous_track
        next_state['support_only_turn_count'] = int(previous_state.get('support_only_turn_count') or 0) + 1

    if selection.mode == 'cbt':
        next_state['used_cbt'] = True
    if selection.mode == 'psychoanalysis':
        next_state['used_psychoanalysis'] = True
    if child_result.used_fallback:
        next_state['fallback_count'] = int(previous_state.get('fallback_count') or 0) + 1

    route_trace = list(previous_state.get('route_trace') or [])
    progress_marker = str(child_result.state.get('last_progress_marker') or selection.reason_code)
    route_trace.append(
        {
            'turn_index': int(next_state.get('turn_index') or 0),
            'mode': selection.mode,
            'switch_from': selection.switch_from,
            'switch_to': selection.switch_to,
            'reason_code': selection.reason_code,
            'support_before': selection.support_mode if selection.mode == 'support_only' else 'none',
            'support_after': selection.support_mode if selection.mode != 'support_only' else 'none',
            'progress_marker': progress_marker,
            'fallback_used': child_result.used_fallback,
        }
    )
    next_state['route_trace'] = route_trace[-10:]
    next_state['summary_hints'] = append_summary_hint(previous_state.get('summary_hints') or [], selection)
    return MasterGuideState(next_state)


def _sanitize_master_guide_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    return {key: value for key, value in state_patch.items() if key in MASTER_GUIDE_STATE_KEYS}


def _serialize_master_guide_state(state: MasterGuideState) -> dict:
    return {
        key: value
        for key, value in state.items()
        if key in MASTER_GUIDE_STATE_KEYS
    }


def _build_master_guide_persist_patch(previous_state: MasterGuideState, next_state: MasterGuideState) -> dict:
    previous_persistable = _serialize_master_guide_state(previous_state)
    next_persistable = _serialize_master_guide_state(next_state)
    return {
        key: value
        for key, value in next_persistable.items()
        if previous_persistable.get(key) != value
    }
