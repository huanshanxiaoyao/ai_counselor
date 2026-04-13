"""
Tests for Roundtable agents.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestDirectorAgent:
    """Tests for DirectorAgent"""

    @pytest.fixture
    def director_agent(self):
        """Create DirectorAgent instance with mocked LLM client"""
        with patch('backend.roundtable.services.director.LLMClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = '''[
                {"name": "孔子", "era": "春秋", "reason": "儒家思想代表"},
                {"name": "韩非子", "era": "战国", "reason": "法家思想代表"},
                {"name": "秦始皇", "era": "秦", "reason": "统一六国"}
            ]'''
            mock_client.return_value = mock_instance

            from backend.roundtable.services.director import DirectorAgent
            agent = DirectorAgent()
            return agent

    def test_suggest_characters_returns_list(self, director_agent):
        """Test that suggest_characters returns a list of characters"""
        result = director_agent.suggest_characters("项羽该不该渡江", count=20)

        assert isinstance(result, list)
        assert len(result) > 0

    def test_suggest_characters_has_required_fields(self, director_agent):
        """Test that each character has required fields"""
        result = director_agent.suggest_characters("项羽该不该渡江", count=20)

        for char in result:
            assert 'name' in char
            assert 'era' in char
            assert 'reason' in char

    def test_analyze_topic_returns_dict(self, director_agent):
        """Test that analyze_topic returns a dictionary"""
        with patch.object(director_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = '''{
                "core_issue": "生存还是死亡",
                "recommended_roles": ["哲学家", "军事家"],
                "discussion_angles": ["个人价值", "历史意义"]
            }'''

            result = director_agent.analyze_topic("项羽该不该渡江")

            assert isinstance(result, dict)
            assert 'core_issue' in result


class TestCharacterAgent:
    """Tests for CharacterAgent"""

    @pytest.fixture
    def character_agent(self):
        """Create CharacterAgent instance with mocked LLM client"""
        with patch('backend.roundtable.services.character.LLMClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = '''{
                "bio": "西楚霸王",
                "background": "灭秦主力，兵败乌江",
                "major_works": ["《垓下歌》"],
                "viewpoints": {"霸业": "以力经营天下"},
                "temporal_constraints": {
                    "can_discuss": ["楚汉争霸"],
                    "cannot_discuss": ["清朝"],
                    "knowledge_cutoff": "公元前202年"
                }
            }'''
            mock_client.return_value = mock_instance

            from backend.roundtable.services.character import CharacterAgent
            agent = CharacterAgent()
            return agent

    def test_configure_character_returns_dict(self, character_agent):
        """Test that configure_character returns a dictionary"""
        character = {'name': '项羽', 'era': '秦末'}
        result = character_agent.configure_character(character, "项羽该不该渡江", "秦末")

        assert isinstance(result, dict)
        assert 'name' in result
        assert result['name'] == '项羽'

    def test_configure_character_has_required_fields(self, character_agent):
        """Test that configured character has all required fields"""
        character = {'name': '项羽', 'era': '秦末'}
        result = character_agent.configure_character(character, "项羽该不该渡江", "秦末")

        assert 'bio' in result
        assert 'background' in result
        assert 'major_works' in result
        assert 'viewpoints' in result
        assert 'temporal_constraints' in result
        assert 'language_style' in result
        assert 'representative_articles' in result

    def test_generate_speech_returns_string(self, character_agent):
        """Test that generate_speech returns a string"""
        config = {
            'name': '项羽',
            'era': '秦末',
            'bio': '西楚霸王',
            'background': '灭秦主力',
            'language_style': {'tone': '豪迈', 'catchphrases': [], 'speaking_habits': ''},
            'temporal_constraints': {'can_discuss': [], 'cannot_discuss': [], 'knowledge_cutoff': ''},
            'viewpoints': {}
        }

        with patch.object(character_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = "吾意已决，绝不渡江！@主持人"
            result = character_agent.generate_speech(config, "项羽该不该渡江", "")

            assert isinstance(result, str)
            assert len(result) > 0


class TestModeratorAgent:
    """Tests for ModeratorAgent"""

    @pytest.fixture
    def moderator_agent(self):
        """Create ModeratorAgent instance with mocked LLM client"""
        with patch('backend.roundtable.services.moderator.LLMClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = "各位嘉宾好，欢迎参加讨论。@秦始皇 请发言"
            mock_client.return_value = mock_instance

            from backend.roundtable.services.moderator import ModeratorAgent
            agent = ModeratorAgent()
            return agent

    def test_generate_opening_returns_string(self, moderator_agent):
        """Test that generate_opening returns a string"""
        characters = [
            {'name': '项羽', 'era': '秦末', 'bio': '西楚霸王'},
            {'name': '秦始皇', 'era': '秦', 'bio': '千古一帝'}
        ]

        with patch.object(moderator_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = "欢迎各位，今天我们来讨论..."
            result = moderator_agent.generate_opening("项羽该不该渡江", characters, 'moderator')

            assert isinstance(result, str)
            assert len(result) > 0

    def test_generate_invitation_returns_string(self, moderator_agent):
        """Test that generate_invitation returns a string"""
        with patch.object(moderator_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = "@项羽 请发表您的看法"
            result = moderator_agent.generate_invitation("项羽", "项羽该不该渡江", "")

            assert isinstance(result, str)
            assert '项羽' in result

    def test_should_continue_returns_bool(self, moderator_agent):
        """Test that should_continue returns a boolean"""
        result = moderator_agent.should_continue(5, 100, ["msg1", "msg2", "msg3"])
        assert isinstance(result, bool)

        result = moderator_agent.should_continue(100, 100, ["msg1"])
        assert result == False

    def test_generate_summary_returns_string(self, moderator_agent):
        """Test that generate_summary returns a string"""
        with patch.object(moderator_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = "【主持人总结】目前讨论了..."
            result = moderator_agent.generate_summary("项羽该不该渡江", ["msg1", "msg2"])

            assert isinstance(result, str)

    def test_generate_closing_returns_string(self, moderator_agent):
        """Test that generate_closing returns a string"""
        characters = [{'name': '项羽'}, {'name': '秦始皇'}]

        with patch.object(moderator_agent.client, 'complete') as mock_complete:
            mock_complete.return_value = "感谢各位参与讨论"
            result = moderator_agent.generate_closing("项羽该不该渡江", characters, "讨论热烈")

            assert isinstance(result, str)
            assert len(result) > 0