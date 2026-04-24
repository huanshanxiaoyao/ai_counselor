from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage

from ..psychoanalysis import PsychoanalysisGraph
from ..psychoanalysis.pattern_memory import load_recent_pattern_memory
from ..psychoanalysis.signal_extractor import extract_psychoanalysis_turn_signals
from ..psychoanalysis.state import PsychoanalysisGraphState, build_psychoanalysis_state_from_session
from .model_option_service import normalize_selected_model


logger = logging.getLogger(__name__)


ALLOWED_STATE_PATCH_KEYS = {
    'current_stage',
    'current_phase',
    'current_technique_id',
    'focus_theme',
    'association_openness',
    'manifest_theme',
    'repetition_theme_candidate',
    'working_hypothesis',
    'pattern_confidence',
    'insight_score',
    'insight_ready',
    'interpretation_depth',
    'active_defense',
    'resistance_level',
    'alliance_strength',
    'relational_pull',
    'here_and_now_triggered',
    'containment_needed',
    'emotional_intensity',
    'safety_status',
    'alliance_rupture_detected',
    'resistance_spike_detected',
    'advice_pull_detected',
    'exception_flags',
    'last_route_reason',
    'recalled_pattern_memory_count',
    'recalled_pattern_memory_preview',
    'technique_attempt_count',
    'technique_stall_count',
    'last_progress_marker',
    'circuit_breaker_open',
    'next_fallback_action',
    'technique_trace',
}
PERSISTABLE_STATE_KEYS = ALLOWED_STATE_PATCH_KEYS | {
    'therapy_mode',
    'selected_model',
    'session_phase',
}
FORCE_PERSIST_STATE_KEYS = {
    'last_route_reason',
    'recalled_pattern_memory_count',
    'recalled_pattern_memory_preview',
}
TURN_RESPONSE_SCHEMA_PROMPT = '\n'.join(
    [
        '请返回一个 JSON 对象，字段固定为：',
        '{',
        '  "reply": "给用户看的自然中文回复",',
        '  "state_patch": {',
        '    "focus_theme": "",',
        '    "association_openness": "partial",',
        '    "manifest_theme": "",',
        '    "repetition_theme_candidate": "",',
        '    "working_hypothesis": "",',
        '    "pattern_confidence": 0.0,',
        '    "insight_score": 0,',
        '    "insight_ready": false,',
        '    "interpretation_depth": "surface",',
        '    "active_defense": "",',
        '    "resistance_level": "low",',
        '    "alliance_strength": "medium",',
        '    "relational_pull": "",',
        '    "here_and_now_triggered": false,',
        '    "containment_needed": false,',
        '    "emotional_intensity": 0,',
        '    "alliance_rupture_detected": false,',
        '    "resistance_spike_detected": false,',
        '    "advice_pull_detected": false',
        '  }',
        '}',
        '不要输出 markdown，不要输出额外解释。',
    ]
)


