"""
Chat views for AI Counselor.
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.http import JsonResponse
from django.views import View
from django.shortcuts import render

from backend.llm import LLMClient, LLMConfigurationError, get_all_providers

logger = logging.getLogger(__name__)

# All available providers
ALL_PROVIDERS = ['qwen', 'deepseek', 'minimax', 'doubao']

PROVIDER_NAMES = {
    'qwen': '通义千问',
    'deepseek': 'DeepSeek',
    'minimax': 'MiniMax',
    'doubao': '豆包',
}

PROVIDER_COLORS = {
    'qwen': '#ff6b6b',
    'deepseek': '#4ecdc4',
    'minimax': '#45b7d1',
    'doubao': '#f39c12',
}


def get_llm_client(provider: str) -> LLMClient:
    """Create an LLM client for the specified provider."""
    return LLMClient(provider_name=provider)


def get_available_models():
    """Get available models for each provider from environment/config."""
    providers = get_all_providers()
    models = {}
    for name, config in providers.items():
        # Use available_models from config if available, otherwise default to [default_model]
        provider_models = config.available_models if config.available_models else [config.default_model]
        models[name] = list(dict.fromkeys(provider_models))  # Remove duplicates
    return models


class HomeView(View):
    """Home page view."""

    def get(self, request):
        """Render the home page."""
        return render(request, 'home/index.html')


class ChatView(View):
    """Main chat page view."""

    def get(self, request):
        """Render the chat interface."""
        import json as _json
        available_models = get_available_models()
        providers_dict = {}
        for pid in ALL_PROVIDERS:
            providers_dict[pid] = {
                'id': pid,
                'name': PROVIDER_NAMES.get(pid, pid),
                'color': PROVIDER_COLORS.get(pid, '#666'),
                'models': available_models.get(pid, []),
            }
        context = {
            'providers': _json.dumps(providers_dict),
        }
        return render(request, 'chat/index.html', context)


class ChatAPIView(View):
    """API endpoint for chat with multiple AI providers."""

    def post(self, request):
        """Handle chat request with multiple AI responses."""
        try:
            data = json.loads(request.body)
            prompt = data.get('prompt', '').strip()
            selected = data.get('providers', [])  # [{provider, model}, ...]

            if not prompt:
                return JsonResponse({'error': 'Prompt is required'}, status=400)

            if not selected:
                return JsonResponse({'error': 'No providers selected'}, status=400)

            results = self._get_ai_responses(prompt, selected)
            return JsonResponse({'responses': results})

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.exception("Chat API error")
            return JsonResponse({'error': '服务器内部错误'}, status=500)

    def _get_ai_responses(self, prompt: str, selected: list) -> dict:
        """Get responses from selected AI providers concurrently."""
        results = {}

        with ThreadPoolExecutor(max_workers=len(selected)) as executor:
            future_to_key = {
                executor.submit(
                    self._get_single_response,
                    item['provider'],
                    prompt,
                    item.get('model'),
                ): item['provider']  # Use provider name as key directly
                for item in selected
            }

            for future in as_completed(future_to_key):
                provider = future_to_key[future]
                try:
                    result = future.result()
                    results[provider] = {
                        'provider': provider,
                        'name': PROVIDER_NAMES.get(provider, provider),
                        'response': result['text'],
                        'model': result['model'],
                        'elapsed_seconds': result['elapsed_seconds'],
                        'usage': {
                            'prompt_tokens': result['usage']['prompt_tokens'],
                            'completion_tokens': result['usage']['completion_tokens'],
                            'total_tokens': result['usage']['total_tokens'],
                        },
                        'error': None,
                    }
                except Exception as e:
                    results[provider] = {
                        'provider': provider,
                        'name': PROVIDER_NAMES.get(provider, provider),
                        'response': None,
                        'model': '',
                        'elapsed_seconds': 0,
                        'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                        'error': str(e),
                    }

        return results

    def _get_single_response(self, provider: str, prompt: str, model: str = None) -> dict:
        """Get response from a single AI provider with metadata."""
        client = get_llm_client(provider)
        result = client.complete_with_metadata(
            prompt=prompt,
            system_prompt="你是一个有帮助的AI助手。请用简洁、清晰的语言回答用户的问题。",
            model=model or None,
        )
        return {
            'text': result.text,
            'model': result.model,
            'elapsed_seconds': result.elapsed_seconds,
            'usage': {
                'prompt_tokens': result.usage.prompt_tokens,
                'completion_tokens': result.usage.completion_tokens,
                'total_tokens': result.usage.total_tokens,
            },
        }


class ModelsAPIView(View):
    """API endpoint to get available models for each provider."""

    def get(self, request):
        """Return available providers and their models."""
        import requests as _requests

        # For Doubao, we can list models via API
        models_data = {}

        # Try to get models from Doubao API
        try:
            from dotenv import load_dotenv
            import os
            load_dotenv()
            doubao_key = os.getenv('DOUBAO_API_KEY', '')
            if doubao_key:
                client = _requests.get(
                    'https://ark.cn-beijing.volces.com/api/v3/models',
                    headers={'Authorization': f'Bearer {doubao_key}'},
                    timeout=10,
                )
                if client.status_code == 200:
                    data = client.json()
                    model_ids = [m['id'] for m in data.get('data', [])]
                    models_data['doubao'] = model_ids[:10]  # Limit to 10
        except Exception as e:
            logger.warning(f"Failed to fetch Doubao models: {e}")

        # For other providers, use environment defaults
        providers = get_all_providers()
        for name in ALL_PROVIDERS:
            if name not in models_data:
                config = providers.get(name)
                if config:
                    models_data[name] = [config.default_model]
                else:
                    models_data[name] = []

        # Build response
        result = {}
        for pid in ALL_PROVIDERS:
            result[pid] = {
                'name': PROVIDER_NAMES.get(pid, pid),
                'color': PROVIDER_COLORS.get(pid, '#666'),
                'models': models_data.get(pid, []),
            }

        return JsonResponse({'providers': result})
