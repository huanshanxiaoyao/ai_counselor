"""
Auto Continue Service - 自动继续讨论服务
负责在开场白后自动邀请角色发言，实现完全自动化的讨论流程
"""
import logging
import time
from typing import Optional, Tuple, List, Dict

from django.db import close_old_connections

from backend.llm import LLMClient
from backend.roundtable.models import Discussion, Character, Message

logger = logging.getLogger(__name__)


class AutoContinueService:
    """
    自动继续讨论服务

    机制：
    1. 初始化阶段（Round <= 角色数量）：按顺序轮询每个角色，不使用LLM决策
    2. LLM决策阶段（Round > 角色数量）：每轮使用LLM决策下一位发言者
    """

    def __init__(self, discussion_id: int):
        self.discussion_id = discussion_id
        self._discussion: Optional[Discussion] = None
        self._characters: List[Character] = []
        self._character_count: int = 0

    def run(self):
        """
        执行自动继续讨论主循环
        """
        try:
            close_old_connections()
            self._discussion = Discussion.objects.get(id=self.discussion_id)
            self._characters = list(self._discussion.characters.all())
            self._character_count = len(self._characters)

            if self._character_count == 0:
                logger.warning(f"[AutoContinue:{self.discussion_id}] 没有角色，停止")
                return

            logger.info(f"[AutoContinue:{self.discussion_id}] 开始自动继续，共 {self._character_count} 个角色")

            # 主循环
            while self._should_continue():
                close_old_connections()
                self._refresh_state()

                # 判断当前阶段
                current_round = self._discussion.current_round

                if current_round <= self._character_count:
                    # 初始化阶段：按顺序轮询
                    self._run_init_phase(current_round)
                else:
                    # LLM决策阶段
                    self._run_llm_phase()

                # 短暂休息
                time.sleep(1)

            # 循环退出后，正常结束讨论
            self._finish_discussion()
            logger.info(f"[AutoContinue:{self.discussion_id}] 讨论正常结束，达到最大轮次 {self._discussion.max_rounds}")

        except Discussion.DoesNotExist:
            logger.error(f"[AutoContinue:{self.discussion_id}] 讨论不存在")
        except Exception as e:
            logger.exception(f"[AutoContinue:{self.discussion_id}] 出错: {e}")

    def _should_continue(self) -> bool:
        """判断是否应该继续讨论"""
        if not self._discussion:
            return False
        if self._discussion.status == 'finished':
            return False
        if self._discussion.current_round >= self._discussion.max_rounds:
            return False
        return True

    def _refresh_state(self):
        """刷新讨论和角色状态"""
        self._discussion.refresh_from_db()
        self._characters = list(self._discussion.characters.all())

    def _get_conversation_history(self, limit: int = 20) -> str:
        """获取对话历史"""
        messages = list(self._discussion.messages.all())[-limit:]
        lines = []
        for msg in messages:
            speaker = msg.character.name if msg.character else '系统'
            lines.append(f"{speaker}：{msg.content}")
        return "\n".join(lines)

    def _run_init_phase(self, current_round: int):
        """
        初始化阶段：按顺序邀请每个角色发言（不使用LLM决策）

        Round 1: 主持人开场（已完成），current_round=1
        Round 2: 邀请角色1，current_round=2
        ...
        注意：首位角色可能在开场白中被邀请过，需要跳过
        """
        # 计算当前应该邀请哪个角色（从索引0开始）
        # Round 1 -> char_index = 0 (首位角色)
        # Round 2 -> char_index = 1 (第2个角色)
        char_index = current_round - 1

        if char_index < 0:
            # Round 1: 开场刚完成，等待下一轮
            return

        if char_index >= self._character_count:
            # 初始化阶段完成，标记并进入下一阶段
            self._discussion.init_completed = True
            self._discussion.save()
            self._broadcast({
                'type': 'phase_change',
                'data': {'phase': 'llm', 'message': '初始化阶段完成，进入LLM决策阶段'}
            })
            self._broadcast_debug(f"[阶段切换] 初始化完成，进入LLM决策阶段")
            logger.info(f"[AutoContinue:{self.discussion_id}] 初始化阶段完成，进入LLM决策阶段")
            return

        char = self._characters[char_index]

        # 关键修复：跳过已发言的角色（可能在开场白中被邀请过）
        char.refresh_from_db()
        if char.message_count > 0:
            self._broadcast_debug(f"[初始化] {char.name} 已发言({char.message_count}次)，跳过")
            logger.info(f"[AutoContinue:{self.discussion_id}] {char.name} 已发言，跳过，进入下一轮")
            # 原子自增，避免与 Consumer 的并发写冲突
            from django.db.models import F
            Discussion.objects.filter(id=self.discussion_id).update(
                current_round=F('current_round') + 1,
            )
            self._discussion.refresh_from_db()
            return
        history = self._get_conversation_history()

        # 生成邀请语（不使用LLM，简单生成）
        from .host_agent import HostAgent
        host = HostAgent()
        invitation = host.generate_invitation(
            character_name=char.name,
            topic=self._discussion.topic,
            conversation_history=history,
        )

        # 保存邀请消息
        Message.objects.create(
            discussion=self._discussion,
            content=invitation,
            word_count=len(invitation),
            is_moderator=True,
        )

        # 原子更新，避免与 Consumer 并发写冲突
        from django.db.models import F
        Discussion.objects.filter(id=self.discussion_id).update(
            current_round=F('current_round') + 1,
            current_speaker=char.name,
        )
        self._discussion.refresh_from_db()

        # 广播邀请消息
        self._broadcast({
            'type': 'message',
            'data': {
                'speaker': '主持人',
                'content': invitation,
                'is_moderator': True,
                'is_user': False,
            }
        })
        self._broadcast_debug(f"[初始化:Round {self._discussion.current_round}] 邀请 {char.name}")

        logger.info(f"[AutoContinue:{self.discussion_id}] 第{self._discussion.current_round}轮(初始化): 邀请 {char.name}")

        # 生成角色发言
        time.sleep(0.5)
        self._generate_character_speech(char, history + f"\n主持人：{invitation}")

    def _run_llm_phase(self):
        """LLM决策阶段：每轮使用LLM决策下一位发言者"""
        history = self._get_conversation_history()
        last_speaker = self._discussion.current_speaker or ''

        from .host_agent import HostAgent
        host = HostAgent()

        # 关键改变：每一轮都使用LLM决策
        self._broadcast_debug(f"[LLM决策] 当前轮次={self._discussion.current_round}, 最后发言者={last_speaker}")
        next_char_name, transition = host.decide_next_speaker(
            characters=[{'name': c.name} for c in self._characters],
            last_speaker=last_speaker,
            conversation_history=history,
            topic=self._discussion.topic,
            use_llm=True,  # 每次都用LLM
            round_count=self._discussion.current_round,
        )

        if not next_char_name:
            self._broadcast_debug(f"[LLM决策] 无法决定下一位发言者，停止")
            logger.info(f"[AutoContinue:{self.discussion_id}] 无法决定下一位发言者，停止")
            self._discussion.status = 'finished'
            self._discussion.save()
            return

        # 查找角色对象
        next_char = next((c for c in self._characters if c.name == next_char_name), None)
        if not next_char:
            self._broadcast_debug(f"[LLM决策] 找不到角色 {next_char_name}")
            logger.error(f"[AutoContinue:{self.discussion_id}] 找不到角色 {next_char_name}")
            return

        # 生成邀请语
        invitation = host.generate_invitation(
            character_name=next_char_name,
            topic=self._discussion.topic,
            conversation_history=history,
            transition=transition,
        )

        # 保存邀请消息
        Message.objects.create(
            discussion=self._discussion,
            content=invitation,
            word_count=len(invitation),
            is_moderator=True,
        )

        # 原子更新，避免与 Consumer 并发写冲突
        from django.db.models import F
        Discussion.objects.filter(id=self.discussion_id).update(
            current_round=F('current_round') + 1,
            current_speaker=next_char_name,
        )
        self._discussion.refresh_from_db()

        # 广播邀请消息
        self._broadcast({
            'type': 'message',
            'data': {
                'speaker': '主持人',
                'content': invitation,
                'is_moderator': True,
                'is_user': False,
            }
        })
        self._broadcast_debug(f"[LLM:Round {self._discussion.current_round}] 邀请 {next_char_name}")

        logger.info(f"[AutoContinue:{self.discussion_id}] 第{self._discussion.current_round}轮(LLM): 邀请 {next_char_name}")

        # 生成角色发言
        time.sleep(0.5)
        self._generate_character_speech(next_char, history + f"\n主持人：{invitation}")

    def _generate_character_speech(self, char: Character, history: str):
        """生成角色发言"""
        from .character import CharacterAgent

        char.refresh_from_db()
        character_agent = CharacterAgent(provider=char.llm_provider or None)

        speech = character_agent.generate_speech(
            character_config={
                'name': char.name,
                'era': char.era,
                'bio': char.bio,
                'background': char.background,
                'language_style': char.language_style,
                'temporal_constraints': char.temporal_constraints,
                'viewpoints': char.viewpoints,
            },
            topic=self._discussion.topic,
            conversation_history=history,
            character_limit=self._discussion.character_limit,
            model=char.llm_model or None,
        )

        # 累计 token 消耗到 Discussion
        if character_agent.last_token_usage:
            from django.db.models import F
            Discussion.objects.filter(id=self.discussion_id).update(
                total_tokens=F('total_tokens') + character_agent.last_token_usage.total_tokens
            )

        # 保存角色发言
        msg = Message.objects.create(
            discussion=self._discussion,
            character=char,
            content=speech,
            word_count=len(speech),
            is_moderator=False,
        )

        from django.db.models import F
        Character.objects.filter(id=char.id).update(
            message_count=F('message_count') + 1
        )

        # 广播角色发言
        self._broadcast({
            'type': 'message',
            'data': {
                'id': msg.id,
                'speaker': char.name,
                'content': speech,
                'is_moderator': False,
                'is_user': False,
            }
        })

        # 广播令牌状态
        self._broadcast_token_state()

        self._broadcast_debug(f"[发言] {char.name} 发言完成 ({len(speech)} 字)")
        logger.info(f"[AutoContinue:{self.discussion_id}] {char.name} 发言完成 ({len(speech)} 字)")

    def _broadcast(self, message: dict):
        """通过Django Channels广播消息到WebSocket"""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()
            room_group_name = f"discussion_{self.discussion_id}"

            # Extract the message type from the message dict (read-only, do not mutate caller's dict)
            message_type = message.get('type', 'message')
            message_data = message.get('data', {k: v for k, v in message.items() if k != 'type'})

            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'chat_message',
                    'message_type': message_type,
                    'data': message_data
                }
            )
        except Exception as e:
            logger.error(f"[AutoContinue:{self.discussion_id}] 广播失败: {e}")

    def _broadcast_debug(self, message: str):
        """广播调试信息到前端"""
        self._broadcast({
            'type': 'debug_info',
            'data': {'message': message}
        })

    def _broadcast_token_state(self):
        """广播令牌状态到前端"""
        try:
            self._broadcast({
                'type': 'token_update',
                'data': {
                    'host_token_holder': self._discussion.host_token_holder or '主持人',
                    'player_token_holder': self._discussion.player_token_holder or '玩家',
                    'current_round': self._discussion.current_round,
                    'current_speaker': self._discussion.current_speaker,
                }
            })
        except Exception as e:
            logger.error(f"[AutoContinue:{self.discussion_id}] 广播令牌状态失败: {e}")

    def _finish_discussion(self):
        """正常结束讨论：更新状态、生成结束语、广播到前端"""
        from django.utils import timezone
        from .host_agent import HostAgent

        try:
            close_old_connections()
            self._discussion = Discussion.objects.get(id=self.discussion_id)

            # 更新状态
            self._discussion.status = 'finished'
            self._discussion.ended_at = timezone.now()
            self._discussion.save()

            # 生成结束语
            host = HostAgent()
            closing = host.generate_closing(
                topic=self._discussion.topic,
                characters=[{'name': c.name} for c in self._characters],
                discussion_summary="讨论已达到最大轮次"
            )

            # 保存结束语消息
            Message.objects.create(
                discussion=self._discussion,
                content=closing,
                word_count=len(closing),
                is_moderator=True,
            )

            # 广播结束语
            self._broadcast({
                'type': 'message',
                'data': {
                    'speaker': '主持人',
                    'content': closing,
                    'is_moderator': True,
                    'is_user': False,
                }
            })

            # 广播讨论结束事件
            self._broadcast({
                'type': 'discussion_end',
                'data': {
                    'status': 'finished',
                    'closing': closing,
                    'reason': '达到最大轮次',
                }
            })

            # 广播最终状态
            self._broadcast({
                'type': 'state_update',
                'data': {
                    'status': 'finished',
                    'current_round': self._discussion.current_round,
                    'current_speaker': '',
                }
            })

            self._broadcast_debug(f"[结束] 讨论已达到最大轮次，正常结束")

            # 广播 Token 统计
            try:
                total = Discussion.objects.get(id=self.discussion_id).total_tokens
                self._broadcast_debug(f"[Token 统计] 本次会话共消耗 {total} tokens")
            except Exception:
                pass

            logger.info(f"[AutoContinue:{self.discussion_id}] 已广播讨论结束")

        except Exception as e:
            logger.exception(f"[AutoContinue:{self.discussion_id}] 结束讨论失败: {e}")


def start_auto_continue(discussion_id: int):
    """
    启动自动继续任务的入口函数

    Args:
        discussion_id: 讨论ID
    """
    service = AutoContinueService(discussion_id)
    service.run()
