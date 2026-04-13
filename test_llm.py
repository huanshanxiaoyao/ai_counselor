#!/usr/bin/env python
"""
Test script for LLM providers.
"""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from llm.client import LLMClient
from llm.providers import get_provider


def test_provider(provider_name: str):
    """Test a specific provider."""
    print(f"\n{'='*60}")
    print(f"Testing provider: {provider_name}")
    print('='*60)

    try:
        provider = get_provider(provider_name)
        if not provider:
            print(f"ERROR: Provider '{provider_name}' not found")
            return False

        print(f"  SDK type: {provider.sdk_type}")
        print(f"  Base URL: {provider.base_url}")
        print(f"  Default model: {provider.default_model}")
        print(f"  API key: {provider.api_key[:20]}..." if provider.api_key else "  API key: None")

        client = LLMClient(provider_name=provider_name)
        print(f"  Client created successfully")

        response = client.complete(
            prompt="Hello, please respond with a brief greeting.",
            system_prompt="You are a helpful assistant.",
        )
        print(f"  Response: {response}")
        print(f"SUCCESS: {provider_name} is working!")
        return True

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_providers():
    """Test all configured providers."""
    providers = ['openai', 'qwen', 'deepseek', 'minimax']
    results = {}

    for provider in providers:
        results[provider] = test_provider(provider)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for provider, success in results.items():
        status = "PASS" if success else "FAIL"
        print(f"  {provider}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    return all_passed


if __name__ == '__main__':
    # Load .env file if exists
    from dotenv import load_dotenv
    load_dotenv()

    print("Starting LLM Provider Tests")
    print(f"Python: {sys.version}")
    print(f"Working directory: {os.getcwd()}")

    test_all_providers()
