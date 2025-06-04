"""
Django settings for hotel_ac project.
"""

import os
from pathlib import Path

# 构建基本路径
BASE_DIR = Path(__file__).resolve().parent.parent

# 安全密钥
SECRET_KEY = 'django-insecure-d4a#3kj!hn&j+o@3y@e3h9l5c*p9#q_7s+6=(2e&b#9)5p!1v7'

# 调试模式设置
DEBUG = True

ALLOWED_HOSTS = []

# 应用定义
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'channels',
    # 自定义应用
    'hotel_ac.core',
    'hotel_ac.room',
    'hotel_ac.reception',
    'hotel_ac.admin_app',
    'hotel_ac.manager',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hotel_ac.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hotel_ac.wsgi.application'
ASGI_APPLICATION = 'hotel_ac.asgi.application'

# 数据库配置 - MySQL
# 请在下方修改数据库的用户名和密码为您实际的MySQL用户名和密码
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.mysql',
#         'NAME': 'hotel_ac_db',
#         'USER': 'root',         # 请修改为您的MySQL用户名
#         'PASSWORD': '12345678',   # 请修改为您的MySQL密码
#         'HOST': 'localhost',
#         'PORT': '3306',
#         'OPTIONS': {
#             'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
#             'charset': 'utf8mb4',
#         },
#     }
# }

# 如果您在配置MySQL时遇到问题，可以暂时使用SQLite作为替代
# 取消下方注释并注释上方MySQL配置即可使用SQLite
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 密码验证
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# 国际化
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# 静态文件 (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# 媒体文件配置
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 默认主键类型
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Channels 配置
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# CORS 配置
CORS_ALLOW_ALL_ORIGINS = True  # 仅在开发环境使用，生产环境应限制具体域名 

# CSRF 配置
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8000', 'http://localhost:8000']
CSRF_COOKIE_SECURE = False  # 在开发环境中设为False，生产环境应设为True
CSRF_USE_SESSIONS = False  # 使用cookie存储CSRF令牌
CSRF_COOKIE_HTTPONLY = False  # 允许JavaScript访问CSRF令牌

# 空调系统配置
MAX_SERVICE_ROOMS = 3  # 最大同时服务房间数 