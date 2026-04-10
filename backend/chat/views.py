"""
Chat views for AI Counselor.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.http import JsonResponse
from django.views import View
from django.shortcuts import render

from backend.llm import LLMClient, LLMConfigurationError

logger = logging.getLogger(__name__)

# Providers to use for multi-AI chat
AI_PROVIDERS = ['qwen', 'deepseek', 'minimax']

PROVIDER_NAMES = {
    'qwen': '通义千问',
    'deepseek': 'DeepSeek',
    'minimax': 'MiniMax',
}


def get_llm_client(provider: str) -> LLMClient:
    """Create an LLM client for the specified provider."""
    return LLMClient(provider_name=provider)


class ChatView(View):
    """Main chat page view."""

    def get(self, request):
        """Render the chat interface."""
        return render(request, 'chat/index.html')


class ChatAPIView(View):
    """API endpoint for chat with multiple AI providers."""

    def post(self, request):
        """Handle chat request with multiple AI responses."""
        try:
            data = json.loads(request.body)
            prompt = data.get('prompt', '').strip()

            if not prompt:
                return JsonResponse({'error': 'Prompt is required'}, status=400)

            results = self._get_ai_responses(prompt)
            return JsonResponse({'responses': results})

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.exception("Chat API error")
            return JsonResponse({'error': str(e)}, status=500)

    def _get_ai_responses(self, prompt: str) -> dict:
        """Get responses from all AI providers concurrently."""
        results = {}

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_provider = {
                executor.submit(self._get_single_response, provider, prompt): provider
                for provider in AI_PROVIDERS
            }

            for future in as_completed(future_to_provider):
                provider = future_to_provider[future]
                try:
                    response = future.result()
                    results[provider] = {
                        'name': PROVIDER_NAMES.get(provider, provider),
                        'response': response,
                        'error': None,
                    }
                except Exception as e:
                    results[provider] = {
                        'name': PROVIDER_NAMES.get(provider, provider),
                        'response': None,
                        'error': str(e),
                    }

        return results

    def _get_single_response(self, provider: str, prompt: str) -> str:
        """Get response from a single AI provider."""
        client = get_llm_client(provider)
        return client.complete(
            prompt=prompt,
            system_prompt="你是一个有帮助的AI助手。请用简洁、清晰的语言回答用户的问题。",
        )
