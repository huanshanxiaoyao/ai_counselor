from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from backend.llm import LLMAPIError, LLMClient
from backend.moodpal.services.model_option_service import get_model_options, normalize_selected_model
from backend.moodpal_eval.services.structured_completion_service import complete_json_with_strategy


PLAIN_PROMPT_TEMPLATE = '请用一句简短中文回复：PONG {token}。不要解释，不要换行。'
JSON_PROMPT_TEMPLATE = (
    '请只输出一个 JSON 对象，不要输出 markdown，不要输出额外文本。'
    'JSON schema: {"status":"ok","token":"%s"}。'
    '其中 token 字段必须原样返回。'
)


@dataclass(frozen=True)
class ProbeCallResult:
    success: bool
    error_type: str = ''
    error_message: str = ''
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    text_preview: str = ''
    json_mode_degraded: bool = False
    completion_mode: str = ''
    json_mode_attempted: bool = False
    structured_output_policy: str = ''
    token_echoed: bool = False


@dataclass(frozen=True)
class ModelProbeResult:
    selected_model: str
    provider: str
    model: str
    plain_call: ProbeCallResult
    json_mode_call: ProbeCallResult
    structured_call: ProbeCallResult

    @property
    def available_for_eval(self) -> bool:
        return self.plain_call.success and self.structured_call.success


class Command(BaseCommand):
    help = 'Smoke-test configured MoodPal models outside OpenAI under the current LLM timeout/retry config.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--models',
            default='',
            help='Comma-separated selected models such as "qwen:qwen-plus,deepseek:deepseek-chat". Defaults to all non-openai configured models.',
        )
        parser.add_argument(
            '--include-openai',
            action='store_true',
            help='Include OpenAI provider in the smoke list.',
        )
        parser.add_argument(
            '--output',
            default='',
            help='Optional JSON report path.',
        )

    def handle(self, *args, **options):
        selected_models = _resolve_models(
            raw_models=options['models'],
            include_openai=bool(options['include_openai']),
        )
        if not selected_models:
            raise CommandError('no_models_selected')

        report = {
            'generated_at': datetime.now().isoformat(),
            'models': [],
        }
        results: list[ModelProbeResult] = []
        for selected_model in selected_models:
            self.stdout.write(f'[probe] {selected_model}')
            result = _probe_model(selected_model)
            results.append(result)
            report['models'].append(
                {
                    'selected_model': result.selected_model,
                    'provider': result.provider,
                    'model': result.model,
                    'available_for_eval': result.available_for_eval,
                    'plain_call': asdict(result.plain_call),
                    'json_mode_call': asdict(result.json_mode_call),
                    'structured_call': asdict(result.structured_call),
                }
            )
            self.stdout.write(_format_probe_line(result))

        report['available_for_eval_models'] = [item.selected_model for item in results if item.available_for_eval]
        report['unavailable_models'] = [item.selected_model for item in results if not item.available_for_eval]

        output_path = _resolve_output_path(options['output'], prefix='moodpal_model_smoke')
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'smoke report written to {output_path}'))


def _resolve_models(*, raw_models: str, include_openai: bool) -> list[str]:
    if raw_models.strip():
        values = []
        for part in raw_models.split(','):
            normalized = normalize_selected_model(part)
            if normalized not in values:
                values.append(normalized)
        return values

    values = []
    for item in get_model_options():
        provider = item['provider']
        if provider == 'openai' and not include_openai:
            continue
        selected_model = item['value']
        if selected_model not in values:
            values.append(selected_model)
    return values


def _probe_model(selected_model: str) -> ModelProbeResult:
    provider, model = selected_model.split(':', 1)
    token = uuid.uuid4().hex[:10]
    client = LLMClient(provider_name=provider)

    plain_prompt = PLAIN_PROMPT_TEMPLATE.format(token=token)
    plain_call = _run_plain_probe(client=client, model=model, token=token, prompt=plain_prompt)
    json_mode_call = _run_json_mode_probe(client=client, model=model, token=token)
    structured_call = _run_structured_probe(client=client, model=model, token=token)

    return ModelProbeResult(
        selected_model=selected_model,
        provider=provider,
        model=model,
        plain_call=plain_call,
        json_mode_call=json_mode_call,
        structured_call=structured_call,
    )


