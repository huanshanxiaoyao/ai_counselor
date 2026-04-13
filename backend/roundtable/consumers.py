"""
WebSocket consumer for real-time roundtable discussion.
Supports three user roles: host, participant, observer
"""
import json
import logging
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


def parse_mention(message: str) -> dict:
    """
    解析@指令

    Args:
        message: 用户输入的消息

    Returns:
        dict: {
            'has_mention': bool,
            'target': str or None,  # 被@的角色名
            'content': str  # 去除@指令后的内容
        }
    """
    if not message:
        return {'has_mention': False, 'target': None, 'content': ''}

    # 匹配以@开头的指令
    # 格式: @角色名 内容
    # 只匹配中文名字，防止用户输入奇怪的格式
    pattern = r'^@([\u4e00-\u9fa5·]+)(?:[（\-—""''\s]|$)(.*)$'
    match = re.match(pattern, message.strip())

    if match:
        target = match.group(1)
        content = match.group(2).strip() if match.group(2) else ''
        return {
            'has_mention': True,
            'target': target,
            'content': content
        }

    # 回退：尝试简单的模式（以@开头后跟非空白字符）
    pattern_fallback = r'^@(\S+)\s*(.*)$'
    match_fallback = re.match(pattern_fallback, message.strip())
    if match_fallback:
        target = match_fallback.group(1)
        content = match_fallback.group(2) if match_fallback.group(2) else ''
        return {
            'has_mention': True,
            'target': target,
            'content': content
        }

    return {
        'has_mention': False,
        'target': None,
        'content': message
    }


