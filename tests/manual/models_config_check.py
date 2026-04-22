#!/usr/bin/env python
"""Manual script to verify model configuration."""
import os
import sys
from pathlib import Path

import django
from dotenv import load_dotenv

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
django.setup()

from backend.llm.providers import get_all_providers
from backend.chat.views import get_available_models

def main() -> None:
    print("=" * 60)
    print("Checking Model Configuration")
    print("=" * 60)

    print("\n1. Providers from backend.llm.providers:")
    providers = get_all_providers()
    for name, config in providers.items():
        print(f"\n   {name}:")
        print(f"      Default model: {config.default_model}")
        print(f"      Available models: {config.available_models}")
        print(f"      SDK type: {config.sdk_type}")

    print("\n" + "=" * 60)
    print("2. Available models from backend.chat.views:")
    models = get_available_models()
    for name, model_list in models.items():
        print(f"\n   {name}: {model_list}")

    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    print("手工核对以上配置是否符合当前 .env 与供应商开通状态。")


if __name__ == "__main__":
    main()
