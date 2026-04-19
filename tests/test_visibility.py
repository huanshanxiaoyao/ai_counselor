import pytest
from django.contrib.auth import get_user_model
from django.test import Client
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


@pytest.mark.django_db
def test_history_hides_others_private():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    mine_public = Discussion.objects.create(topic='mp', owner=alice, visibility='public')
    mine_private = Discussion.objects.create(topic='mpr', owner=alice, visibility='private')
    bob_public = Discussion.objects.create(topic='bp', owner=bob, visibility='public')
    bob_private = Discussion.objects.create(topic='bpr', owner=bob, visibility='private')
    legacy = Discussion.objects.create(topic='leg')  # owner=None
    client = Client()
    client.force_login(alice)
    resp = client.get('/roundtable/api/history/')
    assert resp.status_code == 200
    ids = {item['id'] for item in resp.json()['history']}
    assert mine_public.id in ids
    assert mine_private.id in ids
    assert bob_public.id in ids
    assert legacy.id in ids  # public (default) so visible
    assert bob_private.id not in ids


@pytest.mark.django_db
def test_history_marks_is_mine_and_visibility():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    mine = Discussion.objects.create(topic='m', owner=alice, visibility='private')
    bobs = Discussion.objects.create(topic='b', owner=bob, visibility='public')
    client = Client()
    client.force_login(alice)
    resp = client.get('/roundtable/api/history/')
    by_id = {item['id']: item for item in resp.json()['history']}
    assert by_id[mine.id]['is_mine'] is True
    assert by_id[mine.id]['visibility'] == 'private'
    assert by_id[bobs.id]['is_mine'] is False
    assert by_id[bobs.id]['visibility'] == 'public'
