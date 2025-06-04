from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# 创建一个新的DRF路由器实例
router = DefaultRouter()

# 注册RoomControlViewSet
# 它提供了如 /api/core/room-control/set-state/, /api/core/room-control/toggle-ac/,
# /api/core/room-control/{room_pk}/status/, /api/core/room-control/all-rooms-status/
router.register(r'room-control', views.RoomControlViewSet, basename='room_control')

# 注册SchedulerControlViewSet
# 它提供了如 /api/core/scheduler/status/
router.register(r'scheduler', views.SchedulerControlViewSet, basename='scheduler_control')

# 注册QueueLogViewSet (只读队列日志)
# 它提供了如 /api/core/queue-logs/, /api/core/queue-logs/{queue_pk}/
router.register(r'queue-logs', views.QueueLogViewSet, basename='queue_log')

# 注册BillTestViewSet
# 它提供了如 /api/core/bill-test/calculate-room-bill/
router.register(r'bill-test', views.BillTestViewSet, basename='bill_test')

# 旧的 SchedulerViewSet 和 QueueViewSet 已被新的视图集替代，所以不再需要注册它们。
# router.register(r'schedule', views.SchedulerViewSet, basename='schedule') # 旧的，已移除或被替代
# router.register(r'queue', views.QueueViewSet, basename='queue')         # 旧的，已移除或被替代

urlpatterns = [
    # 包含由路由器自动生成的所有URL模式
    path('', include(router.urls)),
]

# 访问 /api/core/ 将会显示所有注册到这个路由器的API端点列表。 