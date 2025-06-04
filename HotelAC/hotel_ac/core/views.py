from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
from datetime import datetime  # 导入标准库的datetime

from .models import Room, Queue, ACUsage, Bill, FanSpeed, ACMode, QueuePriority
from .serializers import (
    RoomSerializer, QueueSerializer, ACUsageSerializer, BillSerializer,
    RoomControlSerializer, ScheduleRequestSerializer
)
from .services import get_scheduler_service, QueueManagerService

from rest_framework import serializers

class APIWindSpeedRequestSerializer(serializers.Serializer):
    room_id = serializers.IntegerField(help_text="房间ID")
    fan_speed = serializers.ChoiceField(choices=FanSpeed.choices, help_text="目标风速")
    # priority = serializers.ChoiceField(choices=QueuePriority.choices, default=QueuePriority.MEDIUM, required=False, help_text="请求优先级")

class APITempRequestSerializer(serializers.Serializer):
    room_id = serializers.IntegerField(help_text="房间ID")
    target_temperature = serializers.FloatField(min_value=16.0, max_value=30.0, help_text="目标温度 (16-30)")
    # priority = serializers.ChoiceField(choices=QueuePriority.choices, default=QueuePriority.MEDIUM, required=False, help_text="请求优先级")

class APIAcOnOffRequestSerializer(serializers.Serializer):
    room_id = serializers.IntegerField(help_text="房间ID")
    turn_on = serializers.BooleanField(help_text="True为开机, False为关机")
    # 开机时可选参数
    target_temperature = serializers.FloatField(min_value=16.0, max_value=30.0, required=False, help_text="目标温度 (开机时可选)")
    fan_speed = serializers.ChoiceField(choices=FanSpeed.choices, required=False, help_text="目标风速 (开机时可选)")
    ac_mode = serializers.ChoiceField(choices=ACMode.choices, required=False, help_text="空调模式 (开机时可选)")
    priority = serializers.ChoiceField(choices=QueuePriority.choices, default=QueuePriority.MEDIUM, required=False, help_text="请求优先级 (开机时可选)")

class APIRoomStateRequestSerializer(serializers.Serializer): # 用于客户端直接设定完整状态
    room_id = serializers.IntegerField(help_text="房间ID")
    target_temperature = serializers.FloatField(min_value=16.0, max_value=30.0, help_text="目标温度 (16-30)")
    fan_speed = serializers.ChoiceField(choices=FanSpeed.choices, help_text="目标风速")
    ac_mode = serializers.ChoiceField(choices=ACMode.choices, help_text="空调模式 (制冷/制热)")
    is_ac_on = serializers.BooleanField(default=True, help_text="空调是否开启") # 默认为开启，因为设定状态通常意味着要开
    priority = serializers.ChoiceField(choices=QueuePriority.choices, default=QueuePriority.MEDIUM, required=False, help_text="请求优先级")


