from django.urls import path
from . import consumers

websocket_urlpatterns = [
    # 管理员实时监控WebSocket
    path('ws/admin/monitor/', consumers.AdminMonitorConsumer.as_asgi()),
    # 房间状态实时更新WebSocket
    path('ws/room/<str:room_id>/', consumers.RoomStatusConsumer.as_asgi()),
] 