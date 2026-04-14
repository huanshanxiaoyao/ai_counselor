#!/usr/bin/env python
"""
Test script for Doubao (豆包) LLM API.

豆包大模型使用兼容 OpenAI 的 API 格式，通过火山引擎 (Volcengine) 提供服务。
API 文档: https://www.volcengine.com/docs/82379/1399202

使用前请在火山引擎控制台开通模型服务：
1. 登录火山引擎控制台: https://console.volcengine.com/ark
2. 进入「方舟大模型平台」
3. 在「模型服务」中开通你需要的模型
4. 可选：创建推理接入点 (Endpoint) 获得更稳定的服务
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 豆包 API 配置
DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
DOUBAO_MODEL = os.getenv("DOUBAO_MODEL", "")


def list_available_models(client: OpenAI):
    """列出所有可用的模型。"""
    print("正在列出可用模型...")
    try:
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        print(f"共有 {len(model_ids)} 个模型")
        # 按名称分组显示
        print("\n部分模型列表 (前20个):")
        for m in model_ids[:20]:
            print(f"  - {m}")
        if len(model_ids) > 20:
            print(f"  ... 还有 {len(model_ids) - 20} 个模型")
        return model_ids
    except Exception as e:
        print(f"列出模型失败: {e}")
        return []


def test_model(client: OpenAI, model: str) -> bool:
    """测试指定模型是否可用。"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个有帮助的助手。"},
                {"role": "user", "content": "你好，请用一句话介绍你自己。"},
            ],
            max_tokens=100,
        )
        print(f"\n模型 {model} 测试成功!")
        print(f"回复: {response.choices[0].message.content}")
        print(f"Tokens: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")
        return True
    except Exception as e:
        err_msg = str(e)
        if "ModelNotOpen" in err_msg:
            print(f"模型 {model} 未开通，请在控制台开通此模型服务")
        elif "InvalidEndpointOrModel" in err_msg:
            print(f"模型 {model} 无效，可能需要创建推理接入点")
        else:
            print(f"模型 {model} 测试失败: {e}")
        return False


def test_doubao():
    """测试豆包大模型 API 连通性。"""
    print("=" * 60)
    print("豆包大模型 API 连通性测试")
    print("=" * 60)

    if not DOUBAO_API_KEY:
        print("错误: 未设置 DOUBAO_API_KEY 环境变量")
        print("请设置: export DOUBAO_API_KEY=你的API密钥")
        return False

    print(f"API Key: {DOUBAO_API_KEY[:8]}...{DOUBAO_API_KEY[-4:]}")
    print(f"Base URL: {DOUBAO_BASE_URL}")
    if DOUBAO_MODEL:
        print(f"指定模型: {DOUBAO_MODEL}")
    print()

    try:
        client = OpenAI(
            api_key=DOUBAO_API_KEY,
            base_url=DOUBAO_BASE_URL,
        )
        print("[OK] OpenAI client 创建成功")
        print()

        # 列出可用模型
        model_ids = list_available_models(client)
        print()

        # 如果指定了模型，测试该模型
        if DOUBAO_MODEL:
            print(f"测试指定模型: {DOUBAO_MODEL}")
            if test_model(client, DOUBAO_MODEL):
                return True

        # 否则尝试测试一些常用模型
        print("尝试测试常用模型...")
        # 推荐的模型列表（按优先级）
        recommended_models = [
            "doubao-seed-1-6-flash-250615",  # 免费/低成本
            "doubao-lite-4k-240328",
            "doubao-1-5-pro-32k-250115",
            "doubao-pro-32k-240828",
        ]

        for model in recommended_models:
            if model in model_ids:
                print(f"\n尝试模型: {model}")
                if test_model(client, model):
                    print(f"\n推荐设置环境变量: DOUBAO_MODEL={model}")
                    return True

        print("\n" + "=" * 60)
        print("未能找到已开通的模型")
        print("请在火山引擎控制台开通模型服务:")
        print("  1. 登录 https://console.volcengine.com/ark")
        print("  2. 进入「模型服务」->「模型推理」")
        print("  3. 开通你需要的模型（推荐 doubao-seed-1-6-flash 或 doubao-1-5-pro）")
        print("=" * 60)
        return False

    except Exception as e:
        print(f"API 连接失败: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    success = test_doubao()
    sys.exit(0 if success else 1)
