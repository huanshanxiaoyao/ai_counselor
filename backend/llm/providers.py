"""
LLM Provider configuration module.

Defines the supported LLM providers and their configurations.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    sdk_type: str = "openai"  # "openai" or "anthropic"


# Environment-based provider configurations
LLM_PROVIDERS = {
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'api_key': os.getenv('OPENAI_API_KEY', ''),
        'default_model': os.getenv('OPENAI_MODEL', 'gpt-4o'),
    },
    'qwen': {
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'api_key': os.getenv('QWEN_API_KEY', ''),
        'default_model': os.getenv('QWEN_MODEL', 'qwen-plus'),
    },
    'deepseek': {
        'base_url': 'https://api.deepseek.com/v1',
        'api_key': os.getenv('DEEPSEEK_API_KEY', ''),
        'default_model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    },
    'minimax': {
        'sdk_type': 'anthropic',
        'base_url': os.getenv('ANTHROPIC_BASE_URL', 'https://api.minimax.io/anthropic'),
        'api_key': os.getenv('ANTHROPIC_API_KEY', ''),
        'default_model': os.getenv('MINIMAX_MODEL', 'MiniMax-M2.1'),
    },
}


def get_provider(name: str) -> Optional[ProviderConfig]:
    """Get provider configuration by name."""
    config = LLM_PROVIDERS.get(name)
    if not config:
        return None
    return ProviderConfig(
        name=name,
        base_url=config['base_url'],
        api_key=config.get('api_key', ''),
        default_model=config.get('default_model', 'gpt-4o'),
        sdk_type=config.get('sdk_type', 'openai'),
    )


def get_all_providers() -> dict[str, ProviderConfig]:
    """Get all configured providers."""
    return {
        name: ProviderConfig(
            name=name,
            base_url=cfg['base_url'],
            api_key=cfg.get('api_key', ''),
            default_model=cfg.get('default_model', 'gpt-4o'),
            sdk_type=cfg.get('sdk_type', 'openai'),
        )
        for name, cfg in LLM_PROVIDERS.items()
    }
