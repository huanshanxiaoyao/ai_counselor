from __future__ import annotations

from django.conf import settings

from backend.llm.providers import get_all_providers


PROVIDER_NAMES = {
    'qwen': '通义千问',
    'deepseek': 'DeepSeek',
    'minimax': 'MiniMax',
    'doubao': '豆包',
    'openai': 'OpenAI',
}


def get_default_selected_model() -> str:
    providers = get_all_providers()
    default_provider = getattr(settings, 'LLM_DEFAULT_PROVIDER', 'qwen')
    provider_config = providers.get(default_provider)
    if provider_config is None:
        for provider_name, config in providers.items():
            model_name = (config.default_model or '').strip()
            if model_name:
                return f'{provider_name}:{model_name}'
        return ''
    model_name = (provider_config.default_model or '').strip()
    return f'{default_provider}:{model_name}' if model_name else default_provider


def get_model_options() -> list[dict]:
    providers = get_all_providers()
    options = []
    default_value = get_default_selected_model()
    for provider_name, config in providers.items():
        models = config.available_models or [config.default_model]
        for model_name in list(dict.fromkeys(models)):
            value = f'{provider_name}:{model_name}'
            options.append(
                {
                    'value': value,
                    'provider': provider_name,
                    'model': model_name,
                    'label': f"{PROVIDER_NAMES.get(provider_name, provider_name)} / {model_name}",
                    'is_default': value == default_value,
                }
            )
    return options


def normalize_selected_model(selected_model: str) -> str:
    value = (selected_model or '').strip()
    options = get_model_options()
    allowed_values = {item['value'] for item in options}
    if not value:
        return get_default_selected_model()
    if value in allowed_values:
        return value

    if ':' not in value:
        matches = [item['value'] for item in options if item['model'] == value]
        if len(matches) == 1:
            return matches[0]
    return get_default_selected_model()


def describe_selected_model(selected_model: str) -> str:
    normalized = normalize_selected_model(selected_model)
    for item in get_model_options():
        if item['value'] == normalized:
            return item['label']
    return normalized
