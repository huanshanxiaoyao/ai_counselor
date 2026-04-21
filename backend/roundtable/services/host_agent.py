"""
Host Agent (主持人Agent) - 扩展自Moderator Agent
负责主持人功能、讨论流程控制、发言权管理
"""
import json
import logging
import re
from typing import List, Dict, Optional, Tuple

from backend.llm import LLMClient, TokenUsage

logger = logging.getLogger(__name__)


class HostAgent:
    """AI主持人 Agent - 负责控场和引导讨论（扩展自ModeratorAgent）"""

    SYSTEM_PROMPT = """你是一位专业、中立的主持人，负责主持圆桌讨论。

你的职责：
1. 开场：介绍话题、参与者和讨论规则
2. 控场：确保讨论围绕话题及其衍生方向展开，可以发散但不应脱离话题的内在逻辑
3. 平衡：让每位参与者都有发言机会
4. 引导：当讨论游离于话题之外时，通过提问引导回到与话题相关的方向
5. 总结：适时进行阶段性总结
6. 收尾：生成最终总结

你的风格：
- 中立：不表达自己的观点
- 引导性：多用提问引导讨论
- 简洁：发言简短有力
- 礼貌：维护良好的讨论氛围

重要规则：
- 每次只邀请一位角色发言
- 用 @角色名 邀请特定角色发言
- 发言权在你手中，只有你邀请的角色才能发言"""

    def __init__(self, provider: str = None):
        self.client = LLMClient(provider_name=provider)
        self.last_token_usage: Optional[TokenUsage] = None

    def _complete(self, **kwargs) -> str:
        """LLM call wrapper that tracks token usage."""
        result = self.client.complete_with_metadata(**kwargs)
        self.last_token_usage = result.usage
        return result.text

    def generate_opening(
        self,
        topic: str,
        characters: List[Dict],
        user_role: str
    ) -> str:
        """
        生成开场白

        Args:
            topic: 讨论话题
            characters: 角色配置列表
            user_role: 用户角色 (host/participant/observer)

        Returns:
            开场白文本
        """
        participant_list = [f"{c['name']}（{c['era']}）" for c in characters]
        participants_str = "、".join(participant_list)

        user_role_desc = {
            'host': '用户担任主持人，控制发言权',
            'participant': '用户作为参与者参与讨论',
            'observer': '用户作为旁观者观看讨论'
        }.get(user_role, '旁观者')

        prompt = f"""为以下圆桌讨论生成开场白：

话题：{topic}
参与者：{participants_str}
用户角色：{user_role_desc}

开场白应该：
1. 自我介绍为主持人
2. 介绍讨论话题
3. 介绍各位参与者（简要）
4. 说明讨论规则（200字限制、@mention发言机制）
5. 邀请第一位角色发言

保持简洁，约 200-300 字。

格式要求：
- 以"【主持人】"开头
- 邀请角色时用"@角色名"格式"""

        response = self._complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
        )

        return f"【主持人】{response.strip()}"

    def generate_invitation(
        self,
        character_name: str,
        topic: str,
        conversation_history: str = "",
        transition: str = None
    ) -> str:
        """
        生成邀请角色发言的文案

        Args:
            character_name: 被邀请的角色名
            topic: 讨论话题
            conversation_history: 对话历史
            transition: 可选的过渡语（用于承上启下）

        Returns:
            邀请文案
        """
        transition_part = f"\n承上启下：{transition}" if transition else ""

        prompt = f"""作为主持人，邀请角色发言：

被邀请角色：{character_name}
话题：{topic}
{transition_part}

对话历史：
{conversation_history or '（暂无）'}

请生成一段简短的邀请语（50字以内），用 @角色名 格式邀请该角色就当前话题发表看法。
{('可以呼应上一位的观点，自然过渡。' if transition else '保持引导性，让角色有发挥空间。')}
引导角色围绕话题"{topic}"或其衍生方向展开。"""

        response = self._complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
        )

        return response.strip()

    def should_respond_to_player(
        self,
        player_message: str,
        conversation_history: str
    ) -> bool:
        """
        判断主持人是否应该回应参与者的发言（参与者模式）

        Args:
            player_message: 参与者的发言内容
            conversation_history: 对话历史

        Returns:
            是否应该回应
        """
        # 简单策略：如果参与者发言有意义的问题或观点，主持人应该回应
        # 可以后续优化为LLM判断

        if not player_message:
            return False

        # 如果参与者@了某个角色，主持人不需要额外回应
        if player_message.strip().startswith('@'):
            return False

        # 简化为：大部分情况都回应，除非是简单的赞同
        short_acknowledgments = ['好', '是', '对的', '嗯', '好观点', '有道理']
        if player_message.strip() in short_acknowledgments:
            return False

        return True

    def decide_next_speaker(
        self,
        characters: List[Dict],
        last_speaker: str,
        conversation_history: str,
        topic: str,
        use_llm: bool = False,
        round_count: int = 0
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        决定下一个发言角色（LLM智能决策）

        机制：
        - 初始化阶段（round_count <= 角色数量）：使用简单轮询
        - LLM决策阶段（round_count > 角色数量）：每轮都使用LLM决策

        Args:
            characters: 所有角色列表
            last_speaker: 最后发言的角色
            conversation_history: 对话历史
            topic: 讨论话题
            use_llm: 是否使用LLM决策
            round_count: 当前轮次

        Returns:
            Tuple[下一个角色名, 过渡语(可选)]，如果没有则返回(None, None)
        """
        if not characters:
            return None, None

        character_names = [c['name'] for c in characters]

        # 初始化阶段：使用简单轮询
        if round_count <= len(characters):
            if not last_speaker or last_speaker == '主持人':
                return character_names[0], None
            try:
                idx = character_names.index(last_speaker)
                next_idx = (idx + 1) % len(character_names)
                return character_names[next_idx], None
            except ValueError:
                return character_names[0] if character_names else None, None

        # LLM决策阶段：每轮都使用LLM
        if use_llm:
            return self.decide_next_with_llm(characters, conversation_history, last_speaker, topic)

        # 兜底：轮询策略
        try:
            idx = character_names.index(last_speaker) if last_speaker else -1
            next_idx = (idx + 1) % len(character_names)
            return character_names[next_idx], None
        except ValueError:
            return character_names[0] if character_names else None, None

    def decide_next_with_llm(
        self,
        characters: List[Dict],
        conversation_history: str,
        last_speaker: str,
        topic: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        使用LLM智能决策下一轮发言（承上启下）

        Args:
            characters: 所有角色列表
            conversation_history: 对话历史
            last_speaker: 最后发言的角色
            topic: 讨论话题

        Returns:
            Tuple[下一个角色名, 过渡语]
        """
        if not characters:
            return None, None

        character_names = [c['name'] for c in characters]
        # 取最近10条消息作为上下文
        recent_history = self._extract_recent_history(conversation_history, 10)

        prompt = f"""分析以下讨论历史，决定下一轮邀请谁发言：

话题：{topic}
最后发言：{last_speaker}
最近讨论历史：
{recent_history or '（暂无）'}

请决定：
1. 邀请谁发言？选择与上一轮观点相关或发言较少的角色
2. 如何承上启下？用一句简短的话概括过渡（30字以内）

回复格式（只返回JSON）：
{{"invite": "角色名", "transition": "过渡语"}}

注意：
- 只从以下角色中选择：{', '.join(character_names)}
- 过渡语要自然衔接上文
- 不要邀请已连续发言2轮的角色
- 选择能从新角度探讨话题或其衍生子话题的角色，避免讨论停留在同一层面打转
- 过渡语应帮助衔接上下文，同时引导发言者围绕话题及其相关延伸展开"""

        try:
            response = self._complete(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                json_mode=True,
            )
            # 尝试解析JSON
            import json
            result = json.loads(response)
            invite = result.get('invite')
            transition = result.get('transition', '')

            # 验证邀请的角色是否在列表中
            if invite in character_names:
                return invite, transition
            else:
                # 如果LLM返回的角色不在列表中，回退到轮询
                logger.warning(f"LLM返回的角色'{invite}'不在列表中，使用轮询")
                idx = character_names.index(last_speaker) if last_speaker in character_names else -1
                next_idx = (idx + 1) % len(character_names)
                return character_names[next_idx], None

        except Exception as e:
            logger.error(f"LLM决策失败: {e}，使用轮询策略")
            idx = character_names.index(last_speaker) if last_speaker in character_names else -1
            next_idx = (idx + 1) % len(character_names)
            return character_names[next_idx], None

    def _extract_recent_history(self, history: str, max_messages: int = 10) -> str:
        """从对话历史中提取最近的消息"""
        if not history:
            return ""
        lines = history.strip().split('\n')
        # 每行是一条消息，取最后max_messages条
        recent = lines[-max_messages:] if len(lines) > max_messages else lines
        return '\n'.join(recent)

    def generate_response_to_player(
        self,
        player_message: str,
        conversation_history: str,
        topic: str
    ) -> str:
        """
        生成主持人对参与者发言的回应

        Args:
            player_message: 参与者的发言
            conversation_history: 对话历史
            topic: 讨论话题

        Returns:
            回应文本
        """
        prompt = f"""作为主持人，回应参与者的发言：

参与者发言：{player_message}
话题：{topic}
对话历史：
{conversation_history or '（暂无）'}

请生成一段简短的回应（50字以内），要求：
1. 认可参与者的发言
2. 体现主持人对讨论的引导作用
3. 如果合适，可以提出追问或过渡到下一个话题

保持中立和礼貌。"""

        response = self._complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
        )

        return response.strip()

    def should_continue(
        self,
        current_round: int,
        max_rounds: int,
        recent_messages: List[str]
    ) -> bool:
        """
        判断是否继续讨论

        Args:
            current_round: 当前轮次
            max_rounds: 最大轮次
            recent_messages: 最近的消息列表

        Returns:
            是否继续
        """
        if current_round >= max_rounds:
            return False

        # 如果最近几轮没有实质讨论内容，可以考虑结束
        if len(recent_messages) >= 4:
            recent = recent_messages[-4:]
            avg_length = sum(len(m) for m in recent) / len(recent)
            if avg_length < 30 and current_round > 10:
                return False

        return True

    def generate_summary(
        self,
        topic: str,
        recent_messages: List[str]
    ) -> str:
        """
        生成阶段性总结

        Args:
            topic: 讨论话题
            recent_messages: 最近的发言列表

        Returns:
            总结文本
        """
        if not recent_messages:
            return ""

        messages_str = "\n".join(recent_messages[-6:])

        prompt = f"""对以下讨论进行阶段性总结：

话题：{topic}
近期发言：
{messages_str}

请做一个简短的阶段性总结（100字以内），指出：
1. 讨论已覆盖的要点
2. 各方的主要观点
3. 接下来可以深入的方向

以"【主持人总结】"开头。"""

        response = self._complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
        )

        return f"【主持人总结】{response.strip()}"

    def generate_closing(
        self,
        topic: str,
        characters: List[Dict],
        discussion_summary: str
    ) -> str:
        """
        生成结束语

        Args:
            topic: 讨论话题
            characters: 角色列表
            discussion_summary: 讨论总结

        Returns:
            结束语文本
        """
        participant_names = [c['name'] for c in characters]

        prompt = f"""为圆桌讨论生成结束语：

话题：{topic}
参与者：{participant_names}
讨论总结：{discussion_summary}

结束语应该：
1. 感谢各位参与者
2. 总结讨论的主要成果
3. 提出开放性问题或未来思考

保持简洁，约 150-200 字。

格式要求：
- 以"【主持人】"开头"""

        response = self._complete(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
        )

        return f"【主持人】{response.strip()}"


# 保持向后兼容
ModeratorAgent = HostAgent
