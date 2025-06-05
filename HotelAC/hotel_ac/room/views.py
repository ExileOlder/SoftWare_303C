from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils import timezone
from datetime import datetime, timedelta
from django.utils.decorators import method_decorator
import logging
from decimal import Decimal, ROUND_HALF_UP

from hotel_ac.core.models import Room, FanSpeed, ACMode, ACUsage, Queue, QueuePriority
from hotel_ac.core.services.scheduler_service import get_scheduler_service
from hotel_ac.core.serializers import RoomSerializer
from hotel_ac.core.services.queue_manager_service import QueueManagerService

logger = logging.getLogger(__name__)

class RoomControlViewSet(viewsets.ViewSet):
    """客房空调控制视图集"""
    
    def retrieve(self, request, pk=None):
        """获取指定房间的详细信息"""
        try:
            room = Room.objects.get(pk=pk)
            serializer = RoomSerializer(room)
            
            # 获取当前费用信息
            current_usage = ACUsage.objects.filter(
                room=room, 
                end_time__isnull=True
            ).order_by('-start_time').first()
            
            # 直接从数据库获取费用，不再进行实时计算
            cost = float(current_usage.cost) if current_usage and current_usage.cost is not None else 0
            
            # 获取服务队列状态
            queue_status = "OFF"  # 默认为关闭
            
            if room.is_ac_on:
                queue_status = "WAITING"  # 如果开机，至少是等待状态
                
                # 检查是否在服务队列中
                active_request = Queue.objects.filter(room=room, is_active=True).first()
            
                if active_request:
                    # 获取调度器实例，检查是否正在被服务
                    scheduler = get_scheduler_service()
                    if room in scheduler.service_queue:
                        queue_status = "SERVING"
            
            data = serializer.data
            data.update({
                'cost': cost,
                'queue_status': queue_status
            })
            
            return Response(data)
        except Room.DoesNotExist:
            return Response({"error": "房间不存在"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error retrieving room {pk} details: {str(e)}", exc_info=True)
            return Response({"error": "获取房间详情失败: " + str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def power(self, request, pk=None):
        """控制空调开关"""
        try:
            room = Room.objects.get(pk=pk)
            power_state = request.data.get('power', False)
            
            scheduler = get_scheduler_service()
            queue_manager = QueueManagerService()
            
            if power_state:
                # 开机逻辑
                # 先检查是否已有运行中的使用记录
                existing_usage = queue_manager.get_current_usage(room)
                if existing_usage and room.is_ac_on:
                    # 房间已经开机，无需重复操作
                    logger.info(f"Room {room.room_number} AC is already on with usage ID: {existing_usage.id}")
                    return Response({"message": "空调已开启", "status": "success"})
                
                # 更新房间状态
                room.is_ac_on = True
                
                # 默认设置，如果请求中没有指定
                target_temp = request.data.get('target_temperature', room.target_temperature)
                fan_speed = request.data.get('fan_speed', room.fan_speed)
                ac_mode = request.data.get('ac_mode', room.ac_mode)
                
                # 更新房间温控参数
                room.target_temperature = target_temp
                room.fan_speed = fan_speed
                room.ac_mode = ac_mode
                room.save()
                
                # 创建使用记录
                usage = queue_manager.start_room_ac_usage(room)
                
                # 验证使用记录是否创建成功
                if not usage:
                    logger.error(f"Failed to create ACUsage record for room {room.room_number}")
                    return Response({"message": "空调开启失败，无法创建使用记录", "status": "error"}, status=500)
                
                # 立即创建队列请求并加入等待队列
                queue_request, created = Queue.objects.update_or_create(
                    room=room,
                    defaults={
                        'priority': QueuePriority.MEDIUM,
                        'is_active': True,
                        'target_temperature': target_temp,
                        'fan_speed': fan_speed,
                        'ac_mode': ac_mode,
                        'request_time': timezone.now()
                    }
                )
                
                # 立即执行一次调度，尝试加入服务队列
                scheduler.schedule()
                
                return Response({"message": "空调已开启", "status": "success"})
            else:
                # 关机逻辑，只有在当前是开机状态时才更新
                if room.is_ac_on:
                    # 停止空调使用记录
                    queue_manager.stop_room_ac_usage(room)
                    
                    # 更新房间状态
                    room.is_ac_on = False
                    room.save()
                
                    # 更新队列状态
                    Queue.objects.filter(room=room, is_active=True).update(is_active=False)
                    
                    # 从调度队列中移除
                    scheduler.remove_request(room.id, turn_off_ac=False)  # 不重复关闭空调
                    
                return Response({"message": "空调已关闭", "status": "success"})
        except Room.DoesNotExist:
            return Response({"message": "房间不存在", "status": "error"}, status=404)
        except Exception as e:
            logger.error(f"Power control error: {e}")
            return Response({"message": f"操作失败: {str(e)}", "status": "error"}, status=500)
    
    @action(detail=True, methods=['post'])
    def set_temperature(self, request, pk=None):
        """设置目标温度"""
        try:
            room = Room.objects.get(pk=pk)
            
            # 验证温度范围
            temp = request.data.get('temperature')
            if temp is None:
                return Response({"error": "必须提供温度参数"}, status=status.HTTP_400_BAD_REQUEST)
                
            temp = float(temp)
            
            # 根据空调模式验证温度范围
            if room.ac_mode == ACMode.COOL:
                # 制冷模式：18-25度
                if temp < 18 or temp > 25:
                    return Response({"error": "制冷模式下温度必须在18°C到25°C之间"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                # 制热模式：25-30度
                if temp < 25 or temp > 30:
                    return Response({"error": "制热模式下温度必须在25°C到30°C之间"}, status=status.HTTP_400_BAD_REQUEST)
            
            # 先更新房间的目标温度，不管空调是否开启
            room.target_temperature = temp
            room.save(update_fields=['target_temperature'])
            
            # 如果空调已开启，更新或创建服务请求，但不重启调度器以避免关闭空调
            if room.is_ac_on:
                # 获取现有请求或创建新请求
                queue_request, created = Queue.objects.update_or_create(
                    room=room,
                    defaults={
                        'priority': QueuePriority.MEDIUM,
                        'is_active': True,
                        'target_temperature': temp,
                        'fan_speed': room.fan_speed,
                        'ac_mode': room.ac_mode,
                        'request_time': timezone.now()
                    }
                )
                
                # 不调用scheduler.add_request，因为它会重置整个调度过程
                # 直接确保请求在队列中
                scheduler = get_scheduler_service()
                if room not in scheduler.service_queue and not any(q.room_id == room.id for q in scheduler.waiting_queue):
                    scheduler.waiting_queue.append(queue_request)
                    print(f"添加房间 {room.room_number} 到等待队列，目标温度: {temp}")
                
            return Response({
                "message": "目标温度已设置", 
                "target_temperature": temp
            })
            
        except Room.DoesNotExist:
            return Response({"error": "房间不存在"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"error": "温度必须是一个有效数字"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error setting temperature for room {pk}: {str(e)}", exc_info=True)
            return Response({"error": "设置温度失败: " + str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def set_mode(self, request, pk=None):
        """设置空调模式（制冷/制热）"""
        try:
            room = Room.objects.get(pk=pk)
            
            mode = request.data.get('mode')
            if not mode or mode not in [ACMode.COOL, ACMode.HEAT]:
                return Response({"error": "必须提供有效的模式：COOL或HEAT"}, status=status.HTTP_400_BAD_REQUEST)
            
            # 先更新房间的模式设置，不管空调是否开启
            room.ac_mode = mode
            room.save(update_fields=['ac_mode'])
            
            # 如果空调已开启，更新或创建服务请求，但不重启调度器以避免关闭空调
            if room.is_ac_on:
                # 获取现有请求或创建新请求
                queue_request, created = Queue.objects.update_or_create(
                    room=room,
                    defaults={
                        'priority': QueuePriority.MEDIUM,
                        'is_active': True,
                        'target_temperature': room.target_temperature,
                        'fan_speed': room.fan_speed,
                        'ac_mode': mode,
                        'request_time': timezone.now()
                    }
                )
                
                # 不调用scheduler.add_request，因为它会重置整个调度过程
                # 直接确保请求在队列中
                scheduler = get_scheduler_service()
                if room not in scheduler.service_queue and not any(q.room_id == room.id for q in scheduler.waiting_queue):
                    scheduler.waiting_queue.append(queue_request)
                    print(f"添加房间 {room.room_number} 到等待队列，模式: {mode}")
                
            return Response({
                "message": "空调模式已设置", 
                "mode": "制冷" if mode == ACMode.COOL else "制热"
            })
            
        except Room.DoesNotExist:
            return Response({"error": "房间不存在"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error setting mode for room {pk}: {str(e)}", exc_info=True)
            return Response({"error": "设置模式失败: " + str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def set_fan_speed(self, request, pk=None):
        """设置风速"""
        try:
            room = Room.objects.get(pk=pk)
            
            fan_speed = request.data.get('fan_speed')
            if not fan_speed or fan_speed not in [FanSpeed.LOW, FanSpeed.MEDIUM, FanSpeed.HIGH]:
                return Response({"error": "必须提供有效的风速：LOW、MEDIUM或HIGH"}, status=status.HTTP_400_BAD_REQUEST)
            
            # 先更新房间的风速设置，不管空调是否开启
            room.fan_speed = fan_speed
            room.save(update_fields=['fan_speed'])
            
            # 如果空调已开启，更新或创建服务请求，但不重启调度器以避免关闭空调
            if room.is_ac_on:
                # 获取现有请求或创建新请求
                queue_request, created = Queue.objects.update_or_create(
                    room=room,
                    defaults={
                        'priority': QueuePriority.MEDIUM,
                        'is_active': True,
                        'target_temperature': room.target_temperature,
                        'fan_speed': fan_speed,
                        'ac_mode': room.ac_mode,
                        'request_time': timezone.now()
                    }
                )
                
                # 不调用scheduler.add_request，因为它会重置整个调度过程
                # 直接确保请求在队列中
                scheduler = get_scheduler_service()
                if room not in scheduler.service_queue and not any(q.room_id == room.id for q in scheduler.waiting_queue):
                    scheduler.waiting_queue.append(queue_request)
                    print(f"添加房间 {room.room_number} 到等待队列，风速: {fan_speed}")
                
            return Response({
                "message": "风速已设置", 
                "fan_speed": "低速" if fan_speed == FanSpeed.LOW else 
                            ("中速" if fan_speed == FanSpeed.MEDIUM else "高速")
            })
            
        except Room.DoesNotExist:
            return Response({"error": "房间不存在"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error setting fan speed for room {pk}: {str(e)}", exc_info=True)
            return Response({"error": "设置风速失败: " + str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @method_decorator(ensure_csrf_cookie)
    def control_panel(self, request, room_number):
        """渲染控制面板页面"""
        try:
            room = Room.objects.get(room_number=room_number)
            return render(request, 'room/control_panel.html', {'room_number': room_number})
        except Room.DoesNotExist:
            return JsonResponse({"error": "房间不存在"}, status=404)


class RoomStatusViewSet(viewsets.ViewSet):
    """房间状态视图集，主要用于前端实时获取状态更新"""
    
    def list(self, request):
        """获取所有房间的状态简要信息（适用于监控面板）"""
        # 检查是否有room_number过滤参数
        room_number = request.query_params.get('room_number')
        if room_number:
            rooms = Room.objects.filter(room_number=room_number)
        else:
                rooms = Room.objects.all()
            
        serializer = RoomSerializer(rooms, many=True)
        
        # 增加服务队列状态信息
        scheduler = get_scheduler_service()
        serviced_room_ids = [r.id for r in scheduler.service_queue]
        
        data = serializer.data
        for room_data in data:
            room_id = room_data['id']
            if room_id in serviced_room_ids:
                room_data['queue_status'] = 'SERVING'
            else:
                active_request = Queue.objects.filter(room_id=room_id, is_active=True).exists()
                room_data['queue_status'] = 'WAITING' if active_request else 'OFF'
        
        # 将数据包装在results字段中，与前端期望的格式匹配
        return Response({"results": data})
    
    def retrieve(self, request, pk=None):
        """获取单个房间的详细状态"""
        room = get_object_or_404(Room, pk=pk)
        serializer = RoomSerializer(room)
        
        # 获取房间的当前使用记录
        current_usage = ACUsage.objects.filter(
            room=room,
            end_time__isnull=True
        ).order_by('-start_time').first()
        
        # 获取房间的服务队列状态
        scheduler = get_scheduler_service()
        in_service = room in scheduler.service_queue
        in_queue = Queue.objects.filter(room=room, is_active=True).exists()
        
        # 构建响应数据
        data = serializer.data
        data.update({
            'in_service': in_service,
            'in_queue': in_queue,
            'service_start_time': scheduler.room_service_start_time.get(room.id),
            'current_cost': float(current_usage.cost) if current_usage else 0,
            'usage_start_time': current_usage.start_time if current_usage else None,
            'usage_duration': (timezone.now() - current_usage.start_time).total_seconds() if current_usage else 0
        })
        
        return Response(data)
    
    @action(detail=True, methods=['get'])
    def usage_history(self, request, pk=None):
        """获取指定房间的使用历史记录"""
        room = get_object_or_404(Room, pk=pk)
        
        # 获取查询参数，默认最近24小时的记录
        start_time = request.query_params.get(
            'start_time', 
            (timezone.now() - timedelta(days=1)).isoformat()
        )
        end_time = request.query_params.get('end_time', timezone.now().isoformat())
        
        # 查询使用记录
        usages = ACUsage.objects.filter(
            room=room,
            start_time__gte=start_time,
            end_time__lte=end_time
        ).order_by('-start_time')
        
        # 构建响应数据
        usage_data = []
        for usage in usages:
            duration = usage.duration.total_seconds() if usage.duration else 0
            
            usage_data.append({
                'id': usage.id,
                'start_time': usage.start_time,
                'end_time': usage.end_time,
                'duration_seconds': duration,
                'start_temperature': usage.start_temperature,
                'end_temperature': usage.end_temperature,
                'mode': usage.mode,
                'fan_speed': usage.fan_speed,
                'cost': float(usage.cost),
                'energy_consumption': usage.energy_consumption
            })
        
        return Response(usage_data) 