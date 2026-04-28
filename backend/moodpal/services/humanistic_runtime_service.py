from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage

from ..humanistic import HumanisticGraph
from ..humanistic.resonance_evaluator import HumanisticResonanceEvaluator
from ..humanistic.resonance_rule_config import get_resonance_rule
from ..humanistic.signal_extractor import extract_humanistic_turn_signals
from ..humanistic.state import HumanisticGraphState, build_humanistic_state_from_session
from ..runtime.types import ExitEvaluationResult
from .model_option_service import normalize_selected_model
from .runtime_completion_service import complete_runtime_structured_turn


logger = logging.getLogger(__name__)


ALLOWED_STATE_PATCH_KEYS = {
    'current_stage',
    'current_phase',
    'current_technique_id',
    'emotional_intensity',
    'dominant_emotions',
    'emotional_clarity',
    'openness_level',
    'self_attack_flag',
    'shame_signal',
    'body_signal_present',
    'body_focus_ready',
    'felt_sense_description',
    'resonance_score',
    'being_understood_signal',
    'relational_trust',
    'unmet_need_candidate',
    'self_compassion_shift',
    'homework_candidate',
    'safety_status',
    'alliance_rupture_detected',
    'numbness_detected',
    'advice_pull_detected',
    'exception_flags',
    'technique_attempt_count',
    'technique_stall_count',
    'last_progress_marker',
    'circuit_breaker_open',
    'next_fallback_action',
    'technique_trace',
}
PRE_FLIGHT_SIGNAL_KEYS = {
    'emotional_intensity',
    'dominant_emotions',
    'emotional_clarity',
    'openness_level',
    'self_attack_flag',
    'shame_signal',
    'body_signal_present',
    'body_focus_ready',
    'unmet_need_candidate',
    'alliance_rupture_detected',
    'numbness_detected',
    'advice_pull_detected',
    'exception_flags',
}
LOCAL_FALLBACK_STATE_KEYS = {
    'emotional_intensity',
    'dominant_emotions',
    'emotional_clarity',
    'body_signal_present',
    'body_focus_ready',
    'unmet_need_candidate',
    'self_compassion_shift',
}
PERSISTABLE_STATE_KEYS = ALLOWED_STATE_PATCH_KEYS | {
    'therapy_mode',
    'selected_model',
    'session_phase',
}
TURN_RESPONSE_SCHEMA_PROMPT = '\n'.join(
    [
        '请返回一个 JSON 对象，字段固定为：',
        '{',
        '  "reply": "给用户看的自然中文回复",',
        '  "state_patch": {',
        '    "emotional_intensity": 0,',
        '    "dominant_emotions": [],',
        '    "emotional_clarity": "diffuse",',
        '    "openness_level": "partial",',
        '    "self_attack_flag": false,',
        '    "shame_signal": false,',
        '    "body_signal_present": false,',
        '    "body_focus_ready": false,',
        '    "felt_sense_description": "",',
        '    "resonance_score": 0,',
        '    "being_understood_signal": false,',
        '    "relational_trust": "medium",',
        '    "unmet_need_candidate": "",',
        '    "self_compassion_shift": "",',
        '    "homework_candidate": "",',
        '    "alliance_rupture_detected": false,',
        '    "numbness_detected": false,',
        '    "advice_pull_detected": false',
        '  }',
        '}',
        '不要输出 markdown，不要输出额外解释。',
    ]
)


