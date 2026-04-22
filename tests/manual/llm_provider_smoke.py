#!/usr/bin/env python
"""
Test script for LLM providers.
"""
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from backend.llm.client import LLMClient
from backend.llm.providers import get_provider


def run_provider(provider_name: str):
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


def run_all_providers():
    """Test all configured providers."""
    providers = ['openai', 'qwen', 'deepseek', 'minimax']
    results = {}

    for provider in providers:
        results[provider] = run_provider(provider)

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
    import os
    load_dotenv()

    print("Starting LLM Provider Tests")
    print(f"Python: {sys.version}")
    print(f"Working directory: {os.getcwd()}")

    run_all_providers()
