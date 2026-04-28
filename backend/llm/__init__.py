"""
LLM module for AI Counselor.

Provides unified access to multiple LLM providers.
"""
from .client import LLMClient, CompletionResult, TokenUsage
from .providers import get_provider, get_all_providers, LLM_PROVIDERS
from .exceptions import (
    LLMError,
    LLMConfigurationError,
    LLMAPIError,
    LLMTimeoutError,
    LLMMaxRetriesExceededError,
)
from .structured_output import (
    StructuredOutputResult,
    complete_json_with_fallback,
    complete_json_with_strategy,
    is_json_mode_unsupported_error,
    parse_json_payload,
    reset_structured_output_policy_cache,
)

__all__ = [
    'LLMClient',
    'CompletionResult',
    'TokenUsage',
    'get_provider',
    'get_all_providers',
    'LLM_PROVIDERS',
    'LLMError',
    'LLMConfigurationError',
    'LLMAPIError',
    'LLMTimeoutError',
    'LLMMaxRetriesExceededError',
    'StructuredOutputResult',
    'complete_json_with_fallback',
    'complete_json_with_strategy',
    'is_json_mode_unsupported_error',
    'parse_json_payload',
    'reset_structured_output_policy_cache',
]
