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
        # Identity gate: authenticated user OR a session-bound guest_id (populated by
        # GuestSessionMiddleware on any prior HTTP request). Reject only truly cookie-less
        # connections — those are drive-bys that never loaded a page.
        user = self.scope.get('user')
        is_user = user is not None and getattr(user, 'is_authenticated', False)
        session = self.scope.get('session')
        guest_id = session.get('guest_id') if session else None
        if not is_user and not guest_id:
            await self.close(code=4401)
            return
        self.identity = user.username if is_user else f'guest:{guest_id}'

        self.discussion_id = self.scope['url_route']['kwargs']['discussion_id']
        self.room_group_name = f'discussion_{self.discussion_id}'

        # Token 统计（本次 WS 连接期间的 LLM 消耗）
        self.session_tokens = {'prompt': 0, 'completion': 0, 'total': 0}

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

        # participant 模式：若进程内还没有后台 AutoContinueService，启动一个。
        # 这让讨论在没有用户输入时也能自动推进，用户可以随时 @角色 插话。
        # ensure_auto_continue_running 会与 views.py 的启动共享同一个注册表，
        # 避免同一讨论被起两份线程导致主持人邀请语重复。
        if (initial_data.get('user_role') == 'participant'
                and initial_data.get('status') == 'active'):
            from .services.auto_continue import ensure_auto_continue_running
            ensure_auto_continue_running(int(self.discussion_id))

    async def disconnect(self, close_code):
        room = getattr(self, 'room_group_name', None)
        if room:
            await self.channel_layer.group_discard(room, self.channel_name)

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
                'message': '服务器内部错误'
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

        # participant 模式由后台 AutoContinueService 负责推进后续轮次，
        # 无需 consumer 在这里再额外驱动，避免与后台线程竞争 current_round。

    @database_sync_to_async
    def _save_and_broadcast_message(self, content: str, speaker: str,
                                     is_moderator: bool, is_user: bool,
                                     player_mentioned_character: str = None):
        """保存消息到数据库并广播"""
        from .models import Discussion, Message, Character
        from django.db.models import F

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
            Message.objects.create(
                discussion=discussion,
                character=character,
                content=content,
                word_count=len(content),
                is_moderator=is_moderator,
                is_user=is_user,
                player_mentioned_character=player_mentioned_character,
            )

            # 原子更新轮次状态（仅角色发言才增加轮次，避免覆盖并发的 token 等字段）
            if speaker != '主持人' and speaker != '你':
                Discussion.objects.filter(id=self.discussion_id).update(
                    current_round=F('current_round') + 1,
                    current_speaker=speaker,
                )

        except Exception as e:
            logger.error(f"Error saving message: {e}")

    @database_sync_to_async
    def _fetch_character_data(self, character_name: str) -> dict:
        """
        从数据库读取角色和讨论数据，返回纯 Python dict（不含 ORM 对象）。
        只做 DB 查询，不调用 LLM，可安全放入数据库线程池。
        """
        from .models import Discussion, Character

        discussion = Discussion.objects.get(id=self.discussion_id)
        char_obj = Character.objects.get(discussion=discussion, name=character_name)
        history = self._get_conversation_history(discussion)
        return {
            'char_id': char_obj.id,
            'char_name': char_obj.name,
            'llm_provider': char_obj.llm_provider,
            'llm_model': char_obj.llm_model,
            'config': {
                'name': char_obj.name,
                'era': char_obj.era,
                'bio': char_obj.bio,
                'background': char_obj.background,
                'language_style': char_obj.language_style,
                'temporal_constraints': char_obj.temporal_constraints,
                'viewpoints': char_obj.viewpoints,
            },
            'topic': discussion.topic,
            'character_limit': discussion.character_limit,
            'history': history,
        }

    @database_sync_to_async
    def _save_character_message(self, char_id: int, speech: str,
                                token_total: int, declined: bool = False):
        """
        保存角色消息并原子更新统计字段。
        只做 DB 写入，可安全放入数据库线程池。
        返回 (msg_id, char_name)。
        """
        from .models import Character, Message
        from django.db.models import F

        char_obj = Character.objects.get(id=char_id)
        msg = Message.objects.create(
            discussion_id=self.discussion_id,
            character=char_obj,
            content=speech,
            word_count=len(speech),
            is_moderator=False,
            is_user=False,
            read_but_no_reply=declined,
        )
        Character.objects.filter(id=char_id).update(
            message_count=F('message_count') + 1
        )
        if token_total:
            from .models import Discussion
            Discussion.objects.filter(id=self.discussion_id).update(
                total_tokens=F('total_tokens') + token_total
            )
        return msg.id, char_obj.name

    async def _get_character_response(self, character_name: str, context: str) -> dict:
        """
        获取角色回复。

        三段式结构，将 LLM 调用与 DB 操作完全分离：
          1. _fetch_character_data  → 数据库线程池（快，纯 DB 读）
          2. sync_to_async(llm_call) → 通用线程池（慢，网络 IO，不占 DB 槽）
          3. _save_character_message → 数据库线程池（快，纯 DB 写）
        """
        from .models import Character
        from .services.character import CharacterAgent

        try:
            data = await self._fetch_character_data(character_name)
        except Character.DoesNotExist:
            return {'error': f'未找到角色：{character_name}'}
        except Exception as e:
            logger.error(f"Error fetching character data for {character_name}: {e}")
            return None

        def _llm_call():
            agent = CharacterAgent(provider=data['llm_provider'] or None)
            speech = agent.generate_speech(
                character_config=data['config'],
                topic=data['topic'],
                conversation_history=data['history'],
                character_limit=data['character_limit'],
                model=data['llm_model'] or None,
            )
            token_total = (
                agent.last_token_usage.total_tokens
                if agent.last_token_usage else 0
            )
            return speech, token_total

        try:
            speech, token_total = await sync_to_async(_llm_call)()
        except Exception as e:
            logger.error(f"Error generating speech for {character_name}: {e}")
            return None

        msg_id, char_name = await self._save_character_message(
            data['char_id'], speech, token_total
        )
        return {
            'id': msg_id,
            'speaker': char_name,
            'content': speech,
            'is_moderator': False,
            'is_user': False,
        }

    async def _get_character_response_with_decline(self, character_name: str, player_message: str) -> tuple:
        """
        获取角色回复（支持婉拒机制）。

        三段式结构同 _get_character_response，LLM 在通用线程池中运行。

        Returns:
            tuple: (response_dict, declined_bool)
        """
        from .models import Character
        from .services.character import CharacterAgent

        try:
            data = await self._fetch_character_data(character_name)
        except Character.DoesNotExist:
            return {'error': f'未找到角色：{character_name}'}, False
        except Exception as e:
            logger.error(f"Error fetching character data for {character_name}: {e}")
            return None, False

        def _llm_call():
            agent = CharacterAgent(provider=data['llm_provider'] or None)
            should_respond = agent.should_respond_to_player(
                character_config=data['config'],
                player_message=player_message,
                conversation_history=data['history'],
            )
            if should_respond:
                speech = agent.generate_speech(
                    character_config=data['config'],
                    topic=data['topic'],
                    conversation_history=data['history'],
                    character_limit=data['character_limit'],
                    model=data['llm_model'] or None,
                )
                token_total = (
                    agent.last_token_usage.total_tokens
                    if agent.last_token_usage else 0
                )
                return speech, token_total, False
            else:
                speech = agent.generate_decline_response(
                    character_config=data['config'],
                    player_message=player_message,
                )
                return speech, 0, True

        try:
            speech, token_total, declined = await sync_to_async(_llm_call)()
        except Exception as e:
            logger.error(f"Error generating character response with decline for {character_name}: {e}")
            return None, False

        msg_id, char_name = await self._save_character_message(
            data['char_id'], speech, token_total, declined=declined
        )
        return {
            'id': msg_id,
            'speaker': char_name,
            'content': speech,
            'is_moderator': False,
            'is_user': False,
        }, declined

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

            # 播报 Token 统计汇总
            try:
                total = await sync_to_async(
                    lambda: Discussion.objects.get(id=self.discussion_id).total_tokens
                )()
                await self._send_debug_info(
                    f"[Token 统计] 本次会话共消耗 {total} tokens"
                )
            except Exception:
                pass

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
    def _release_expired_tokens(self) -> list[str]:
        """检查并自动释放已超时的令牌，返回被释放的令牌名称列表"""
        from .models import Discussion
        from django.utils import timezone
        import datetime

        released = []
        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            now = timezone.now()
            timeout = datetime.timedelta(seconds=discussion.token_timeout_seconds)

            # 检查主持人令牌：非'主持人'持有 + 超时
            if (
                discussion.host_token_holder
                and discussion.host_token_holder != '主持人'
                and discussion.host_token_at
                and now - discussion.host_token_at > timeout
            ):
                holder = discussion.host_token_holder
                discussion.host_token_holder = '主持人'
                discussion.host_token_at = now
                released.append(f"主持人令牌（{holder} → 主持人，已持有 {timeout}）")

            # 检查玩家令牌：非'玩家'持有 + 超时（participant 模式）
            if (
                discussion.user_role == 'participant'
                and discussion.player_token_holder
                and discussion.player_token_holder != '玩家'
                and discussion.player_token_at
                and now - discussion.player_token_at > timeout
            ):
                holder = discussion.player_token_holder
                discussion.player_token_holder = '玩家'
                discussion.player_waiting_for = None
                discussion.player_token_at = now
                released.append(f"玩家令牌（{holder} → 玩家，已持有 {timeout}）")

            if released:
                discussion.save()
                logger.warning(f"[Token] Auto-released expired tokens: {released}")
        except Exception as e:
            logger.error(f"Error releasing expired tokens: {e}")

        return released

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
        """原子更新讨论轮次和当前发言者，避免与 AutoContinueService 的竞态覆盖"""
        from .models import Discussion
        from django.db.models import F

        try:
            Discussion.objects.filter(id=self.discussion_id).update(
                current_round=F('current_round') + 1,
                current_speaker=speaker,
            )
            logger.info(f"Updated discussion state atomically: speaker={speaker}")
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

            max_rounds = state.get('max_rounds', 30)
            if current_round >= max_rounds:
                await self._send_debug_info(f"[自动继续] 已达到最大轮次限制 {max_rounds}，停止")
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

                # 递归检查是否继续。背景 AutoContinueService 才是 observer 模式的主驱动；
                # 在 host/participant 模式下，consumer 在本次用户输入触发的回合结束后停止递归，
                # 等待下一次用户输入，避免与后台线程（若存在）争抢 current_round。
                current_round = state.get('current_round', 0)
                await self._send_debug_info(f"[状态] 当前轮次: {current_round}")
                await self._send_debug_info(f"[自动继续] 本轮结束，等待用户输入或后台推进")
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
        """生成邀请语（只返回文本，不保存消息——由调用方统一保存）"""
        from .models import Discussion
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

            return invitation
        except Exception as e:
            logger.error(f"Error generating invitation: {e}")
            return None

    def _get_conversation_history_sync(self):
        """获取对话历史（同步版本）"""
        from .models import Discussion
        discussion = Discussion.objects.get(id=self.discussion_id)
        messages = list(discussion.messages.select_related('character').all())[-20:]
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
        released = await self._release_expired_tokens()
        state = await self.get_state()
        await self.send(text_data=json.dumps({
            'type': 'poll_response',
            'data': state
        }))
        if released:
            await self.send(text_data=json.dumps({
                'type': 'system_message',
                'message': f'令牌超时已自动归还：{"; ".join(released)}'
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
            user = self.scope.get('user')
            user_id = user.id if user is not None and getattr(user, 'is_authenticated', False) else None
            effective_role = discussion.user_role or 'participant'
            if discussion.owner_id and discussion.owner_id != user_id:
                effective_role = 'observer'
            return effective_role
        except Discussion.DoesNotExist:
            return 'participant'

    @database_sync_to_async
    def get_initial_state(self):
        """获取初始状态"""
        from .models import Discussion, Character, Message

        try:
            discussion = Discussion.objects.get(id=self.discussion_id)
            characters = list(discussion.characters.all())
            messages = list(discussion.messages.select_related('character').all())

            user = self.scope.get('user')
            user_id = user.id if user is not None and getattr(user, 'is_authenticated', False) else None
            effective_role = discussion.user_role
            if discussion.owner_id and discussion.owner_id != user_id:
                effective_role = 'observer'

            return {
                'discussion_id': discussion.id,
                'topic': discussion.topic,
                'status': discussion.status,
                'user_role': effective_role,
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
                'max_rounds': discussion.max_rounds,
                'current_speaker': discussion.current_speaker,
                'host_token_holder': discussion.host_token_holder,
                'player_token_holder': discussion.player_token_holder,
            }
        except Discussion.DoesNotExist:
            return {'error': 'Discussion not found'}

    def _get_conversation_history(self, discussion, limit=10):
        """获取对话历史"""
        messages = list(discussion.messages.select_related('character').all())[-(limit * 2):]
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