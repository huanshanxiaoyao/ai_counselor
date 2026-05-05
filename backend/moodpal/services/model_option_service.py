from __future__ import annotations

from django.conf import settings

from backend.llm.providers import get_all_providers


MODEL_SCOPE_ASSISTANT = 'assistant'
MODEL_SCOPE_PATIENT = 'patient'
MODEL_SCOPE_JUDGE = 'judge'
MODEL_SCOPE_ALL = 'all'

PROVIDER_NAMES = {
    'qwen': '通义千问',
    'deepseek': 'DeepSeek',
    'minimax': 'MiniMax',
    'doubao': '豆包',
    'openai': 'OpenAI',
}

PROJECT_BLOCKED_PROVIDERS = {'minimax'}
JUDGE_ONLY_MODEL_VALUES = {
    'qwen:qwen3.5-plus',
    'doubao:doubao-seed-2-0-pro-260215',
}


def get_default_selected_model(scope: str = MODEL_SCOPE_ASSISTANT) -> str:
    options = _build_model_options(scope=scope)
    if not options:
        return ''

    providers = get_all_providers()
    default_provider = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    provider_config = providers.get(default_provider)
    allowed_values = {item['value'] for item in options}
    if provider_config is None:
        return options[0]['value']
    model_name = (provider_config.default_model or '').strip()
    candidate = f'{default_provider}:{model_name}' if model_name else default_provider
    if candidate in allowed_values:
        return candidate
    return options[0]['value']


def get_model_options(scope: str = MODEL_SCOPE_ASSISTANT) -> list[dict]:
    options = _build_model_options(scope=scope)
    default_value = get_default_selected_model(scope=scope)
    return [
        {
            **item,
            'is_default': item['value'] == default_value,
        }
        for item in options
    ]


def is_selected_model_allowed(selected_model: str, scope: str = MODEL_SCOPE_ASSISTANT) -> bool:
    value = (selected_model or '').strip()
    if not value:
        return False
    allowed_values = {item['value'] for item in _build_model_options(scope=scope)}
    if value in allowed_values:
        return True
    if ':' not in value:
        return any(item['model'] == value for item in _build_model_options(scope=scope))
    return False


def normalize_selected_model(selected_model: str, scope: str = MODEL_SCOPE_ASSISTANT) -> str:
    value = (selected_model or '').strip()
    options = get_model_options(scope=scope)
    allowed_values = {item['value'] for item in options}
    if not value:
        return get_default_selected_model(scope=scope)
    if value in allowed_values:
        return value

    if ':' not in value:
        matches = [item['value'] for item in options if item['model'] == value]
        if len(matches) == 1:
            return matches[0]
    return get_default_selected_model(scope=scope)


def describe_selected_model(selected_model: str, scope: str = MODEL_SCOPE_ASSISTANT) -> str:
    normalized = normalize_selected_model(selected_model, scope=scope)
    for item in get_model_options(scope=scope):
        if item['value'] == normalized:
            return item['label']
    return normalized


def _build_model_options(scope: str) -> list[dict]:
    providers = get_all_providers()
    options = []
    for provider_name, config in providers.items():
        models = config.available_models or [config.default_model]
        for model_name in list(dict.fromkeys(models)):
            value = f'{provider_name}:{model_name}'
            if not _is_model_allowed(provider_name=provider_name, value=value, scope=scope):
                continue
            options.append(
                {
                    'value': value,
                    'provider': provider_name,
                    'model': model_name,
                    'label': f"{PROVIDER_NAMES.get(provider_name, provider_name)} / {model_name}",
                }
            )
    return options


def _is_model_allowed(*, provider_name: str, value: str, scope: str) -> bool:
    if scope == MODEL_SCOPE_ALL:
        return True
    if provider_name in PROJECT_BLOCKED_PROVIDERS:
        return False
    if scope in {MODEL_SCOPE_ASSISTANT, MODEL_SCOPE_PATIENT}:
        return value not in JUDGE_ONLY_MODEL_VALUES
    if scope == MODEL_SCOPE_JUDGE:
        return True
    raise ValueError(f'unsupported_model_scope:{scope}')
