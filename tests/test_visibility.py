import pytest
from unittest.mock import patch
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
def test_start_rejects_anonymous_private_visibility():
    import json as _json
    client = Client()
    payload = {
        'topic': 't',
        'characters': _minimal_chars(),
        'user_role': 'observer',
        'max_rounds': 5,
        'visibility': 'private',
    }
    resp = client.post(
        '/roundtable/api/start/',
        data=_json.dumps(payload),
        content_type='application/json',
    )
    assert resp.status_code == 401
    data = resp.json()
    assert 'login_url' in data
    assert Discussion.objects.count() == 0


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


@pytest.mark.django_db
def test_detail_view_downgrades_non_owner_to_observer():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_dv1', password='p')
    bob = User.objects.create_user(username='bob_dv1', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(bob)
    resp = client.get(f'/roundtable/d/{d.id}/')
    assert resp.status_code == 200
    assert resp.context['user_role'] == 'observer'


@pytest.mark.django_db
def test_detail_view_blocks_private_discussion_for_non_owner():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_dv_private1', password='p')
    bob = User.objects.create_user(username='bob_dv_private1', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                  visibility='private', status='active')
    client = Client()
    client.force_login(bob)
    resp = client.get(f'/roundtable/d/{d.id}/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_view_blocks_private_discussion_for_anonymous():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_dv_private2', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                  visibility='private', status='active')
    client = Client()
    resp = client.get(f'/roundtable/d/{d.id}/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_view_keeps_owner_role():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_dv2', password='p')
    d = Discussion.objects.create(topic='t', user_role='participant', owner=alice,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(alice)
    resp = client.get(f'/roundtable/d/{d.id}/')
    assert resp.status_code == 200
    assert resp.context['user_role'] == 'participant'


@pytest.mark.django_db
def test_detail_view_legacy_no_owner_uses_original_role():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_dv3', password='p')
    d = Discussion.objects.create(topic='t', user_role='host', owner=None,
                                  visibility='public', status='active')
    client = Client()
    client.force_login(alice)
    resp = client.get(f'/roundtable/d/{d.id}/')
    assert resp.status_code == 200
    assert resp.context['user_role'] == 'host'


def _restart_chars(d):
    from backend.roundtable.models import Character
    Character.objects.create(
        discussion=d, name='c1', viewpoints={}, language_style={}, temporal_constraints={},
    )


@pytest.mark.django_db
def test_restart_forces_participant_and_sets_owner():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    bob = User.objects.create_user(username='bob', password='p')
    original = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                         visibility='public', status='finished')
    _restart_chars(original)
    client = Client()
    client.force_login(bob)
    with patch('backend.roundtable.services.host_agent.HostAgent.generate_opening',
               return_value='欢迎参加讨论。'), \
         patch('backend.roundtable.services.auto_continue.ensure_auto_continue_running'):
        resp = client.post(
            f'/roundtable/api/restart/{original.id}/',
            data='{"visibility":"private"}',
            content_type='application/json',
        )
    assert resp.status_code == 200, resp.content
    new_id = resp.json()['new_discussion_id']
    new_d = Discussion.objects.get(id=new_id)
    assert new_d.user_role == 'participant'
    assert new_d.owner_id == bob.id
    assert new_d.visibility == 'private'


@pytest.mark.django_db
def test_restart_default_visibility_public_when_body_empty():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    original = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                         visibility='private', status='finished')
    _restart_chars(original)
    client = Client()
    client.force_login(alice)
    with patch('backend.roundtable.services.host_agent.HostAgent.generate_opening',
               return_value='欢迎参加讨论。'), \
         patch('backend.roundtable.services.auto_continue.ensure_auto_continue_running'):
        resp = client.post(
            f'/roundtable/api/restart/{original.id}/',
            data='',
            content_type='application/json',
        )
    assert resp.status_code == 200, resp.content
    new_id = resp.json()['new_discussion_id']
    assert Discussion.objects.get(id=new_id).visibility == 'public'


@pytest.mark.django_db
def test_restart_rejects_invalid_visibility():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    original = Discussion.objects.create(topic='t', owner=alice, status='finished')
    _restart_chars(original)
    client = Client()
    client.force_login(alice)
    resp = client.post(
        f'/roundtable/api/restart/{original.id}/',
        data='{"visibility":"secret"}',
        content_type='application/json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_restart_rejects_anonymous_private_visibility():
    User = get_user_model()
    alice = User.objects.create_user(username='alice_restart_private', password='p')
    original = Discussion.objects.create(topic='t', owner=alice, status='finished')
    _restart_chars(original)
    client = Client()
    resp = client.post(
        f'/roundtable/api/restart/{original.id}/',
        data='{"visibility":"private"}',
        content_type='application/json',
    )
    assert resp.status_code == 401
    data = resp.json()
    assert 'login_url' in data
    assert Discussion.objects.filter(topic='t').count() == 1


@pytest.mark.django_db
def test_start_allows_anonymous_user_owner_none():
    """匿名访问者创建讨论时 owner 应为 None，而不是报 500。"""
    import json as _json
    client = Client()
    payload = {
        'topic': 't',
        'characters': [
            {'name': f'c{i}', 'era': '', 'viewpoints': {}, 'language_style': {},
             'temporal_constraints': {}}
            for i in range(3)
        ],
        'user_role': 'observer',
        'max_rounds': 5,
    }
    resp = client.post(
        '/roundtable/api/start/', data=_json.dumps(payload),
        content_type='application/json',
    )
    assert resp.status_code == 200, resp.content
    d = Discussion.objects.get(id=resp.json()['discussion_id'])
    assert d.owner is None
    assert d.visibility == 'public'


@pytest.mark.django_db
def test_history_anonymous_sees_only_public():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    pub = Discussion.objects.create(topic='pub', owner=alice, visibility='public')
    priv = Discussion.objects.create(topic='priv', owner=alice, visibility='private')
    legacy = Discussion.objects.create(topic='leg')
    client = Client()
    resp = client.get('/roundtable/api/history/')
    assert resp.status_code == 200
    items = resp.json()['history']
    ids = {i['id'] for i in items}
    assert pub.id in ids
    assert legacy.id in ids
    assert priv.id not in ids
    for it in items:
        assert it['is_mine'] is False


@pytest.mark.django_db
def test_restart_allows_anonymous_user_owner_none():
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='p')
    original = Discussion.objects.create(topic='t', user_role='host', owner=alice,
                                         visibility='public', status='finished')
    _restart_chars(original)
    client = Client()
    with patch(
        'backend.roundtable.services.host_agent.HostAgent.generate_opening',
        return_value='opening',
    ), patch(
        'backend.roundtable.services.auto_continue.ensure_auto_continue_running',
        return_value=True,
    ):
        resp = client.post(
            f'/roundtable/api/restart/{original.id}/',
            data='{"visibility":"public"}',
            content_type='application/json',
        )
    assert resp.status_code == 200, resp.content
    new_id = resp.json()['new_discussion_id']
    assert Discussion.objects.get(id=new_id).owner is None
