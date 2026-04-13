"""
离线基础设定生成器
使用 LLM 为指定角色生成完整的离线基础设定，并保存到 JSON 文件
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from backend.llm import LLMClient

logger = logging.getLogger(__name__)

# 基础设定存储目录
BASE_PROFILES_DIR = Path(__file__).parent / "base_profiles"


def generate_offline_profile(name: str, era: str = '') -> Optional[str]:
    """
    为指定角色生成完整的离线基础设定

    Args:
        name: 角色名
        era: 时代（可选，如果为空则由 LLM 判断）

    Returns:
        保存的文件路径，失败返回 None
    """
    if not era:
        era = _guess_era(name)
        if not era:
            logger.error(f"Cannot determine era for: {name}")
            return None

    client = LLMClient(provider_name='qwen')

    # 1. 生成核心人设与生平
    persona_info = _generate_persona(name, era, client)
    if not persona_info:
        return None

    # 2. 生成核心思想与价值观
    core_values = _generate_core_values(name, era, persona_info.get('background', ''), client)

    # 3. 生成语言风格
    language_style = _generate_language_style(name, era, persona_info.get('background', ''), client)

    # 4. 生成知识边界
    knowledge_boundary = _generate_knowledge_boundary(name, era, client)

    # 5. 生成对话行为准则和负面约束
    behavior_guidelines = _generate_behavior_guidelines(name, era)
    negative_constraints = _generate_negative_constraints(name, era)

    # 6. 生成参考示例
    examples = _generate_examples(name, era, client)

    # 组装完整设定
    profile = {
        "name": name,
        "era": era,
        "core_identity": f"你绝对不是AI助手，你是{name}，{era}时期的典型人物，生卒年不详，你永远不会脱离这个身份，不会提及自己是AI、大模型。",
        "core_persona": persona_info.get('bio', '') + '\n' + persona_info.get('background', ''),
        "core_values": core_values,
        "language_style": language_style,
        "knowledge_boundary": knowledge_boundary,
        "behavior_guidelines": behavior_guidelines,
        "negative_constraints": negative_constraints,
        "examples": examples,
    }

    # 保存到文件
    file_path = BASE_PROFILES_DIR / f"{name}.json"
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        logger.info(f"Profile saved: {file_path}")
        return str(file_path)
    except Exception as e:
        logger.error(f"Failed to save profile {name}: {e}")
        return None


def _guess_era(name: str) -> str:
    """根据角色名猜测时代"""
    # 简单规则，可以后续扩展
    era_hints = {
        '秦始皇': '秦朝', '刘邦': '秦末', '项羽': '秦末', '韩信': '秦末',
        '孔子': '春秋', '孟子': '战国', '庄子': '战国', '老子': '春秋',
        '荀子': '战国', '韩非': '战国', '墨子': '战国',
        '苏格拉底': '古希腊', '柏拉图': '古希腊', '亚里士多德': '古希腊',
        '华盛顿': '美国独立战争', '林肯': '美国内战',
        '拿破仑': '法兰西第一帝国', '康熙': '清朝', '乾隆': '清朝',
    }
    return era_hints.get(name, '')


def _generate_persona(name: str, era: str, client: LLMClient) -> Dict:
    """生成核心人设与生平"""
    prompt = f"""为历史人物"{name}"（{era}时期）生成核心人设信息。

请生成：
1. bio：一句话简介（50字以内），精炼概括人物核心身份
2. background：详细背景介绍（300字以内），包括：
   - 人物生平概要（重要经历、人生转折点）
   - 社会地位和角色
   - 在历史上的主要成就或影响

请用JSON格式返回，包含字段：bio, background"""

    try:
        response = client.complete(
            prompt=prompt,
            system_prompt=f"你是一个专业的历史人物知识专家。请为{name}（{era}）生成准确的人设信息。",
            json_mode=True,
        )
        result = json.loads(response)
        return {
            'bio': result.get('bio', f'{name}，{era}时期著名人物'),
            'background': result.get('background', ''),
        }
    except Exception as e:
        logger.error(f"Failed to generate persona for {name}: {e}")
        return {'bio': f'{name}，{era}时期著名人物', 'background': ''}


def _generate_core_values(name: str, era: str, background: str, client: LLMClient) -> str:
    """生成核心思想与价值观"""
    prompt = f"""为历史人物"{name}"（{era}时期）生成核心思想与价值观描述。

人物背景：{background}

请生成一段200字以内的文字，描述该人物的核心主张、人生信仰、处事原则。
明确他对世界、人生、关键事件的核心态度。
用该人物的第一人称视角来描述。"""

    try:
        response = client.complete(
            prompt=prompt,
            system_prompt=f"你是一个专业的历史人物知识专家。请为{name}生成符合其身份的核心思想描述。",
        )
        return response.strip()
    except Exception as e:
        logger.error(f"Failed to generate core values for {name}: {e}")
        return f'{name}有着独特的价值观和人生信条。'


def _generate_language_style(name: str, era: str, background: str, client: LLMClient) -> Dict:
    """生成语言风格"""
    prompt = f"""为历史人物"{name}"（{era}时期）生成语言风格描述。

