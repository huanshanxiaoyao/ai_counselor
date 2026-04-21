import json
from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_suggestions_fallback_when_llm_unavailable():
    client = Client()
    with patch(
        'backend.roundtable.services.director.DirectorAgent.suggest_characters',
        side_effect=Exception('llm down'),
    ):
        resp = client.post(
            '/roundtable/api/suggestions/',
            data=json.dumps({'topic': '人工智能与教育'}),
            content_type='application/json',
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data['fallback'] is True
    assert data['count'] >= 3
    assert len(data['characters']) >= 3