def _run_plain_probe(*, client: LLMClient, model: str, token: str, prompt: str) -> ProbeCallResult:
    try:
        completion = client.complete_with_metadata(
            prompt=prompt,
            model=model,
            temperature=0,
        )
        text = (completion.text or '').strip()
        token_echoed = bool(text) and token in text
        success = bool(text)
        return ProbeCallResult(
            success=success,
            elapsed_seconds=float(completion.elapsed_seconds or 0),
            prompt_tokens=int(getattr(completion.usage, 'prompt_tokens', 0) or 0),
            completion_tokens=int(getattr(completion.usage, 'completion_tokens', 0) or 0),
            total_tokens=int(getattr(completion.usage, 'total_tokens', 0) or 0),
            text_preview=text[:180],
            token_echoed=token_echoed,
            error_type='' if success else 'plain_empty_reply',
            error_message='' if success else 'empty_text',
        )
    except Exception as exc:
        return _build_error_probe_result(exc)


def _run_json_mode_probe(*, client: LLMClient, model: str, token: str) -> ProbeCallResult:
    try:
        completion = client.complete_with_metadata(
            prompt=JSON_PROMPT_TEMPLATE % token,
            model=model,
            temperature=0,
            json_mode=True,
        )
        payload = _parse_json_payload(completion.text)
        success = isinstance(payload, dict) and payload.get('status') == 'ok' and payload.get('token') == token
        return ProbeCallResult(
            success=success,
            elapsed_seconds=float(completion.elapsed_seconds or 0),
            prompt_tokens=int(getattr(completion.usage, 'prompt_tokens', 0) or 0),
            completion_tokens=int(getattr(completion.usage, 'completion_tokens', 0) or 0),
            total_tokens=int(getattr(completion.usage, 'total_tokens', 0) or 0),
            text_preview=(completion.text or '').strip()[:180],
            error_type='' if success else 'json_mode_validation_failed',
            error_message='' if success else f'payload={payload!r}',
        )
    except Exception as exc:
        return _build_error_probe_result(exc)


def _run_structured_probe(*, client: LLMClient, model: str, token: str) -> ProbeCallResult:
    try:
        structured = complete_json_with_strategy(
            client,
            prompt=JSON_PROMPT_TEMPLATE % token,
            model=model,
            temperature=0,
        )
        completion = structured.completion
        payload = _parse_json_payload(completion.text)
        success = isinstance(payload, dict) and payload.get('status') == 'ok' and payload.get('token') == token
        return ProbeCallResult(
            success=success,
            elapsed_seconds=float(completion.elapsed_seconds or 0),
            prompt_tokens=int(getattr(completion.usage, 'prompt_tokens', 0) or 0),
            completion_tokens=int(getattr(completion.usage, 'completion_tokens', 0) or 0),
            total_tokens=int(getattr(completion.usage, 'total_tokens', 0) or 0),
            text_preview=(completion.text or '').strip()[:180],
            json_mode_degraded=bool(structured.json_mode_degraded),
            completion_mode=structured.completion_mode,
            json_mode_attempted=bool(structured.json_mode_attempted),
            structured_output_policy=structured.policy,
            error_type='' if success else 'structured_validation_failed',
            error_message='' if success else f'payload={payload!r}',
        )
    except Exception as exc:
        return _build_error_probe_result(exc)


def _parse_json_payload(raw_text: str):
    text = (raw_text or '').strip()
    if not text:
        return None
    candidates = [text]
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _build_error_probe_result(exc: Exception) -> ProbeCallResult:
    status_code = getattr(exc, 'status_code', None)
    error_type = exc.__class__.__name__
    if isinstance(exc, LLMAPIError) and status_code:
        error_type = f'{error_type}:{status_code}'
    return ProbeCallResult(
        success=False,
        error_type=error_type,
        error_message=str(exc)[:300],
    )


def _format_probe_line(result: ModelProbeResult) -> str:
    plain_status = 'ok' if result.plain_call.success else f'fail[{result.plain_call.error_type}]'
    if result.plain_call.success and not result.plain_call.token_echoed:
        plain_status = 'ok(non_echo)'
    json_status = 'ok' if result.json_mode_call.success else f'fail[{result.json_mode_call.error_type}]'
    structured_status = 'ok'
    if not result.structured_call.success:
        structured_status = f'fail[{result.structured_call.error_type}]'
    elif result.structured_call.completion_mode == 'prompt_json' and not result.structured_call.json_mode_attempted:
        structured_status = 'ok(prompt_only)'
    elif result.structured_call.json_mode_degraded:
        structured_status = 'ok(degraded)'
    availability = 'available' if result.available_for_eval else 'blocked'
    return (
        f'  -> {availability} | plain={plain_status} | json_mode={json_status} | '
        f'structured={structured_status} | total_tokens='
        f'{result.plain_call.total_tokens}/{result.json_mode_call.total_tokens}/{result.structured_call.total_tokens}'
    )


def _resolve_output_path(raw_path: str, *, prefix: str) -> Path:
    if raw_path.strip():
        path = Path(raw_path).expanduser()
    else:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        path = Path('tmp') / f'{prefix}-{stamp}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