class RoomControlViewSet(viewsets.ViewSet):
    """
    房间空调控制API端点。
    允许客户端对指定房间的空调进行操作，如开关、设置温度、风速和模式。
    """
    permission_classes = [permissions.AllowAny] # 开发阶段允许所有请求，后续应设置权限
    scheduler = get_scheduler_service() # 获取调度服务单例

    @action(detail=False, methods=['post'], url_path='set-room-ac-state')
    def set_room_ac_state(self, request):
        """
        设置房间空调的完整状态（开机、目标温度、风速、模式）。
        如果 is_ac_on 为 false，则等同于关机。
        """
        serializer = APIRoomStateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        room_id = data['room_id']
        is_on = data.get('is_ac_on', True) # 如果前端传来is_ac_on=false, 则关机

        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": f"Room with ID {room_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        if not is_on:
            # 如果请求是关机
            _, success, msg = self.scheduler.remove_request(room_id=room.id, turn_off_ac=True)
            if success:
                return Response({"message": f"空调已为房间 {room.room_number} 关闭", "details": msg}, status=status.HTTP_200_OK)
            else:
                return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # 如果请求是开机或修改设置
            target_temp = data['target_temperature']
            fan_speed = data['fan_speed']
            ac_mode = data['ac_mode']
            priority = data.get('priority', QueuePriority.MEDIUM)

            # 调用调度服务处理请求
            queue_request, success, msg = self.scheduler.add_request(
                room_id=room.id,
                target_temperature=target_temp,
                requested_fan_speed=fan_speed,
                requested_ac_mode=ac_mode,
                priority=priority
            )
            if success:
                return Response({
                    "message": f"空调请求已为房间 {room.room_number} 处理", 
                    "details": msg,
                    "queue_item": QueueSerializer(queue_request).data if queue_request else None
                }, status=status.HTTP_200_OK)
            else:
                return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='toggle-ac')
    def toggle_ac(self, request):
        """
        开关指定房间的空调。
        如果开机，可以附带初始设置。
        """
        serializer = APIAcOnOffRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        room_id = data['room_id']
        turn_on = data['turn_on']

        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": f"Room with ID {room_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        if turn_on:
            # 开机逻辑: 使用房间当前的目标设置，或请求中提供的新设置
            target_temp = data.get('target_temperature', room.target_temperature)
            fan_speed = data.get('fan_speed', room.fan_speed)
            ac_mode = data.get('ac_mode', room.ac_mode)
            priority = data.get('priority', QueuePriority.MEDIUM)
            
            queue_request, success, msg = self.scheduler.add_request(
                room_id=room.id, 
                target_temperature=target_temp, 
                requested_fan_speed=fan_speed,
                requested_ac_mode=ac_mode,
                priority=priority
            )
            if success:
                return Response({"message": f"空调已为房间 {room.room_number} 开启", "details": msg}, status=status.HTTP_200_OK)
            else:
                return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # 关机逻辑
            _, success, msg = self.scheduler.remove_request(room_id=room.id, turn_off_ac=True)
            if success:
                return Response({"message": f"空调已为房间 {room.room_number} 关闭", "details": msg}, status=status.HTTP_200_OK)
            else:
                return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='status') # detail=True, pk为room_id
    def room_status(self, request, pk=None):
        """获取指定房间的当前状态 (包括空调和队列信息)"""
        try:
            room = Room.objects.get(pk=pk)
            room_data = RoomSerializer(room).data
            # 补充队列信息
            queue_info = self.scheduler.get_status() # 获取完整状态，然后筛选
            
            current_room_in_service = next((r for r in queue_info['servicing_rooms'] if r['room_number'] == room.room_number), None)
            current_room_in_waiting = next((r for r in queue_info['waiting_queue'] if r['room_number'] == room.room_number), None)
            
            room_data['queue_details'] = current_room_in_service or current_room_in_waiting or None
            return Response(room_data)
        except Room.DoesNotExist:
            return Response({"error": f"Room with ID {pk} not found."}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=['get'], url_path='all-rooms-status')
    def all_rooms_status(self, request):
        """获取所有房间的简要状态列表"""
        rooms = Room.objects.all()
        data = RoomSerializer(rooms, many=True).data
        return Response(data)

class SchedulerControlViewSet(viewsets.ViewSet):
    """
    中央空调调度系统控制和状态API。
    """
    permission_classes = [permissions.IsAdminUser] # 通常只有管理员可以访问
    scheduler = get_scheduler_service()

    @action(detail=False, methods=['get'], url_path='status')
    def get_scheduler_status(self, request):
        """获取当前调度系统的整体状态 (服务队列、等待队列等)"""
        status_data = self.scheduler.get_status()
        return Response(status_data)

    # 未来可以添加更多控制接口，如：
    # - 动态修改MAX_SERVICE_ROOMS
    # - 暂停/恢复整个调度服务
    # - 手动调整某个房间的优先级等

# 注意: 原有的 SchedulerViewSet 和 QueueViewSet 可以被以上两个新的ViewSet替代或删除。
# Queue的直接增删改查API通常不直接暴露给普通用户，而是通过SchedulerService的逻辑间接管理。
# 如果需要直接管理Queue对象的API（例如管理员操作），可以保留或创建一个专门的QueueModelViewSet。

# 示例：如果需要一个只读的Queue模型视图（例如给管理员查看所有历史和当前请求）
class QueueLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    只读的队列请求日志视图。
    """
    queryset = Queue.objects.all().order_by('-request_time')
    serializer_class = QueueSerializer
    permission_classes = [permissions.IsAdminUser] # 仅管理员

# 账单相关视图暂时放在reception应用中会更合适，但这里可以为测试目的留一个简单的
class BillTestViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    queue_manager = QueueManagerService()

    @action(detail=False, methods=['get'], url_path='calculate-room-bill')
    def calculate_room_bill(self, request):
        room_id = request.query_params.get('room_id')
        check_in_str = request.query_params.get('check_in_time') # 格式: YYYY-MM-DDTHH:MM:SSZ
        check_out_str = request.query_params.get('check_out_time') # 同上, 可选

        if not room_id or not check_in_str:
            return Response({"error": "room_id and check_in_time are required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            room = Room.objects.get(id=int(room_id))
            # 修复日期时间处理
            check_in_time = timezone.make_aware(datetime.fromisoformat(check_in_str.replace('Z', '+00:00')))
            check_out_time = timezone.make_aware(datetime.fromisoformat(check_out_str.replace('Z', '+00:00'))) if check_out_str else timezone.now()
        except Room.DoesNotExist:
            return Response({"error": f"Room with ID {room_id} not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"error": "Invalid datetime format. Use ISO format YYYY-MM-DDTHH:MM:SSZ."}, status=status.HTTP_400_BAD_REQUEST)

        bill_data = self.queue_manager.calculate_bill(room, check_in_time, check_out_time)
        return Response(bill_data) 