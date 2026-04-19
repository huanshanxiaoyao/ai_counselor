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