@dataclass(frozen=True)
class PsychoanalysisRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    state: PsychoanalysisGraphState
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_psychoanalysis_turn(*, session, history_messages: list[dict]) -> PsychoanalysisRuntimeTurnResult:
    state = _load_state(session=session, history_messages=history_messages)
    graph = PsychoanalysisGraph()
    plan = graph.plan_turn(state)
    logger.info(
        'MoodPal Psychoanalysis route selected session=%s subject=%s phase=%s technique=%s reason=%s fallback_action=%s circuit_open=%s',
        session.id,
        session.usage_subject,
        plan.selection.track,
        plan.selection.technique_id,
        plan.selection.reason,
        plan.selection.fallback_action,
        bool(state.get('circuit_breaker_open')),
    )
    execution_state = _prepare_state_for_selection(state, plan.selection.technique_id)

    if not plan.selection.technique_id:
        reply_text = '我先停一下。你刚才提到的内容可能涉及更高优先级的安全风险，这里不继续走普通对话流程。'
        next_state = dict(execution_state)
        next_state['current_stage'] = 'wrap_up'
        next_state['current_phase'] = plan.selection.track
        next_state['last_route_reason'] = plan.selection.reason
        _append_trace(next_state, plan.selection, progress_marker='safety_override', done=True, should_trip_circuit=False)
        _log_trace(
            session=session,
            state=next_state,
            phase=plan.selection.track,
            technique_id=plan.selection.technique_id,
            progress_marker='safety_override',
            done=True,
            should_trip_circuit=False,
        )
        return PsychoanalysisRuntimeTurnResult(
            reply_text=reply_text,
            reply_metadata={
                'engine': 'psychoanalysis_graph',
                'track': plan.selection.track,
                'technique_id': '',
                'reason': plan.selection.reason,
                'fallback_used': True,
                'provider': '',
                'model': '',
            },
            state=next_state,
            persist_patch=_build_persistable_state_patch(state, next_state),
            used_fallback=True,
        )

    reply_text, raw_state_patch, llm_meta, used_fallback = _execute_turn(
        session=session,
        state=execution_state,
        technique_id=plan.selection.technique_id,
        system_prompt=plan.payload.system_prompt,
        user_prompt=plan.payload.user_prompt,
        fallback_reply=plan.payload.visible_reply_hint,
    )
    if used_fallback:
        logger.warning(
            'MoodPal Psychoanalysis local fallback applied session=%s subject=%s phase=%s technique=%s',
            session.id,
            session.usage_subject,
            plan.selection.track,
            plan.selection.technique_id,
        )

    next_state = dict(execution_state)
    next_state.update(_sanitize_state_patch(raw_state_patch))
    next_state['current_phase'] = plan.selection.track
    next_state['current_technique_id'] = plan.selection.technique_id
    next_state['current_stage'] = 'evaluate_insight'
    next_state['last_assistant_message'] = reply_text
    next_state['last_route_reason'] = plan.selection.reason

    evaluation = graph.evaluate_turn(next_state, plan.selection.technique_id)
    next_state.update(_sanitize_state_patch(evaluation.state_patch))

    if evaluation.should_trip_circuit:
        next_state['current_stage'] = 'wrap_up' if evaluation.next_fallback_action == 'wrap_up_now' else 'determine_phase'
    elif evaluation.done:
        next_state['current_stage'] = 'wrap_up' if evaluation.next_fallback_action == 'wrap_up_now' else 'determine_phase'
    else:
        next_state['current_stage'] = 'execute_technique'

    _append_trace(
        next_state,
        plan.selection,
        progress_marker=evaluation.progress_marker or next_state.get('last_progress_marker', ''),
        done=evaluation.done,
        should_trip_circuit=evaluation.should_trip_circuit,
    )
    if evaluation.should_trip_circuit:
        logger.warning(
            'MoodPal Psychoanalysis circuit breaker opened session=%s subject=%s technique=%s trip_reason=%s next_action=%s attempts=%s stalls=%s',
            session.id,
            session.usage_subject,
            plan.selection.technique_id,
            evaluation.trip_reason,
            evaluation.next_fallback_action,
            evaluation.technique_attempt_count,
            evaluation.technique_stall_count,
        )
    _log_trace(
        session=session,
        state=next_state,
        phase=plan.selection.track,
        technique_id=plan.selection.technique_id,
        progress_marker=evaluation.progress_marker or next_state.get('last_progress_marker', ''),
        done=evaluation.done,
        should_trip_circuit=evaluation.should_trip_circuit,
    )
    return PsychoanalysisRuntimeTurnResult(
        reply_text=reply_text,
        reply_metadata={
            'engine': 'psychoanalysis_graph',
            'track': plan.selection.track,
            'technique_id': plan.selection.technique_id,
            'reason': plan.selection.reason,
            'fallback_action': evaluation.next_fallback_action,
            'fallback_used': used_fallback,
            'provider': llm_meta.get('provider', ''),
            'model': llm_meta.get('model', ''),
            'usage': llm_meta.get('usage', {}),
        },
        state=next_state,
        persist_patch=_build_persistable_state_patch(state, next_state),
        used_fallback=used_fallback,
    )


