from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

from backend.llm import LLMClient
from backend.roundtable.services.token_quota import parse_subject_key, record_token_usage

from ..cbt import CBTGraph
from ..cbt.state import CBTGraphState, build_cbt_state_from_session
from .model_option_service import normalize_selected_model


logger = logging.getLogger(__name__)


ALLOWED_STATE_PATCH_KEYS = {
    'current_stage',
    'current_track',
    'current_technique_id',
    'mood_label',
    'mood_score',
    'emotion_stability',
    'agenda_topic',
    'agenda_locked',
    'captured_automatic_thought',
    'thought_format',
    'belief_confidence',
    'alternative_explanation',
    'cognitive_distortion_label',
    'balanced_response',
    'balanced_response_confidence',
    'energy_level',
    'behavioral_shutdown',
    'activation_step',
    'experiment_plan',
    'task_first_step',
    'homework_candidate',
    'repeated_theme_detected',
    'core_belief_candidate',
    'intermediate_belief_candidate',
    'alliance_strength',
    'safety_status',
    'alliance_rupture_detected',
    'topic_drift_detected',
    'homework_obstacle_detected',
    'head_heart_split_detected',
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
        '    "agenda_topic": "",',
        '    "agenda_locked": false,',
        '    "captured_automatic_thought": "",',
        '    "thought_format": "",',
        '    "belief_confidence": 0,',
        '    "alternative_explanation": "",',
        '    "cognitive_distortion_label": "",',
        '    "balanced_response": "",',
        '    "balanced_response_confidence": 0,',
        '    "energy_level": "medium",',
        '    "behavioral_shutdown": false,',
        '    "activation_step": "",',
        '    "homework_candidate": "",',
        '    "task_first_step": "",',
        '    "experiment_plan": {},',
        '    "core_belief_candidate": "",',
        '    "intermediate_belief_candidate": "",',
        '    "mood_label": "",',
        '    "mood_score": 0,',
        '    "emotion_stability": "medium",',
        '    "alliance_strength": "medium",',
        '    "repeated_theme_detected": false,',
        '    "alliance_rupture_detected": false,',
        '    "topic_drift_detected": false,',
        '    "homework_obstacle_detected": false,',
        '    "head_heart_split_detected": false',
        '  }',
        '}',
        '不要输出 markdown，不要输出额外解释。',
    ]
)


@dataclass(frozen=True)
class CBTRuntimeTurnResult:
    reply_text: str
    reply_metadata: dict
    state: CBTGraphState
    persist_patch: dict = field(default_factory=dict)
    used_fallback: bool = False