人物背景：{background}

请生成该人物的语言风格：
1. tone：整体语气特点（如：豪迈直率、温文尔雅、犀利冷峻、恬淡平和）
2. catchphrases：5-8个该人物可能会用的经典表达/口头禅
3. speaking_habits：说话习惯（如：善用反问、惯用排比、言简意赅、善用比喻）
4. forbidden_words：5-10个该人物绝对不会使用的现代词汇（如：现代词汇、网络用语、专业术语列表）

请用JSON格式返回，包含字段：tone, catchphrases, speaking_habits, forbidden_words"""

    try:
        response = client.complete(
            prompt=prompt,
            system_prompt=f"你是一个专业的历史人物知识专家。请为{name}生成符合其身份的语言风格。",
            json_mode=True,
        )
        result = json.loads(response)
        # 确保 forbidden_words 字段存在
        if 'forbidden_words' not in result:
            result['forbidden_words'] = ['现代词汇', '网络用语', 'AI', '大模型']
        return result
    except Exception as e:
        logger.error(f"Failed to generate language style for {name}: {e}")
        return {
            'tone': '中性',
            'catchphrases': [],
            'speaking_habits': '一般的说话习惯',
            'forbidden_words': ['现代词汇', '网络用语', 'AI', '大模型'],
        }


def _generate_knowledge_boundary(name: str, era: str, client: LLMClient) -> Dict:
    """生成知识边界"""
    prompt = f"""为历史人物"{name}"（{era}时期）生成知识边界。

请确定：
1. knowledge_cutoff：该人物知识的最终时间点（通常是其去世年份或认知截止年份）
2. can_discuss：该人物可能讨论的话题/概念（其所在时代已知的事物），列出8-15个
3. cannot_discuss：该人物不可能知道的事物（后世才出现的人物、事件、概念），列出8-15个

请用JSON格式返回，包含字段：knowledge_cutoff, can_discuss, cannot_discuss"""

    try:
        response = client.complete(
            prompt=prompt,
            system_prompt=f"你是一个专业的历史人物知识专家。请为{name}生成严格的知识边界。",
            json_mode=True,
        )
        result = json.loads(response)
        return {
            'knowledge_cutoff': result.get('knowledge_cutoff', f'{era}时期'),
            'can_discuss': result.get('can_discuss', []),
            'cannot_discuss': result.get('cannot_discuss', []),
        }
    except Exception as e:
        logger.error(f"Failed to generate knowledge boundary for {name}: {e}")
        return {
            'knowledge_cutoff': f'{era}时期',
            'can_discuss': [],
            'cannot_discuss': [],
        }


def _generate_behavior_guidelines(name: str, era: str) -> str:
    """生成对话行为准则"""
    return f"""以第一人称对话，符合{name}的身份和语气；
对话要体现人物的性格特点，有情感、有温度；
回应要贴合问题，用符合人物习惯的方式展开；
永远坚守人物的核心立场和价值观。"""


def _generate_negative_constraints(name: str, era: str) -> str:
    """生成负面约束"""
    return f"""1. 禁止使用现代词汇、网络用语、互联网梗、不符合时代的表达；
2. 禁止脱离人设，以AI助手的身份回答问题；
3. 禁止出现历史穿越、事实错误、与人物生平相悖的内容；
4. 禁止OOC，说出任何不符合{name}性格、身份、立场的话。"""


def _generate_examples(name: str, era: str, client: LLMClient) -> list:
    """生成参考示例"""
    prompt = f"""为历史人物"{name}"（{era}时期）生成3个问答示例。

请生成3组用户问题和该人物的可能回答。
每个回答应该：
- 符合人物的身份和语言风格
- 50-150字
- 展现人物的核心思想和性格特点

请用JSON数组格式返回，每项包含：user（用户问题）, you（人物回答）"""

    try:
        response = client.complete(
            prompt=prompt,
            system_prompt=f"你是一个专业的历史人物模拟专家。请为{name}生成真实的问答示例。",
            json_mode=True,
        )
        result = json.loads(response)
        if isinstance(result, list):
            return result[:3]  # 只取前3个
        elif isinstance(result, dict) and 'examples' in result:
            return result['examples'][:3]
        return []
    except Exception as e:
        logger.error(f"Failed to generate examples for {name}: {e}")
        return []


def save_generated_profile(name: str, profile: Dict) -> Optional[str]:
    """
    保存生成的基础设定到文件

    Args:
        name: 角色名
        profile: 设定字典

    Returns:
        保存的文件路径
    """
    file_path = BASE_PROFILES_DIR / f"{name}.json"
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        logger.info(f"Profile saved: {file_path}")
        return str(file_path)
    except Exception as e:
        logger.error(f"Failed to save profile {name}: {e}")
        return None
