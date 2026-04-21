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
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

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
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'channels',
    'backend.chat',
    'backend.roundtable',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'backend.config.middleware.GuestSessionMiddleware',
    # NOTE: LoginRequiredMiddleware is intentionally NOT mounted — anonymous users
    # are welcome. Use @login_required on individual views that require a real account.
]

# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

ROOT_URLCONF = 'backend.config.urls'

# In DEBUG mode, bypass cached.Loader so template edits are visible without restart.
# In production, use cached.Loader for performance.
_template_loaders = (
    [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ]
    if DEBUG else
    [
        ('django.template.loaders.cached.Loader', [
            'django.template.loaders.filesystem.Loader',
            'django.template.loaders.app_directories.Loader',
        ])
    ]
)

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': False,          # must be False when 'loaders' is set
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'loaders': _template_loaders,
        },
    },
]

WSGI_APPLICATION = 'backend.config.wsgi.application'
ASGI_APPLICATION = 'backend.config.asgi.application'

# Channel Layers for WebSocket
# Use InMemoryChannelLayer if Redis is not available
_redis_host = os.getenv('REDIS_HOST', 'localhost')
_redis_port = int(os.getenv('REDIS_PORT', '6379'))
try:
    import redis
    import channels_redis  # noqa: F401 — verify installed before configuring backend
    r = redis.Redis(host=_redis_host, port=_redis_port, socket_connect_timeout=1)
    r.ping()
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [(_redis_host, _redis_port)],
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

STATIC_URL = '/ac-static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS settings (for development)
CORS_ALLOW_ALL_ORIGINS = DEBUG

# LLM Configuration
LLM_DEFAULT_PROVIDER = os.getenv('LLM_DEFAULT_PROVIDER', 'qwen')
LLM_TIMEOUT = int(os.getenv('LLM_TIMEOUT', '12'))
LLM_MAX_RETRIES = int(os.getenv('LLM_MAX_RETRIES', '3'))
TOKEN_QUOTA_LIMIT = int(
    os.getenv('TOKEN_QUOTA_LIMIT', '100000' if DEBUG else '1000000')
)

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
