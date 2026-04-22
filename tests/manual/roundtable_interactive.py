#!/usr/bin/env python
"""
交互式讨论室测试脚本 - 令牌制版本

运行方式：
    docker exec -i ai_counselor-backend-1 python /app/tests/manual/roundtable_interactive.py
"""
import os
import sys
from datetime import datetime

# Setup Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')

import django
django.setup()

from backend.roundtable.models import Discussion, Character, Message
from backend.roundtable.services.character import CharacterAgent
from backend.roundtable.services.host_agent import HostAgent as ModeratorAgent
from backend.roundtable.views import parse_mentions


def print_header(title):
    print(f"\n{'#'*70}")
    print(f"  {title}")
    print('#'*70)


def print_message(speaker, content, is_player=False):
    prefix = "[你]" if is_player else f"[{speaker}]"
    print(f"\n{prefix} {content}")
    print("-" * 50)


def get_player_input(prompt):
    """获取玩家输入"""
    try:
        return input(prompt)
    except EOFError:
        return 'n'


def run_interactive_discussion():
    """运行交互式讨论 - 令牌制版本"""
    print_header("交互式讨论室测试 - 令牌制")
    print("角色: 庄子、苏格拉底、切·格瓦拉、列夫·托尔斯泰")
    print("话题: 人生有没有意义")
    print("你将以【参与者】身份参与讨论")
    print("令牌规则:")
    print("  - 主持人令牌: 主持人@角色 = 转移令牌给该角色")
    print("  - 角色发言结束后@主持人 = 归还令牌")
    print("  - 每3轮使用一次LLM决策下一轮邀请谁")
    print("="*70)

    # 清理旧数据
    print("\n[系统] 清理旧数据...")
    Discussion.objects.all().delete()

    # 选择角色 - 从离线设定加载
    from backend.roundtable.profiles import get_base_profile_loader
    profile_loader = get_base_profile_loader()

    character_names = ['庄子', '苏格拉底', '切·格瓦拉', '列夫·托尔斯泰']

    topic = "人生有没有意义"

    # 创建讨论（玩家是参与者）
    print("\n[系统] 创建讨论...")
    discussion = Discussion.objects.create(
        topic=topic,
        user_role='participant',
        status='active',
    )

    # 初始化主持人令牌
    discussion.host_token_holder = '主持人'
    discussion.save()

    # 创建角色 - 使用离线设定
    character_objs = []
    for i, name in enumerate(character_names):
        profile = profile_loader.get_profile(name)
        if profile:
            # 使用离线设定
            era = profile.get('era', '')
            bio = profile.get('core_identity', '')
            background = profile.get('core_persona', '')
            # 解析 language_style
            ls = profile.get('language_style', {})
            language_style = {
                'tone': ls.get('tone', '中性'),
                'catchphrases': ls.get('catchphrases', []),
                'speaking_habits': ls.get('speaking_habits', ''),
            }
            # 解析 knowledge_boundary
            kb = profile.get('knowledge_boundary', {})
            temporal_constraints = {
                'can_discuss': kb.get('can_discuss', []),
                'cannot_discuss': kb.get('cannot_discuss', []),
                'knowledge_cutoff': kb.get('knowledge_cutoff', ''),
            }
            print(f"  - 创建角色: {name}（{era}）- 使用离线设定")
        else:
            # 没有离线设定，使用默认值
            era = '未知'
            bio = ''
            background = ''
            language_style = {}
            temporal_constraints = {}
            print(f"  - 创建角色: {name} - 无离线设定，使用默认值")

        char_obj = Character.objects.create(
            discussion=discussion,
            name=name,
            era=era,
            bio=bio,
            background=background,
            language_style=language_style,
            temporal_constraints=temporal_constraints,
            speaking_order=i,
        )
        character_objs.append(char_obj)

    print(f"  讨论ID: {discussion.id}")
    print(f"  话题: {discussion.topic}")
    print(f"  用户角色: {discussion.user_role}")
    print(f"  主持人令牌持有者: {discussion.host_token_holder}")

    # 生成开场白
    print_header("生成开场白")
    moderator = ModeratorAgent()
    characters_for_opening = [
        {'name': c.name, 'era': c.era, 'bio': c.bio}
        for c in character_objs
    ]

    print("[主持人] 生成开场白中...")
    opening = moderator.generate_opening(
        topic=topic,
        characters=characters_for_opening,
        user_role='participant',
    )

    # 保存开场消息
    opening_msg = Message.objects.create(
        discussion=discussion,
        content=opening,
        word_count=len(opening),
        is_moderator=True,
    )

    # 更新最后发言
    discussion.current_speaker = '主持人'
    discussion.save()

    print_message("主持人", opening)

    # 解析开场白中的@mention
    mentioned_in_opening = parse_mentions(opening)
    print(f"\n[系统] 开场白中@的角色: {mentioned_in_opening}")

    # 存储对话历史
    history = f"主持人：{opening}"

    # 获取需要发言的角色队列
    pending_characters = []
    for name in mentioned_in_opening:
        char_obj = next((c for c in character_objs if c.name == name), None)
        if char_obj:
            pending_characters.append(char_obj)

    round_num = 1

    # 轮询轮数阈值（前N轮使用轮询，之后使用LLM）
    ROUND_ROBIN_THRESHOLD = 2

    # 主循环
    while True:
        print_header(f"第 {round_num} 轮讨论")

        # 检查主持人令牌
        current_token_holder = discussion.host_token_holder
        print(f"\n[系统] 主持人令牌持有者: {current_token_holder}")

        # 如果有待发言角色，先让角色发言
        while pending_characters:
            char_obj = pending_characters.pop(0)

            # 授予令牌给角色
            print(f"\n[系统] 授予令牌给 {char_obj.name}...")
            discussion.host_token_holder = char_obj.name
            discussion.save()

            # 生成角色发言
            print(f"[系统] 正在生成 {char_obj.name} 的发言...")
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
                character_limit=200,
            )

            # 保存消息
            msg = Message.objects.create(
                discussion=discussion,
                character=char_obj,
                content=speech,
                word_count=len(speech),
                is_moderator=False,
                is_user=False,
            )
            char_obj.message_count += 1
            char_obj.consecutive_mentions = 0  # 重置连续@计数
            char_obj.save()

            # 更新历史
            history += f"\n{char_obj.name}：{speech}"

            # 更新讨论状态
            discussion.current_round = round_num
            discussion.current_speaker = char_obj.name
            discussion.save()

            # 输出发言
            print_message(char_obj.name, speech)

            # 归还令牌给主持人
            print(f"[系统] {char_obj.name} 归还令牌给主持人...")
            discussion.host_token_holder = '主持人'
            discussion.save()

            # 询问玩家是否发言
            print()
            player_choice = get_player_input(
                f"[询问] 你要发言吗？(y/n/q退出): "
            ).strip().lower()

            if player_choice == 'q':
                print("\n[系统] 讨论结束")
                return

            if player_choice == 'y':
                # 玩家发言
                player_msg_text = get_player_input("[你] 请输入你的发言（可用@角色名）: ").strip()

                if player_msg_text:
                    # 解析@mention
                    mentioned = parse_mentions(player_msg_text)

                    # 保存玩家消息
                    player_char, _ = Character.objects.get_or_create(
                        discussion=discussion,
                        name='你',
                        defaults={'era': '现代', 'bio': '参与者'}
                    )

                    player_msg = Message.objects.create(
                        discussion=discussion,
                        character=player_char,
                        content=player_msg_text,
                        word_count=len(player_msg_text),
                        is_user=True,
                    )

                    print_message("你", player_msg_text, is_player=True)

                    # 更新历史
                    history += f"\n你：{player_msg_text}"

                    # 如果@了角色，让被@的角色响应（使用玩家令牌）
                    for name in mentioned:
                        char_to_respond = next((c for c in character_objs if c.name == name), None)
                        if char_to_respond:
                            print(f"\n[系统] {char_to_respond.name} 被@，正在判断是否回应...")

                            # 检查是否连续@超过2次
                            if char_to_respond.consecutive_mentions >= 2:
                                print(f"[系统] {char_to_respond.name} 已连续被@2次，使用婉拒...")
                                decline = character_agent.generate_decline_response(
                                    character_config={
                                        'name': char_to_respond.name,
                                        'era': char_to_respond.era,
                                        'bio': char_to_respond.bio,
                                        'background': char_to_respond.background,
                                        'language_style': char_to_respond.language_style,
                                        'temporal_constraints': char_to_respond.temporal_constraints,
                                        'viewpoints': char_to_respond.viewpoints,
                                    },
                                    player_message=player_msg_text
                                )
                                print_message(char_to_respond.name, f"(婉拒) {decline}")
                                history += f"\n{char_to_respond.name}：{decline}"
                                # 重置其他角色的连续@计数
                                for c in character_objs:
                                    if c.name != name:
                                        c.consecutive_mentions = 0
                                        c.save()
                            else:
                                # 判断是否应该回应
                                should_respond = character_agent.should_respond_to_player(
                                    character_config={
                                        'name': char_to_respond.name,
                                        'era': char_to_respond.era,
                                        'bio': char_to_respond.bio,
                                        'background': char_to_respond.background,
                                        'language_style': char_to_respond.language_style,
                                        'temporal_constraints': char_to_respond.temporal_constraints,
                                        'viewpoints': char_to_respond.viewpoints,
                                    },
                                    player_message=player_msg_text,
                                    conversation_history=history
                                )

                                if should_respond:
                                    # 增加连续@计数
                                    char_to_respond.consecutive_mentions += 1
                                    char_to_respond.save()

                                    speech = character_agent.generate_speech(
                                        character_config={
                                            'name': char_to_respond.name,
                                            'era': char_to_respond.era,
                                            'bio': char_to_respond.bio,
                                            'background': char_to_respond.background,
                                            'language_style': char_to_respond.language_style,
                                            'temporal_constraints': char_to_respond.temporal_constraints,
                                            'viewpoints': char_to_respond.viewpoints,
                                        },
                                        topic=discussion.topic,
                                        conversation_history=history,
                                        character_limit=200,
                                    )

                                    msg = Message.objects.create(
                                        discussion=discussion,
                                        character=char_to_respond,
                                        content=speech,
                                        word_count=len(speech),
                                        is_moderator=False,
                                        is_user=False,
                                    )
                                    char_to_respond.message_count += 1
                                    char_to_respond.save()

                                    history += f"\n{char_to_respond.name}：{speech}"

                                    print_message(char_to_respond.name, speech)

                                    # 如果这个角色不在待发言列表中，加入队列
                                    if char_to_respond not in pending_characters:
                                        pending_characters.append(char_to_respond)
                                else:
                                    # 角色选择不回应
                                    decline = character_agent.generate_decline_response(
                                        character_config={
                                            'name': char_to_respond.name,
                                            'era': char_to_respond.era,
                                            'bio': char_to_respond.bio,
                                            'background': char_to_respond.background,
                                            'language_style': char_to_respond.language_style,
                                            'temporal_constraints': char_to_respond.temporal_constraints,
                                            'viewpoints': char_to_respond.viewpoints,
                                        },
                                        player_message=player_msg_text
                                    )
                                    print_message(char_to_respond.name, f"(婉拒) {decline}")
                                    history += f"\n{char_to_respond.name}：{decline}"
            # else: 玩家选择'n'跳过，不做任何事，继续下一轮

            # 每轮结束后检查是否达到最大轮次
            if round_num >= discussion.max_rounds:
                print("\n[系统] 达到最大轮次，讨论结束")
                break

            round_num += 1

        # 如果没有更多待发言角色，让主持人自动邀请下一位
        if not pending_characters:
            # 检查是否达到最大轮次
            if round_num >= discussion.max_rounds:
                print("\n[系统] 达到最大轮次，讨论结束")
                break

            # 主持人自动邀请下一位（玩家没有按q退出就继续）
            print("\n[系统] 主持人自动邀请下一位...")

            # 决策策略：前N轮轮询，之后使用LLM
            use_llm = round_num > ROUND_ROBIN_THRESHOLD
            print(f"[系统] 第 {round_num} 轮, {'使用LLM决策(承上启下)' if use_llm else '使用轮询策略'}")

            next_char_name, transition = moderator.decide_next_speaker(
                characters=[{'name': c.name} for c in character_objs],
                last_speaker=discussion.current_speaker,
                conversation_history=history,
                topic=discussion.topic,
                use_llm=use_llm,
                round_count=round_num
            )

            if next_char_name:
                print(f"[系统] 决定邀请: {next_char_name}")
                if transition:
                    print(f"[系统] 承上启下: {transition}")

                invitation = moderator.generate_invitation(
                    character_name=next_char_name,
                    topic=discussion.topic,
                    conversation_history=history,
                    transition=transition if use_llm else None,
                )

                inv_msg = Message.objects.create(
                    discussion=discussion,
                    content=invitation,
                    word_count=len(invitation),
                    is_moderator=True,
                )

                print_message("主持人", invitation)
                history += f"\n主持人：{invitation}"

                # 将角色加入待发言
                next_char = next((c for c in character_objs if c.name == next_char_name), None)
                if next_char:
                    pending_characters.append(next_char)

                round_num += 1
            else:
                print("[系统] 无法决定下一位发言者，结束讨论")
                break

    # 总结
    print_header("讨论结束 - 统计")
    print(f"总轮次: {round_num}")
    print(f"消息总数: {discussion.messages.count()}")
    print("\n各角色发言次数:")
    for c in character_objs:
        print(f"  - {c.name}: {c.message_count} 次")
    print(f"  - 你: {discussion.messages.filter(is_user=True).count()} 次")

    # 清理
    print("\n[系统] 清理测试数据...")
    Discussion.objects.all().delete()
    print("[系统] 完成！")


if __name__ == '__main__':
    run_interactive_discussion()
