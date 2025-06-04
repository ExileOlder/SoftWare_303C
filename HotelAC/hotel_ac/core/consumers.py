import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from .models import Room
from .serializers import RoomSerializer
from .services import get_scheduler_service


class AdminMonitorConsumer(AsyncWebsocketConsumer):
    """管理员监控WebSocket消费者"""
    
    async def connect(self):
        """连接时加入管理员监控组"""
        self.group_name = 'admin_monitor'
        
        # 加入管理员监控组
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"AdminMonitorConsumer connected. Channel: {self.channel_name}")
        
        # 连接后立即发送一次当前调度器状态
        scheduler = get_scheduler_service()
        initial_status = await sync_to_async(scheduler.get_status)()
        await self.send(text_data=json.dumps({
            'type': 'scheduler_status_update',
            'status': initial_status
        }))
    
    async def disconnect(self, close_code):
        """断开连接时离开组"""
        print(f"AdminMonitorConsumer disconnected. Channel: {self.channel_name}")
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """接收前端消息"""
        data = json.loads(text_data)
        message_type = data.get('type')
        print(f"AdminMonitorConsumer received message: {data}")
        
        if message_type == 'request_scheduler_status':
            scheduler = get_scheduler_service()
            current_status = await sync_to_async(scheduler.get_status)()
            await self.send(text_data=json.dumps({
                'type': 'scheduler_status_update',
                'status': current_status
            }))
    
    @database_sync_to_async
    def get_all_rooms_status(self):
        """获取所有房间状态"""
        rooms = Room.objects.all()
        room_data = []
        
        for room in rooms:
            # 获取该房间的队列信息（如果存在）
            queue = Queue.objects.filter(room=room, is_active=True).first()
            queue_info = {
                'in_queue': queue is not None,
                'priority': queue.priority if queue else None,
                'remaining_time': queue.remaining_time if queue else None,
            }
            
            room_data.append({
                'id': room.id,
                'room_number': room.room_number,
                'is_occupied': room.is_occupied,
                'current_temperature': room.current_temperature,
                'target_temperature': room.target_temperature,
                'ac_mode': room.ac_mode,
                'fan_speed': room.fan_speed,
                'is_ac_on': room.is_ac_on,
                'queue_info': queue_info,
            })
        
        return room_data
    
    async def scheduler_status_update(self, event):
        """
        处理由 SchedulerService 通过 group_send 发送的调度器状态更新。
        event 将包含 {'type': 'scheduler_status_update', 'status': status_data}
        """
        print(f"AdminMonitorConsumer: Forwarding scheduler_status_update: {event['status']}")
        await self.send(text_data=json.dumps({
            'type': 'scheduler_status_update',
            'status': event['status'] 
        }))


class RoomStatusConsumer(AsyncWebsocketConsumer):
    """房间状态WebSocket消费者"""
    
    async def connect(self):
        """连接时加入房间特定组"""
        self.room_number = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'room_{self.room_number}'
        
        # 加入房间特定组
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"RoomStatusConsumer connected for room {self.room_number}. Channel: {self.channel_name}")
        
        # 连接后立即发送一次当前房间状态
        await self.send_current_room_status()
    
    async def disconnect(self, close_code):
        """断开连接时离开组"""
        print(f"RoomStatusConsumer disconnected for room {self.room_number}. Channel: {self.channel_name}")
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """接收前端消息"""
        data = json.loads(text_data)
        message_type = data.get('type')
        print(f"RoomStatusConsumer for {self.room_number} received message: {data}")
        
        if message_type == 'request_room_status':
            await self.send_current_room_status()
    
    @database_sync_to_async
    def _get_room_details(self):
        try:
            room = Room.objects.get(room_number=self.room_number)
            # 尝试从SchedulerService获取更完整的状态，或者直接从模型构建
            scheduler = get_scheduler_service()
            scheduler_status = scheduler.get_status()
            
            room_data_from_scheduler = None
            for r_info in scheduler_status.get('servicing_rooms', []):
                if r_info['room_number'] == room.room_number:
                    room_data_from_scheduler = r_info
                    break
            if not room_data_from_scheduler:
                for r_info in scheduler_status.get('waiting_queue', []):
                    if r_info['room_number'] == room.room_number:
                        # 在等待队列中，信息可能不包含current_temp等实时信息
                        # 我们需要合并模型数据和队列数据
                        room_data_from_scheduler = {
                            **RoomSerializer(room).data,
                            'priority': r_info.get('priority'),
                            'request_time': r_info.get('request_time'),
                        }
                        break
            
            if room_data_from_scheduler:
                 # 确保包含所有RoomSerializer的字段，并补充队列特有信息
                base_room_data = RoomSerializer(room).data
                # 更新或添加来自调度器的信息
                for key, value in room_data_from_scheduler.items():
                    base_room_data[key] = value
                return base_room_data
            else:
                # 如果不在服务或等待队列，则只返回房间模型基本信息
                # 但也应该包含一个空的queue_info，与服务层通知的结构一致
                serialized_room = RoomSerializer(room).data
                serialized_room['queue_info'] = {
                    'in_queue': False,
                    'priority': None,
                    'target_temperature': room.target_temperature,
                    'fan_speed': room.fan_speed,
                    'ac_mode': room.ac_mode,
                }
                return serialized_room
        except Room.DoesNotExist:
            return None
        except Exception as e:
            print(f"Error in _get_room_details for {self.room_number}: {e}")
            return None

    async def send_current_room_status(self):
        """发送当前房间的详细状态"""
        room_details = await self._get_room_details()
        if room_details:
            await self.send(text_data=json.dumps({
                'type': 'room_status_update',
                'room': room_details
            }))
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Room {self.room_number} not found or error fetching status.'
            }))

    async def room_status_update(self, event):
        """
        处理由 SchedulerService 通过 group_send 发送的特定房间状态更新。
        event 将包含 {'type': 'room_status_update', 'room': room_data}
        其中 room_data 是由 SchedulerService._notify_room_status 准备好的完整房间信息。
        """
        print(f"RoomStatusConsumer for {self.room_number}: Forwarding room_status_update: {event['room']}")
        await self.send(text_data=json.dumps({
            'type': 'room_status_update',
            'room': event['room']
        }))

# 需要在 scheduler_service.py 中导入 RoomSerializer，如果还没导入的话
# from hotel_ac.core.serializers import RoomSerializer 