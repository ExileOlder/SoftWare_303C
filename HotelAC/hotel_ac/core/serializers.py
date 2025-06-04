from rest_framework import serializers
from .models import Room, Queue, ACUsage, Bill


class RoomSerializer(serializers.ModelSerializer):
    """房间序列化器"""
    class Meta:
        model = Room
        fields = [
            'id', 'room_number', 'is_occupied', 'current_temperature', 
            'target_temperature', 'ac_mode', 'fan_speed', 'is_ac_on',
            'created_at', 'updated_at'
        ]


class QueueSerializer(serializers.ModelSerializer):
    """服务队列序列化器"""
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    
    class Meta:
        model = Queue
        fields = [
            'id', 'room', 'room_number', 'priority', 'is_active',
            'remaining_time', 'created_at', 'updated_at'
        ]


class ACUsageSerializer(serializers.ModelSerializer):
    """空调使用记录序列化器"""
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    
    class Meta:
        model = ACUsage
        fields = [
            'id', 'room', 'room_number', 'start_time', 'end_time',
            'start_temperature', 'end_temperature', 'mode', 'fan_speed',
            'duration', 'energy_consumption', 'cost', 'is_billed'
        ]


class BillSerializer(serializers.ModelSerializer):
    """账单序列化器"""
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    
    class Meta:
        model = Bill
        fields = [
            'id', 'room', 'room_number', 'check_in_time', 'check_out_time',
            'total_cost', 'is_paid', 'payment_time', 'created_at', 'updated_at'
        ]


class RoomControlSerializer(serializers.Serializer):
    """房间控制序列化器"""
    room_number = serializers.CharField(required=True)
    is_ac_on = serializers.BooleanField(required=False)
    target_temperature = serializers.FloatField(required=False, min_value=16.0, max_value=30.0)
    ac_mode = serializers.ChoiceField(required=False, choices=Room._meta.get_field('ac_mode').choices)
    fan_speed = serializers.ChoiceField(required=False, choices=Room._meta.get_field('fan_speed').choices)


class ScheduleRequestSerializer(serializers.Serializer):
    """调度请求序列化器"""
    room_number = serializers.CharField(required=True)
    target_temperature = serializers.FloatField(required=True, min_value=16.0, max_value=30.0)
    priority = serializers.ChoiceField(required=False, choices=Queue._meta.get_field('priority').choices, default='MEDIUM')