class DiscussionConsumer(AsyncWebsocketConsumer):
    """讨论 WebSocket Consumer - 处理实时讨论消息"""

    async def connect(self):
        self.discussion_id = self.scope['url_route']['kwargs']['discussion_id']
        self.room_group_name = f'discussion_{self.discussion_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial state
        initial_data = await self.get_initial_state()
        await self.send(text_data=json.dumps({
            'type': 'initial_state',
            'data': initial_data
        }))

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """接收客户端消息"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'user_message':
                await self.handle_user_message(data)
            elif message_type == 'poll':
                await self.handle_poll()
            elif message_type == 'typing_start':
                await self.broadcast_typing(data)
            elif message_type == 'typing_end':
                await self.broadcast_typing_end()
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))
        except Exception as e:
            logger.exception("Error receiving WebSocket message")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def handle_user_message(self, data):
        """处理用户消息 - 根据用户角色分发到不同处理逻辑"""
        content = data.get('content', '').strip()

        if not content:
            return

        # 获取用户角色
        user_role = await self.get_user_role()

        if user_role == 'observer':
            # 旁观者模式：不响应用户输入
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': '旁观者模式无法发言'
            }))
            return

        # 解析@指令（提前解析，所有角色共用）
        parsed = parse_mention(content)
        mentioned = parsed['target']

        # 检查是否 @主持人 + /quit 结束对话
        if mentioned == '主持人' and '/quit' in parsed['content']:
            await self._end_discussion()
            return

        # 根据用户角色分发处理
        if user_role == 'host':
            await self._handle_host_message(content)
        else:  # participant
            await self._handle_participant_message(content)

    async def _handle_host_message(self, content: str):
        """
        处理主持人模式的用户消息

        主持人模式规则：
        - 用户输入直接显示为"主持人"
        - 如果@了角色，该角色直接回复
        - AI主持人不自动干预用户输入
        """
        # 解析@指令
        parsed = parse_mention(content)
        mentioned = parsed['target']

        responses = []

        # 1. 直接显示用户发言为"主持人"
        await self._save_and_broadcast_message(
            content=content,
            speaker='主持人',
            is_moderator=True,
            is_user=False
        )

        # 发送用户消息到前端
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': {
                'speaker': '主持人',
                'content': content,
                'is_moderator': True,
                'is_user': False,
            }
        }))

        # 2. 如果@了角色，让该角色回复
        if mentioned:
            char_response = await self._get_character_response(mentioned, content)
            if char_response:
                responses.append(char_response)

        # 广播状态更新
        state = await self.get_state()
        await self.send(text_data=json.dumps({
            'type': 'state_update',
            'data': state
        }))

        # 广播角色回复
        for response in responses:
            await self.send(text_data=json.dumps({
                'type': 'message',
                'data': response
            }))

        # 3. 自动继续讨论流程（角色发言结束后自动邀请下一位）
        if mentioned and responses:
            await self._auto_continue_discussion()

    async def _handle_participant_message(self, content: str):
        """
        处理参与者模式的用户消息

        参与者模式规则（双令牌机制）：
        - 用户持有玩家令牌，可以发言
        - 如果@了角色，转移玩家令牌给该角色，该角色决定是否回复
        - 如果@了主持人，主持人回应玩家
        - 如果没有@，玩家令牌保留，但仅在初始化阶段忽略
        - AI主持人令牌和玩家令牌独立运行，可并行
        """
        # 解析@指令
        parsed = parse_mention(content)
        mentioned = parsed['target']

        responses = []

        # 检查玩家令牌状态
        player_waiting = await self._check_player_waiting()

        if player_waiting and mentioned and mentioned != '主持人':
            # 情况：玩家正在等待回复，但仍尝试@角色
            # 拒绝发言，提示等待
            waiting_for = await self._get_player_waiting_for()
            await self.send(text_data=json.dumps({
                'type': 'player_waiting',
                'data': {
                    'message': f'你的问题正在被 {waiting_for} 回复中，请稍等...',
                    'waiting_for': waiting_for,
                }
            }))
            return

        # 1. 直接显示用户发言为"你"
        await self._save_and_broadcast_message(
            content=content,
            speaker='你',
            is_moderator=False,
            is_user=True,
            player_mentioned_character=mentioned if mentioned != '主持人' else None,
        )

        # 2. 发送用户消息到前端
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': {
                'speaker': '你',
                'content': content,
                'is_moderator': False,
                'is_user': True,
            }
        }))

        if mentioned:
            if mentioned == '主持人':
                # @主持人：让主持人回应玩家
                host_response = await self._get_host_response_to_player(content)
                if host_response:
                    responses.append(host_response)
            else:
                # @角色：转移玩家令牌给被@角色
                await self._transfer_player_token(mentioned)

                # 获取角色回复（角色AI决定是否回复）
                char_response, declined = await self._get_character_response_with_decline(mentioned, content)

                if declined:
                    # 角色婉拒，发送"已读未回"通知
                    await self.send(text_data=json.dumps({
                        'type': 'read_but_no_reply',
                        'data': {
                            'character_name': mentioned,
                            'decline_message': char_response.get('content', ''),
                        }
                    }))
                    # 归还玩家令牌
                    await self._return_player_token()
                elif char_response:
                    responses.append(char_response)
                    # 角色回复后，归还玩家令牌
                    await self._return_player_token()

        else:
            # 情况A：没有@，直接发言（玩家令牌保留）
            # 检查是否在初始化阶段
            in_init_phase = await self._is_in_init_phase()

            # 初始化阶段不处理无@的玩家发言
            if not in_init_phase:
                # AI主持人决定是否回应
                should_respond = await self._should_host_respond(content)
                if should_respond:
                    host_response = await self._get_host_response_to_player(content)
                    if host_response:
                        responses.append(host_response)

                        # 主持人决定是否@角色
                        next_speaker = await self._decide_next_speaker(content)
                        if next_speaker:
                            char_response = await self._get_character_response(next_speaker, '')
                            if char_response:
                                responses.append(char_response)

        # 广播状态更新
        state = await self.get_state()
        await self.send(text_data=json.dumps({
            'type': 'state_update',
            'data': state
        }))

        # 广播回复
        for response in responses:
            await self.send(text_data=json.dumps({
                'type': 'message',
                'data': response
            }))

        # 3. 自动继续讨论流程（角色发言结束后自动邀请下一位）
        if responses and any(r.get('speaker') not in ['主持人', '你'] for r in responses):
            await self._auto_continue_discussion()

    @database_sync_to_async
    def _save_and_broadcast_message(self, content: str, speaker: str,
                                     is_moderator: bool, is_user: bool,
                                     player_mentioned_character: str = None):
        """保存消息到数据库并广播"""
        from .models import Discussion, Message, Character

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)

            # 确定角色
            character = None
            if speaker != '主持人' and speaker != '你':
                try:
                    character = Character.objects.get(discussion=discussion, name=speaker)
                except Character.DoesNotExist:
                    pass

            # 保存消息
            msg = Message.objects.create(
                discussion=discussion,
                character=character,
                content=content,
                word_count=len(content),
                is_moderator=is_moderator,
                is_user=is_user,
                player_mentioned_character=player_mentioned_character,
            )

            # 更新讨论状态
            if speaker != '主持人' and speaker != '你':
                discussion.current_round += 1
                discussion.current_speaker = speaker
            discussion.save()

        except Exception as e:
            logger.error(f"Error saving message: {e}")

    @database_sync_to_async
    def _get_character_response(self, character_name: str, context: str) -> dict:
        """获取角色的回复"""
        from .models import Discussion, Character
        from .services.character import CharacterAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            char_obj = Character.objects.get(discussion=discussion, name=character_name)

            # 获取对话历史
            history = self._get_conversation_history(discussion)

            # 生成角色发言
            character_agent = CharacterAgent()
            speech = character_agent.generate_speech(
                character_config={
                    'name': char_obj.name,
                    'era': char_obj.era,
                    'bio': char_obj.bio,
                    'background': char_obj.background,
                    'language_style': char_obj.language_style,
                    'temporal_constraints': char_obj.temporal_constraints,
                    'viewpoints': char_obj.viewpoints,
                },
                topic=discussion.topic,
                conversation_history=history,
                character_limit=discussion.character_limit,
            )

            # 保存角色消息
            msg = Message.objects.create(
                discussion=discussion,
                character=char_obj,
                content=speech,
                word_count=len(speech),
                is_moderator=False,
                is_user=False,
            )

            char_obj.message_count += 1
            char_obj.save()

            return {
                'id': msg.id,
                'speaker': char_obj.name,
                'content': speech,
                'is_moderator': False,
                'is_user': False,
            }

        except Character.DoesNotExist:
            return {
                'error': f'未找到角色：{character_name}'
            }
        except Exception as e:
            logger.error(f"Error getting character response: {e}")
            return None

    @database_sync_to_async
    def _get_character_response_with_decline(self, character_name: str, player_message: str) -> tuple:
        """
        获取角色回复（支持婉拒机制）

        Returns:
            tuple: (response_dict, declined_bool)
                   - response_dict: 回复内容（如果是婉拒，则是婉拒语）
                   - declined_bool: 是否婉拒
        """
        from .models import Discussion, Character, Message
        from .services.character import CharacterAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            char_obj = Character.objects.get(discussion=discussion, name=character_name)

            # 获取对话历史
            history = self._get_conversation_history(discussion)

            character_agent = CharacterAgent()

            # 首先让AI决定是否应该回复
            should_respond = character_agent.should_respond_to_player(
                character_config={
                    'name': char_obj.name,
                    'bio': char_obj.bio,
                    'era': char_obj.era,
                    'background': char_obj.background,
                    'language_style': char_obj.language_style,
                    'temporal_constraints': char_obj.temporal_constraints,
                    'viewpoints': char_obj.viewpoints,
                },
                player_message=player_message,
                conversation_history=history,
            )

            speech = ""
            declined = False

            if should_respond:
                # 生成正常回复
                speech = character_agent.generate_speech(
                    character_config={
                        'name': char_obj.name,
                        'era': char_obj.era,
                        'bio': char_obj.bio,
                        'background': char_obj.background,
                        'language_style': char_obj.language_style,
                        'temporal_constraints': char_obj.temporal_constraints,
                        'viewpoints': char_obj.viewpoints,
                    },
                    topic=discussion.topic,
                    conversation_history=history,
                    character_limit=discussion.character_limit,
                )
            else:
                # 生成婉拒回复
                declined = True
                speech = character_agent.generate_decline_response(
                    character_config={
                        'name': char_obj.name,
                        'bio': char_obj.bio,
                        'era': char_obj.era,
                        'background': char_obj.background,
                        'language_style': char_obj.language_style,
                        'temporal_constraints': char_obj.temporal_constraints,
                        'viewpoints': char_obj.viewpoints,
                    },
                    player_message=player_message,
                )

            # 保存消息
            msg = Message.objects.create(
                discussion=discussion,
                character=char_obj,
                content=speech,
                word_count=len(speech),
                is_moderator=False,
                is_user=False,
                read_but_no_reply=declined,
            )

            char_obj.message_count += 1
            char_obj.save()

            return {
                'id': msg.id,
                'speaker': char_obj.name,
                'content': speech,
                'is_moderator': False,
                'is_user': False,
            }, declined

        except Character.DoesNotExist:
            return {
                'error': f'未找到角色：{character_name}'
            }, False
        except Exception as e:
            logger.error(f"Error getting character response with decline: {e}")
            return None, False

    async def _end_discussion(self):
        """结束讨论"""
        # 立即发送调试反馈，让用户知道指令已收到
        await self._send_debug_info("[指令] 收到结束指令，正在终止讨论...")

        try:
            from .models import Discussion
            from django.utils import timezone
            from .services.host_agent import HostAgent

            # 异步安全地更新讨论状态
            await sync_to_async(self._finish_discussion_sync)()

            # 生成结束语
            discussion = await self._get_discussion()
            characters = await sync_to_async(lambda: list(discussion.characters.all()))()
            host = HostAgent()
            closing = await sync_to_async(lambda: host.generate_closing(
                topic=discussion.topic,
                characters=[{'name': c.name} for c in characters],
                discussion_summary="讨论已结束"
            ))()

            # 发送结束语消息
            await self.send(text_data=json.dumps({
                'type': 'message',
                'data': {
                    'speaker': '主持人',
                    'content': closing,
                    'is_moderator': True,
                    'is_user': False,
                }
            }))

            # 广播结束事件
            await self.send(text_data=json.dumps({
                'type': 'discussion_end',
                'data': {
                    'status': 'finished',
                    'closing': closing,
                }
            }))

            await self._send_debug_info("[结束] 讨论已成功终止")

        except Exception as e:
            logger.exception(f"Error ending discussion: {e}")
            await self._send_debug_info(f"[错误] 结束讨论失败: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'结束讨论失败: {e}'
            }))

    def _finish_discussion_sync(self):
        """同步方法：更新讨论状态为已结束"""
        from .models import Discussion
        from django.utils import timezone
        discussion = Discussion.objects.get(id=self.discussion_id)
        discussion.status = 'finished'
        discussion.ended_at = timezone.now()
        discussion.save()

    @database_sync_to_async
    def _get_discussion(self):
        """获取讨论对象"""
        from .models import Discussion
        return Discussion.objects.get(id=self.discussion_id)

    # 玩家令牌管理方法
    @database_sync_to_async
    def _check_player_waiting(self) -> bool:
        """检查玩家是否正在等待回复"""
        from .models import Discussion
        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            return bool(discussion.player_waiting_for)
        except Exception as e:
            logger.error(f"Error checking player waiting: {e}")
            return False

    @database_sync_to_async
    def _get_player_waiting_for(self) -> str:
        """获取玩家正在等待的角色"""
        from .models import Discussion
        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            return discussion.player_waiting_for or ""
        except Exception as e:
            logger.error(f"Error getting player waiting: {e}")
            return ""

    @database_sync_to_async
    def _transfer_player_token(self, character_name: str):
        """转移玩家令牌给角色"""
        from .models import Discussion
        from django.utils import timezone

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            discussion.player_token_holder = character_name
            discussion.player_waiting_for = character_name
            discussion.player_token_at = timezone.now()
            discussion.save()
            logger.info(f"Player token transferred to {character_name}")
        except Exception as e:
            logger.error(f"Error transferring player token: {e}")

    @database_sync_to_async
    def _return_player_token(self):
        """归还玩家令牌给玩家"""
        from .models import Discussion
        from django.utils import timezone

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            discussion.player_token_holder = '玩家'
            discussion.player_waiting_for = None
            discussion.player_token_at = timezone.now()
            discussion.save()
            logger.info("Player token returned to player")
        except Exception as e:
            logger.error(f"Error returning player token: {e}")

    @database_sync_to_async
    def _is_in_init_phase(self) -> bool:
        """检查是否在初始化阶段"""
        from .models import Discussion
        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            char_count = discussion.characters.count()
            # 初始化阶段：current_round <= 角色数量
            return discussion.current_round <= char_count
        except Exception as e:
            logger.error(f"Error checking init phase: {e}")
            return False

    async def _should_host_respond(self, player_message: str) -> bool:
        """判断主持人是否应该回应参与者的发言"""
        # Use sync_to_async to wrap the sync function call
        return await sync_to_async(self._should_host_respond_sync)(player_message)

    def _should_host_respond_sync(self, player_message: str) -> bool:
        """判断主持人是否应该回应参与者的发言（同步版本）"""
        from .models import Discussion
        from .services.host_agent import HostAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            history = self._get_conversation_history(discussion)

            host = HostAgent()
            return host.should_respond_to_player(player_message, history)
        except Exception as e:
            logger.error(f"Error checking host respond: {e}")
            return False

    async def _get_host_response_to_player(self, player_message: str) -> dict:
        """获取主持人对参与者的回应"""
        return await sync_to_async(self._get_host_response_to_player_sync)(player_message)

    def _get_host_response_to_player_sync(self, player_message: str) -> dict:
        """获取主持人对参与者的回应（同步版本）"""
        from .models import Discussion, Message
        from .services.host_agent import HostAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            history = self._get_conversation_history(discussion)

            host = HostAgent()
            response_text = host.generate_response_to_player(
                player_message=player_message,
                conversation_history=history,
                topic=discussion.topic
            )

            # 保存主持人消息
            msg = Message.objects.create(
                discussion=discussion,
                content=response_text,
                word_count=len(response_text),
                is_moderator=True,
                is_user=False,
            )

            return {
                'id': msg.id,
                'speaker': '主持人',
                'content': response_text,
                'is_moderator': True,
                'is_user': False,
            }

        except Exception as e:
            logger.error(f"Error getting host response: {e}")
            return None

    async def _decide_next_speaker(self, context: str) -> str:
        """决定下一个发言的角色"""
        return await sync_to_async(self._decide_next_speaker_sync)(context)

    def _decide_next_speaker_sync(self, context: str) -> str:
        """决定下一个发言的角色（同步版本）"""
        from .models import Discussion
        from .services.host_agent import HostAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            characters = list(discussion.characters.all())
            last_speaker = discussion.current_speaker or ''
            history = self._get_conversation_history(discussion)

            host = HostAgent()
            next_name, transition = host.decide_next_speaker(
                characters=[{'name': c.name} for c in characters],
                last_speaker=last_speaker,
                conversation_history=history,
                topic=discussion.topic,
                use_llm=True,
                round_count=discussion.current_round
            )
            return next_name

        except Exception as e:
            logger.error(f"Error deciding next speaker: {e}")
            return None

    @database_sync_to_async
    def _grant_host_token(self, character_name: str):
        """授予主持人令牌给角色"""
        from .models import Discussion
        from django.utils import timezone

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            discussion.host_token_holder = character_name
            discussion.host_token_at = timezone.now()
            discussion.save()
            logger.info(f"Token granted to {character_name}")
        except Exception as e:
            logger.error(f"Error granting token: {e}")

    @database_sync_to_async
    def _return_host_token(self):
        """归还主持人令牌给主持人"""
        from .models import Discussion
        from django.utils import timezone

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            discussion.host_token_holder = '主持人'
            discussion.host_token_at = timezone.now()
            discussion.save()
            logger.info("Host token returned to moderator")
        except Exception as e:
            logger.error(f"Error returning token: {e}")

    @database_sync_to_async
    def _update_discussion_state(self, speaker: str):
        """更新讨论状态（当前发言者和轮次）"""
        from .models import Discussion

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            discussion.current_round += 1
            discussion.current_speaker = speaker
            discussion.save()
            logger.info(f"Updated discussion state: round={discussion.current_round}, speaker={speaker}")
        except Exception as e:
            logger.error(f"Error updating discussion state: {e}")

    async def _send_debug_info(self, message: str):
        """发送调试信息到前端"""
        await self.send(text_data=json.dumps({
            'type': 'debug_info',
            'data': {
                'message': message,
            }
        }))

    async def _auto_continue_discussion(self):
        """
        自动继续讨论流程

        当角色发言结束后（令牌归还给主持人），自动：
        1. 主持人决定下一位发言者
        2. 生成邀请语
        3. 邀请下一位角色发言
        """
        try:
            # 获取当前状态
            user_role = await self.get_user_role()
            if user_role == 'observer':
                # 旁观者模式不自动继续
                return

            # 检查是否达到最大轮次
            state = await self.get_state()
            current_round = state.get('current_round', 0)

            # 发送调试信息：开始自动继续
            await self._send_debug_info(f"[自动继续] 第 {current_round + 1} 轮开始")

            if current_round >= 20:  # max_rounds 默认是20
                await self._send_debug_info("[自动继续] 已达到最大轮次限制，停止")
                return

            # 获取所有角色
            characters = await sync_to_async(lambda: list(self._get_characters()))()
            if not characters:
                await self._send_debug_info("[自动继续] 错误：没有角色")
                return

            # 获取最后发言者和历史
            last_speaker = state.get('current_speaker', '')
            host_token_holder = state.get('host_token_holder', '未知')
            await self._send_debug_info(f"[状态] 当前轮次={current_round}, 最后发言者={last_speaker}, 主持人令牌持有者={host_token_holder}")

            history = await sync_to_async(self._get_conversation_history_sync)()

            # 决定下一位发言者
            await self._send_debug_info(f"[决策] 正在决定下一位发言者，上一位是: {last_speaker}")
            next_char_name, transition = await sync_to_async(
                self._decide_next_speaker_with_transition_sync
            )(last_speaker, history)

            if not next_char_name:
                await self._send_debug_info("[决策] 无法决定下一位发言者，停止自动继续")
                logger.info("No next speaker decided, skipping auto-continue")
                return

            await self._send_debug_info(f"[决策] 决定邀请: {next_char_name}")
            if transition:
                await self._send_debug_info(f"[过渡] {transition}")

            # 归还令牌给主持人
            await self._return_host_token()
            await self._send_debug_info(f"[令牌] {next_char_name} 归还令牌给主持人")

            # 生成主持人邀请
            await self._send_debug_info(f"[邀请] 正在生成对 {next_char_name} 的邀请语...")
            invitation = await sync_to_async(
                self._generate_invitation_sync
            )(next_char_name, history, transition)

            if not invitation:
                await self._send_debug_info(f"[邀请] 生成邀请失败")
                return

            # 保存主持人邀请消息
            await self._save_and_broadcast_message(
                content=invitation,
                speaker='主持人',
                is_moderator=True,
                is_user=False
            )

            # 发送邀请消息
            await self.send(text_data=json.dumps({
                'type': 'message',
                'data': {
                    'speaker': '主持人',
                    'content': invitation,
                    'is_moderator': True,
                    'is_user': False,
                }
            }))

            # 授予令牌给下一位角色
            await self._grant_host_token(next_char_name)
            await self._send_debug_info(f"[令牌] 授予令牌给 {next_char_name}")

            # 角色发言
            await self._send_debug_info(f"[发言] 正在生成 {next_char_name} 的发言...")
            char_response = await self._get_character_response(next_char_name, invitation)
            if char_response:
                # 更新讨论状态（角色发言后）
                await self._update_discussion_state(next_char_name)

                # 发送角色消息
                await self.send(text_data=json.dumps({
                    'type': 'message',
                    'data': char_response
                }))

                await self._send_debug_info(f"[发言] {next_char_name} 发言完成，字数: {char_response.get('content', '') and len(char_response.get('content', ''))}")

                # 归还令牌给主持人
                await self._return_host_token()
                await self._send_debug_info(f"[令牌] {next_char_name} 归还令牌给主持人")

                # 更新状态
                state = await self.get_state()
                await self.send(text_data=json.dumps({
                    'type': 'state_update',
                    'data': state
                }))

                # 递归检查是否继续（防止无限循环，这里限制最多3轮自动）
                current_round = state.get('current_round', 0)
                await self._send_debug_info(f"[状态] 当前轮次: {current_round}")

                if current_round < 3:
                    await self._auto_continue_discussion()
                else:
                    await self._send_debug_info(f"[自动继续] 已达自动继续上限({current_round}/3)，等待用户输入")
            else:
                await self._send_debug_info(f"[错误] 获取 {next_char_name} 的发言失败")

        except Exception as e:
            logger.exception(f"Error in auto-continue discussion: {e}")
            await self._send_debug_info(f"[错误] 自动继续异常: {e}")

    def _get_characters(self):
        """获取讨论的所有角色"""
        from .models import Discussion, Character
        discussion = Discussion.objects.get(id=self.discussion_id)
        return discussion.characters.all()

    def _decide_next_speaker_with_transition_sync(self, last_speaker: str, history: str):
        """决定下一位发言者（带过渡语）"""
        from .models import Discussion
        from .services.host_agent import HostAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            characters = list(discussion.characters.all())

            host = HostAgent()
            # 初始化阶段使用轮询，LLM阶段每轮都用LLM
            use_llm = discussion.current_round > len(characters)

            logger.info(f"[决策] 决定下一位发言者: last_speaker={last_speaker}, round={discussion.current_round}, use_llm={use_llm}")
            logger.info(f"[决策] 可选角色: {[c.name for c in characters]}")

            next_name, transition = host.decide_next_speaker(
                characters=[{'name': c.name} for c in characters],
                last_speaker=last_speaker,
                conversation_history=history,
                topic=discussion.topic,
                use_llm=use_llm,
                round_count=discussion.current_round
            )

            logger.info(f"[决策] 决策结果: next_name={next_name}, transition={transition}")
            return next_name, transition
        except Exception as e:
            logger.error(f"Error deciding next speaker: {e}")
            return None, None

    def _generate_invitation_sync(self, character_name: str, history: str, transition: str = None):
        """生成邀请语"""
        from .models import Discussion, Message
        from .services.host_agent import HostAgent

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)

            host = HostAgent()
            invitation = host.generate_invitation(
                character_name=character_name,
                topic=discussion.topic,
                conversation_history=history,
                transition=transition
            )

            # 保存邀请消息
            Message.objects.create(
                discussion=discussion,
                content=invitation,
                word_count=len(invitation),
                is_moderator=True,
            )

            return invitation
        except Exception as e:
            logger.error(f"Error generating invitation: {e}")
            return None

    def _get_conversation_history_sync(self):
        """获取对话历史（同步版本）"""
        from .models import Discussion
        discussion = Discussion.objects.get(id=self.discussion_id)
        messages = list(discussion.messages.all())[-20:]
        history = []
        for msg in messages:
            speaker = msg.character.name if msg.character else '系统'
            history.append(f"{speaker}：{msg.content}")
        return "\n".join(history)

    @database_sync_to_async
    def _get_token_state(self) -> dict:
        """获取令牌状态"""
        from .models import Discussion

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            return {
                'host_token_holder': discussion.host_token_holder,
                'player_token_holder': discussion.player_token_holder,
            }
        except Exception as e:
            logger.error(f"Error getting token state: {e}")
            return {}

    async def handle_poll(self):
        """处理轮询请求"""
        state = await self.get_state()
        await self.send(text_data=json.dumps({
            'type': 'poll_response',
            'data': state
        }))

    async def broadcast_typing(self, data):
        """广播用户正在输入"""
        character_name = data.get('character_name', '有人')
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_typing',
                'character_name': character_name
            }
        )

    async def broadcast_typing_end(self):
        """广播用户结束输入"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_typing_end'
            }
        )

    async def user_typing(self, event):
        """发送用户正在输入的消息"""
        await self.send(text_data=json.dumps({
            'type': 'user_typing',
            'character_name': event['character_name']
        }))

    async def user_typing_end(self, event):
        """发送用户结束输入的消息"""
        await self.send(text_data=json.dumps({
            'type': 'user_typing_end'
        }))

    @database_sync_to_async
    def get_user_role(self) -> str:
        """获取当前用户的角色"""
        from .models import Discussion

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            return discussion.user_role or 'participant'  # 默认是参与者
        except Discussion.DoesNotExist:
            return 'participant'

    @database_sync_to_async
    def get_initial_state(self):
        """获取初始状态"""
        from .models import Discussion, Character, Message

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            characters = list(discussion.characters.all())
            messages = list(discussion.messages.all())

            return {
                'discussion_id': discussion.id,
                'topic': discussion.topic,
                'status': discussion.status,
                'user_role': discussion.user_role,
                'current_round': discussion.current_round,
                'max_rounds': discussion.max_rounds,
                'characters': [
                    {
                        'id': c.id,
                        'name': c.name,
                        'era': c.era,
                        'bio': c.bio,
                        'message_count': c.message_count,
                    }
                    for c in characters
                ],
                'messages': [
                    {
                        'id': m.id,
                        'content': m.content,
                        'speaker': m.character.name if m.character else ('主持人' if m.is_moderator else '系统'),
                        'is_moderator': m.is_moderator,
                        'is_system': m.is_system,
                        'is_user': m.is_user,
                        'created_at': m.created_at.isoformat(),
                    }
                    for m in messages
                ],
            }
        except Discussion.DoesNotExist:
            return {'error': 'Discussion not found'}

    @database_sync_to_async
    def get_state(self):
        """获取当前状态"""
        from .models import Discussion

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            return {
                'status': discussion.status,
                'current_round': discussion.current_round,
                'current_speaker': discussion.current_speaker,
                'host_token_holder': discussion.host_token_holder,
                'player_token_holder': discussion.player_token_holder,
            }
        except Discussion.DoesNotExist:
            return {'error': 'Discussion not found'}

    def _get_conversation_history(self, discussion, limit=10):
        """获取对话历史"""
        messages = list(discussion.messages.all())[-(limit * 2):]
        history = []
        for msg in messages:
            speaker = msg.character.name if msg.character else '系统'
            history.append(f"{speaker}：{msg.content}")
        return "\n".join(history)

    # Handler for broadcasting messages to the group
    async def chat_message(self, event):
        """Send chat message to WebSocket"""
        # Extract message_type and data from event
        message_type = event.get('message_type', 'message')
        data = event.get('data', {})

        await self.send(text_data=json.dumps({
            'type': message_type,
            'data': data
        }))