"""
Test settings for AI Counselor.
"""
from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Tests hit views directly without a user session. Drop the auth gate so existing
# API tests keep working; auth enforcement is covered by production settings.
MIDDLEWARE = [m for m in MIDDLEWARE if m != 'backend.config.middleware.LoginRequiredMiddleware']