def run_cbt_turn(*, session, history_messages: list[dict]) -> CBTRuntimeTurnResult:
    state = _load_state(session=session, history_messages=history_messages)
    graph = CBTGraph()
    plan = graph.plan_turn(state)
    logger.info(
        'MoodPal CBT route selected session=%s subject=%s track=%s technique=%s reason=%s fallback_action=%s circuit_open=%s',
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
        next_state['current_track'] = plan.selection.track
        _append_trace(next_state, plan.selection, progress_marker='safety_override', done=True, should_trip_circuit=False)
        _log_trace(
            session=session,
            state=next_state,
            track=plan.selection.track,
            technique_id=plan.selection.technique_id,
            progress_marker='safety_override',
            done=True,
            should_trip_circuit=False,
        )
        return CBTRuntimeTurnResult(
            reply_text=reply_text,
            reply_metadata={
                'engine': 'cbt_graph',
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
            'MoodPal CBT local fallback applied session=%s subject=%s track=%s technique=%s',
            session.id,
            session.usage_subject,
            plan.selection.track,
            plan.selection.technique_id,
        )

    next_state = dict(execution_state)
    next_state.update(_sanitize_state_patch(raw_state_patch))
    next_state['current_track'] = plan.selection.track
    next_state['current_technique_id'] = plan.selection.technique_id
    next_state['current_stage'] = 'evaluate_exit'
    next_state['last_assistant_message'] = reply_text

    evaluation = graph.evaluate_turn(next_state, plan.selection.technique_id)
    next_state.update(_sanitize_state_patch(evaluation.state_patch))

    if evaluation.should_trip_circuit:
        next_state['current_stage'] = 'wrap_up' if evaluation.next_fallback_action == 'wrap_up_now' else 'route_track'
    elif evaluation.done:
        next_state['current_stage'] = 'wrap_up' if evaluation.next_fallback_action == 'wrap_up_now' else 'route_track'
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
            'MoodPal CBT circuit breaker opened session=%s subject=%s technique=%s trip_reason=%s next_action=%s attempts=%s stalls=%s',
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
        track=plan.selection.track,
        technique_id=plan.selection.technique_id,
        progress_marker=evaluation.progress_marker or next_state.get('last_progress_marker', ''),
        done=evaluation.done,
        should_trip_circuit=evaluation.should_trip_circuit,
    )
    return CBTRuntimeTurnResult(
        reply_text=reply_text,
        reply_metadata={
            'engine': 'cbt_graph',
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


def _load_state(*, session, history_messages: list[dict]) -> CBTGraphState:
    metadata = dict(session.metadata or {})
    persisted_state = dict(metadata.get('cbt_state') or {})
    last_summary = metadata.get('last_summary') or {}
    state = build_cbt_state_from_session(
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
    return state


def merge_cbt_state_metadata(metadata: dict | None, state_patch: dict | None) -> dict:
    next_metadata = dict(metadata or {})
    merged_state = dict(next_metadata.get('cbt_state') or {})
    merged_state.update(_sanitize_persistable_state_patch(state_patch))
    next_metadata['cbt_state'] = merged_state
    return next_metadata


def _append_trace(state: dict, selection, *, progress_marker: str, done: bool, should_trip_circuit: bool):
    trace = list(state.get('technique_trace') or [])
    trace.append(
        {
            'turn_index': len(trace) + 1,
            'track': selection.track,
            'technique_id': selection.technique_id,
            'progress_marker': progress_marker,
            'done': done,
            'should_trip_circuit': should_trip_circuit,
        }
    )
    state['technique_trace'] = trace


def _log_trace(*, session, state: dict, track: str, technique_id: str, progress_marker: str, done: bool, should_trip_circuit: bool):
    trace = list(state.get('technique_trace') or [])
    turn_index = trace[-1]['turn_index'] if trace else 0
    logger.info(
        'MoodPal CBT trace appended session=%s subject=%s turn=%s track=%s technique=%s progress=%s done=%s circuit_open=%s stage=%s',
        session.id,
        session.usage_subject,
        turn_index,
        track,
        technique_id,
        progress_marker,
        done,
        should_trip_circuit,
        state.get('current_stage', ''),
    )


def _prepare_state_for_selection(state: CBTGraphState, technique_id: str) -> CBTGraphState:
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
    return {key: value for key, value in state_patch.items() if key in ALLOWED_STATE_PATCH_KEYS}


def _sanitize_persistable_state_patch(state_patch: Optional[dict]) -> dict:
    if not isinstance(state_patch, dict):
        return {}
    return {key: value for key, value in state_patch.items() if key in PERSISTABLE_STATE_KEYS}


def _serialize_persistable_state(state: CBTGraphState) -> dict:
    return {
        key: value
        for key, value in state.items()
        if key in PERSISTABLE_STATE_KEYS
    }


def _build_persistable_state_patch(previous_state: CBTGraphState, next_state: CBTGraphState) -> dict:
    previous_persistable = _serialize_persistable_state(previous_state)
    next_persistable = _serialize_persistable_state(next_state)
    return {
        key: value
        for key, value in next_persistable.items()
        if previous_persistable.get(key) != value
    }


def _execute_turn(*, session, state: CBTGraphState, technique_id: str, system_prompt: str, user_prompt: str, fallback_reply: str):
    provider_name, model_name = _resolve_provider_and_model(session.selected_model)
    schema_prompt = '\n'.join(
        [
            user_prompt,
            '',
            TURN_RESPONSE_SCHEMA_PROMPT,
        ]
    )
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
                source='moodpal.cbt.turn',
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
        logger.exception('MoodPal CBT turn failed, using local fallback')
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


def _build_local_fallback(*, state: CBTGraphState, technique_id: str, fallback_reply: str) -> dict:
    user_text = (state.get('last_user_message') or '').strip()
    compact_text = ' '.join(user_text.split())
    if len(compact_text) > 48:
        compact_text = compact_text[:48].rstrip() + '...'

    if technique_id == 'cbt_structure_agenda_setting':
        return {
            'reply': fallback_reply or '你刚才提到了几件都不轻的事。为了让这次对话真正有用，我们先只锁定一个最想处理的点，好吗？',
            'state_patch': {
                'agenda_topic': compact_text or state.get('agenda_topic', ''),
                'agenda_locked': bool(compact_text),
            },
        }
    if technique_id in ['cbt_cog_identify_at_basic', 'cbt_cog_identify_at_telegraphic']:
        return {
            'reply': fallback_reply or f'我们先别急着下结论。回到那一刻，你脑子里最刺耳的一句话，最接近哪一句？比如“{compact_text}”？',
            'state_patch': {
                'captured_automatic_thought': compact_text if compact_text and any(token in user_text for token in ['我', '如果', '就是', '肯定', '完了']) else '',
                'thought_format': 'question' if user_text.endswith('？') or user_text.endswith('?') else 'statement' if compact_text else '',
            },
        }
    if technique_id == 'cbt_cog_identify_at_imagery':
        return {
            'reply': fallback_reply or '没关系，想不起来很正常。我们先把那个场景慢一点重放一遍，再看看当时脑子里闪过了什么。',
            'state_patch': {
                'thought_format': 'imagery',
            },
        }
    if technique_id == 'cbt_cog_eval_distortion':
        return {
            'reply': fallback_reply or '我注意到这里面有一点“把结果一下推到最坏”的味道。我们先不争对错，只看看这个想法有没有灾难化或绝对化。',
            'state_patch': {
                'cognitive_distortion_label': '灾难化' if any(token in user_text for token in ['完了', '全毁了', '没救了']) else '',
            },
        }
    if technique_id == 'cbt_cog_eval_socratic':
        return {
            'reply': fallback_reply or '我们当一回侦探。支持这个想法的证据是什么，反对它的证据又是什么？有没有别的解释也说得通？',
            'state_patch': {},
        }
    if technique_id == 'cbt_cog_response_coping':
        balanced_response = f'虽然我现在会往坏处想，但仅凭眼前这些信息，还不能证明最糟结果已经发生。'
        return {
            'reply': fallback_reply or balanced_response,
            'state_patch': {
                'balanced_response': balanced_response,
                'balanced_response_confidence': 62,
            },
        }
    if technique_id == 'cbt_beh_activation':
        activation_step = '起身喝口水，或者走到窗边站一分钟'
        return {
            'reply': fallback_reply or '当能量很低时，我们先不解决大问题，只定一个非常小的动作。比如起身喝口水，或者走到窗边站一分钟。',
            'state_patch': {
                'activation_step': activation_step,
                'homework_candidate': activation_step,
                'behavioral_shutdown': True,
                'energy_level': 'low',
            },
        }
    if technique_id == 'cbt_beh_graded_task':
        task_first_step = '把任务标题写下来，停在这里'
        return {
            'reply': fallback_reply or '这件事现在看起来像一整座山。我们先只拆出一个不会失败的第一步，好吗？',
            'state_patch': {
                'task_first_step': task_first_step,
                'homework_candidate': task_first_step,
            },
        }
    if technique_id == 'cbt_beh_experiment':
        experiment_plan = {
            'action': '做一个低风险的小测试',
            'timepoint': '今天或下一次类似场景',
            'metric': '记录实际发生了什么',
        }
        return {
            'reply': fallback_reply or '这更像一个可以被验证的预测。我们可以设计一个很小、很安全的现实测试，看看结果是否真像你预想的那样。',
            'state_patch': {
                'experiment_plan': experiment_plan,
                'homework_candidate': '在下一次类似情境里做一个低风险测试，并记录实际结果',
            },
        }
    if technique_id == 'cbt_core_downward_arrow':
        return {
            'reply': fallback_reply or '如果最坏的情况真的发生了，那对你来说最糟糕的含义会是什么？',
            'state_patch': {
                'intermediate_belief_candidate': compact_text or '如果出错，就说明我不够好',
            },
        }
    if technique_id == 'cbt_exception_alliance_rupture':
        return {
            'reply': fallback_reply or '如果刚才的方式让你觉得不被理解，那我先停下来。你可以直接告诉我，哪一句最让你不舒服，我按你的反馈改。',
            'state_patch': {
                'alliance_strength': 'medium',
                'alliance_rupture_detected': False,
            },
        }
    if technique_id == 'cbt_exception_yes_but':
        return {
            'reply': fallback_reply or '这很正常，理智跟上了，情绪不一定会立刻跟上。我们先不逼自己相信，只看看心里那个没被安抚的部分还在担心什么。',
            'state_patch': {
                'head_heart_split_detected': False,
                'belief_confidence': 58,
            },
        }
    if technique_id == 'cbt_exception_homework_obstacle':
        return {
            'reply': fallback_reply or '先别责怪自己。没做成通常不是态度问题，而是当时有个卡点还没被看见。我们先找那个瞬间的阻力。',
            'state_patch': {
                'homework_obstacle_detected': False,
                'captured_automatic_thought': compact_text or '我做不到，做了也没用',
                'homework_candidate': '下次卡住时先记下脑中最冒出来的那句话',
            },
        }
    if technique_id == 'cbt_exception_redirecting':
        return {
            'reply': fallback_reply or '我先帮你按一下暂停。我们回到刚才最刺到你的那个具体场景，只抓住一个点继续。',
            'state_patch': {
                'topic_drift_detected': False,
            },
        }
    return {
        'reply': fallback_reply or '我先陪你把这一步说清楚，我们只往前走一小步。',
        'state_patch': {},
    }
