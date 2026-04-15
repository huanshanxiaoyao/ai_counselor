"""
Character Agent - Generates detailed character configurations for roundtable discussions.
"""
import json
import logging
from typing import Dict, List, Optional

from backend.llm import LLMClient, TokenUsage
from backend.roundtable.profiles import get_topic_cache, get_base_profile_loader

logger = logging.getLogger(__name__)


class CharacterAgent:
    """角色配置 Agent - 为选定角色生成详细配置"""

    def __init__(self, provider: str = None):
        self.client = LLMClient(provider_name=provider)
        self._profile_loader = get_base_profile_loader()
        self._topic_cache = get_topic_cache()
        self.last_token_usage: Optional[TokenUsage] = None

    def has_offline_profile(self, name: str) -> bool:
        """检查是否有离线基础设定"""
        return self._profile_loader.has_profile(name)

    def get_offline_profile(self, name: str) -> Optional[dict]:
        """获取离线基础设定"""
        return self._profile_loader.get_profile(name)

    def should_respond_to_player(
        self,
        character_config: Dict,
        player_message: str,
        conversation_history: str = ""
    ) -> bool:
        """
        决定角色是否应该回应玩家的@mention（礼貌婉拒机制）

        Args:
            character_config: 角色配置
            player_message: 玩家消息
            conversation_history: 对话历史

        Returns:
            是否应该回应（True=回应，False=礼貌婉拒）
        """
        name = character_config.get('name', '')
        bio = character_config.get('bio', '')

        # 构建判断 prompt
        prompt = f"""你是角色：{name}
背景：{bio}

当前情况：
- 玩家@了你
- 玩家说：{player_message}

请判断：作为这个角色，你是否应该正式回应玩家？

规则：
1. 如果玩家的问题与角色高度相关，应该回应
2. 如果角色已经被连续@了2次以上，可以婉拒让其他人发言
3. 如果角色身份不适合回应某些话题，可以礼貌回避
4. 如果角色正在深度思考/已有其他角色在发言，应该等待

回复格式（只返回JSON）：
{{"should_respond": true/false, "reason": "简短原因"}}
"""

        try:
            response = self.client.complete(
                prompt=prompt,
                system_prompt=self._get_speaking_system_prompt(
                    name=name,
                    era=character_config.get('era', ''),
                    bio=bio,
                    background=character_config.get('background', ''),
                    language_style=character_config.get('language_style', {}),
                    temporal_constraints=character_config.get('temporal_constraints', {}),
                    viewpoints=character_config.get('viewpoints', {}),
                    character_limit=100
                ),
                json_mode=True,
            )
            result = json.loads(response)
            return result.get('should_respond', True)
        except Exception as e:
            logger.error(f"判断回应失败: {e}")
            return True  # 默认应该回应

    def generate_decline_response(
        self,
        character_config: Dict,
        player_message: str
    ) -> str:
        """
        生成礼貌婉拒的回应

        Args:
            character_config: 角色配置
            player_message: 玩家消息

        Returns:
            婉拒文本
        """
        name = character_config.get('name', '')

        prompt = f"""你是角色：{name}

当前情况：玩家@了你，但你想礼貌地婉拒，让讨论继续

玩家说：{player_message}

请生成一段简短的婉拒语（30字以内），要求：
1. 保持角色特色
2. 委婉有礼
3. 简单说明原因或表达关注
4. 不用@玩家，直接说即可

例如：
- "此论题我已有拙见，不妨听听诸位的高见。"
- "老夫于此事略有涉猎，还是先听听诸位的见解吧。"

直接返回婉拒语，不要加引号。"""

        try:
            response = self.client.complete(
                prompt=prompt,
                system_prompt=self._get_speaking_system_prompt(
                    name=name,
                    era=character_config.get('era', ''),
                    bio=character_config.get('bio', ''),
                    background=character_config.get('background', ''),
                    language_style=character_config.get('language_style', {}),
                    temporal_constraints=character_config.get('temporal_constraints', {}),
                    viewpoints=character_config.get('viewpoints', {}),
                    character_limit=50
                ),
            )
            return response.strip()
        except Exception as e:
            logger.error(f"生成婉拒失败: {e}")
            return "此事我暂无高见，还是先听听诸位的见解。"

    def get_cache_stats(self) -> dict:
        """获取话题缓存统计"""
        return self._topic_cache.get_stats()

    def get_cache_entries(self) -> List[dict]:
        """获取所有缓存条目"""
        entries = self._topic_cache.get_all()
        return [
            {
                'key': e.key,
                'character_name': e.character_name,
                'topic': e.topic,
                'created_at': e.created_at.isoformat(),
            }
            for e in entries
        ]

    def generate_speech(
        self,
        character_config: Dict,
        topic: str,
        conversation_history: str = "",
        character_limit: int = 200,
        model: str = None,
    ) -> str:
        """
        生成角色发言

        Args:
            character_config: 角色配置
            topic: 讨论话题
            conversation_history: 对话历史
            character_limit: 字数限制

        Returns:
            角色发言文本
        """
        name = character_config.get('name', '')
        era = character_config.get('era', '')
        bio = character_config.get('bio', '')
        background = character_config.get('background', '')
        language_style = character_config.get('language_style', {})
        temporal_constraints = character_config.get('temporal_constraints', {})
        viewpoints = character_config.get('viewpoints', {})

        # 构建角色 system prompt
        system_prompt = self._get_speaking_system_prompt(
            name=name,
            era=era,
            bio=bio,
            background=background,
            language_style=language_style,
            temporal_constraints=temporal_constraints,
            viewpoints=viewpoints,
            character_limit=character_limit
        )

        # 构建发言 prompt
        prompt = self._build_speaking_prompt(
            topic=topic,
            conversation_history=conversation_history,
            character_limit=character_limit
        )

        result = self.client.complete_with_metadata(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
        )
        self.last_token_usage = result.usage

        return result.text.strip()

    def _get_speaking_system_prompt(
        self,
        name: str,
        era: str,
        bio: str,
        background: str,
        language_style: Dict,
        temporal_constraints: Dict,
        viewpoints: Dict,
        character_limit: int
    ) -> str:
        """构建角色发言的 system prompt"""

        can_discuss = temporal_constraints.get('can_discuss', [])
        cannot_discuss = temporal_constraints.get('cannot_discuss', [])
        knowledge_cutoff = temporal_constraints.get('knowledge_cutoff', '')

        tone = language_style.get('tone', '中性')
        catchphrases = language_style.get('catchphrases', [])
        speaking_habits = language_style.get('speaking_habits', '')

        viewpoints_str = "\n".join([f"- {k}: {v}" for k, v in viewpoints.items()])

        return f"""你扮演历史人物：{name}

【基本信息】
- 时代：{era}
- 简介：{bio}
- 背景：{background}

【核心观点】
{viewpoints_str or '（暂无详细观点）'}

【语言风格】
- 语气：{tone}
- 常用表达：{', '.join(catchphrases) if catchphrases else '一般表达'}
- 说话习惯：{speaking_habits}

【时代约束 - 非常重要】
- 知识截止于：{knowledge_cutoff}
- 可以讨论：{', '.join(can_discuss) if can_discuss else '一般话题'}
- 不能讨论：{', '.join(cannot_discuss) if cannot_discuss else '无特别限制'}
- 严禁提及尚未发生的历史事件、人物或概念
- 严禁使用近现代才出现的词汇

【发言规则】
1. 严格控制在 {character_limit} 字以内
2. 保持角色设定一致，用角色的视角和语气说话
3. 积极回应其他角色的观点
4. 用 @主持人 结束发言，表示发言权交回
5. 如需引用，可以用简短的名言警句

请开始扮演这个角色发言。"""

    def _build_speaking_prompt(
        self,
        topic: str,
        conversation_history: str,
        character_limit: int
    ) -> str:
        """构建发言 prompt"""
        history = conversation_history if conversation_history else "（讨论刚开始）"

        # 提取最后一位发言者及其内容，用于要求角色承接
        lines = history.split('\n')
        last_speaker_content = ""
        if len(lines) >= 2:
            # 最后一行通常是主持人的邀请，前一行是最后一位角色发言
            for line in reversed(lines[:-1]):
                if '主持人' not in line:
                    last_speaker_content = line
                    break

        承接_requirement = ""
        if last_speaker_content:
            # 找出上一位发言者名字
            last_speaker_name = last_speaker_content.split('：')[0] if '：' in last_speaker_content else "前一位角色"
            承接_requirement = f"""

【重要 - 承接要求】
上一位发言者是「{last_speaker_name}」。你的发言必须：
1. 直接回应或反驳 {last_speaker_name} 的观点
2. 可以引用对方说过的话作为回应起点
3. 体现不同角色之间的观点碰撞和对话感
4. 不要泛泛而谈，要具体回应"""

        return f"""话题：{topic}

对话历史：
{history}
{承接_requirement}

请以角色身份，针对以上对话历史和话题发表看法。
要求：
- 控制在 {character_limit} 字以内
- 积极回应之前的讨论内容，尤其要承接上一位发言者的具体观点
- 体现角色的独特视角和观点碰撞
- 不要重复之前说过的内容"""

    def configure_character(
        self,
        character: Dict,
        topic: str,
        era: str
    ) -> Dict:
        """
        为角色生成完整配置

        Args:
            character: 角色基本信息（包含 name）
            topic: 讨论话题
            era: 角色所在时代

        Returns:
            角色的完整配置字典
        """
        name = character.get('name', '')

        # 0. 检查是否有离线基础设定
        base_profile = self._profile_loader.get_profile(name)
        has_offline_profile = base_profile is not None

        # 1. 获取基础信息（优先使用离线设定）
        if has_offline_profile:
            basic_info = {
                'bio': base_profile.get('core_persona', '').split('。')[0] + '。',
                'background': base_profile.get('core_persona', ''),
                'viewpoints': {},  # 话题相关，从缓存或生成
                'temporal_constraints': self._parse_temporal_constraints(base_profile),
            }
            language_style = self._parse_language_style(base_profile)
        else:
            basic_info = self._generate_basic_info(name, era, topic)
            language_style = self._generate_language_style(name, era, basic_info.get('background', ''))

        # 2. 检查话题设定缓存（失败不影响配置）
        topic_cached = False
        viewpoints = {}
        articles = []
        temporal_constraints = {}

        try:
            cached_topic = self._topic_cache.get(name, topic)
            topic_cached = cached_topic is not None
            if cached_topic:
                # 使用缓存的话题设定
                viewpoints = cached_topic.viewpoints or basic_info.get('viewpoints', {})
                articles = cached_topic.representative_articles or []
                if cached_topic.language_style:
                    language_style = cached_topic.language_style
                temporal_constraints = cached_topic.temporal_constraints or basic_info.get('temporal_constraints', {})
                logger.info(f"Using cached topic profile for {name}:{topic}")
        except Exception as cache_err:
            logger.warning(f"Cache read failed for {name}:{topic}, generating fresh: {cache_err}")
            cached_topic = None

        if not topic_cached:
            # 缓存未命中，生成话题相关设定
            viewpoints, articles, topic_temporal = self._generate_topic_profile(name, era, topic, basic_info.get('background', ''))

            if topic_temporal:
                temporal_constraints = topic_temporal
            if viewpoints:
                basic_info['viewpoints'] = viewpoints

            # 更新缓存（失败不影响配置结果）
            try:
                self._topic_cache.set(
                    character_name=name,
                    topic=topic,
                    viewpoints=viewpoints,
                    representative_articles=articles,
                    language_style=language_style if has_offline_profile else None,
                    temporal_constraints=temporal_constraints
                )
                logger.info(f"Generated and cached topic profile for {name}:{topic}")
            except Exception as cache_err:
                logger.warning(f"Cache write failed for {name}:{topic}, continuing without cache: {cache_err}")

        return {
            'name': name,
            'era': era,
            'bio': basic_info.get('bio', ''),
            'background': basic_info.get('background', ''),
            'major_works': basic_info.get('major_works', []),
            'viewpoints': viewpoints or basic_info.get('viewpoints', {}),
            'temporal_constraints': temporal_constraints or basic_info.get('temporal_constraints', {}),
            'language_style': language_style,
            'representative_articles': articles,
            'has_offline_profile': has_offline_profile,
            '_cached': topic_cached,
        }

    def _parse_temporal_constraints(self, base_profile: dict) -> Dict:
        """从离线基础设定解析时代边界"""
        kb = base_profile.get('knowledge_boundary', {})
        return {
            'can_discuss': kb.get('can_discuss', []),
            'cannot_discuss': kb.get('cannot_discuss', []),
            'knowledge_cutoff': kb.get('knowledge_cutoff', ''),
        }

    def _parse_language_style(self, base_profile: dict) -> Dict:
        """从离线基础设定解析语言风格"""
        ls = base_profile.get('language_style', {})
        return {
            'tone': ls.get('tone', '中性'),
            'catchphrases': ls.get('catchphrases', []),
            'speaking_habits': ls.get('speaking_habits', ''),
        }

    def _generate_topic_profile(self, name: str, era: str, topic: str, background: str) -> tuple:
        """
        生成话题相关设定

        Returns:
            (viewpoints, articles, temporal_constraints)
        """
        # 并行生成观点和文章
        import concurrent.futures

        viewpoints = {}
        articles = []
        temporal_constraints = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            vp_future = executor.submit(self._generate_viewpoints_only, name, era, topic, background)
            articles_future = executor.submit(self._generate_representative_articles, name, era, topic)

            try:
                vp_result = vp_future.result(timeout=60)
                if vp_result:
                    viewpoints = vp_result.get('viewpoints', {})
                    temporal_constraints = vp_result.get('temporal_constraints', {})
            except Exception as e:
                logger.error(f"Failed to generate viewpoints: {e}")

            try:
                articles_result = articles_future.result(timeout=60)
                if articles_result:
                    articles = articles_result
            except Exception as e:
                logger.error(f"Failed to generate articles: {e}")

        return viewpoints, articles, temporal_constraints

    def _generate_viewpoints_only(self, name: str, era: str, topic: str, background: str) -> Dict:
        """仅生成观点（不生成语言风格，因为离线设定已有）"""
        prompt = f"""为以下历史人物针对特定话题生成核心观点：

人物：{name}
时代：{era}
背景：{background}
讨论话题：{topic}

请生成该人物针对此话题的 3-5 个核心观点，每个观点格式为"维度名: 具体观点"。

请用 JSON 格式返回，包含字段：viewpoints（dict）, temporal_constraints（时代认知边界）
temporal_constraints包含：can_discuss, cannot_discuss, knowledge_cutoff"""

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self._get_base_system_prompt(name, era),
            json_mode=True,
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse viewpoints for {name}")
            return {}

    def _generate_basic_info(self, name: str, era: str, topic: str) -> Dict:
        """生成角色基础信息"""
        prompt = f"""为以下历史人物生成适合圆桌讨论的背景信息：

人物：{name}
时代：{era}
讨论话题：{topic}

请生成：
1. bio：一句话简介（50字以内）
2. background：详细背景介绍（200字以内），包括：
   - 人物生平概要
   - 与讨论话题相关的经历
   - 在该话题上的立场基础
3. major_works：2-3 项主要作品/成就
4. viewpoints：针对话题的 3-5 个核心观点维度
5. temporal_constraints：时代认知边界
   - can_discuss：该人物可能讨论的话题/概念（其所在时代已知的事物）
   - cannot_discuss：该人物不可能知道的事物（如：后世朝代名称、近现代概念）
   - knowledge_cutoff：该人物知识的最终时间点

请用 JSON 格式返回，包含字段：bio, background, major_works, viewpoints, temporal_constraints
其中 temporal_constraints 包含：can_discuss, cannot_discuss, knowledge_cutoff"""

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self._get_base_system_prompt(name, era),
            json_mode=True,
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse basic info for {name}")
            return {
                'bio': f'{name}，{era}时期历史人物',
                'background': '',
                'major_works': [],
                'viewpoints': {},
                'temporal_constraints': {
                    'can_discuss': [],
                    'cannot_discuss': [],
                    'knowledge_cutoff': ''
                }
            }

    def _generate_language_style(self, name: str, era: str, background: str) -> Dict:
        """生成角色语言风格"""
        prompt = f"""为以下历史人物生成语言风格描述：

人物：{name}
时代：{era}
背景：{background}

请生成该人物在圆桌讨论中的语言风格：
1. tone：整体语气特点（如：豪迈直率、温文尔雅、犀利冷峻）
2. catchphrases：3-5 个该人物可能会用的经典表达
3. speaking_habits：说话习惯（如：善用反问、惯用排比、言简意赅）

请用 JSON 格式返回，包含字段：tone, catchphrases, speaking_habits"""

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self._get_base_system_prompt(name, era),
            json_mode=True,
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse language style for {name}")
            return {
                'tone': '中性',
                'catchphrases': [],
                'speaking_habits': ''
            }

    def _generate_representative_articles(
        self,
        name: str,
        era: str,
        topic: str
    ) -> List[Dict]:
        """生成代表文章"""
        prompt = f"""为该人物推荐 1-2 篇与讨论话题相关的代表文章/著作片段：

人物：{name}
时代：{era}
讨论话题：{topic}

规则：
1. 优先选择该人物本人的著作
2. 如无本人著作，选择描述该人物的重要文献
3. 如原文超过 200 字，请进行摘要压缩，保留核心观点
4. 需要标注文章来源（source）

请用 JSON 数组格式返回：
[
  {{
    "title": "文章/著作标题",
    "source": "《作品名》作者（可选）",
    "content": "原文或摘要（200字以内）",
    "reason": "为什么推荐这篇"
  }}
]"""

        response = self.client.complete(
            prompt=prompt,
            system_prompt=self._get_base_system_prompt(name, era),
            json_mode=True,
        )

        try:
            result = json.loads(response)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and 'articles' in result:
                return result['articles']
            else:
                return []
        except json.JSONDecodeError:
            logger.error(f"Failed to parse representative articles for {name}")
            return []

    def _get_base_system_prompt(self, name: str, era: str) -> str:
        """获取基础 system prompt，包含时代约束"""
        return f"""你是一个专业的历史人物模拟专家，负责为圆桌讨论生成角色配置。

【重要时代约束】
角色：{name}
时代：{era}
在发言时，该角色：
- 只能提及其生前已知的事物、历史事件、人物
- 不得提及尚未发生的历史
- 不得使用近现代才出现的概念和词汇
- 如果被问及相关话题，应表示"不知"或"未曾听闻"

请严格按照角色设定生成内容。"""