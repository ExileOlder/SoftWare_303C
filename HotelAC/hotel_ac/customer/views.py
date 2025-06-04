from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required

from hotel_ac.core.models import Room, ACUsage, Queue
from hotel_ac.core.decorators import guest_login_required, room_access_required

@room_access_required
def room_control_panel(request, room_number):
    """显示房间控制面板"""
    room = get_object_or_404(Room, room_number=room_number)
    
    # 获取访客姓名
    guest_name = request.session.get('guest_name', '访客')
    
    context = {
        'room': room,
        'guest_name': guest_name,
        'modes': [
            {'id': 'COOL', 'name': '制冷'},
            {'id': 'HEAT', 'name': '制热'},
        ],
        'fan_speeds': [
            {'id': 'LOW', 'name': '低风速'},
            {'id': 'MEDIUM', 'name': '中风速'},
            {'id': 'HIGH', 'name': '高风速'},
        ]
    }
    return render(request, 'customer/room_control.html', context)

@require_http_methods(['POST'])
@room_access_required
def set_ac_settings(request, room_number):
    """设置空调参数"""
    room = get_object_or_404(Room, room_number=room_number)
    
    # 获取请求数据
    target_temp = request.POST.get('target_temperature')
    fan_speed = request.POST.get('fan_speed')
    ac_mode = request.POST.get('ac_mode')
    ac_status = request.POST.get('ac_status')
    
    # 更新房间空调设置
    if target_temp:
        room.target_temperature = float(target_temp)
    
    if fan_speed:
        room.fan_speed = fan_speed
    
    if ac_mode:
        room.ac_mode = ac_mode
    
    if ac_status:
        room.is_ac_on = ac_status.lower() == 'true'
    
    room.save()
    
    # 创建或更新服务队列请求
    if room.is_ac_on:
        # 根据风速设置优先级
        priority = 'MEDIUM'
        if room.fan_speed == 'HIGH':
            priority = 'HIGH'
        elif room.fan_speed == 'LOW':
            priority = 'LOW'
        
        # 检查是否已存在活跃的队列请求
        existing_queue = Queue.objects.filter(room=room, is_active=True).first()
        
        if existing_queue:
            # 更新现有队列请求
            existing_queue.priority = priority
            existing_queue.target_temperature = room.target_temperature
            existing_queue.fan_speed = room.fan_speed
            existing_queue.ac_mode = room.ac_mode
            existing_queue.save()
        else:
            # 创建新的队列请求
            Queue.objects.create(
                room=room,
                priority=priority,
                target_temperature=room.target_temperature,
                fan_speed=room.fan_speed,
                ac_mode=room.ac_mode
            )
    
    return JsonResponse({
        'success': True,
        'room_settings': {
            'target_temperature': room.target_temperature,
            'current_temperature': room.current_temperature,
            'fan_speed': room.fan_speed,
            'ac_mode': room.ac_mode,
            'is_ac_on': room.is_ac_on
        }
    })

@require_http_methods(['GET'])
@room_access_required
def get_room_status(request, room_number):
    """获取房间状态"""
    room = get_object_or_404(Room, room_number=room_number)
    
    return JsonResponse({
        'room_settings': {
            'target_temperature': room.target_temperature,
            'current_temperature': room.current_temperature,
            'fan_speed': room.fan_speed,
            'ac_mode': room.ac_mode,
            'is_ac_on': room.is_ac_on
        }
    }) 