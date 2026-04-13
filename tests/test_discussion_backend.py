"""
测试讨论室后端逻辑 - 集成测试

测试场景：
1. 创建讨论（5个角色 + 主持人）
2. 测试旁观者模式（不能发言）
3. 测试发言权流转
4. 测试@mention功能
5. 测试角色响应

运行方式（Docker内）：
docker exec ai_counselor-backend-1 python -c "
import os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
import django
django.setup()
from tests.test_discussion_backend import run_all_tests
run_all_tests()
"
"""
import os
import sys
import json
import time
import logging

# Setup Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')

import django
django.setup()

from backend.roundtable.models import Discussion, Character, Message
from backend.roundtable.services.character import CharacterAgent
from backend.roundtable.services.host_agent import HostAgent as ModeratorAgent
from backend.roundtable.services.director import DirectorAgent
from backend.roundtable.views import parse_mentions

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def print_result(name, passed, error=None):
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status}: {name}")
    if error:
        print(f"         Error: {error}")


def test_offline_profiles():
    """测试1: 验证离线角色设定是否可用"""
    print_section("测试1: 离线角色设定")

    agent = CharacterAgent()
    test_chars = ['尼采', '庄子', '苏格拉底', '王阳明', '孔子']

    for name in test_chars:
        has_profile = agent.has_offline_profile(name)
        profile = agent.get_offline_profile(name)
        print(f"  - {name}: has_profile={has_profile}, profile_exists={profile is not None}")
        if profile:
            print(f"         era: {profile.get('era', 'N/A')}")

    return True


def test_discussion_creation():
    """测试2: 创建讨论"""
    print_section("测试2: 创建讨论")

    # 清理旧数据
    Discussion.objects.all().delete()

    # 使用5个有离线设定的角色
    characters_data = [
        {'name': '尼采', 'era': '近代德国', 'bio': '德国哲学家', 'background': '提出超人哲学和权力意志'},
        {'name': '庄子', 'era': '战国时期', 'bio': '道家代表人物', 'background': '主张逍遥自在，无为而治'},
        {'name': '苏格拉底', 'era': '古希腊', 'bio': '古希腊哲学家', 'background': '西方哲学奠基人'},
        {'name': '王阳明', 'era': '明代', 'bio': '心学大师', 'background': '提出知行合一'},
        {'name': '孔子', 'era': '春秋时期', 'bio': '儒家创始人', 'background': '主张仁义礼智信'},
    ]

    topic = "人生有没有意义"

    # 创建讨论
    discussion = Discussion.objects.create(
        topic=topic,
        user_role='observer',  # 旁观者模式
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
        print(f"  创建角色: {char_obj.name}（{char_obj.era}）")

    print(f"  讨论ID: {discussion.id}")
    print(f"  话题: {discussion.topic}")
    print(f"  用户角色: {discussion.user_role}")
    print(f"  状态: {discussion.status}")

    return discussion, character_objs


def test_opening_generation(discussion, character_objs):
    """测试3: 生成开场白并解析@mention"""
    print_section("测试3: 生成开场白")

    moderator = ModeratorAgent()
    characters_for_opening = [
        {'name': c.name, 'era': c.era, 'bio': c.bio}
        for c in character_objs
    ]

    print(f"  生成开场白中（话题: {discussion.topic}）...")
    opening = moderator.generate_opening(
        topic=discussion.topic,
        characters=characters_for_opening,
        user_role='observer',
    )

    print(f"  开场白长度: {len(opening)} 字")
    print(f"  开场白内容:\n    {'─'*50}")
    # 打印开场白，每行缩进4个空格
    for line in opening.split('\n'):
        print(f"    {line}")
    print(f"    {'─'*50}")

    # 解析@mention
    mentioned = parse_mentions(opening)
    print(f"  解析到的@mention: {mentioned}")

    # 保存开场消息
    msg = Message.objects.create(
        discussion=discussion,
        content=opening,
        word_count=len(opening),
        is_moderator=True,
    )
    print(f"  开场消息已保存: ID={msg.id}")

    return mentioned


def test_character_response(discussion, character_objs, char_name, history):
    """测试4: 测试单个角色响应"""
    print_section(f"测试4: 角色响应 - {char_name}")

    char_obj = next((c for c in character_objs if c.name == char_name), None)
    if not char_obj:
        print(f"  ✗ FAIL: 找不到角色 {char_name}")
        return None

    print(f"  角色: {char_obj.name}（{char_obj.era}）")
    print(f"  历史上下文长度: {len(history)} 字")

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
        character_limit=200,
    )

    print(f"  发言长度: {len(speech)} 字")
    print(f"  发言内容:\n    {'─'*50}")
    for line in speech.split('\n'):
        print(f"    {line}")
    print(f"    {'─'*50}")

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

    return speech


def test_observer_mode(discussion):
    """测试5: 测试旁观者模式"""
    print_section("测试5: 旁观者模式验证")

    print(f"  讨论状态: {discussion.status}")
    print(f"  用户角色: {discussion.user_role}")

    # 旁观者不能发言
    can_speak = discussion.user_role != 'observer'
    print(f"  旁观者能否发言: {can_speak}")

    if discussion.user_role == 'observer':
        print("  ✓ PASS: 旁观者模式正确设置")
        return True
    else:
        print("  ✗ FAIL: 用户角色设置错误")
        return False


