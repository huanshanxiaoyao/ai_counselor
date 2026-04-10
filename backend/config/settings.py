"""
Django settings for AI Counselor project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'rest_framework',
    'backend.chat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'backend.config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS settings (for development)
CORS_ALLOW_ALL_ORIGINS = DEBUG

# LLM Configuration
LLM_DEFAULT_PROVIDER = os.getenv('LLM_DEFAULT_PROVIDER', 'qwen')
LLM_TIMEOUT = int(os.getenv('LLM_TIMEOUT', '12'))
LLM_MAX_RETRIES = int(os.getenv('LLM_MAX_RETRIES', '3'))

LLM_PROVIDERS = {
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'api_key': os.getenv('OPENAI_API_KEY', ''),
        'default_model': os.getenv('OPENAI_MODEL', 'gpt-4o'),
    },
    'qwen': {
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'api_key': os.getenv('QWEN_API_KEY', ''),
        'default_model': os.getenv('QWEN_MODEL', 'qwen-plus'),
    },
    'deepseek': {
        'base_url': 'https://api.deepseek.com/v1',
        'api_key': os.getenv('DEEPSEEK_API_KEY', ''),
        'default_model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    },
    'minimax': {
        'sdk_type': 'anthropic',
        'base_url': os.getenv('ANTHROPIC_BASE_URL', 'https://api.minimax.io/anthropic'),
        'api_key': os.getenv('ANTHROPIC_API_KEY', ''),
        'default_model': os.getenv('MINIMAX_MODEL', 'MiniMax-M2.1'),
    },
}
