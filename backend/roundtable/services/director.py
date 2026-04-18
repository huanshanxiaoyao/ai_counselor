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

    DEFAULT_REJECTION = "评委会未能通过你推荐的人物"

    VALIDATOR_SYSTEM_PROMPT = """你是圆桌会谈的"评委会"，负责审核用户推荐的嘉宾是否符合参会资格。

【参会资格】（满足任一即通过）
1. 真实存在的历史人物或当代知名人士（政治、科学、文学、艺术、商业等领域）
2. 知名文学作品、影视、戏剧、神话、宗教典籍中的角色（如林黛玉、孙悟空、福尔摩斯、哈姆雷特）

【拒绝条件】（满足任一即驳回）
- 名字无法识别为任何真实人物或知名虚构角色
- 明显是随机字符、键盘乱敲、或恶意输入
- 仅是普通职业/称谓（如"老师"、"医生"），不指向具体个人
- 网络梗、虚构博主、不知名作品中的小人物"""

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

    def validate_manual_characters(
        self, topic: str, names: List[str]
    ) -> List[Dict]:
        """
        校验用户手动输入的人物是否为真实名人或知名文学/影视人物。

        Returns: 与 names 等长且保序的字典列表。
        LLM 返回不合法时整体 fallback 为 invalid（log warning）。
        """
        prompt = self._build_validator_prompt(topic, names)

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self.VALIDATOR_SYSTEM_PROMPT,
            json_mode=True,
        )

        parsed = self._parse_validator_response(response)
        if parsed is None or len(parsed) != len(names):
            logger.warning(
                "Validator response length mismatch or unparseable; "
                "falling back to all-invalid. names=%s response=%s",
                names, response[:500] if isinstance(response, str) else response,
            )
            return self._fallback_all_invalid(names)

        by_name = {item.get("name"): item for item in parsed if isinstance(item, dict)}
        if set(by_name.keys()) != set(names):
            logger.warning(
                "Validator response names misaligned; falling back. "
                "expected=%s got=%s", names, list(by_name.keys()),
            )
            return self._fallback_all_invalid(names)

        normalized: List[Dict] = []
        for name in names:
            item = by_name[name]
            valid = bool(item.get("valid"))
            if valid:
                normalized.append({
                    "name": name,
                    "valid": True,
                    "era": item.get("era") or "",
                    "reason": item.get("reason") or "",
                    "rejection_reason": None,
                })
            else:
                normalized.append({
                    "name": name,
                    "valid": False,
                    "era": None,
                    "reason": None,
                    "rejection_reason": item.get("rejection_reason")
                        or self.DEFAULT_REJECTION,
                })
        return normalized

    def _build_validator_prompt(self, topic: str, names: List[str]) -> str:
        names_json = json.dumps(names, ensure_ascii=False)
        return f"""【讨论话题】（仅作语境参考，不影响是否通过）
{topic}

【待审核名单】
{names_json}

请严格按以下 JSON 数组格式返回，顺序与待审核名单一致，不要输出任何其他文字：

[
  {{
    "name": "原名字",
    "valid": true,
    "era": "时代/出处，如'明代'或'清代《红楼梦》'",
    "reason": "30 字以内的人物简介",
    "rejection_reason": null
  }},
  {{
    "name": "原名字",
    "valid": false,
    "era": null,
    "reason": null,
    "rejection_reason": "具体驳回原因"
  }}
]"""

    def _parse_validator_response(self, response: str):
        """解析 LLM 响应为列表；不合法返回 None。"""
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            try:
                start = response.find('[')
                end = response.rfind(']') + 1
                if start != -1 and end > start:
                    data = json.loads(response[start:end])
                else:
                    return None
            except Exception:
                return None
        if isinstance(data, dict) and 'results' in data:
            data = data['results']
        if not isinstance(data, list):
            return None
        return data

    def _fallback_all_invalid(self, names: List[str]) -> List[Dict]:
        return [
            {
                "name": name,
                "valid": False,
                "era": None,
                "reason": None,
                "rejection_reason": self.DEFAULT_REJECTION,
            }
            for name in names
        ]