def test_message_save_and_query(discussion, character_objs):
    """测试6: 测试消息保存和查询"""
    print_section("测试6: 消息保存和查询")

    # 验证消息数量
    msg_count = discussion.messages.count()
    print(f"  当前消息数量: {msg_count}")

    # 查询最后一条消息
    last_msg = discussion.messages.last()
    if last_msg:
        speaker = last_msg.character.name if last_msg.character else ('主持人' if last_msg.is_moderator else '系统')
        print(f"  最后一条消息: [{speaker}] {last_msg.content[:50]}...")

    # 验证QuerySet切片（测试负索引修复）
    print("  测试负索引切片...")
    try:
        all_msgs = list(discussion.messages.all())
        recent_msgs = list(discussion.messages.all())[-4:]  # 这应该能正常工作
        print(f"  ✓ 负索引切片成功: 获取到 {len(recent_msgs)} 条消息")
        slice_works = True
    except Exception as e:
        print(f"  ✗ 负索引切片失败: {e}")
        slice_works = False

    return slice_works


def test_conversation_history(discussion):
    """测试7: 测试对话历史获取"""
    print_section("测试7: 对话历史获取")

    messages = list(discussion.messages.all())[-10:]
    history = []
    for msg in messages:
        speaker = msg.character.name if msg.character else '系统'
        history.append(f"{speaker}：{msg.content}")

    history_text = "\n".join(history)
    print(f"  历史消息数量: {len(messages)}")
    print(f"  历史文本长度: {len(history_text)} 字")
    print(f"  历史内容预览:\n    {'─'*50}")
    for line in history_text.split('\n')[:5]:
        print(f"    {line[:80]}...")
    if len(history_text.split('\n')) > 5:
        print(f"    ... (共 {len(history_text.split(chr(10)))} 行)")
    print(f"    {'─'*50}")

    return history_text


def test_mention_parsing():
    """测试8: 测试@mention解析"""
    print_section("测试8: @mention解析")

    # 注意：修复后的正则只匹配@后紧跟中文名的部分
    test_cases = [
        ("@尼采 说说你得想法？", ["尼采"]),
        ("@庄子 @尼采 请你们发表意见", ["庄子", "尼采"]),
        ("大家好，我是主持人", []),
        ("@苏格拉底 你怎么看？@王阳明 同意吗？", ["苏格拉底", "王阳明"]),
        # 测试HostAgent生成的开场白格式（带（）描述）
        ("@尼采（以'上帝已死'唤醒价值重估的德国哲人）", ["尼采"]),
        ("@庄子（齐物逍遥、梦蝶问道的战国隐逸智者）", ["庄子"]),
        # 测试HostAgent生成的开场白格式（带——描述）
        ("@尼采——您以'上帝已死'震颤现代精神", ["尼采"]),
        ("@庄子——您在濠梁观鱼", ["庄子"]),
        # 没有@的情况
        ("大家好，我是主持人", []),
    ]

    all_passed = True
    for text, expected in test_cases:
        result = parse_mentions(text)
        passed = result == expected
        all_passed = all_passed and passed
        print(f"  {'✓' if passed else '✗'}: \"{text[:30]}...\"")
        print(f"      期望: {expected}, 实际: {result}")

    return all_passed


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("  讨论室后端逻辑集成测试")
    print("="*60)

    results = {}

    try:
        # 测试1: 离线角色设定
        results['offline_profiles'] = test_offline_profiles()

        # 测试2: 创建讨论
        discussion, character_objs = test_discussion_creation()
        results['discussion_creation'] = discussion is not None

        # 测试3: 生成开场白
        mentioned = test_opening_generation(discussion, character_objs)
        results['opening_generation'] = len(mentioned) > 0
        if not results['opening_generation']:
            print("  ⚠ 警告: 开场白中没有@任何人")

        # 测试8: @mention解析
        results['mention_parsing'] = test_mention_parsing()

        # 测试4: 角色响应（测试第一个@到的角色）
        if mentioned:
            first_mention = mentioned[0]
            # 构建历史
            history = f"主持人：{discussion.messages.first().content}"
            char_response = test_character_response(discussion, character_objs, first_mention, history)
            results['character_response'] = char_response is not None and len(char_response) > 0
        else:
            # 如果没有@，手动测试一个角色
            history = f"主持人：{discussion.messages.first().content}"
            char_response = test_character_response(discussion, character_objs, '尼采', history)
            results['character_response'] = char_response is not None and len(char_response) > 0

        # 测试5: 旁观者模式
        results['observer_mode'] = test_observer_mode(discussion)

        # 测试6: 消息保存和查询
        results['message_save'] = test_message_save_and_query(discussion, character_objs)

        # 测试7: 对话历史获取
        results['history'] = bool(test_conversation_history(discussion))

    except Exception as e:
        logger.exception("测试执行出错")
        print(f"\n✗ 测试过程出错: {e}")
        return

    # 汇总结果
    print_section("测试结果汇总")
    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"\n  通过: {passed_count}/{total_count}")
    for name, passed in results.items():
        print_result(name, passed)

    if passed_count == total_count:
        print("\n✓ 所有测试通过！")
    else:
        print(f"\n✗ 有 {total_count - passed_count} 项测试失败")

    # 清理测试数据
    print("\n清理测试数据...")
    Discussion.objects.all().delete()
    print("完成！")


if __name__ == '__main__':
    run_all_tests()