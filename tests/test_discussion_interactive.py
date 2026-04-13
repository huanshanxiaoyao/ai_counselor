"""
交互式讨论室测试脚本

模拟完整的讨论流程：
1. 创建讨论（4个角色）
2. 生成开场白
3. 主持人依次邀请角色发言
4. 每次发言后询问玩家是否要发言
5. 玩家可以选择发言（带@mention）或跳过

运行方式（Docker内）：
docker exec -i ai_counselor-backend-1 python -c "
import os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
import django
django.setup()
from tests.test_discussion_interactive import run_interactive_discussion
run_interactive_discussion()
"
"""
import os
import sys

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
    """运行交互式讨论"""
    print_header("交互式讨论室测试")
    print("角色: 庄子、苏格拉底、切·格瓦拉、列夫·托尔斯泰")
    print("话题: 人生有没有意义")
    print("你将以【参与者】身份参与讨论")
    print("="*70)

    # 清理旧数据
    print("\n[系统] 清理旧数据...")
    Discussion.objects.all().delete()

    # 选择角色
    characters_data = [
        {'name': '庄子', 'era': '战国时期', 'bio': '道家代表人物', 'background': '主张逍遥自在，无为而治'},
        {'name': '苏格拉底', 'era': '古希腊', 'bio': '古希腊哲学家', 'background': '西方哲学奠基人'},
        {'name': '切·格瓦拉', 'era': '20世纪阿根廷', 'bio': '革命家', 'background': '古巴革命核心人物'},
        {'name': '列夫·托尔斯泰', 'era': '19世纪俄国', 'bio': '作家', 'background': '《战争与和平》作者'},
    ]

    topic = "人生有没有意义"

    # 创建讨论（玩家是参与者）
    print("\n[系统] 创建讨论...")
    discussion = Discussion.objects.create(
        topic=topic,
        user_role='participant',  # 参与者模式
        status='active',
    )

    # 创建角色
    character_objs = []
    for i, char_data in enumerate(characters_data):
        char_obj = Character.objects.create(
            discussion=discussion,
            name=char_data['name'],
            era=char_data['era'],
            bio=char_data['bio'],
            background=char_data['background'],
            speaking_order=i,
        )
        character_objs.append(char_obj)
        print(f"  - 创建角色: {char_obj.name}（{char_obj.era}）")

    print(f"  讨论ID: {discussion.id}")
    print(f"  话题: {discussion.topic}")
    print(f"  用户角色: {discussion.user_role}")

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

    # 主循环
    while pending_characters or True:
        print_header(f"第 {round_num} 轮讨论")

        # 如果有待发言角色，先让角色发言
        while pending_characters:
            char_obj = pending_characters.pop(0)

            # 生成角色发言
            print(f"\n[系统] 正在生成 {char_obj.name} 的发言...")
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
            char_obj.save()

            # 更新历史
            history += f"\n{char_obj.name}：{speech}"

            # 更新讨论状态
            discussion.current_round = round_num
            discussion.current_speaker = char_obj.name
            discussion.save()

            # 输出发言
            print_message(char_obj.name, speech)

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

                    # 如果@了角色，让被@的角色发言
                    for name in mentioned:
                        char_to_respond = next((c for c in character_objs if c.name == name), None)
                        if char_to_respond:
                            print(f"\n[系统] {char_to_respond.name} 被@，正在生成回复...")

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
                # 玩家选择跳过，让主持人继续
                print("[你] 选择跳过")

            # 每轮结束后检查是否达到最大轮次
            if round_num >= discussion.max_rounds:
                print("\n[系统] 达到最大轮次，讨论结束")
                break

            round_num += 1

        # 如果没有更多待发言角色，询问主持人是否继续
        if not pending_characters:
            print_header("讨论可能的结束")

            # 检查是否所有角色都已发言
            all_spoken = all(c.message_count > 0 for c in character_objs)

            if all_spoken and round_num > 1:
                print("\n[系统] 所有角色都已发言一轮")
                continue_choice = get_player_input(
                    "[询问] 继续讨论吗？(y继续/n退出): "
                ).strip().lower()

                if continue_choice != 'y':
                    print("\n[系统] 讨论结束")
                    break
                else:
                    # 重新开始一轮，让主持人邀请
                    print("\n[系统] 让主持人继续邀请...")
                    last_speaker = discussion.current_speaker

                    invitation = moderator.generate_invitation(
                        character_name=character_objs[0].name,
                        topic=discussion.topic,
                        conversation_history=history,
                    )

                    inv_msg = Message.objects.create(
                        discussion=discussion,
                        content=invitation,
                        word_count=len(invitation),
                        is_moderator=True,
                    )

                    print_message("主持人", invitation)
                    history += f"\n主持人：{invitation}"

                    # 将第一个角色加入待发言
                    pending_characters.append(character_objs[0])

                    round_num += 1
            else:
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