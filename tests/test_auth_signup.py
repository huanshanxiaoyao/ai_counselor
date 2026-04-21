import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_signup_page_returns_200_for_anonymous():
    client = Client()
    resp = client.get('/accounts/signup/')
    assert resp.status_code == 200
    assert '注册' in resp.content.decode('utf-8')


@pytest.mark.django_db
def test_signup_success_auto_login_and_redirect_next():
    client = Client()
    payload = {
        'username': 'new_user_1',
        'password1': 'StrongPass12345',
        'password2': 'StrongPass12345',
        'next': '/roundtable/',
    }
    resp = client.post('/accounts/signup/', data=payload)
    assert resp.status_code == 302
    assert resp['Location'] == '/roundtable/'

    User = get_user_model()
    assert User.objects.filter(username='new_user_1').exists()
    assert '_auth_user_id' in client.session


@pytest.mark.django_db
def test_signup_rejects_duplicate_username():
    User = get_user_model()
    User.objects.create_user(username='dup_user', password='StrongPass12345')
    client = Client()
    payload = {
        'username': 'dup_user',
        'password1': 'StrongPass12345',
        'password2': 'StrongPass12345',
    }
    resp = client.post('/accounts/signup/', data=payload)
    assert resp.status_code == 200
    content = resp.content.decode('utf-8')
    assert '已存在' in content or 'already exists' in content


@pytest.mark.django_db
def test_signup_rejects_password_mismatch():
    client = Client()
    payload = {
        'username': 'new_user_2',
        'password1': 'StrongPass12345',
        'password2': 'StrongPass99999',
    }
    resp = client.post('/accounts/signup/', data=payload)
    assert resp.status_code == 200
    content = resp.content.decode('utf-8')
    assert '不一致' in content or 'didn' in content.lower()


@pytest.mark.django_db
def test_signup_redirects_authenticated_user():
    User = get_user_model()
    user = User.objects.create_user(username='signed_in', password='StrongPass12345')
    client = Client()
    client.force_login(user)
    resp = client.get('/accounts/signup/?next=/roundtable/')
    assert resp.status_code == 302
    assert resp['Location'] == '/roundtable/'
