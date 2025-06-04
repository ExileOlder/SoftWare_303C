"""
ASGI config for hotel_ac project.
支持HTTP和WebSocket协议
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import hotel_ac.core.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_ac.settings')

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            hotel_ac.core.routing.websocket_urlpatterns
        )
    ),
}) 