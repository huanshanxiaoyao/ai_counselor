"""
Django settings for AI Counselor project.
"""
import os
from pathlib import Path

# Load .env file for development
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

# SECURITY WARNING: keep the secret key used in production secret!
# In production, DJANGO_SECRET_KEY environment variable MUST be set.
if DEBUG:
    # Development: use a random key if not set
    import secrets
    SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', secrets.token_hex(32))
else:
    # Production: MUST have SECRET_KEY set via environment variable
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("DJANGO_SECRET_KEY environment variable must be set in production")

# SECURITY WARNING: configure allowed hosts properly!
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'rest_framework',
    'channels',
    'backend.chat',
    'backend.roundtable',
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
ASGI_APPLICATION = 'backend.config.asgi.application'

# Channel Layers for WebSocket
# Use InMemoryChannelLayer if Redis is not available
try:
    import redis
    r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=1)
    r.ping()
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [('localhost', 6379)],
            },
        },
    }
except Exception:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

import dj_database_url

# Parse DATABASE_URL environment variable
database_url = os.getenv('DATABASE_URL')
if database_url:
    DATABASES = {
        'default': dj_database_url.parse(database_url, conn_max_age=600)
    }
else:
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

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'backend': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'backend.roundtable': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'daphne': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
