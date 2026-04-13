"""
Roundtable views - handles topic input, character suggestions, and setup.
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.http import JsonResponse
from django.views import View
from django.shortcuts import render

from .services.director import DirectorAgent
from .services.character import CharacterAgent
from .services.host_agent import HostAgent as ModeratorAgent
from .models import Discussion, Character, Message

logger = logging.getLogger(__name__)


def parse_mentions(text: str) -> list:
    """
    从文本中解析 @角色名

    Args:
        text: 文本内容

    Returns:
        角色名列表
    """
    if not text:
        return []
    # 匹配 @角色名，捕获纯名字部分
    # 中文名可能包含 · 中点，但后面必须有特定分隔符或标点
    # 格式如: @尼采（描述... 或 @尼采——描述... 或 @尼采，你好
    # 防止匹配 "被@时方可发言" 这种非mention情况
    pattern = r'@([\u4e00-\u9fa5·]+)(?:[（\-—""''\s，。！？；、]|$)'
    matches = re.findall(pattern, text)
    return matches


class IndexView(View):
    """圆桌会谈首页 - 话题输入"""

    def get(self, request):
        """渲染话题输入页面"""
        return render(request, 'roundtable/index.html')


class SetupView(View):
    """角色配置页面"""

    def get(self, request):
        """渲染角色配置页面"""
        # 从 URL 参数获取 topic 和 characters
        topic = request.GET.get('topic', '')
        characters_param = request.GET.get('characters', '')
        user_role = request.GET.get('user_role', 'participant')

        if not topic or not characters_param:
            # 重定向到首页
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect('/roundtable/')

        try:
            characters = json.loads(characters_param)
        except json.JSONDecodeError:
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect('/roundtable/')

        # 验证 user_role
        valid_roles = ['host', 'participant', 'observer']
        if user_role not in valid_roles:
            user_role = 'participant'

        context = {
            'topic': topic,
            'characters_json': json.dumps(characters, ensure_ascii=False),
            'user_role': user_role,
        }
        return render(request, 'roundtable/setup.html', context)


class SuggestionsView(View):
    """API endpoint - 获取导演推荐的角色"""

    def post(self, request):
        """根据话题返回推荐角色列表"""
        try:
            data = json.loads(request.body)
            topic = data.get('topic', '').strip()

            if not topic:
                return JsonResponse({'error': '话题不能为空'}, status=400)

            if len(topic) > 200:
                return JsonResponse({'error': '话题不能超过200字'}, status=400)

            # 调用导演 Agent 获取推荐
            director = DirectorAgent()
            characters = director.suggest_characters(topic, count=20)

            if not characters:
                return JsonResponse({
                    'error': '暂时无法获取角色推荐，请稍后再试'
                }, status=500)

            # 跟踪推荐角色：检查是否有离线基础设定
            # 如果没有，加入候选队列
            try:
                from .profiles import get_candidate_queue, get_base_profile_loader
                profile_loader = get_base_profile_loader()
                candidate_queue = get_candidate_queue()

                for char in characters:
                    name = char.get('name', '')
                    era = char.get('era', '')
                    if name and not profile_loader.has_profile(name):
                        # 没有离线基础设定，加入候选队列
                        entry = candidate_queue.add_candidate(name, era)
                        char['_in_candidate_queue'] = True
                        char['_recommend_count'] = entry.recommend_count
                        char['_has_offline_profile'] = False
                    else:
                        char['_has_offline_profile'] = True
            except Exception as e:
                logger.warning(f"Failed to track candidates: {e}")

            return JsonResponse({
                'topic': topic,
                'characters': characters,
                'count': len(characters)
            }, json_dumps_params={'ensure_ascii': False})

        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求格式'}, status=400)
        except Exception as e:
            logger.exception("Error getting character suggestions")
            return JsonResponse({'error': str(e)}, status=500)


class ConfigureView(View):
    """API endpoint - 配置选定角色的详细信息"""

    def post(self, request):
        """为选定的角色生成详细配置"""
        try:
            data = json.loads(request.body)
            topic = data.get('topic', '').strip()
            characters = data.get('characters', [])

            if not topic:
                return JsonResponse({'error': '话题不能为空'}, status=400)

            if not characters or len(characters) < 3:
                return JsonResponse({'error': '至少需要选择3个角色'}, status=400)

            if len(characters) > 5:
                return JsonResponse({'error': '最多只能选择5个角色'}, status=400)

            # 机制2：当用户选定角色后，如果没有离线基础设定，则生成并保存离线设定
            def ensure_offline_profile(name: str, era: str):
                """确保角色有离线基础设定，如果没有则生成并保存"""
                try:
                    from .profiles import get_base_profile_loader, generate_offline_profile
                    profile_loader = get_base_profile_loader()
                    if not profile_loader.has_profile(name):
                        logger.info(f"Generating offline profile for: {name}")
                        result = generate_offline_profile(name, era)
                        if result:
                            logger.info(f"Offline profile saved: {result}")
                        else:
                            logger.warning(f"Failed to generate offline profile for: {name}")
                except Exception as e:
                    logger.warning(f"Error ensuring offline profile for {name}: {e}")

            # 为每个角色生成配置 - 并行执行
            def configure_single(char):
                """单独配置一个角色"""
                name = char.get('name', '')
                era = char.get('era', '')
                if not name:
                    return None

                # 机制2：确保有离线基础设定（会在后台异步保存）
                ensure_offline_profile(name, era)

                character_agent = CharacterAgent()
                return character_agent.configure_character(
                    character=char,
                    topic=topic,
                    era=era
                )

            # 使用线程池并行处理所有角色
            configured_characters = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(configure_single, char): char for char in characters}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            configured_characters.append(result)
                    except Exception as e:
                        logger.exception(f"Error configuring character")

            return JsonResponse({
                'topic': topic,
                'characters': configured_characters,
                'count': len(configured_characters)
            }, json_dumps_params={'ensure_ascii': False})

        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求格式'}, status=400)
        except Exception as e:
            logger.exception("Error configuring characters")
            return JsonResponse({'error': str(e)}, status=500)


class DiscussionView(View):
    """讨论页面"""

    def get(self, request, discussion_id):
        """渲染讨论页面"""
        try:
            discussion = Discussion.objects.get(id=discussion_id)
            characters = discussion.characters.all()

            # URL query param takes precedence, fallback to discussion.user_role
            user_role = request.GET.get('role', discussion.user_role)
            valid_roles = ['host', 'participant', 'observer']
            if user_role not in valid_roles:
                user_role = discussion.user_role

            context = {
                'discussion_id': discussion.id,
                'topic': discussion.topic,
                'status': discussion.status,
                'user_role': user_role,
                'current_round': discussion.current_round,
                'max_rounds': discussion.max_rounds,
                'characters': [
                    {
                        'id': c.id,
                        'name': c.name,
                        'era': c.era,
                        'bio': c.bio,
                        'language_style': c.language_style,
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
                    for m in discussion.messages.all()
                ],
            }
            return render(request, 'roundtable/discussion.html', context)

        except Discussion.DoesNotExist:
            from django.http import HttpResponseNotFound
            return HttpResponseNotFound("讨论不存在")


class DiscussionStartView(View):
    """API endpoint - 开始讨论"""

    def post(self, request):
        """创建讨论并生成开场"""
        try:
            data = json.loads(request.body)
            topic = data.get('topic', '').strip()
            characters_data = data.get('characters', [])
            user_role = data.get('user_role', 'host')

            if not topic:
                return JsonResponse({'error': '话题不能为空'}, status=400)

            if len(characters_data) < 3:
                return JsonResponse({'error': '至少需要3个角色'}, status=400)

            # 创建讨论
            discussion = Discussion.objects.create(
                topic=topic,
                user_role=user_role,
                status='active',
            )

            # 创建角色
            character_objs = []
            for i, char_data in enumerate(characters_data):
                char_obj = Character.objects.create(
                    discussion=discussion,
                    name=char_data['name'],
                    era=char_data.get('era', ''),
                    bio=char_data.get('bio', ''),
                    background=char_data.get('background', ''),
                    major_works=char_data.get('major_works', []),
                    viewpoints=char_data.get('viewpoints', {}),
                    language_style=char_data.get('language_style', {}),
                    representative_articles=char_data.get('representative_articles', []),
                    temporal_constraints=char_data.get('temporal_constraints', {}),
                    speaking_order=i,
                )
                character_objs.append(char_obj)

            # 生成开场白
            moderator = ModeratorAgent()
            characters_for_opening = [
                {
                    'name': c.name,
                    'era': c.era,
                    'bio': c.bio,
                }
                for c in character_objs
            ]

            opening = moderator.generate_opening(
                topic=topic,
                characters=characters_for_opening,
                user_role=user_role,
            )

            # 保存开场消息
            Message.objects.create(
                discussion=discussion,
                content=opening,
                word_count=len(opening),
                is_moderator=True,
            )

            # 解析开场白中的 @ 提及并触发角色响应
            mentioned_names = parse_mentions(opening)
            initial_responses = []

            # 获取对话历史（此时只有开场白）
            history = f"主持人：{opening}"

            for name in mentioned_names:
                # 查找对应的角色
                char_obj = next((c for c in character_objs if c.name == name), None)
                if char_obj:
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
                        topic=topic,
                        conversation_history=history,
                        character_limit=200,
                    )

                    # 保存角色消息
                    msg = Message.objects.create(
                        discussion=discussion,
                        character=char_obj,
                        content=speech,
                        word_count=len(speech),
                        is_moderator=False,
                    )

                    char_obj.message_count += 1
                    char_obj.save()

                    initial_responses.append({
                        'id': msg.id,
                        'speaker': char_obj.name,
                        'content': speech,
                        'is_moderator': False,
                        'is_user': False,
                    })

                    # 更新历史
                    history += f"\n{char_obj.name}：{speech}"

            discussion.current_round = 1
            discussion.current_speaker = mentioned_names[-1] if mentioned_names else ''
            discussion.save()

            # 启动后台任务：自动继续邀请角色发言
            import threading
            from .services.auto_continue import start_auto_continue

            # 启动后台线程，使用新的 AutoContinueService
            thread = threading.Thread(
                target=start_auto_continue,
                args=(discussion.id,),
                daemon=True
            )
            thread.start()
            logger.info(f"[AutoContinue] 已启动后台任务 for discussion {discussion.id}")

            return JsonResponse({
                'discussion_id': discussion.id,
                'opening': opening,
                'initial_responses': initial_responses,
                'status': 'active',
            }, json_dumps_params={'ensure_ascii': False})

        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求格式'}, status=400)
        except Exception as e:
            logger.exception("Error starting discussion")
            return JsonResponse({'error': str(e)}, status=500)


class DiscussionMessageView(View):
    """API endpoint - 发送消息/获取AI回复"""

    def post(self, request, discussion_id):
        """发送用户消息并获取AI回复"""
        try:
            discussion = Discussion.objects.get(id=discussion_id)

            data = json.loads(request.body)
            content = data.get('content', '').strip()
            character_id = data.get('character_id')

            if not content:
                return JsonResponse({'error': '消息不能为空'}, status=400)

            # 获取或创建用户消息
            user_char, _ = Character.objects.get_or_create(
                discussion=discussion,
                name='你',
                defaults={'era': '现代', 'bio': '参与者'}
            )

            # 保存用户消息
            user_msg = Message.objects.create(
                discussion=discussion,
                character=user_char if not character_id else None,
                content=content,
                word_count=len(content),
                is_user=True,
            )

            # 获取对话历史
            history = self._get_conversation_history(discussion)

            # 如果用户扮演的是某个角色，让该角色发言
            responses = []

            if character_id:
                try:
                    char_obj = Character.objects.get(id=character_id)
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

                    # 保存角色回复
                    char_msg = Message.objects.create(
                        discussion=discussion,
                        character=char_obj,
                        content=speech,
                        word_count=len(speech),
                    )

                    char_obj.message_count += 1
                    char_obj.save()

                    responses.append({
                        'id': char_msg.id,
                        'speaker': char_obj.name,
                        'content': speech,
                        'is_moderator': False,
                    })

                except Character.DoesNotExist:
                    pass

            # 生成主持人引导
            moderator = ModeratorAgent()
            characters = list(discussion.characters.all())

            if characters and len(responses) > 0:
                # 邀请下一个角色发言
                last_speaker = responses[-1]['speaker'] if responses else None
                next_char = self._get_next_speaker(characters, last_speaker)

                if next_char:
                    invitation = moderator.generate_invitation(
                        character_name=next_char.name,
                        topic=discussion.topic,
                        conversation_history=history,
                    )

                    mod_msg = Message.objects.create(
                        discussion=discussion,
                        content=invitation,
                        word_count=len(invitation),
                        is_moderator=True,
                    )

                    responses.append({
                        'id': mod_msg.id,
                        'speaker': '主持人',
                        'content': invitation,
                        'is_moderator': True,
                    })

                    discussion.current_speaker = next_char.name

            # 更新轮次
            discussion.current_round += 1

            # 检查是否达到最大轮次
            if discussion.current_round >= discussion.max_rounds:
                discussion.status = 'finished'
                closing = moderator.generate_closing(
                    topic=discussion.topic,
                    characters=[
                        {'name': c.name}
                        for c in characters
                    ],
                    discussion_summary="（详见总结）"
                )
                Message.objects.create(
                    discussion=discussion,
                    content=closing,
                    word_count=len(closing),
                    is_moderator=True,
                )
                responses.append({
                    'speaker': '主持人',
                    'content': closing,
                    'is_moderator': True,
                })

            discussion.save()

            return JsonResponse({
                'messages': responses,
                'round': discussion.current_round,
                'max_round': discussion.max_rounds,
                'status': discussion.status,
            }, json_dumps_params={'ensure_ascii': False})

        except Discussion.DoesNotExist:
            return JsonResponse({'error': '讨论不存在'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求格式'}, status=400)
        except Exception as e:
            logger.exception("Error in discussion message")
            return JsonResponse({'error': str(e)}, status=500)

    def _get_conversation_history(self, discussion, limit=10):
        """获取对话历史"""
        messages = list(discussion.messages.all())[-(limit * 2):]
        history = []
        for msg in messages:
            speaker = msg.character.name if msg.character else '系统'
            history.append(f"{speaker}：{msg.content}")
        return "\n".join(history)

    def _get_next_speaker(self, characters, last_speaker=None):
        """获取下一个发言的角色"""
        if not last_speaker:
            return characters[0] if characters else None

        for i, char in enumerate(characters):
            if char.name == last_speaker:
                next_idx = (i + 1) % len(characters)
                return characters[next_idx]
        return characters[0] if characters else None


class DiscussionPollView(View):
    """API endpoint - 轮询获取新消息（简化版，不需要）"""

    def get(self, request, discussion_id):
        """获取当前状态"""
        try:
            discussion = Discussion.objects.get(id=discussion_id)

            messages_data = [
                {
                    'id': m.id,
                    'content': m.content,
                    'speaker': m.character.name if m.character else ('主持人' if m.is_moderator else '系统'),
                    'is_moderator': m.is_moderator,
                    'is_system': m.is_system,
                    'is_user': m.is_user,
                    'created_at': m.created_at.isoformat(),
                }
                for m in discussion.messages.all()
            ]

            return JsonResponse({
                'status': discussion.status,
                'current_round': discussion.current_round,
                'current_speaker': discussion.current_speaker,
                'messages': messages_data,
            }, json_dumps_params={'ensure_ascii': False})

        except Discussion.DoesNotExist:
            return JsonResponse({'error': '讨论不存在'}, status=404)


class ProfileListView(View):
    """人物设定管理页面"""

    def get(self, request):
        """渲染人物设定管理页面"""
        return render(request, 'roundtable/profiles.html')


class ProfileListApiView(View):
    """API - 获取已配置的基础设定列表"""

    def get(self, request):
        """获取已配置的离线基础设定列表"""
        try:
            from .services.character import CharacterAgent

            agent = CharacterAgent()
            profile_loader = agent._profile_loader

            all_profiles = profile_loader.get_all_profiles()
            profiles_list = []

            for name, profile in all_profiles.items():
                profiles_list.append({
                    'name': name,
                    'era': profile.get('era', ''),
                    'core_identity': profile.get('core_identity', '')[:100] + '...' if profile.get('core_identity') else '',
                    'core_persona': profile.get('core_persona', '')[:100] + '...' if profile.get('core_persona') else '',
                })

            return JsonResponse({
                'profiles': profiles_list,
                'count': len(profiles_list),
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.exception("Error getting profile list")
            return JsonResponse({'error': str(e)}, status=500)


class ProfileDetailApiView(View):
    """API - 获取/删除单个基础设定"""

    def get(self, request, name):
        """获取指定人物的基础设定详情"""
        try:
            from .services.character import CharacterAgent

            agent = CharacterAgent()
            profile = agent.get_offline_profile(name)

            if not profile:
                return JsonResponse({'error': '基础设定不存在'}, status=404)

            return JsonResponse({
                'profile': profile,
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.exception(f"Error getting profile {name}")
            return JsonResponse({'error': str(e)}, status=500)


class CacheStatsApiView(View):
    """API - 获取缓存统计信息"""

    def get(self, request):
        """获取话题设定缓存统计"""
        try:
            from .services.character import CharacterAgent

            agent = CharacterAgent()
            stats = agent.get_cache_stats()
            entries = agent.get_cache_entries()

            return JsonResponse({
                'stats': stats,
                'entries': entries,
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.exception("Error getting cache stats")
            return JsonResponse({'error': str(e)}, status=500)


class CacheDeleteApiView(View):
    """API - 删除缓存条目"""

    def post(self, request):
        """删除指定缓存条目"""
        try:
            data = json.loads(request.body)
            character_name = data.get('character_name', '')
            topic = data.get('topic', '')

            if not character_name or not topic:
                return JsonResponse({'error': '缺少参数'}, status=400)

            from .services.character import CharacterAgent

            agent = CharacterAgent()
            cache = agent._topic_cache

            deleted = cache.delete(character_name, topic)

            return JsonResponse({
                'success': deleted,
                'message': '删除成功' if deleted else '缓存条目不存在',
            })

        except Exception as e:
            logger.exception("Error deleting cache entry")
            return JsonResponse({'error': str(e)}, status=500)


class CacheClearApiView(View):
    """API - 清空所有缓存"""

    def post(self, request):
        """清空所有话题设定缓存"""
        try:
            from .services.character import CharacterAgent

            agent = CharacterAgent()
            cache = agent._topic_cache
            cache.clear()

            return JsonResponse({
                'success': True,
                'message': '缓存已清空',
            })

        except Exception as e:
            logger.exception("Error clearing cache")
            return JsonResponse({'error': str(e)}, status=500)


class CandidateQueueListApiView(View):
    """API - 获取候选队列列表"""

    def get(self, request):
        """获取所有候选角色"""
        try:
            from .profiles import get_candidate_queue

            queue = get_candidate_queue()
            candidates = queue.get_all_candidates()
            stats = queue.get_stats()

            return JsonResponse({
                'candidates': [c.to_dict() for c in candidates],
                'stats': stats,
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.exception("Error getting candidate queue")
            return JsonResponse({'error': str(e)}, status=500)


class CandidateQueueTriggerApiView(View):
    """API - 手动触发生成候选角色基础设定"""

    def post(self, request):
        """触发生成指定角色的离线基础设定"""
        try:
            data = json.loads(request.body)
            name = data.get('name', '')

            if not name:
                return JsonResponse({'error': '角色名不能为空'}, status=400)

            from .profiles import get_candidate_queue

            queue = get_candidate_queue()
            triggered = queue.trigger_generation(name)

            if triggered:
                return JsonResponse({
                    'success': True,
                    'message': f'已触发生成 {name} 的离线基础设定',
                })
            else:
                entry = queue.get_candidate(name)
                if entry and entry.status == 'generating':
                    return JsonResponse({
                        'success': False,
                        'message': f'{name} 正在生成中，请勿重复触发',
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': f'{name} 不在候选队列中或已完成生成',
                    })

        except Exception as e:
            logger.exception("Error triggering candidate generation")
            return JsonResponse({'error': str(e)}, status=500)


class CandidateQueueResetApiView(View):
    """API - 重置候选角色计数"""

    def post(self, request):
        """重置指定角色的推荐计数"""
        try:
            data = json.loads(request.body)
            name = data.get('name', '')

            if not name:
                return JsonResponse({'error': '角色名不能为空'}, status=400)

            from .profiles import get_candidate_queue

            queue = get_candidate_queue()
            entry = queue.reset_count(name)

            if entry:
                return JsonResponse({
                    'success': True,
                    'message': f'已重置 {name} 的推荐计数',
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': f'{name} 不在候选队列中',
                })

        except Exception as e:
            logger.exception("Error resetting candidate count")
            return JsonResponse({'error': str(e)}, status=500)


class CandidateQueueDeleteApiView(View):
    """API - 从候选队列移除"""

    def post(self, request):
        """从候选队列中移除指定角色"""
        try:
            data = json.loads(request.body)
            name = data.get('name', '')

            if not name:
                return JsonResponse({'error': '角色名不能为空'}, status=400)

            from .profiles import get_candidate_queue

            queue = get_candidate_queue()
            deleted = queue.remove_candidate(name)

            return JsonResponse({
                'success': deleted,
                'message': '已移除' if deleted else '角色不在候选队列中',
            })

        except Exception as e:
            logger.exception("Error removing candidate")
            return JsonResponse({'error': str(e)}, status=500)


class CandidateQueueClearApiView(View):
    """API - 清空候选队列"""

    def post(self, request):
        """清空所有候选角色"""
        try:
            from .profiles import get_candidate_queue

            queue = get_candidate_queue()
            queue.clear()

            return JsonResponse({
                'success': True,
                'message': '候选队列已清空',
            })

        except Exception as e:
            logger.exception("Error clearing candidate queue")
            return JsonResponse({'error': str(e)}, status=500)


class HistoryListApiView(View):
    """API - 获取历史讨论列表"""

    def get(self, request):
        """获取所有历史讨论"""
        try:
            discussions = Discussion.objects.all().order_by('-created_at')

            history_list = []
            for d in discussions:
                characters = d.characters.all()
                char_names = ', '.join([c.name for c in characters[:3]])
                if characters.count() > 3:
                    char_names += f' 等{characters.count()}人'

                history_list.append({
                    'id': d.id,
                    'topic': d.topic,
                    'status': d.status,
                    'user_role': d.user_role,
                    'character_names': char_names,
                    'character_count': characters.count(),
                    'current_round': d.current_round,
                    'max_rounds': d.max_rounds,
                    'created_at': d.created_at.strftime('%Y-%m-%d %H:%M'),
                })

            return JsonResponse({
                'history': history_list,
                'count': len(history_list),
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.exception("Error getting history list")
            return JsonResponse({'error': str(e)}, status=500)


class RestartApiView(View):
    """API - 复制配置重新开始讨论"""

    def post(self, request, discussion_id):
        """复制原讨论配置，创建新讨论"""
        try:
            original = Discussion.objects.get(id=discussion_id)
            original_chars = original.characters.all()

            if not original_chars:
                return JsonResponse({'error': '原讨论没有角色配置'}, status=400)

            # 创建新讨论（复制 topic 和 user_role）
            new_discussion = Discussion.objects.create(
                topic=original.topic,
                user_role=original.user_role,
                status='active',
                max_rounds=original.max_rounds,
                character_limit=original.character_limit,
            )

            # 复制角色配置（直接复制字段，不调用 LLM）
            for i, orig_char in enumerate(original_chars):
                Character.objects.create(
                    discussion=new_discussion,
                    name=orig_char.name,
                    era=orig_char.era,
                    bio=orig_char.bio,
                    background=orig_char.background,
                    major_works=orig_char.major_works,
                    viewpoints=orig_char.viewpoints,
                    language_style=orig_char.language_style,
                    representative_articles=orig_char.representative_articles,
                    temporal_constraints=orig_char.temporal_constraints,
                    speaking_order=i,
                )

            # 生成开场白
            from .services.host_agent import HostAgent
            host = HostAgent()
            new_chars = new_discussion.characters.all()
            characters_for_opening = [
                {'name': c.name, 'era': c.era, 'bio': c.bio}
                for c in new_chars
            ]
            opening = host.generate_opening(
                topic=new_discussion.topic,
                characters=characters_for_opening,
                user_role=new_discussion.user_role,
            )

            # 保存开场消息
            Message.objects.create(
                discussion=new_discussion,
                content=opening,
                word_count=len(opening),
                is_moderator=True,
            )

            # 解析开场白中的 @ 提及，生成首个角色发言
            mentioned_names = parse_mentions(opening)
            history = f"主持人：{opening}"

            for name in mentioned_names:
                char_obj = next((c for c in new_chars if c.name == name), None)
                if char_obj:
                    from .services.character import CharacterAgent
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
                        topic=new_discussion.topic,
                        conversation_history=history,
                        character_limit=new_discussion.character_limit,
                    )
                    Message.objects.create(
                        discussion=new_discussion,
                        character=char_obj,
                        content=speech,
                        word_count=len(speech),
                        is_moderator=False,
                    )
                    char_obj.message_count += 1
                    char_obj.save()
                    history += f"\n{char_obj.name}：{speech}"

            new_discussion.current_round = 1
            new_discussion.current_speaker = mentioned_names[-1] if mentioned_names else ''
            new_discussion.save()

            # 启动后台自动继续任务
            import threading
            from .services.auto_continue import start_auto_continue
            thread = threading.Thread(
                target=start_auto_continue,
                args=(new_discussion.id,),
                daemon=True
            )
            thread.start()

            return JsonResponse({
                'success': True,
                'new_discussion_id': new_discussion.id,
                'topic': new_discussion.topic,
                'character_count': len(new_chars),
            }, json_dumps_params={'ensure_ascii': False})

        except Discussion.DoesNotExist:
            return JsonResponse({'error': '原讨论不存在'}, status=404)
        except Exception as e:
            logger.exception("Error restarting discussion")
            return JsonResponse({'error': str(e)}, status=500)