def _load_state(*, session, history_messages: list[dict]) -> PsychoanalysisGraphState:
    metadata = dict(session.metadata or {})
    persisted_state = dict(metadata.get('psychoanalysis_state') or {})
    last_summary = metadata.get('last_summary') or {}
    recalled_pattern_memory = load_recent_pattern_memory(session=session)
    state = build_psychoanalysis_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
        recalled_pattern_memory=recalled_pattern_memory,
    )
    for key, value in persisted_state.items():
        if key in ALLOWED_STATE_PATCH_KEYS or key in {'therapy_mode', 'selected_model'}:
            state[key] = value
    state['session_id'] = str(session.id)
    state['subject_key'] = session.usage_subject
    state['persona_id'] = session.persona_id
    state['selected_model'] = session.selected_model
    state['session_phase'] = session.status
    state['recalled_pattern_memory'] = recalled_pattern_memory
    state['recalled_pattern_memory_count'] = len(recalled_pattern_memory)
    state['recalled_pattern_memory_preview'] = _build_recalled_pattern_memory_preview(recalled_pattern_memory)
    if history_messages:
        state['last_user_message'] = history_messages[-1].get('content', '') if history_messages[-1].get('role') == 'user' else state.get('last_user_message', '')
        if len(history_messages) >= 2 and history_messages[-2].get('role') == 'assistant':
            state['last_assistant_message'] = history_messages[-2].get('content', '')
    inferred_patch = extract_psychoanalysis_turn_signals(state)
    if _should_apply_inferred_signals(state.get('last_user_message', ''), inferred_patch):
        state.update(_sanitize_state_patch(inferred_patch))
    if history_messages:
        state['current_stage'] = 'determine_phase'
    return state


def merge_psychoanalysis_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    merged_state = dict(next_metadata.get('psychoanalysis_state') or {})
    merged_state.update(_sanitize_persistable_state_patch(state_patch))
    next_metadata['psychoanalysis_state'] = merged_state
    return next_metadata


def _append_trace(state: dict, selection, *, progress_marker: str, done: bool, should_trip_circuit: bool):
    trace = list(state.get('technique_trace') or [])
    trace.append(
        {
            'turn_index': len(trace) + 1,
            'phase': selection.track,
            'technique_id': selection.technique_id,
            'progress_marker': progress_marker,
            'done': done,
            'should_trip_circuit': should_trip_circuit,
        }
    )
    state['technique_trace'] = trace


def _log_trace(*, session, state: dict, phase: str, technique_id: str, progress_marker: str, done: bool, should_trip_circuit: bool):
    trace = list(state.get('technique_trace') or [])
    turn_index = trace[-1]['turn_index'] if trace else 0
    logger.info(
        'MoodPal Psychoanalysis trace appended session=%s subject=%s turn=%s phase=%s technique=%s progress=%s done=%s circuit_open=%s stage=%s',
        session.id,
        session.usage_subject,
        turn_index,
        phase,
        technique_id,
        progress_marker,
        done,
        should_trip_circuit,
        state.get('current_stage', ''),
    )


def _prepare_state_for_selection(state: PsychoanalysisGraphState, technique_id: str) -> PsychoanalysisGraphState:
    next_state = dict(state)
    current_technique_id = (next_state.get('current_technique_id') or '').strip()
    if technique_id and technique_id != current_technique_id:
        next_state['technique_attempt_count'] = 0
        next_state['technique_stall_count'] = 0
        next_state['last_progress_marker'] = ''
        next_state['circuit_breaker_open'] = False
        next_state['next_fallback_action'] = 'retry_same_technique'
    return next_state


def _should_apply_inferred_signals(user_text: str, inferred_patch: dict) -> bool:
    source = (user_text or '').strip()
    if not source:
        return False
    if len(source) >= 8:
        return True
    if inferred_patch.get('repetition_theme_candidate'):
        return True
    if inferred_patch.get('active_defense'):
        return True
    if inferred_patch.get('relational_pull'):
        return True
    if inferred_patch.get('association_openness') == 'guarded':
        return True
    signal_flags = (
        'alliance_rupture_detected',
        'resistance_spike_detected',
        'advice_pull_detected',
        'here_and_now_triggered',
        'containment_needed',
    )
    return any(bool(inferred_patch.get(key)) for key in signal_flags)


def _sanitize_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    sanitized = {key: value for key, value in state_patch.items() if key in ALLOWED_STATE_PATCH_KEYS}
    if 'recalled_pattern_memory_preview' in sanitized and not isinstance(sanitized['recalled_pattern_memory_preview'], list):
        sanitized['recalled_pattern_memory_preview'] = []
    if 'pattern_confidence' in sanitized:
        try:
            sanitized['pattern_confidence'] = float(sanitized['pattern_confidence'] or 0.0)
        except (TypeError, ValueError):
            sanitized['pattern_confidence'] = 0.0
    if 'insight_score' in sanitized:
        try:
            sanitized['insight_score'] = max(0, min(10, int(sanitized['insight_score'] or 0)))
        except (TypeError, ValueError):
            sanitized['insight_score'] = 0
    if 'emotional_intensity' in sanitized:
        try:
            sanitized['emotional_intensity'] = max(0, min(10, int(sanitized['emotional_intensity'] or 0)))
        except (TypeError, ValueError):
            sanitized['emotional_intensity'] = 0
    return sanitized


