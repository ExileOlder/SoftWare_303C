from django.utils import timezone
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import threading
import time

from hotel_ac.core.models import Room, Queue, ACUsage, FanSpeed, ACMode, QueuePriority
from hotel_ac.core.serializers import RoomSerializer # 确保RoomSerializer在这里可用
from .queue_manager_service import QueueManagerService

print("DEBUG: scheduler_service.py top level - Attempt 2")
print(f"DEBUG: QueuePriority type: {type(QueuePriority)}")
try:
    print(f"DEBUG: QueuePriority.HIGH: {QueuePriority.HIGH}")
    print(f"DEBUG: QueuePriority.MEDIUM: {QueuePriority.MEDIUM}")
    print(f"DEBUG: QueuePriority.LOW: {QueuePriority.LOW}")
except AttributeError as e:
    print(f"DEBUG: Error accessing QueuePriority members: {e}")
    # 如果 Queue 此时是 DeferredAttribute，尝试打印它
    if 'Queue' in globals():
        print(f"DEBUG: Queue type at this point: {type(Queue)}")
        if hasattr(Queue, 'priority'):
            print(f"DEBUG: Queue.priority type: {type(Queue.priority)}")
            try:
                print(f"DEBUG: Trying to access Queue.priority.HIGH: {Queue.priority.HIGH}")
            except AttributeError as de:
                print(f"DEBUG: Error accessing Queue.priority.HIGH: {de}")

# 默认配置 (可以在 settings.py 中覆盖)
MAX_SERVICE_ROOMS = getattr(settings, 'MAX_SERVICE_ROOMS', 3) # 最大同时服务房间数
DEFAULT_TIME_SLICE = getattr(settings, 'DEFAULT_TIME_SLICE', 5 * 60) # 默认时间片5分钟 (秒)
PRIORITY_TIME_SLICE_FACTOR = {
    QueuePriority.HIGH: 1.5, # 高优先级时间片是默认的1.5倍
    QueuePriority.MEDIUM: 1.0,
    QueuePriority.LOW: 0.75,
}
CHECK_INTERVAL = getattr(settings, 'SCHEDULER_CHECK_INTERVAL', 10)

