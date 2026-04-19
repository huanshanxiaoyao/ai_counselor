import pytest
from django.contrib.auth import get_user_model
from backend.roundtable.models import Discussion


@pytest.mark.django_db
def test_discussion_has_owner_and_visibility_defaults():
    User = get_user_model()
    user = User.objects.create_user(username='u1', password='p')
    d = Discussion.objects.create(topic='t', owner=user)
    assert d.owner_id == user.id
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_discussion_owner_nullable_for_legacy_records():
    d = Discussion.objects.create(topic='legacy')
    assert d.owner is None
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_discussion_visibility_choices():
    d = Discussion.objects.create(topic='t', visibility='private')
    assert d.visibility == 'private'


def _minimal_chars():
    # DiscussionStartView requires >= 3 characters
    return [
        {'name': f'c{i}', 'era': '', 'viewpoints': {}, 'language_style': {}, 'temporal_constraints': {}}
        for i in range(3)
    ]


@pytest.mark.django_db
def test_start_writes_owner_and_default_visibility_public():
    from django.test import Client
    User = get_user_model()
    user = User.objects.create_user(username='sv_u1', password='p')
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/roundtable/api/start/',
        data=__import__('json').dumps({
            'topic': 't', 'characters': _minimal_chars(),
            'user_role': 'observer', 'max_rounds': 5,
        }),
        content_type='application/json',
    )
    assert resp.status_code == 200, resp.content
    d = Discussion.objects.get(id=resp.json()['discussion_id'])
    assert d.owner_id == user.id
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_start_accepts_visibility_private():
    from django.test import Client
    User = get_user_model()
    user = User.objects.create_user(username='sv_u2', password='p')
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/roundtable/api/start/',
        data=__import__('json').dumps({
            'topic': 't', 'characters': _minimal_chars(),
            'user_role': 'observer', 'max_rounds': 5,
            'visibility': 'private',
        }),
        content_type='application/json',
    )
    assert resp.status_code == 200, resp.content
    d = Discussion.objects.get(id=resp.json()['discussion_id'])
    assert d.visibility == 'private'


@pytest.mark.django_db
def test_start_rejects_invalid_visibility():
    from django.test import Client
    User = get_user_model()
    user = User.objects.create_user(username='sv_u3', password='p')
    client = Client()
    client.force_login(user)
    resp = client.post(
        '/roundtable/api/start/',
        data=__import__('json').dumps({
            'topic': 't', 'characters': _minimal_chars(),
            'user_role': 'observer', 'max_rounds': 5,
            'visibility': 'secret',
        }),
        content_type='application/json',
    )
    assert resp.status_code == 400
