"""
Unified LLM Client supporting multiple providers.
"""
import os
import time
import logging
from dataclasses import dataclass, field
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


@dataclass
class TokenUsage:
    """Token usage information for a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class CompletionResult:
    """Result of an LLM completion call, including metadata."""
    text: str = ""
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    provider_name: str = ""
    elapsed_seconds: float = 0.0


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

        Returns:
            The LLM response text
        """
        result = self.complete_with_metadata(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            json_mode=json_mode,
            thinking=thinking,
            **kwargs,
        )
        return result.text

    def complete_with_metadata(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> CompletionResult:
        """
        Generate a completion from the LLM, returning full metadata including token usage.

        Returns:
            CompletionResult with text, usage, model info, etc.
        """
        resolved_model = model or self.provider.default_model
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                usage, text, resp_model = self._client.complete_with_usage(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=resolved_model,
                    json_mode=json_mode,
                    thinking=thinking,
                    **kwargs,
                )
                elapsed = time.time() - start_time

                result = CompletionResult(
                    text=text,
                    model=resp_model or resolved_model,
                    usage=usage,
                    provider_name=self.provider.name,
                    elapsed_seconds=round(elapsed, 3),
                )
                logger.info(
                    f"LLM call: provider={self.provider.name} model={result.model} "
                    f"tokens={usage.total_tokens} ({usage.prompt_tokens}+{usage.completion_tokens}) "
                    f"time={result.elapsed_seconds}s"
                )
                return result
            except LLMTimeoutError as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"LLM timeout, retrying ({attempt + 1}/{self.max_retries})")
                time.sleep(2 ** attempt)
            except LLMAPIError as e:
                last_error = e
                if e.status_code in (400, 401, 403, 404):
                    logger.error(
                        f"LLM non-retryable error (status={e.status_code}): {e}"
                    )
                    raise
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(
                    f"LLM API error (status={e.status_code}): {e}, "
                    f"retrying ({attempt + 1}/{self.max_retries})"
                )
                time.sleep(2 ** attempt)

        raise LLMMaxRetriesExceededError(
            f"LLM call failed after {self.max_retries} attempts "
            f"(provider={self.provider.name}, model={resolved_model}): {last_error}"
        )


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

    def complete_with_usage(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> tuple[TokenUsage, str, str]:
        """Complete request and return usage, text, and model name."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response_format = {"type": "json_object"} if json_mode else None

        try:
            response = self._client.chat.completions.create(
                model=model or self.provider.default_model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
        except openai.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.APIConnectionError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.APIStatusError as e:
            raise LLMAPIError(str(e), status_code=e.status_code) from e

        usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        return usage, response.choices[0].message.content, response.model


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

    def complete_with_usage(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        json_mode: bool = False,
        thinking: bool = False,
        **kwargs,
    ) -> tuple[TokenUsage, str, str]:
        """Complete request and return usage, text, and model name."""
        params = {
            "model": model or self.provider.default_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        }
        if thinking:
            params["thinking"] = {"type": "enabled"}
        if system_prompt:
            params["system"] = system_prompt

        try:
            response = self._client.messages.create(**params)
        except anthropic.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except anthropic.APIConnectionError as e:
            raise LLMTimeoutError(str(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMAPIError(str(e), status_code=e.status_code) from e

        # Handle response content, which may include ThinkingBlocks
        text_parts = []
        for block in response.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)

        usage = TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )
        return usage, "\n".join(text_parts) if text_parts else "", response.model