class SchedulerService:
    """中央空调调度服务"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                print("Attempting to start SchedulerService...")
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.service_queue = []  # 正在服务的房间列表
            self.waiting_queue = []  # 等待服务的请求队列
            self.room_service_start_time = {}  # 记录每个房间开始服务的时间
            self.room_service_time_slice = {}  # 记录每个房间的时间片
            self.queue_manager = QueueManagerService()
            self._stop_event = threading.Event()
            self.scheduler_thread = None
            self.channel_layer = get_channel_layer()
            self.initialized = True

    def start_scheduler(self):
        """启动调度器"""
        if self.scheduler_thread is None or not self.scheduler_thread.is_alive():
            self._stop_event.clear()
            self.scheduler_thread = threading.Thread(target=self._run_scheduler)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            print("Scheduler thread started.")

    def stop_scheduler(self):
        """停止调度器"""
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self._stop_event.set()
            self.scheduler_thread.join()
            print("Scheduler thread stopped.")

    def _run_scheduler(self):
        """调度器主循环"""
        print("Scheduler thread running...")
        while not self._stop_event.is_set():
            try:
                self.schedule()
                self._update_room_temperatures()
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
            time.sleep(CHECK_INTERVAL)

    def schedule(self):
        """核心调度逻辑"""
        # 1. 检查服务队列中的房间是否需要移出
        rooms_to_remove_details = [] # 存储房间及移除原因
        current_time = timezone.now()
        
        # Iterate over a copy for safe removal while iterating
        for room in list(self.service_queue):
            time_expired = False
            target_reached = False

            # 检查服务时间片是否用完
            if room.id in self.room_service_start_time:
                service_duration = (current_time - self.room_service_start_time[room.id]).total_seconds()
                if service_duration >= self.room_service_time_slice.get(room.id, DEFAULT_TIME_SLICE):
                    time_expired = True
            
            # 检查是否已达到目标温度
            if abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                target_reached = True

            if time_expired or target_reached:
                rooms_to_remove_details.append({
                    'room': room, 
                    'time_expired': time_expired, 
                    'target_reached': target_reached
                })

        # 移除超时的或已达到目标温度的房间
        removed_a_room_in_this_cycle = False
        for detail in rooms_to_remove_details:
            room = detail['room']
            
            if room in self.service_queue: # Ensure room is still in service_queue before removing
                self.service_queue.remove(room)
                removed_a_room_in_this_cycle = True
            
            # 清理服务时间记录
            if room.id in self.room_service_start_time:
                del self.room_service_start_time[room.id]
            if room.id in self.room_service_time_slice:
                del self.room_service_time_slice[room.id]
            
            # 停止当前服务段的计费
            self.queue_manager.stop_room_ac_usage(room)
            
            fields_to_update_room = []
            if detail['target_reached']:
                if room.is_ac_on: # 仅当空调开启时才关闭
                    room.is_ac_on = False
                    fields_to_update_room.append('is_ac_on')
                
                # 将队列请求标记为非活动
                Queue.objects.filter(room=room, is_active=True).update(is_active=False)
            
            if fields_to_update_room:
                room.save(update_fields=fields_to_update_room)

            self._notify_room_status(room) # 通知房间状态更新

        # 2. 从数据库加载活跃请求到等待队列
        active_requests = Queue.objects.filter(is_active=True).select_related('room')
        serviced_room_ids = {r.id for r in self.service_queue}
        waiting_room_ids = {q.room_id for q in self.waiting_queue}

        for request in active_requests:
            if request.room_id not in serviced_room_ids and request.room_id not in waiting_room_ids:
                self.waiting_queue.append(request)

        # 3. 按优先级排序等待队列
        self.waiting_queue.sort(key=lambda q: (
            -1 if q.priority == QueuePriority.HIGH else 
            0 if q.priority == QueuePriority.MEDIUM else 1,
            q.request_time
        ))

        # 4. 从等待队列中选择房间进行服务
        added_a_room_to_service_this_cycle = False
        while len(self.service_queue) < MAX_SERVICE_ROOMS and self.waiting_queue:
            next_request = self.waiting_queue.pop(0)
            room = next_request.room

            # 检查是否已达到目标温度 (在加入服务队列前再次检查)
            if abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                if next_request.is_active: # 仅当它是活跃时才更新
                    next_request.is_active = False
                    next_request.save(update_fields=['is_active'])
                self.queue_manager.stop_room_ac_usage(room) # 确保已停止计费
                if room.is_ac_on: # 如果误开，则关闭
                    room.is_ac_on = False
                    room.save(update_fields=['is_ac_on'])
                self._notify_room_status(room) # 通知状态
                continue

            # 将房间加入服务队列
            self.service_queue.append(room)
            added_a_room_to_service_this_cycle = True
            self.room_service_start_time[room.id] = current_time # 使用当前的 current_time
            
            # 根据优先级设置时间片
            priority_factor = PRIORITY_TIME_SLICE_FACTOR.get(next_request.priority, 1.0)
            self.room_service_time_slice[room.id] = DEFAULT_TIME_SLICE * priority_factor

            # 开始计费并通知状态更新
            self.queue_manager.start_room_ac_usage(room)
            self._notify_room_status(room)

        # 如果调度状态有变化（有房间移除、添加或等待队列非空），通知管理员监控
        if removed_a_room_in_this_cycle or added_a_room_to_service_this_cycle or self.waiting_queue:
            self._notify_admin_monitor()

    def _update_room_temperatures(self):
        """更新房间温度并累计费用"""
        for room in self.service_queue:
            # The QueueManagerService will handle the logic for temperature change and fee calculation
            # based on room's current state (is_ac_on, ac_mode, target_temperature, etc.)
            # and the time_delta (CHECK_INTERVAL).
            
            changed, new_temp = self.queue_manager.update_temperature_and_calculate_fee(room, CHECK_INTERVAL)
            
            if changed:
                room.current_temperature = new_temp
                # 假设 Room 模型的 updated_at 是自动管理的。
                # 这里专注于 current_temperature 的更新。
                room.save(update_fields=['current_temperature'])
                self._notify_room_status(room) # 仅当温度实际更改时才通知。
            # else: 如果温度没有变化（例如，已达到目标，或空调关闭且环境温度匹配），
            # 则无需根据此特定更新周期保存或通知温度。
            # schedule() 方法将处理在达到目标时从服务中移除的逻辑。

    def add_request(self, room_id, target_temperature, fan_speed, ac_mode, priority=QueuePriority.MEDIUM):
        """添加新的温控请求"""
        try:
            room = Room.objects.get(id=room_id)
            
            # 更新房间状态
            room.target_temperature = target_temperature
            room.fan_speed = fan_speed
            room.ac_mode = ac_mode
            room.is_ac_on = True
            room.save()

            # 创建或更新队列请求
            queue_request, created = Queue.objects.update_or_create(
                room=room,
                defaults={
                    'priority': priority,
                    'is_active': True,
                    'target_temperature': target_temperature,
                    'fan_speed': fan_speed,
                    'ac_mode': ac_mode,
                    'request_time': timezone.now()
                }
            )

            # 立即进行调度
            self.schedule()
            self._notify_room_status(room)
            self._notify_admin_monitor()
            
            return queue_request, True, "请求已成功处理"
        except Room.DoesNotExist:
            return None, False, f"房间ID {room_id} 不存在"
        except Exception as e:
            print(f"Error adding request: {e}")
            return None, False, str(e)

    def remove_request(self, room_id, turn_off_ac=True):
        """移除温控请求"""
        try:
            room = Room.objects.get(id=room_id)
            
            # 从队列中移除
            if room in self.service_queue:
                self.service_queue.remove(room)
            self.waiting_queue = [q for q in self.waiting_queue if q.room_id != room.id]
            
            # 清理相关数据
            if room.id in self.room_service_start_time:
                del self.room_service_start_time[room.id]
            if room.id in self.room_service_time_slice:
                del self.room_service_time_slice[room.id]

            # 更新数据库状态
            Queue.objects.filter(room=room).update(is_active=False)
            
            if turn_off_ac:
                room.is_ac_on = False
                room.save()
                self.queue_manager.stop_room_ac_usage(room)

            self._notify_room_status(room)
            self._notify_admin_monitor()
            
            return True, "请求已成功移除"
        except Room.DoesNotExist:
            return False, f"房间ID {room_id} 不存在"
        except Exception as e:
            print(f"Error removing request: {e}")
            return False, str(e)

    def get_status(self):
        """获取调度器状态"""
        servicing = []
        for room in self.service_queue:
            queue_info = Queue.objects.filter(room=room, is_active=True).first()
            if queue_info:
                servicing.append({
                    'room_number': room.room_number,
                    'current_temp': room.current_temperature,
                    'target_temp': room.target_temperature,
                    'fan_speed': room.fan_speed,
                    'ac_mode': room.ac_mode,
                    'is_ac_on': room.is_ac_on,
                    'priority': queue_info.priority,
                    'service_start_time': self.room_service_start_time.get(room.id),
                    'time_slice': self.room_service_time_slice.get(room.id)
                })

        waiting = []
        for queue_item in self.waiting_queue:
            waiting.append({
                'room_number': queue_item.room.room_number,
                'current_temp': queue_item.room.current_temperature,
                'target_temp': queue_item.target_temperature,
                'fan_speed': queue_item.fan_speed,
                'ac_mode': queue_item.ac_mode,
                'priority': queue_item.priority,
                'request_time': queue_item.request_time
            })

        return {
            'max_service_rooms': MAX_SERVICE_ROOMS,
            'servicing_rooms': servicing,
            'waiting_queue': waiting
        }

    def _notify_room_status(self, room):
        """通知房间状态更新"""
        try:
            channel_layer = get_channel_layer()
            room_group_name = f"room_{room.room_number}"
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    "type": "room.status",
                    "message": {
                        "room_number": room.room_number,
                        "current_temperature": room.current_temperature,
                        "target_temperature": room.target_temperature,
                        "is_ac_on": room.is_ac_on,
                        "ac_mode": room.ac_mode,
                        "fan_speed": room.fan_speed
                    }
                }
            )
        except Exception as e:
            print(f"Error notifying room status: {e}")

    def _notify_admin_monitor(self):
        """通知管理员监控界面"""
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "admin_monitor",
                {
                    "type": "monitor.update",
                    "message": self.get_status()
                }
            )
        except Exception as e:
            print(f"Error notifying admin monitor: {e}")

# 单例模式获取调度器实例
def get_scheduler_service():
    return SchedulerService() 