#!/usr/bin/env python
"""Test script to verify model configuration."""
import os
import sys
from dotenv import load_dotenv

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

load_dotenv()

from backend.llm.providers import get_all_providers
from backend.chat.views import get_available_models

print("=" * 60)
print("Testing Model Configuration")
print("=" * 60)

# Test 1: Check providers
print("\n1. Checking providers:")
providers = get_all_providers()
for name, config in providers.items():
    print(f"\n   {name}:")
    print(f"      Default model: {config.default_model}")
    print(f"      Available models: {config.available_models}")
    print(f"      SDK type: {config.sdk_type}")

# Test 2: Check available models from views
print("\n" + "=" * 60)
print("2. Checking available models from views:")
models = get_available_models()
for name, model_list in models.items():
    print(f"\n   {name}: {model_list}")

print("\n" + "=" * 60)
print("Configuration Summary:")
print("=" * 60)

expected = {
    'doubao': ['doubao-seed-2-0-lite-260215', 'doubao-seed-2-0-mini-260215', 'doubao-seed-2-0-pro-260215'],
    'qwen': ['qwen-plus', 'qwen-max', 'qwen3.5-plus'],
    'minimax': ['MiniMax-M2.5', 'MiniMax-M2.7'],
    'deepseek': ['deepseek-chat', 'deepseek-reasoner'],
}

all_ok = True
for provider, expected_models in expected.items():
    actual_models = models.get(provider, [])
    if set(actual_models) == set(expected_models):
        print(f"✓ {provider}: OK")
    else:
        print(f"✗ {provider}: MISMATCH")
        print(f"  Expected: {expected_models}")
        print(f"  Actual:   {actual_models}")
        all_ok = False

print("\n" + "=" * 60)
if all_ok:
    print("All configurations are correct! ✓")
else:
    print("Some configurations need attention! ✗")
print("=" * 60)
