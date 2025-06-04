from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import json
import logging

from hotel_ac.core.models import Room, Queue, QueuePriority, FanSpeed, ACMode, ACUsage
from hotel_ac.core.serializers import RoomSerializer, QueueSerializer
from hotel_ac.core.services.scheduler_service import get_scheduler_service

# 配置日志
logger = logging.getLogger(__name__)

class MonitorViewSet(viewsets.ViewSet):
    """监控视图集，提供实时监控信息和控制功能"""
    
    def list(self, request):
        """获取监控概览数据"""
        # 获取调度器实例
        scheduler = get_scheduler_service()
        
        # 获取当前服务中的房间
        serviced_rooms = list(scheduler.service_queue)
        serviced_rooms_data = RoomSerializer(serviced_rooms, many=True).data
        
        # 获取等待队列中的房间请求
        waiting_queue = scheduler.waiting_queue
        waiting_queue_data = QueueSerializer(waiting_queue, many=True).data
        
        # 获取统计数据
        total_rooms = Room.objects.count()
        occupied_rooms = Room.objects.filter(is_occupied=True).count()
        ac_on_rooms = Room.objects.filter(is_ac_on=True).count()
        
        # 计算总能耗和费用（当前活跃的使用记录）
        active_usages = ACUsage.objects.filter(end_time=None)
        total_energy = sum(usage.energy_consumption or 0 for usage in active_usages)
        
        # 构建监控数据
        monitor_data = {
            "service_capacity": settings.MAX_SERVICE_ROOMS,
            "serviced_rooms_count": len(serviced_rooms),
            "waiting_queue_count": len(waiting_queue),
            "statistics": {
                "total_rooms": total_rooms,
                "occupied_rooms": occupied_rooms,
                "ac_on_rooms": ac_on_rooms,
                "total_energy_consumption": round(total_energy, 2),
            },
            "serviced_rooms": serviced_rooms_data,
            "waiting_queue": waiting_queue_data
        }
        
        return Response(monitor_data)
    
    @action(detail=False, methods=['get'])
    def service_status(self, request):
        """获取服务状态，包括服务中和等待中的请求"""
        scheduler = get_scheduler_service()
        
        # 获取服务中的房间
        serviced_room_ids = [r.id for r in scheduler.service_queue]
        serviced_rooms = Room.objects.filter(id__in=serviced_room_ids)
        serviced_data = []
        
        for room in serviced_rooms:
            start_time = scheduler.room_service_start_time.get(room.id)
            time_slice = scheduler.room_service_time_slice.get(room.id)
            
            # 计算剩余服务时间
            remaining_seconds = 0
            if start_time and time_slice:
                elapsed = (timezone.now() - start_time).total_seconds()
                remaining_seconds = max(0, time_slice - elapsed)
            
            # 获取当前使用记录的费用信息
            current_usage = ACUsage.objects.filter(room=room, end_time__isnull=True).order_by('-start_time').first()
            current_cost = 0
            if current_usage:
                current_cost = float(current_usage.cost)
                # 计算使用时间
                usage_duration = (timezone.now() - current_usage.start_time).total_seconds()
                minutes, seconds = divmod(int(usage_duration), 60)
                hours, minutes = divmod(minutes, 60)
                usage_duration_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                usage_duration_formatted = "00:00:00"
            
            room_data = RoomSerializer(room).data
            room_data.update({
                "service_start_time": start_time,
                "time_slice": time_slice,
                "remaining_seconds": remaining_seconds,
                "service_progress_percent": 100 - int(remaining_seconds / time_slice * 100) if time_slice else 0,
                "current_cost": current_cost,
                "service_duration": usage_duration_formatted
            })
            serviced_data.append(room_data)
        
        # 获取等待中的请求
        waiting_requests = Queue.objects.filter(is_active=True).exclude(room_id__in=serviced_room_ids)
        waiting_data = []
        
        for request in waiting_requests:
            # 获取当前使用记录的费用信息
            current_usage = ACUsage.objects.filter(room=request.room, end_time__isnull=True).order_by('-start_time').first()
            current_cost = 0
            if current_usage:
                current_cost = float(current_usage.cost)
            
            # 计算等待时间
            wait_duration = (timezone.now() - request.request_time).total_seconds()
            minutes, seconds = divmod(int(wait_duration), 60)
            hours, minutes = divmod(minutes, 60)
            wait_duration_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            room_data = RoomSerializer(request.room).data
            room_data.update({
                "request_time": request.request_time,
                "priority": request.priority,
                "wait_duration": wait_duration,
                "wait_duration_formatted": wait_duration_formatted,
                "current_cost": current_cost
            })
            waiting_data.append(room_data)
        
        return Response({
            "serviced": serviced_data,
            "waiting": waiting_data
        })
    
    @action(detail=True, methods=['post'])
    def adjust_priority(self, request, pk=None):
        """调整队列中请求的优先级"""
        queue_request = get_object_or_404(Queue, pk=pk)
        
        priority = request.data.get('priority')
        if not priority or priority not in [QueuePriority.HIGH, QueuePriority.MEDIUM, QueuePriority.LOW]:
            return Response({
                "error": "必须提供有效的优先级：HIGH、MEDIUM或LOW"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 更新优先级
        queue_request.priority = priority
        queue_request.save()
        
        # 获取调度器并重新调度
        scheduler = get_scheduler_service()
        scheduler.schedule()
        
        return Response({
            "message": f"请求优先级已调整为 {priority}",
            "request_id": queue_request.id,
            "room_number": queue_request.room.room_number
        })
    
    @action(detail=False, methods=['post'])
    def force_schedule(self, request):
        """强制立即执行一次调度"""
        scheduler = get_scheduler_service()
        
        # 执行调度
        scheduler.schedule()
        scheduler._update_room_temperatures()
        
        # 添加：强制更新管理员监控界面
        scheduler._notify_admin_monitor()
        
        return Response({
            "message": "已执行一次强制调度",
            "timestamp": timezone.now()
        })
    
    def monitor_page(self, request):
        """渲染监控页面"""
        return render(request, 'admin/monitoring.html')

class LogViewSet(viewsets.ViewSet):
    """日志视图集，提供系统日志查询功能"""
    
    def list(self, request):
        """获取系统日志"""
        # 获取查询参数
        limit = int(request.query_params.get('limit', 100))
        level = request.query_params.get('level', 'all').upper()
        
        # 模拟日志记录，实际项目中应从日志文件或数据库中读取
        log_entries = [
            {
                "timestamp": timezone.now() - timedelta(minutes=i*5),
                "level": ["INFO", "WARNING", "ERROR"][i % 3],
                "message": f"系统日志测试消息 #{i}",
                "source": "scheduler" if i % 2 == 0 else "queue_manager"
            } for i in range(min(limit, 100))
        ]
        
        # 根据级别过滤
        if level != 'ALL':
            log_entries = [entry for entry in log_entries if entry["level"] == level]
        
        return Response(log_entries)
    
    @action(detail=False, methods=['get'])
    def system_stats(self, request):
        """获取系统统计信息"""
        # 模拟系统统计数据，实际项目中应从监控系统中获取
        stats = {
            "uptime": "3天12小时45分钟",
            "cpu_usage": "32%",
            "memory_usage": "1.2GB / 4GB",
            "scheduler_status": "运行中",
            "queue_manager_status": "运行中",
            "last_error": "无",
            "error_count": {
                "today": 0,
                "this_week": 2,
                "this_month": 5
            }
        }
        
        return Response(stats)
    
    def log_page(self, request):
        """渲染日志页面"""
        return render(request, 'admin/logs.html')

class SettingsViewSet(viewsets.ViewSet):
    """设置视图集，提供系统参数配置功能"""
    
    def list(self, request):
        """获取当前系统设置"""
        system_settings = {
            "scheduler": {
                "max_service_rooms": settings.MAX_SERVICE_ROOMS,
                "default_time_slice": getattr(settings, 'DEFAULT_TIME_SLICE', 300),
                "check_interval": getattr(settings, 'SCHEDULER_CHECK_INTERVAL', 10)
            },
            "temperature": {
                "default_cool_rate": getattr(settings, 'DEFAULT_TEMP_CHANGE_RATE_COOL', 0.5/60) * 60,  # 每分钟
                "default_heat_rate": getattr(settings, 'DEFAULT_TEMP_CHANGE_RATE_HEAT', 0.6/60) * 60,
                "ambient_temp": getattr(settings, 'AMBIENT_DEFAULT_TEMPERATURE', 28.0),
                "temp_reached_threshold": getattr(settings, 'DEFAULT_TARGET_TEMP_REACHED_THRESHOLD', 0.1)
            },
            "cost": {
                "base_rate": float(getattr(settings, 'BASE_RATE_PER_SECOND', 0)) * 3600,  # 每小时
                "energy_price": float(getattr(settings, 'ENERGY_PRICE_PER_UNIT_CONSUMPTION', 0.5))
            }
        }
        
        return Response(system_settings)
    
    @action(detail=False, methods=['post'])
    def update_settings(self, request):
        """更新系统设置（仅模拟，实际需要写入settings或数据库）"""
        # 获取请求数据
        scheduler_settings = request.data.get('scheduler', {})
        temperature_settings = request.data.get('temperature', {})
        cost_settings = request.data.get('cost', {})
        
        # 在实际项目中，这里需要写入到配置文件或数据库
        # 这里仅返回确认信息
        
        return Response({
            "message": "系统设置已更新",
            "settings": {
                "scheduler": scheduler_settings,
                "temperature": temperature_settings,
                "cost": cost_settings
            }
        })
    
    def settings_page(self, request):
        """渲染设置页面"""
        return render(request, 'admin/settings.html') 