@dataclass(frozen=True)
class HumanisticRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    state: HumanisticGraphState
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_humanistic_turn(*, session, history_messages: list[dict], state_overrides: dict | None = None) -> HumanisticRuntimeTurnResult:
    state = _load_state(session=session, history_messages=history_messages, state_overrides=state_overrides)
    graph = HumanisticGraph()
    plan = graph.plan_turn(state)
    logger.info(
        'MoodPal Humanistic route selected session=%s subject=%s phase=%s technique=%s reason=%s fallback_action=%s circuit_open=%s',
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
        return HumanisticRuntimeTurnResult(
            reply_text=reply_text,
            reply_metadata={
                'engine': 'humanistic_graph',
                'track': plan.selection.track,
                'technique_id': '',
                'reason': plan.selection.reason,
                'fallback_used': True,
                'fallback_kind': 'safety_override',
                'provider': '',
                'model': '',
                'json_mode_degraded': False,
                'completion_mode': 'rule_fallback',
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
            'MoodPal Humanistic local fallback applied session=%s subject=%s phase=%s technique=%s',
            session.id,
            session.usage_subject,
            plan.selection.track,
            plan.selection.technique_id,
        )

    next_state = dict(execution_state)
    next_state.update(_build_effective_execution_state_patch(raw_state_patch, used_fallback=used_fallback))
    next_state['current_phase'] = plan.selection.track
    next_state['current_technique_id'] = plan.selection.technique_id
    next_state['current_stage'] = 'evaluate_resonance'
    next_state['last_assistant_message'] = reply_text

    if used_fallback:
        evaluation = _build_local_fallback_evaluation(next_state, plan.selection.technique_id)
    else:
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
            'MoodPal Humanistic circuit breaker opened session=%s subject=%s technique=%s trip_reason=%s next_action=%s attempts=%s stalls=%s',
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
    return HumanisticRuntimeTurnResult(
        reply_text=reply_text,
        reply_metadata={
            'engine': 'humanistic_graph',
            'track': plan.selection.track,
            'technique_id': plan.selection.technique_id,
            'reason': plan.selection.reason,
            'fallback_action': evaluation.next_fallback_action,
            'fallback_used': used_fallback,
            'fallback_kind': 'llm_local_rule' if used_fallback else '',
            'provider': llm_meta.get('provider', ''),
            'model': llm_meta.get('model', ''),
            'usage': llm_meta.get('usage', {}),
            'json_mode_degraded': bool(llm_meta.get('json_mode_degraded')),
            'completion_mode': llm_meta.get('completion_mode', ''),
            'llm_error_type': llm_meta.get('error_type', ''),
        },
        state=next_state,
        persist_patch=_build_persistable_state_patch(state, next_state),
        used_fallback=used_fallback,
    )


def _load_state(*, session, history_messages: list[dict], state_overrides: dict | None = None) -> HumanisticGraphState:
    metadata = dict(session.metadata or {})
    persisted_state = dict(metadata.get('humanistic_state') or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_humanistic_state_from_session(
        session=session,
        history_messages=history_messages,
        last_summary=last_summary,
    )
    for key, value in persisted_state.items():
        if key in ALLOWED_STATE_PATCH_KEYS or key in {'therapy_mode', 'selected_model'}:
            state[key] = value
    state['session_id'] = str(session.id)
    state['subject_key'] = session.usage_subject
    state['persona_id'] = session.persona_id
    state['surface_persona_id'] = session.persona_id
    state['selected_model'] = session.selected_model
    state['support_directive'] = ''
    state['session_phase'] = session.status
    if history_messages:
        state['last_user_message'] = history_messages[-1].get('content', '') if history_messages[-1].get('role') == 'user' else state.get('last_user_message', '')
        if len(history_messages) >= 2 and history_messages[-2].get('role') == 'assistant':
            state['last_assistant_message'] = history_messages[-2].get('content', '')
    inferred_patch = _build_preflight_signal_patch(state, extract_humanistic_turn_signals(state))
    if _should_apply_inferred_signals(state.get('last_user_message', ''), inferred_patch):
        state.update(inferred_patch)
    if history_messages:
        state['current_stage'] = 'affect_assessment'
    if isinstance(state_overrides, dict):
        for key in ('persona_id', 'surface_persona_id', 'support_directive'):
            if key in state_overrides:
                state[key] = state_overrides[key]
    return state


def merge_humanistic_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    merged_state = dict(next_metadata.get('humanistic_state') or {})
    merged_state.update(_sanitize_persistable_state_patch(state_patch))
    next_metadata['humanistic_state'] = merged_state
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
        'MoodPal Humanistic trace appended session=%s subject=%s turn=%s phase=%s technique=%s progress=%s done=%s circuit_open=%s stage=%s',
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


def _prepare_state_for_selection(state: HumanisticGraphState, technique_id: str) -> HumanisticGraphState:
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
    if inferred_patch.get('dominant_emotions'):
        return True
    if inferred_patch.get('unmet_need_candidate'):
        return True
    if inferred_patch.get('openness_level') == 'guarded':
        return True
    if int(inferred_patch.get('emotional_intensity') or 0) >= 6:
        return True
    signal_flags = (
        'self_attack_flag',
        'shame_signal',
        'body_signal_present',
        'alliance_rupture_detected',
        'numbness_detected',
        'advice_pull_detected',
    )
    return any(bool(inferred_patch.get(key)) for key in signal_flags)


def _build_preflight_signal_patch(state: HumanisticGraphState, inferred_patch: Optional[dict]) -> dict:
    sanitized = _sanitize_state_patch(inferred_patch)
    patch = {
        key: value
        for key, value in sanitized.items()
        if key in PRE_FLIGHT_SIGNAL_KEYS
    }
    if patch.get('alliance_rupture_detected'):
        patch['relational_trust'] = 'weak'
    else:
        patch.pop('relational_trust', None)
    return patch


def _build_effective_execution_state_patch(state_patch: Optional[dict], *, used_fallback: bool) -> dict:
    sanitized = _sanitize_state_patch(state_patch)
    if not used_fallback:
        return sanitized
    return {
        key: value
        for key, value in sanitized.items()
        if key in LOCAL_FALLBACK_STATE_KEYS
    }


def _build_local_fallback_evaluation(state: HumanisticGraphState, technique_id: str) -> ExitEvaluationResult:
    previous_progress = str(state.get('last_progress_marker') or '')
    attempt_count = int(state.get('technique_attempt_count') or 0) + 1
    stall_count = int(state.get('technique_stall_count') or 0) + 1
    should_trip_circuit = bool(state.get('circuit_breaker_open'))
    trip_reason = ''
    next_fallback_action = 'retry_same_technique'

    if not should_trip_circuit and (
        attempt_count >= HumanisticResonanceEvaluator.MAX_ATTEMPTS
        or stall_count >= HumanisticResonanceEvaluator.MAX_STALLS
    ):
        should_trip_circuit = True
        trip_reason = 'attempt_limit_reached' if attempt_count >= HumanisticResonanceEvaluator.MAX_ATTEMPTS else 'stall_limit_reached'
        next_fallback_action = get_resonance_rule(technique_id).trip_action
    elif should_trip_circuit:
        next_fallback_action = str(state.get('next_fallback_action') or get_resonance_rule(technique_id).trip_action)

    return ExitEvaluationResult(
        done=False,
        confidence=0.0,
        reason='local_fallback_no_clinical_progress',
        state_patch={
            'technique_attempt_count': attempt_count,
            'technique_stall_count': stall_count,
            'last_progress_marker': previous_progress,
            'circuit_breaker_open': should_trip_circuit,
            'next_fallback_action': next_fallback_action,
        },
        progress_marker=previous_progress,
        stall_detected=True,
        technique_attempt_count=attempt_count,
        technique_stall_count=stall_count,
        should_trip_circuit=should_trip_circuit,
        trip_reason=trip_reason,
        next_fallback_action=next_fallback_action,
    )


def _sanitize_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    sanitized = {key: value for key, value in state_patch.items() if key in ALLOWED_STATE_PATCH_KEYS}
    if isinstance(sanitized.get('dominant_emotions'), str):
        sanitized['dominant_emotions'] = [item.strip() for item in sanitized['dominant_emotions'].split('、') if item.strip()]
    return sanitized


def _sanitize_persistable_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    sanitized = {key: value for key, value in state_patch.items() if key in PERSISTABLE_STATE_KEYS}
    if isinstance(sanitized.get('dominant_emotions'), str):
        sanitized['dominant_emotions'] = [item.strip() for item in sanitized['dominant_emotions'].split('、') if item.strip()]
    return sanitized


def _serialize_persistable_state(state: HumanisticGraphState) -> dict:
    return {
        key: value
        for key, value in state.items()
        if key in PERSISTABLE_STATE_KEYS
    }


def _build_persistable_state_patch(previous_state: HumanisticGraphState, next_state: HumanisticGraphState) -> dict:
    previous_persistable = _serialize_persistable_state(previous_state)
    next_persistable = _serialize_persistable_state(next_state)
    return {
        key: value
        for key, value in next_persistable.items()
        if previous_persistable.get(key) != value
    }


def _execute_turn(*, session, state: HumanisticGraphState, technique_id: str, system_prompt: str, user_prompt: str, fallback_reply: str):
    provider_name, model_name = _resolve_provider_and_model(session.selected_model)
    schema_prompt = '\n'.join([user_prompt, '', TURN_RESPONSE_SCHEMA_PROMPT])
    try:
        structured = complete_runtime_structured_turn(
            provider_name=provider_name,
            model_name=model_name,
            prompt=schema_prompt,
            system_prompt=system_prompt,
            client_factory=LLMClient,
        )
        result = structured.completion
        payload = structured.payload
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
                source='moodpal.humanistic.turn',
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
            'json_mode_degraded': structured.json_mode_degraded,
            'completion_mode': structured.completion_mode,
            'json_mode_attempted': structured.json_mode_attempted,
            'structured_output_policy': structured.structured_output_policy,
            'max_tokens': structured.max_tokens,
        }, False
    except Exception as exc:
        logger.exception('MoodPal Humanistic turn failed, using local fallback')
        fallback = _build_local_fallback(state=state, technique_id=technique_id, fallback_reply=fallback_reply)
        return fallback['reply'], fallback.get('state_patch') or {}, {
            'provider': provider_name,
            'model': model_name or '',
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
            'json_mode_degraded': False,
            'completion_mode': 'rule_fallback',
            'error_type': exc.__class__.__name__,
        }, True


def _resolve_provider_and_model(selected_model: str) -> tuple[str, Optional[str]]:
    value = normalize_selected_model(selected_model)
    if ':' in value:
        provider_name, model_name = value.split(':', 1)
        provider_name = provider_name.strip() or getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
        return provider_name, model_name.strip() or None
    provider_name = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    return provider_name, value or None


def _build_local_fallback(*, state: HumanisticGraphState, technique_id: str, fallback_reply: str) -> dict:
    user_text = ' '.join((state.get('last_user_message') or '').split())
    compact_text = user_text[:48].rstrip() + '...' if len(user_text) > 48 else user_text

    if technique_id == 'hum_validate_normalize':
        return {
            'reply': fallback_reply or f'听到你说“{compact_text}”，这已经很不容易了。你现在有这样的反应并不奇怪，我先在这里陪着你，不急着把它讲清楚。',
            'state_patch': {
                'emotional_intensity': 7 if int(state.get('emotional_intensity') or 0) >= 8 else max(int(state.get('emotional_intensity') or 0), 6),
                'being_understood_signal': True,
                'relational_trust': 'medium',
            },
        }
    if technique_id == 'hum_reflect_feeling':
        return {
            'reply': fallback_reply or '我听见的可能不只是难受，里面好像还有一点委屈和失落。你看看，我这次贴得近不近？',
            'state_patch': {
                'dominant_emotions': ['委屈', '失落'],
                'emotional_clarity': 'emerging',
            },
        }
    if technique_id == 'hum_body_focus':
        return {
            'reply': fallback_reply or '如果现在一下子说不清，也没关系。我们先不急着解释，只看看那份难受更像卡在胸口、喉咙，还是胃里，好吗？',
            'state_patch': {
                'body_signal_present': True,
                'body_focus_ready': True,
                'felt_sense_description': '胸口有点堵',
                'emotional_clarity': 'emerging',
            },
        }
    if technique_id == 'hum_unconditional_regard':
        return {
            'reply': fallback_reply or '你现在这样责怪自己，说明你真的已经很痛了。我不会急着纠正你，但我想先陪你站在自己这边一点点。',
            'state_patch': {
                'self_attack_flag': False,
                'self_compassion_shift': '允许自己先不要这么狠地责怪自己',
                'resonance_score': 66,
            },
        }
    if technique_id == 'hum_exception_alliance_repair':
        return {
            'reply': fallback_reply or '如果刚才那句话让你更烦了，我先停下来。那可能是我没贴住你。你可以直接告诉我，哪一句最让你觉得我没懂。',
            'state_patch': {
                'alliance_rupture_detected': True,
                'relational_trust': state.get('relational_trust', 'weak') or 'weak',
            },
        }
    if technique_id == 'hum_exception_numbness_unfreeze':
        return {
            'reply': fallback_reply or '先不用逼自己一定要说出一个准确的情绪。我们只抓一点点线索就够了。现在这份空白，更像空掉了、堵住了，还是麻掉了？',
            'state_patch': {
                'numbness_detected': False,
                'body_signal_present': True,
                'felt_sense_description': '像空掉了一块',
                'openness_level': 'partial',
            },
        }
    if technique_id == 'hum_boundary_advice_pull':
        return {
            'reply': fallback_reply or '我知道你现在最受不了的是一点抓手都没有。那我们先不把问题摊太大，只选一个你最想先处理的小点，好吗？',
            'state_patch': {
                'advice_pull_detected': True,
                'openness_level': state.get('openness_level', 'guarded') or 'guarded',
                'homework_candidate': '先选一个最想先处理的小点',
            },
        }
    return {
        'reply': fallback_reply or '我先陪你把这一小步放稳，我们不急着一下子说透。',
        'state_patch': {},
    }
