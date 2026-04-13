"""
Unified LLM Client supporting multiple providers.
"""
import os
import time
import logging
from typing import Optional, Any

import openai
import anthropic

from .providers import get_provider, ProviderConfig
from .exceptions import (
    LLMConfigurationError,
    LLMAPIError,
    LLMTimeoutError,
    LLMMaxRetriesExceededError,
)
from anthropic.types import TextBlock, ThinkingBlock

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM client that supports multiple providers.
    Supports OpenAI-compatible APIs and Anthropic SDK.
    """

    DEFAULT_TIMEOUT = 12
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        provider_name: str = None,
        provider: ProviderConfig = None,
        timeout: int = None,
        max_retries: int = None,
    ):
        if provider:
            self.provider = provider
        elif provider_name:
            self.provider = get_provider(provider_name)
            if not self.provider:
                raise LLMConfigurationError(f"Unknown provider: {provider_name}")
        else:
            # Use default provider from env
            default_provider = os.getenv('LLM_DEFAULT_PROVIDER', 'qwen')
            self.provider = get_provider(default_provider)
            if not self.provider:
                raise LLMConfigurationError(f"Default provider '{default_provider}' not configured")

        self.timeout = timeout or int(os.getenv('LLM_TIMEOUT', str(self.DEFAULT_TIMEOUT)))
        self.max_retries = max_retries or int(os.getenv('LLM_MAX_RETRIES', str(self.DEFAULT_MAX_RETRIES)))

        self._client = self._create_client()

    def _create_client(self):
        """Create the appropriate client based on provider type."""
        if self.provider.sdk_type == 'anthropic':
            return AnthropicBackend(self.provider, self.timeout)
        else:
            return OpenAIBackend(self.provider, self.timeout)

    def complete(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> str:
        """
        Generate a completion from the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            model: Override the default model
            json_mode: Whether to response in JSON format
            thinking: Enable thinking/reasoning (if supported)
            **kwargs: Additional provider-specific arguments

        Returns:
            The LLM response text
        """
        for attempt in range(self.max_retries):
            try:
                return self._client.complete(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model or self.provider.default_model,
                    json_mode=json_mode,
                    thinking=thinking,
                    **kwargs,
                )
            except LLMTimeoutError:
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"LLM timeout, retrying ({attempt + 1}/{self.max_retries})")
                time.sleep(2 ** attempt)  # Exponential backoff
            except LLMAPIError as e:
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"LLM API error: {e}, retrying ({attempt + 1}/{self.max_retries})")
                time.sleep(2 ** attempt)


class OpenAIBackend:
    """OpenAI-compatible API backend."""

    def __init__(self, provider: ProviderConfig, timeout: int):
        self.provider = provider
        self.timeout = timeout
        self._client = openai.OpenAI(
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=timeout,
        )

    def complete(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response_format = {"type": "json_object"} if json_mode else None

        response = self._client.chat.completions.create(
            model=model or self.provider.default_model,
            messages=messages,
            response_format=response_format,
            **kwargs,
        )
        return response.choices[0].message.content


class AnthropicBackend:
    """Anthropic SDK backend."""

    def __init__(self, provider: ProviderConfig, timeout: int):
        self.provider = provider
        self.timeout = timeout
        self._client = anthropic.Anthropic(
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=timeout,
        )

    def complete(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> str:
        params = {
            "model": model or self.provider.default_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "thinking": {"type": "enabled"} if thinking else None,
        }
        if system_prompt:
            params["system"] = system_prompt

        response = self._client.messages.create(**params)

        # Handle response content, which may include ThinkingBlocks
        text_parts = []
        for block in response.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            # Ignore ThinkingBlocks as they're just internal reasoning

        return "\n".join(text_parts) if text_parts else ""
