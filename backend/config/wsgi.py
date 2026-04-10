"""
WSGI config for AI Counselor.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
application = get_wsgi_application()
