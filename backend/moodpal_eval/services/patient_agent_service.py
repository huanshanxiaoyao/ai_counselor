from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.llm import LLMClient
from backend.moodpal.services.model_option_service import normalize_selected_model
from backend.moodpal.services.session_service import get_persona_config

from .structured_completion_service import complete_json_with_fallback
from .token_ledger_service import EvalUsageRecord, build_usage_record, summarize_usage_records


AFFECT_VALUES = {'better', 'same', 'worse'}
RESISTANCE_VALUES = {'low', 'medium', 'high'}
DEFAULT_AFFECT = 'same'
DEFAULT_RESISTANCE = 'medium'
REFERENCE_USER_SAMPLE_LIMIT = 8
REFERENCE_PAIR_SAMPLE_LIMIT = 6
THERAPIST_STYLE_MARKERS = (
    '我陪着',
    '不用急着',
    '慢慢呼吸',
    '这已经是很温柔的回应',
    '那说明，你',
    '那说明你',
    '听起来，这',
    '我似乎感觉到',
    '你可以试着',
    '我们先不急着',
)
ROLE_DRIFT_SECOND_PERSON_PATTERNS = (
    r'你还记得',
    r'你心里',
    r'你已经',
    r'你还在这里',
    r'你摸过',
    r'你没松手',
    r'你愿意说这些',
    r'你摸得到',
    r'记得空的位置',
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatientAgentTurnResult:
    reply_text: str
    should_continue: bool
    stop_reason: str
    affect_signal: str
    resistance_level: str
    provider: str = ''
    model: str = ''
    usage: dict[str, int] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    used_repair: bool = False
    usage_records: list[EvalUsageRecord] = field(default_factory=list)


class PatientAgentResponseError(ValueError):
    pass


def build_opening_user_message(case) -> str:
    opening = str(getattr(case, 'first_user_message', '') or '').strip()
    if not opening:
        raise PatientAgentResponseError('missing_opening_user_message')
    return opening


def generate_patient_reply(
    *,
    case,
    transcript: list[dict],
    target_persona_id: str,
    selected_model: str = '',
) -> PatientAgentTurnResult:
    if not transcript or transcript[-1].get('role') != 'assistant':
        raise PatientAgentResponseError('missing_target_reply')

    provider_name, model_name = _resolve_provider_and_model(selected_model)
    client = LLMClient(provider_name=provider_name)
    system_prompt = _build_system_prompt(case=case, target_persona_id=target_persona_id)
    user_prompt = _build_user_prompt(case=case, transcript=transcript)

    completion, json_mode_degraded = complete_json_with_fallback(
        client,
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=model_name,
        temperature=0.6,
    )
    usage_records = [
        build_usage_record(
            scope='patient',
            provider=completion.provider_name,
            model=completion.model,
            usage=completion.usage,
            request_label='patient_reply',
            metadata={
                'target_persona_id': target_persona_id,
                'json_mode_degraded': json_mode_degraded,
            },
        )
    ]
    payload, used_repair, extra_records = _parse_or_repair_payload(
        client=client,
        provider_name=provider_name,
        model_name=model_name,
        raw_text=completion.text,
    )
    usage_records.extend(extra_records)
    payload, role_drift_repaired, rewrite_records = _regenerate_role_drift_payload_if_needed(
        client=client,
        case=case,
        transcript=transcript,
        target_persona_id=target_persona_id,
        model_name=model_name,
        payload=payload,
    )
    usage_records.extend(rewrite_records)
    return _build_turn_result(
        payload=payload,
        provider=completion.provider_name,
        model=completion.model,
        usage=summarize_usage_records(usage_records),
        used_repair=used_repair or role_drift_repaired,
        usage_records=usage_records,
    )


def _build_turn_result(
    *,
    payload: dict,
    provider: str,
    model: str,
    usage,
    used_repair: bool,
    usage_records: list[EvalUsageRecord],
) -> PatientAgentTurnResult:
    should_continue = bool(payload.get('should_continue', True))
    reply_text = str(payload.get('reply') or '').strip()
    stop_reason = str(payload.get('stop_reason') or '').strip()
    affect_signal = str(payload.get('affect_signal') or DEFAULT_AFFECT).strip().lower()
    resistance_level = str(payload.get('resistance_level') or DEFAULT_RESISTANCE).strip().lower()

    if affect_signal not in AFFECT_VALUES:
        affect_signal = DEFAULT_AFFECT
    if resistance_level not in RESISTANCE_VALUES:
        resistance_level = DEFAULT_RESISTANCE
    if should_continue and not reply_text:
        raise PatientAgentResponseError('patient_reply_empty')
    if not should_continue and not stop_reason:
        stop_reason = 'patient_stop'

    return PatientAgentTurnResult(
        reply_text=reply_text,
        should_continue=should_continue,
        stop_reason=stop_reason,
        affect_signal=affect_signal,
        resistance_level=resistance_level,
        provider=provider or '',
        model=model or '',
        usage=dict(usage or {}),
        raw_payload=dict(payload or {}),
        used_repair=used_repair,
        usage_records=list(usage_records or []),
    )


def _parse_or_repair_payload(
    *,
    client: LLMClient,
    provider_name: str,
    model_name: Optional[str],
    raw_text: str,
) -> tuple[dict, bool, list[EvalUsageRecord]]:
    payload = _try_parse_json_payload(raw_text)
    if payload is not None:
        return payload, False, []

    repair_completion, json_mode_degraded = complete_json_with_fallback(
        client,
        prompt=_build_repair_prompt(raw_text),
        system_prompt=(
            '请把给定文本修复成一个合法 JSON 对象，只保留 reply / should_continue / stop_reason / '
            'affect_signal / resistance_level 这五个字段。不要输出 markdown。'
        ),
        model=model_name,
        temperature=0,
    )
    payload = _try_parse_json_payload(repair_completion.text)
    if payload is None:
        raise PatientAgentResponseError('patient_reply_invalid_json')
    return payload, True, [
        build_usage_record(
            scope='patient',
            provider=repair_completion.provider_name or provider_name,
            model=repair_completion.model or model_name or '',
            usage=repair_completion.usage,
            request_label='patient_reply_repair',
            metadata={'repair': True, 'json_mode_degraded': json_mode_degraded},
        )
    ]


def _try_parse_json_payload(raw_text: str) -> dict | None:
    text = (raw_text or '').strip()
    if not text:
        return None
    candidates = [text]
    if '```' in text:
        stripped = text.replace('```json', '```').replace('```JSON', '```')
        parts = [part.strip() for part in stripped.split('```') if part.strip()]
        candidates.extend(parts)
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace:last_brace + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _build_system_prompt(*, case, target_persona_id: str) -> str:
    persona = get_persona_config(target_persona_id)
    return '\n'.join(
        [
            '你正在参与 MoodPal 的内部盲测，扮演一位真实的心理求助者。',
            f'你面对的咨询角色是：{persona["title"]}。',
            '你的参考资料是一段真实或人工构造的既有咨询对话，它代表这个来访者的说话风格、情绪节奏和内在困扰。',
            '参考对话里的 assistant 内容只用于帮助你理解这个来访者通常会怎么回应，不是让你模仿咨询师说话。',
            '你的任务不是复读原文，而是带着同样的人设和情绪基调，对新的 AI 回复做自然反应。',
            '如果对方没有接住你、开始说教、过早建议、或者像在分析你，你可以自然地表现出阻抗、冷淡、烦躁或退缩。',
            '你永远不是咨询师。你的 reply 必须站在来访者第一人称立场，优先用“我”表达自己的感受、记忆、犹豫、困惑。',
            '不要安抚咨询师，不要解释“这说明你……”，不要说“我陪着你 / 不用急着 / 慢慢呼吸”这类咨询师话术。',
            '不要为了难倒系统而故意离题，也不要突然变成另一个人。',
            '请只输出 JSON。',
        ]
    )


def _build_user_prompt(*, case, transcript: list[dict]) -> str:
    reference_messages = list(getattr(case, 'full_reference_dialogue', []) or [])
    reference_user_samples = _format_reference_user_samples(reference_messages)
    reference_response_pairs = _format_reference_response_pairs(reference_messages)
    transcript_text = _format_dialogue(transcript)
    latest_assistant_message = _latest_message_content(transcript, role='assistant')
    topic_tag = str(getattr(case, 'topic_tag', '') or '').strip()
    risk_hint = str(getattr(case, 'risk_hint', '') or '').strip()
    title = str(getattr(case, 'title', '') or getattr(case, 'case_id', '')).strip()
    return '\n\n'.join(
        [
            f'[Case 标题]\n{title}',
            f'[Case 标签]\n{topic_tag or "未标注"}',
            f'[风险提示]\n{risk_hint or "none"}',
            '[来访者语言样本]\n' + reference_user_samples,
            '[参考中的“咨询师 -> 来访者回应”样例]\n' + reference_response_pairs,
            '[到目前为止的新对话]\n' + transcript_text,
            '[你现在要回应的最新咨询师话语]\n' + (latest_assistant_message or '(empty)'),
            '[输出要求]\n'
            '{\n'
            '  "reply": "你下一句要说的话",\n'
            '  "should_continue": true,\n'
            '  "stop_reason": "",\n'
            '  "affect_signal": "better|same|worse",\n'
            '  "resistance_level": "low|medium|high"\n'
            '}\n'
            'reply 必须是来访者对咨询师的回应，不是咨询师反过来安抚、解释或引导来访者。\n'
            '请优先参考“来访者语言样本”和“咨询师->来访者回应样例”来决定你怎么说，不要模仿参考里的咨询师措辞。\n'
            '默认用第一人称“我”来表达自己的处境；如果提到“你”，也只能是来访者在回应咨询师，而不是替咨询师解释来访者。\n'
            '如果你觉得这段对话已经可以自然结束，把 should_continue 设为 false，并给出 stop_reason。\n'
            '不要输出解释，不要输出 markdown。',
        ]
    )


def _build_repair_prompt(raw_text: str) -> str:
    return '\n'.join(
        [
            '[待修复文本]',
            raw_text or '(empty)',
            '',
            '[目标 JSON schema]',
            '{',
            '  "reply": "",',
            '  "should_continue": true,',
            '  "stop_reason": "",',
            '  "affect_signal": "better|same|worse",',
            '  "resistance_level": "low|medium|high"',
            '}',
        ]
    )


def _format_dialogue(messages: list[dict]) -> str:
    lines = []
    for item in messages:
        role = str(item.get('role') or '').strip() or 'unknown'
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        lines.append(f'{role}: {content}')
    return '\n'.join(lines) if lines else '(empty)'


def _resolve_provider_and_model(selected_model: str) -> tuple[str, Optional[str]]:
    value = normalize_selected_model(selected_model)
    if ':' in value:
        provider_name, model_name = value.split(':', 1)
        return provider_name, model_name.strip() or None
    return value, None


def _regenerate_role_drift_payload_if_needed(
    *,
    client: LLMClient,
    case,
    transcript: list[dict],
    target_persona_id: str,
    model_name: Optional[str],
    payload: dict,
) -> tuple[dict, bool, list[EvalUsageRecord]]:
    reply_text = str((payload or {}).get('reply') or '').strip()
    should_continue = bool((payload or {}).get('should_continue', True))
    if not should_continue or not reply_text or not _looks_like_role_drift(reply_text):
        return payload, False, []

    try:
        rewrite_completion, json_mode_degraded = complete_json_with_fallback(
            client,
            prompt=_build_role_drift_regeneration_prompt(
                case=case,
                transcript=transcript,
                target_persona_id=target_persona_id,
                payload=payload,
            ),
            system_prompt=(
                '你是 MoodPal Eval 的角色纠偏器。'
                '请基于相同上下文，重新生成一条自然的“来访者下一句回应”。'
                '不要沿着咨询师口吻改写，要从来访者视角重新说一遍。'
                '只输出 JSON，不要输出 markdown。'
            ),
            model=model_name,
            temperature=0.2,
        )
        rewritten_payload = _try_parse_json_payload(rewrite_completion.text)
        if not isinstance(rewritten_payload, dict) or not str(rewritten_payload.get('reply') or '').strip():
            raise PatientAgentResponseError('patient_role_drift_regen_invalid_json')

        merged = dict(payload or {})
        merged.update(
            {
                'reply': str(rewritten_payload.get('reply') or '').strip(),
                'should_continue': bool(rewritten_payload.get('should_continue', payload.get('should_continue', True))),
                'stop_reason': str(rewritten_payload.get('stop_reason') or payload.get('stop_reason') or '').strip(),
                'affect_signal': str(rewritten_payload.get('affect_signal') or payload.get('affect_signal') or DEFAULT_AFFECT).strip(),
                'resistance_level': str(rewritten_payload.get('resistance_level') or payload.get('resistance_level') or DEFAULT_RESISTANCE).strip(),
            }
        )
        return merged, True, [
            build_usage_record(
                scope='patient',
                provider=rewrite_completion.provider_name,
                model=rewrite_completion.model,
                usage=rewrite_completion.usage,
                request_label='patient_reply_role_drift_regen',
                metadata={'json_mode_degraded': json_mode_degraded, 'role_drift_regen': True},
            )
        ]
    except Exception:
        logger.warning('Patient Agent role drift regeneration failed; keeping original reply', exc_info=True)
        return payload, False, []


def _looks_like_role_drift(reply_text: str) -> bool:
    text = ' '.join((reply_text or '').split())
    if not text:
        return False
    if any(marker in text for marker in THERAPIST_STYLE_MARKERS):
        return True
    if any(re.search(pattern, text) for pattern in ROLE_DRIFT_SECOND_PERSON_PATTERNS):
        return True
    if '那说明' in text and '你' in text:
        return True
    return False


def _build_role_drift_regeneration_prompt(*, case, transcript: list[dict], target_persona_id: str, payload: dict) -> str:
    persona = get_persona_config(target_persona_id)
    transcript_tail = _format_dialogue(list(transcript or [])[-4:])
    reference_messages = list(getattr(case, 'full_reference_dialogue', []) or [])
    return '\n\n'.join(
        [
            f'[Case 标题]\n{getattr(case, "title", "") or getattr(case, "case_id", "")}',
            f'[咨询角色]\n{persona["title"]}',
            '[来访者语言样本]\n' + _format_reference_user_samples(reference_messages),
            '[参考中的“咨询师 -> 来访者回应”样例]\n' + _format_reference_response_pairs(reference_messages),
            '[最近对话尾部]\n' + transcript_tail,
            '[当前错误回复 JSON]\n' + json.dumps(payload, ensure_ascii=False, indent=2),
            '[改写要求]\n'
            '1. 请重新生成一条自然的来访者回复，不要沿着原句逐词修补。\n'
            '2. 保持原来的情绪方向和语义核心，不要突然换话题。\n'
            '3. 不要安抚咨询师，不要解释“这说明你……”，不要说“我陪着你 / 不用急着 / 慢慢呼吸”。\n'
            '4. 如果要提到咨询师，只能是来访者在回应对方，不要替对方下判断。\n'
            '5. should_continue / stop_reason / affect_signal / resistance_level 尽量保持一致。\n'
            '[输出 JSON schema]\n'
            '{\n'
            '  "reply": "",\n'
            '  "should_continue": true,\n'
            '  "stop_reason": "",\n'
            '  "affect_signal": "better|same|worse",\n'
            '  "resistance_level": "low|medium|high"\n'
            '}',
        ]
    )


def _format_reference_user_samples(messages: list[dict]) -> str:
    user_lines = [str(item.get('content') or '').strip() for item in messages if item.get('role') == 'user']
    selected = _select_evenly(user_lines, REFERENCE_USER_SAMPLE_LIMIT)
    if not selected:
        return '(empty)'
    return '\n'.join(f'- {line}' for line in selected)


def _format_reference_response_pairs(messages: list[dict]) -> str:
    pairs: list[tuple[str, str]] = []
    last_assistant = ''
    for item in messages:
        role = str(item.get('role') or '').strip()
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        if role == 'assistant':
            last_assistant = content
            continue
        if role == 'user' and last_assistant:
            pairs.append((last_assistant, content))
            last_assistant = ''
    selected = _select_evenly(pairs, REFERENCE_PAIR_SAMPLE_LIMIT)
    if not selected:
        return '(empty)'
    blocks = []
    for assistant_text, user_text in selected:
        blocks.append(f'assistant: {assistant_text}\nuser: {user_text}')
    return '\n\n'.join(blocks)


def _select_evenly(items: list, limit: int) -> list:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[-1]]
    step = (len(items) - 1) / float(limit - 1)
    indexes = []
    for idx in range(limit):
        indexes.append(min(len(items) - 1, round(idx * step)))
    deduped = []
    seen = set()
    for idx in indexes:
        if idx in seen:
            continue
        seen.add(idx)
        deduped.append(items[idx])
    return deduped


def _latest_message_content(messages: list[dict], *, role: str) -> str:
    for item in reversed(list(messages or [])):
        if str(item.get('role') or '').strip() == role:
            return str(item.get('content') or '').strip()
    return ''
