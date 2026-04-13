"""
Tests for Roundtable API endpoints.
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from django.test import Client


@pytest.fixture
def mock_director_suggest():
    """Mock DirectorAgent.suggest_characters"""
    with patch('backend.roundtable.services.director.DirectorAgent.suggest_characters') as mock:
        mock.return_value = [
            {'name': '孔子', 'era': '春秋', 'reason': '儒家思想代表'},
            {'name': '韩非子', 'era': '战国', 'reason': '法家思想代表'},
            {'name': '秦始皇', 'era': '秦', 'reason': '统一六国'},
        ]
        yield mock


@pytest.fixture
def mock_moderator_opening():
    """Mock ModeratorAgent.generate_opening"""
    with patch('backend.roundtable.services.moderator.ModeratorAgent.generate_opening') as mock:
        mock.return_value = "各位嘉宾好，欢迎参加讨论。"
        yield mock


class TestSuggestionsAPI:
    """Tests for /roundtable/api/suggestions/ endpoint"""

    def test_suggestions_returns_200(self, mock_director_suggest):
        """Test that suggestions endpoint returns 200"""
        client = Client()
        response = client.post(
            '/roundtable/api/suggestions/',
            data=json.dumps({'topic': '项羽该不该渡江'}),
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_suggestions_returns_characters(self, mock_director_suggest):
        """Test that suggestions returns character list"""
        client = Client()
        response = client.post(
            '/roundtable/api/suggestions/',
            data=json.dumps({'topic': '项羽该不该渡江'}),
            content_type='application/json'
        )
        data = json.loads(response.content)
        assert 'characters' in data
        assert len(data['characters']) > 0

    def test_suggestions_requires_topic(self):
        """Test that suggestions requires topic parameter"""
        client = Client()
        response = client.post(
            '/roundtable/api/suggestions/',
            data=json.dumps({}),
            content_type='application/json'
        )
        assert response.status_code == 400


class TestConfigureAPI:
    """Tests for /roundtable/api/configure/ endpoint"""

    def test_configure_returns_200(self):
        """Test that configure endpoint returns 200"""
        with patch('backend.roundtable.services.character.CharacterAgent.configure_character') as mock_config:
            mock_config.return_value = {
                'name': '项羽',
                'era': '秦末',
                'bio': '西楚霸王',
                'background': '灭秦主力，兵败乌江',
                'major_works': ['《垓下歌》'],
                'viewpoints': {'霸业': '以力经营天下'},
                'temporal_constraints': {
                    'can_discuss': ['楚汉争霸'],
                    'cannot_discuss': ['清朝'],
                    'knowledge_cutoff': '公元前202年'
                },
                'language_style': {'tone': '豪迈', 'catchphrases': [], 'speaking_habits': ''},
                'representative_articles': []
            }

            client = Client()
            response = client.post(
                '/roundtable/api/configure/',
                data=json.dumps({
                    'topic': '项羽该不该渡江',
                    'characters': [
                        {'name': '项羽', 'era': '秦末'},
                        {'name': '秦始皇', 'era': '秦'},
                        {'name': '韩信', 'era': '秦末'}
                    ]
                }),
                content_type='application/json'
            )
            assert response.status_code == 200

    def test_configure_returns_configured_characters(self):
        """Test that configure returns characters with full config"""
        with patch('backend.roundtable.services.character.CharacterAgent.configure_character') as mock_config:
            mock_config.return_value = {
                'name': '项羽',
                'era': '秦末',
                'bio': '西楚霸王',
                'background': '灭秦主力',
                'major_works': [],
                'viewpoints': {},
                'temporal_constraints': {'can_discuss': [], 'cannot_discuss': [], 'knowledge_cutoff': ''},
                'language_style': {'tone': '', 'catchphrases': [], 'speaking_habits': ''},
                'representative_articles': []
            }

            client = Client()
            response = client.post(
                '/roundtable/api/configure/',
                data=json.dumps({
                    'topic': '项羽该不该渡江',
                    'characters': [
                        {'name': '项羽', 'era': '秦末'},
                        {'name': '秦始皇', 'era': '秦'},
                        {'name': '韩信', 'era': '秦末'}
                    ]
                }),
                content_type='application/json'
            )
            data = json.loads(response.content)
            assert 'characters' in data
            assert len(data['characters']) == 3
            assert data['characters'][0]['bio'] == '西楚霸王'


class TestStartAPI:
    """Tests for /roundtable/api/start/ endpoint"""

    @pytest.mark.skip(reason="Requires database access - needs integration test")
    def test_start_returns_200(self, mock_moderator_opening):
        """Test that start endpoint returns 200"""
        pass

    @pytest.mark.skip(reason="Requires database access - needs integration test")
    def test_start_returns_discussion_id(self, mock_moderator_opening):
        """Test that start returns discussion_id"""
        pass


class TestDiscussionPage:
    """Tests for discussion page rendering"""

    def test_discussion_page_returns_200(self):
        """Test that discussion page returns 200"""
        with patch('backend.roundtable.models.Discussion.objects.get') as mock_get:
            mock_discussion = MagicMock()
            mock_discussion.id = 1
            mock_discussion.topic = '项羽该不该渡江'
            mock_discussion.status = 'active'
            mock_discussion.current_round = 1
            mock_discussion.max_rounds = 10
            mock_discussion.user_role = 'observer'
            mock_get.return_value = mock_discussion

            with patch('backend.roundtable.models.Message.objects.filter') as mock_messages:
                mock_messages.return_value.order_by = MagicMock(return_value=[])

                with patch('backend.roundtable.models.Character.objects.filter') as mock_chars:
                    mock_chars.return_value = [
                        MagicMock(id=1, name='项羽', era='秦末', message_count=0)
                    ]

                    client = Client()
                    response = client.get('/roundtable/d/1/')
                    assert response.status_code == 200

    def test_discussion_page_contains_topic(self):
        """Test that discussion page contains topic"""
        with patch('backend.roundtable.models.Discussion.objects.get') as mock_get:
            mock_discussion = MagicMock()
            mock_discussion.id = 1
            mock_discussion.topic = '项羽该不该渡江'
            mock_discussion.status = 'active'
            mock_discussion.current_round = 1
            mock_discussion.max_rounds = 10
            mock_discussion.user_role = 'observer'
            mock_get.return_value = mock_discussion

            with patch('backend.roundtable.models.Message.objects.filter') as mock_messages:
                mock_messages.return_value.order_by = MagicMock(return_value=[])

                with patch('backend.roundtable.models.Character.objects.filter') as mock_chars:
                    mock_chars.return_value = [
                        MagicMock(id=1, name='项羽', era='秦末', message_count=0)
                    ]

                    client = Client()
                    response = client.get('/roundtable/d/1/')
                    content = response.content.decode('utf-8')
                    assert '项羽该不该渡江' in content


class TestSetupPage:
    """Tests for setup page"""

    def test_setup_page_returns_200_with_valid_params(self):
        """Test that setup page returns 200 with valid params"""
        with patch('backend.roundtable.services.director.DirectorAgent.suggest_characters') as mock_suggest:
            mock_suggest.return_value = [
                {'name': '孔子', 'era': '春秋', 'reason': '儒家思想代表'}
            ]

            client = Client()
            response = client.get('/roundtable/setup/', {'topic': '项羽该不该渡江', 'characters': json.dumps([{'name': '项羽', 'era': '秦末'}])})
            assert response.status_code == 200

    def test_setup_page_redirects_without_params(self):
        """Test that setup page redirects without params"""
        client = Client()
        response = client.get('/roundtable/setup/')
        assert response.status_code == 302


class TestIndexPage:
    """Tests for index page"""

    def test_index_page_returns_200(self):
        """Test that index page returns 200"""
        client = Client()
        response = client.get('/roundtable/')
        assert response.status_code == 200

    def test_index_page_contains_form(self):
        """Test that index page contains topic input form"""
        client = Client()
        response = client.get('/roundtable/')
        content = response.content.decode('utf-8')
        assert 'topic' in content.lower() or '话题' in content