def _sanitize_persistable_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    filtered = {key: value for key, value in state_patch.items() if key in PERSISTABLE_STATE_KEYS}
    allowed_subset = _sanitize_state_patch({key: value for key, value in filtered.items() if key in ALLOWED_STATE_PATCH_KEYS})
    for key in ('therapy_mode', 'selected_model', 'session_phase'):
        if key in filtered:
            allowed_subset[key] = filtered[key]
    return allowed_subset


def _serialize_persistable_state(state: PsychoanalysisGraphState) -> dict:
    return {
        key: value
        for key, value in state.items()
        if key in PERSISTABLE_STATE_KEYS
    }


def _build_persistable_state_patch(previous_state: PsychoanalysisGraphState, next_state: PsychoanalysisGraphState) -> dict:
    previous_persistable = _serialize_persistable_state(previous_state)
    next_persistable = _serialize_persistable_state(next_state)
    return {
        key: value
        for key, value in next_persistable.items()
        if key in FORCE_PERSIST_STATE_KEYS or previous_persistable.get(key) != value
    }


def _build_recalled_pattern_memory_preview(recalled_pattern_memory: list[dict]) -> list[dict]:
    preview: list[dict] = []
    for entry in recalled_pattern_memory[:2]:
        preview.append(
            {
                'repetition_themes': list(entry.get('repetition_themes') or [])[:2],
                'defense_patterns': list(entry.get('defense_patterns') or [])[:2],
                'relational_pull': list(entry.get('relational_pull') or [])[:2],
                'working_hypotheses': list(entry.get('working_hypotheses') or [])[:2],
            }
        )
    return preview


def _execute_turn(*, session, state: PsychoanalysisGraphState, technique_id: str, system_prompt: str, user_prompt: str, fallback_reply: str):
    provider_name, model_name = _resolve_provider_and_model(session.selected_model)
    schema_prompt = '\n'.join([user_prompt, '', TURN_RESPONSE_SCHEMA_PROMPT])
    try:
        client = LLMClient(provider_name=provider_name)
        result = client.complete_with_metadata(
            prompt=schema_prompt,
            system_prompt=system_prompt,
            model=model_name or None,
            json_mode=True,
        )
        payload = json.loads(result.text or '{}')
        reply_text = (payload.get('reply') or '').strip()
        if not reply_text:
            raise ValueError('empty_reply')
        usage = {
            'prompt_tokens': result.usage.prompt_tokens,
            'completion_tokens': result.usage.completion_tokens,
            'total_tokens': result.usage.total_tokens,
        }
        if result.usage.total_tokens > 0:
            record_token_usage(
                subject=parse_subject_key(session.usage_subject),
                source='moodpal.psychoanalysis.turn',
                total_tokens=result.usage.total_tokens,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                provider=provider_name,
                model=result.model,
                metadata={'technique_id': technique_id},
            )
        return reply_text, payload.get('state_patch') or {}, {
            'provider': provider_name,
            'model': result.model,
            'usage': usage,
        }, False
    except Exception:
        logger.exception('MoodPal Psychoanalysis turn failed, using local fallback')
        fallback = _build_local_fallback(state=state, technique_id=technique_id, fallback_reply=fallback_reply)
        return fallback['reply'], fallback.get('state_patch') or {}, {
            'provider': provider_name,
            'model': model_name or '',
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
        }, True


def _resolve_provider_and_model(selected_model: str) -> tuple[str, Optional[str]]:
    value = normalize_selected_model(selected_model)
    if ':' in value:
        provider_name, model_name = value.split(':', 1)
        provider_name = provider_name.strip() or getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
        return provider_name, model_name.strip() or None
    provider_name = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    return provider_name, value or None


