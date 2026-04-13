"""
Director Agent - Recommends historical characters for roundtable discussions.
"""
import json
import logging
from typing import List, Dict

from backend.llm import LLMClient

logger = logging.getLogger(__name__)


class DirectorAgent:
    """导演 Agent - 根据话题推荐历史人物"""

    SYSTEM_PROMPT = """你是一位经验丰富的导演，负责为圆桌讨论挑选最合适的角色。

你的职责：
1. 深入理解讨论话题的核心意图
2. 根据话题特点，推荐最合适的角色组合
3. 确保角色之间有观点的多样性和碰撞空间
4. 考虑角色的时代背景、专业领域与话题的相关性

推荐角色时考虑：
- 角色的专业背景与话题的匹配度
- 角色之间的观点差异和思想碰撞
- 角色扮演的难度（某些角色较难扮演）
- 讨论的深度和广度需求

你的推荐应该既有广度又有深度，既考虑学术严谨性也考虑趣味性。

重要：只推荐真实存在的历史人物，不要虚构角色。"""

    def __init__(self, provider: str = None):
        self.client = LLMClient(provider_name=provider)

    def suggest_characters(self, topic: str, count: int = 20) -> List[Dict]:
        """
        根据话题推荐历史人物

        Args:
            topic: 讨论话题
            count: 推荐角色数量，默认 20

        Returns:
            角色列表，每项包含 name, era, reason
        """
        prompt = self._build_suggestion_prompt(topic, count)

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            json_mode=True,
        )

        return self._parse_response(response)

    def _build_suggestion_prompt(self, topic: str, count: int) -> str:
        """构建推荐角色的 prompt"""
        return f"""根据以下话题，推荐 {count} 位真实的历史人物参与讨论：

话题：{topic}

要求：
1. 必须全部是真实存在的历史人物，不能是虚构角色或纯文学人物
2. 确保多样性：
   - 不同背景：哲学家、政治家、文学家、科学家、军事家等
   - 不同立场：支持方、反对方、中立派
   - 不同时代：古代、近代、现代（允许跨时空讨论）
3. 每位人物需说明推荐理由（为什么这个人物适合这个话题）

请以 JSON 数组格式返回，示例：
[
  {{"name": "孔子", "era": "春秋", "reason": "儒家思想代表，对仁义有深刻见解"}},
  {{"name": "韩非子", "era": "战国", "reason": "法家思想代表，与儒家形成对比"}}
]

只返回 JSON，不要有其他解释。"""

    def _parse_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回的 JSON 响应"""
        try:
            # 尝试直接解析
            data = json.loads(response)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'characters' in data:
                return data['characters']
            else:
                logger.warning(f"Unexpected response format: {data}")
                return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            # 尝试提取 JSON 部分
            try:
                start = response.find('[')
                end = response.rfind(']') + 1
                if start != -1 and end != 0:
                    data = json.loads(response[start:end])
                    return data
            except Exception:
                pass
            return []

    def analyze_topic(self, topic: str) -> Dict:
        """
        分析话题，返回话题的核心争议点和推荐讨论角度

        Args:
            topic: 讨论话题

        Returns:
            包含话题分析的字典
        """
        prompt = f"""分析以下话题：

话题：{topic}

请分析：
1. 这个话题的核心争议点是什么？
2. 什么样的角色最适合参与这个讨论？
3. 推荐的讨论角度有哪些？

请用 JSON 格式返回：
{{
  "core_issue": "核心争议点描述",
  "recommended_roles": ["角色类型1", "角色类型2"],
  "discussion_angles": ["角度1", "角度2", "角度3"]
}}"""

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            json_mode=True,
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error("Failed to parse topic analysis")
            return {
                "core_issue": topic,
                "recommended_roles": [],
                "discussion_angles": []
            }