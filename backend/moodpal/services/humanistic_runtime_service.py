from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage

from ..humanistic import HumanisticGraph
from ..humanistic.signal_extractor import extract_humanistic_turn_signals
from ..humanistic.state import HumanisticGraphState, build_humanistic_state_from_session
from .model_option_service import normalize_selected_model


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


def run_humanistic_turn(*, session, history_messages: list[dict]) -> HumanisticRuntimeTurnResult:
    state = _load_state(session=session, history_messages=history_messages)
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
            'MoodPal Humanistic local fallback applied session=%s subject=%s phase=%s technique=%s',
            session.id,
            session.usage_subject,
            plan.selection.track,
            plan.selection.technique_id,
        )

    next_state = dict(execution_state)
    next_state.update(_sanitize_state_patch(raw_state_patch))
    next_state['current_phase'] = plan.selection.track
    next_state['current_technique_id'] = plan.selection.technique_id
    next_state['current_stage'] = 'evaluate_resonance'
    next_state['last_assistant_message'] = reply_text

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
            'provider': llm_meta.get('provider', ''),
            'model': llm_meta.get('model', ''),
            'usage': llm_meta.get('usage', {}),
        },
        state=next_state,
        persist_patch=_build_persistable_state_patch(state, next_state),
        used_fallback=used_fallback,
    )


def _load_state(*, session, history_messages: list[dict]) -> HumanisticGraphState:
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
    state['selected_model'] = session.selected_model
    state['session_phase'] = session.status
    if history_messages:
        state['last_user_message'] = history_messages[-1].get('content', '') if history_messages[-1].get('role') == 'user' else state.get('last_user_message', '')
        if len(history_messages) >= 2 and history_messages[-2].get('role') == 'assistant':
            state['last_assistant_message'] = history_messages[-2].get('content', '')
    inferred_patch = extract_humanistic_turn_signals(state)
    state.update(_sanitize_state_patch(inferred_patch))
    if history_messages:
        state['current_stage'] = 'affect_assessment'
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
        }, False
    except Exception:
        logger.exception('MoodPal Humanistic turn failed, using local fallback')
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
                'alliance_rupture_detected': False,
                'relational_trust': 'medium',
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
                'advice_pull_detected': False,
                'openness_level': 'partial',
                'homework_candidate': '先选一个最想先处理的小点',
            },
        }
    return {
        'reply': fallback_reply or '我先陪你把这一小步放稳，我们不急着一下子说透。',
        'state_patch': {},
    }