def _build_local_fallback(*, state: PsychoanalysisGraphState, technique_id: str, fallback_reply: str) -> dict:
    user_text = ' '.join((state.get('last_user_message') or '').split())
    compact_text = user_text[:56].rstrip() + '...' if len(user_text) > 56 else user_text

    if technique_id == 'psa_entry_containment':
        return {
            'reply': fallback_reply or f'我们先不急着把这件事说透。你刚才提到“{compact_text}”，我会先把这句放在这里。我们只从这一小块开始，也可以。',
            'state_patch': {
                'containment_needed': False,
                'association_openness': 'partial',
                'focus_theme': compact_text or state.get('focus_theme', ''),
            },
        }
    if technique_id == 'psa_association_invite':
        return {
            'reply': fallback_reply or '刚才那里面像是已经有一条线露出来了。我们先不急着解释，只跟着那条最有感觉的线，再往前走一点点。',
            'state_patch': {
                'focus_theme': compact_text or state.get('focus_theme', ''),
                'manifest_theme': compact_text or state.get('manifest_theme', ''),
                'association_openness': 'open' if len(user_text) >= 24 else 'partial',
            },
        }
    if technique_id == 'psa_defense_clarification':
        return {
            'reply': fallback_reply or '我有点注意到，每次一靠近那个让你难受的地方，你的话就会很快轻下来，像是有一部分你想先把自己收回去。我们先只看见这个动作。',
            'state_patch': {
                'active_defense': state.get('active_defense', '') or 'withdrawal',
                'resistance_level': 'medium',
            },
        }
    if technique_id == 'psa_pattern_linking':
        return {
            'reply': fallback_reply or '这听起来好像不只是这一回的偶发反应，而是一条反复会出现的线。我们先不急着解释它从哪里来，只把这条重复看清一点。',
            'state_patch': {
                'repetition_theme_candidate': state.get('repetition_theme_candidate', '') or 'repetition_pattern_present',
                'pattern_confidence': max(float(state.get('pattern_confidence') or 0.0), 0.66),
            },
        }
    if technique_id == 'psa_relational_here_now':
        return {
            'reply': fallback_reply or '好像就在刚才这一刻，你和我之间也突然有一点收紧了。我们可以先不谈别的，只停在这一刻，看看你最想从我这里防着的是什么。',
            'state_patch': {
                'here_and_now_triggered': True,
                'relational_pull': state.get('relational_pull', '') or 'testing_authority',
            },
        }
    if technique_id == 'psa_insight_integration':
        return {
            'reply': fallback_reply or '我在想，会不会你心里一直有一套很快启动的保护方式：一感觉到关系里有点危险，你就先把问题收回到自己身上。这个理解不一定完全对，你听听看，哪一部分最贴近你？',
            'state_patch': {
                'working_hypothesis': state.get('working_hypothesis', '') or '一感到关系紧张，就会先把问题收回到自己身上',
                'insight_score': max(int(state.get('insight_score') or 0), 6),
                'interpretation_depth': 'integration',
            },
        }
    if technique_id == 'psa_exception_resistance_soften':
        return {
            'reply': fallback_reply or '我们可以先不硬往下走。你这句想退开的感觉很重要，我不会把门硬掰开。我们先只看见那个想收回去的动作，就已经够了。',
            'state_patch': {
                'resistance_spike_detected': False,
                'resistance_level': 'medium',
                'association_openness': 'partial',
            },
        }
    if technique_id == 'psa_exception_alliance_repair':
        return {
            'reply': fallback_reply or '如果刚才那句话让你更想退开了，我先收回来。那可能是我没有贴住你。你可以直接告诉我，哪一句最让你觉得不对，我先把那里听明白。',
            'state_patch': {
                'alliance_rupture_detected': False,
                'alliance_strength': 'medium',
            },
        }
    if technique_id == 'psa_boundary_advice_pull':
        return {
            'reply': fallback_reply or '我听见你现在最受不了的是一点抓手都没有。那我们先不把问题摊太大，只选一个你最想先处理的小点，好吗？',
            'state_patch': {
                'advice_pull_detected': False,
                'association_openness': 'partial',
                'focus_theme': state.get('focus_theme', '') or compact_text,
            },
        }
    if technique_id == 'psa_reflective_close':
        return {
            'reply': fallback_reply or '今天我们先把这条线轻轻放在这里：一感觉到别人不高兴，你就会很快把自己收回去。接下来不需要急着改掉它。下次它再冒出来时，只要先认出它，就已经很够了。',
            'state_patch': {
                'working_hypothesis': state.get('working_hypothesis', '') or '一感觉到别人不高兴，就会先把自己收回去',
                'insight_score': max(int(state.get('insight_score') or 0), 5),
            },
        }
    return {
        'reply': fallback_reply or '我们先把这一小步放稳，不急着一下子看透。',
        'state_patch': {},
    }
