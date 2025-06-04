from django.utils import timezone
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import threading
import time
import traceback

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
DEFAULT_TIME_SLICE = getattr(settings, 'DEFAULT_TIME_SLICE', 3 * 60) # 默认时间片改为3分钟 (秒)
PRIORITY_TIME_SLICE_FACTOR = {
    QueuePriority.HIGH: 1.5, # 高优先级时间片是默认的1.5倍
    QueuePriority.MEDIUM: 1.0,
    QueuePriority.LOW: 0.75,
}
# 减少轮询时间以加快温度变化和计费同步
CHECK_INTERVAL = getattr(settings, 'SCHEDULER_CHECK_INTERVAL', 2)  # 从5秒改为2秒
# 新增宽限期设置
GRACE_PERIOD = getattr(settings, 'GRACE_PERIOD', 60)  # 空调开启后的宽限期，减少到60秒(1分钟)

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
            self._lock = threading.RLock()  # 添加可重入锁保护共享资源
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
        """调度器主线程"""
        print("Scheduler thread running...")
        while not self._stop_event.is_set():
            try:
                # 执行调度逻辑
                self.schedule()
                
                # 更新所有房间温度
                self._update_room_temperatures()
                
                # 通知管理员监控界面
                self._notify_admin_monitor()
                
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
                traceback.print_exc()
            
            # 等待一段时间再执行下一次调度
            time.sleep(CHECK_INTERVAL)

    def schedule(self):
        """核心调度逻辑"""
        with self._lock:  # 使用锁保护共享资源
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

                # 检查是否已达到目标温度，但优先检查宽限期
                current_usage = self.queue_manager.get_current_usage(room)
                if current_usage:
                    usage_duration = (current_time - current_usage.start_time).total_seconds()
                    # 只有超过宽限期(120秒)后才检查温度是否达标
                    if usage_duration > GRACE_PERIOD and abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                        target_reached = True
                        print(f"Room {room.room_number} reached target temperature after {usage_duration} seconds")
                elif abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
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

                # 仅在房间达到目标温度时停止计费和关闭空调
                if detail['target_reached']:
                    # 停止当前服务段的计费
                    self.queue_manager.stop_room_ac_usage(room)

                    fields_to_update_room = []
                    if room.is_ac_on: # 仅当空调开启时才关闭
                        room.is_ac_on = False
                        fields_to_update_room.append('is_ac_on')

                    # 将队列请求标记为非活动
                    Queue.objects.filter(room=room, is_active=True).update(is_active=False)

                    if fields_to_update_room:
                        room.save(update_fields=fields_to_update_room)
                # 如果只是时间片到期，不关闭空调，仅暂停服务
                elif detail['time_expired']:
                    # 暂停服务但保持空调开启
                    if room.is_ac_on and Queue.objects.filter(room=room, is_active=True).exists():
                        # 将请求移到等待队列，让它有机会重新获取服务
                        request = Queue.objects.filter(room=room, is_active=True).first()
                        if request and request not in self.waiting_queue:
                            self.waiting_queue.append(request)

                self._notify_room_status(room) # 通知房间状态更新

            # 2. 从数据库加载活跃请求到等待队列
            active_requests = Queue.objects.filter(is_active=True).select_related('room')
            serviced_room_ids = {r.id for r in self.service_queue}
            waiting_room_ids = {q.room_id for q in self.waiting_queue}
            
            # 处理未在服务队列中的房间空调
            # 为刚开启的空调创建宽限期，不要立即关闭它们
            for request in active_requests:
                room = request.room
                if room.is_ac_on and room.id not in serviced_room_ids and room.id not in waiting_room_ids:
                    # 检查是否已创建使用记录
                    current_usage = self.queue_manager.get_current_usage(room)
                    if current_usage:
                        # 计算使用记录的存在时间
                        usage_duration = (current_time - current_usage.start_time).total_seconds()
                        print(f"Room {room.room_number} AC usage duration: {usage_duration} seconds, in grace period")
                        
                        # 无论是否达到目标温度，在宽限期内都加入等待队列
                        if usage_duration <= GRACE_PERIOD:  # 120秒宽限期内强制加入等待队列
                            self.waiting_queue.append(request)
                            print(f"Room {room.room_number} added to waiting queue during grace period")
                        # 修复：仅将还未达到目标温度的房间加入等待队列，明确判断条件
                        elif abs(room.current_temperature - room.target_temperature) >= self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                            self.waiting_queue.append(request)
                            print(f"Room {room.room_number} not reached target temperature, added to waiting queue")
                        # 如果已达到目标温度，且超过120秒宽限期，才停止记录
                        else:  
                            print(f"Room {room.room_number} reached target temperature after grace period, stopping")
                            self.queue_manager.stop_room_ac_usage(room)
                            if room.is_ac_on:
                                room.is_ac_on = False
                                room.save(update_fields=['is_ac_on'])
                            request.is_active = False
                            request.save(update_fields=['is_active'])
                            self._notify_room_status(room)
                    else:
                        # 修复：如果没有使用记录但空调开启，创建记录并加入等待队列
                        self.queue_manager.start_room_ac_usage(room)
                        self.waiting_queue.append(request)
                        print(f"Room {room.room_number} created usage record and added to waiting queue")

            # 添加其他未处理的活跃请求到等待队列
            for request in active_requests:
                if request.room_id not in serviced_room_ids and request.room_id not in waiting_room_ids and request not in self.waiting_queue:
                    self.waiting_queue.append(request)

            # 3. 对等待队列按优先级排序
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

                # 确保房间空调开启
                if not room.is_ac_on:
                    room.is_ac_on = True
                    room.save(update_fields=['is_ac_on'])

                # 获取当前使用记录
                current_usage = self.queue_manager.get_current_usage(room)
                
                # 检查是否已达到目标温度，但同样考虑宽限期
                if current_usage:
                    usage_duration = (current_time - current_usage.start_time).total_seconds()
                    # 宽限期内不检查温度
                    if usage_duration <= GRACE_PERIOD:
                        pass  # 在宽限期内不做温度检查，直接加入服务队列
                    # 宽限期后才检查温度
                    elif abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                        if next_request.is_active: # 仅当它是活跃时才更新
                            next_request.is_active = False
                            next_request.save(update_fields=['is_active'])
                        self.queue_manager.stop_room_ac_usage(room) # 确保已停止计费
                        if room.is_ac_on: # 如果误开，则关闭
                            room.is_ac_on = False
                            room.save(update_fields=['is_ac_on'])
                        self._notify_room_status(room) # 通知状态
                        continue
                # 无使用记录但温度已达标
                elif abs(room.current_temperature - room.target_temperature) < self.queue_manager.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD:
                    if next_request.is_active: # 仅当它是活跃时才更新
                        next_request.is_active = False
                        next_request.save(update_fields=['is_active'])
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

                # 开始或更新计费记录
                usage = self.queue_manager.start_room_ac_usage(room)
                if usage:
                    print(f"Started or continued AC usage record for room {room.room_number}. Usage ID: {usage.id}")
                self._notify_room_status(room)

            # 如果调度状态有变化（有房间移除、添加或等待队列非空），通知管理员监控
            if removed_a_room_in_this_cycle or added_a_room_to_service_this_cycle or self.waiting_queue:
                self._notify_admin_monitor()

    def _update_room_temperatures(self):
        """更新所有房间的温度"""
        with self._lock:
            try:
                # 获取所有开启空调的房间
                rooms_with_ac_on = Room.objects.filter(is_ac_on=True)
                
                for room in rooms_with_ac_on:
                    try:
                        # 计算服务时间
                        service_time = 0
                        
                        # 如果在服务队列中，使用服务开始时间
                        if room in self.service_queue and room.id in self.room_service_start_time:
                            service_time = (timezone.now() - self.room_service_start_time[room.id]).total_seconds()
                        
                        # 不管是否在服务队列中，都更新温度和计费（每2秒）
                        changed, new_temp = self.queue_manager.update_temperature_and_calculate_fee(room, CHECK_INTERVAL)
                        
                        # 记录更新日志
                        if changed:
                            print(f"Room {room.room_number} temperature updated to {new_temp}°C")
                        
                        # 通知房间状态更新
                        self._notify_room_status(room)
                        
                    except Exception as e:
                        print(f"Error updating temperature for room {room.room_number}: {e}")
                        traceback.print_exc()
            except Exception as e:
                print(f"Error in _update_room_temperatures: {e}")
                traceback.print_exc()

    def add_request(self, room_id, target_temperature, requested_fan_speed, requested_ac_mode, priority=QueuePriority.MEDIUM):
        """添加新的温控请求"""
        with self._lock:  # 使用锁保护共享资源
            try:
                room = Room.objects.get(id=room_id)
                
                # 更新房间状态
                room.target_temperature = target_temperature
                room.fan_speed = requested_fan_speed
                room.ac_mode = requested_ac_mode
                room.is_ac_on = True
                room.save()

                # 创建或更新队列请求
                queue_request, created = Queue.objects.update_or_create(
                    room=room,
                    defaults={
                        'priority': priority,
                        'is_active': True,
                        'target_temperature': target_temperature,
                        'fan_speed': requested_fan_speed,
                        'ac_mode': requested_ac_mode,
                        'request_time': timezone.now()
                    }
                )
                
                # 检查请求是否已在等待队列或服务队列中
                if room not in self.service_queue and not any(q.room_id == room.id for q in self.waiting_queue):
                    # 先创建使用记录，确保计费正确
                    usage = self.queue_manager.get_current_usage(room)
                    if not usage and room.is_ac_on:
                        usage = self.queue_manager.start_room_ac_usage(room)
                        print(f"为房间 {room.room_number} 创建使用记录 ID: {usage.id if usage else 'None'}")
                    
                    # 将请求加入等待队列，但不直接进行调度
                    self.waiting_queue.append(queue_request)
                    print(f"房间 {room.room_number} 已加入等待队列")
                
                # 通知房间状态更新
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
        with self._lock:  # 使用锁保护共享资源
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
        """通知房间状态更新，确保在主线程中执行"""
        try:
            if threading.current_thread() is threading.main_thread():
                # 在主线程中安全地执行通知
                try:
                    channel_layer = get_channel_layer()
                    room_group_name = f"room_{room.room_number}"
                    
                    # 获取当前使用记录的费用信息 - 确保从数据库获取最新数据
                    current_usage = ACUsage.objects.filter(
                        room=room, 
                        end_time__isnull=True
                    ).order_by('-start_time').first()
                    
                    current_cost = 0
                    if current_usage:
                        current_cost = float(current_usage.cost)
                    
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
                                "fan_speed": room.fan_speed,
                                "current_cost": current_cost
                            }
                        }
                    )
                except Exception as e:
                    print(f"Error sending room status notification: {e}")
            else:
                # 在后台线程中，只记录消息，不尝试发送
                print(f"Scheduling notification for room {room.room_number} from background thread")
        except Exception as e:
            print(f"Error in _notify_room_status: {e}")

    def _notify_admin_monitor(self):
        """通知管理员监控界面，确保在主线程中执行"""
        try:
            if threading.current_thread() is threading.main_thread():
                # 在主线程中安全地执行通知
                try:
                    channel_layer = get_channel_layer()
                    status_data = self.get_status()
                    
                    # 添加每个房间的当前费用和服务时间
                    # 为服务中的房间添加详细信息
                    for room_data in status_data.get('servicing_rooms', []):
                        room_number = room_data.get('room_number')
                        if room_number:
                            try:
                                room = Room.objects.get(room_number=room_number)
                                current_usage = self.queue_manager.get_current_usage(room)
                                if current_usage:
                                    # 计算并更新当前费用
                                    room_data['current_cost'] = float(current_usage.cost)
                                    room_data['energy_consumption'] = current_usage.energy_consumption
                                    
                                    # 计算并更新已服务时间
                                    usage_duration = (timezone.now() - current_usage.start_time).total_seconds()
                                    minutes, seconds = divmod(int(usage_duration), 60)
                                    hours, minutes = divmod(minutes, 60)
                                    room_data['service_duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                    
                                    # 计算服务时间百分比
                                    service_start_time = self.room_service_start_time.get(room.id)
                                    time_slice = self.room_service_time_slice.get(room.id, DEFAULT_TIME_SLICE)
                                    if service_start_time and time_slice:
                                        elapsed = (timezone.now() - service_start_time).total_seconds()
                                        room_data['service_progress_percent'] = min(100, int(elapsed / time_slice * 100))
                            except Exception as e:
                                print(f"Error getting usage data for room {room_number}: {e}")
                    
                    # 为等待队列中的房间添加详细信息
                    for room_data in status_data.get('waiting_queue', []):
                        room_number = room_data.get('room_number')
                        if room_number:
                            try:
                                room = Room.objects.get(room_number=room_number)
                                current_usage = self.queue_manager.get_current_usage(room)
                                if current_usage:
                                    # 计算并更新当前费用
                                    room_data['current_cost'] = float(current_usage.cost)
                                    room_data['energy_consumption'] = current_usage.energy_consumption
                                    
                                    # 计算并更新等待时间
                                    request_time = room_data.get('request_time')
                                    if request_time:
                                        wait_duration = (timezone.now() - request_time).total_seconds()
                                        minutes, seconds = divmod(int(wait_duration), 60)
                                        hours, minutes = divmod(minutes, 60)
                                        room_data['wait_duration_formatted'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                            except Exception as e:
                                print(f"Error getting usage data for waiting room {room_number}: {e}")
                    
                    async_to_sync(channel_layer.group_send)(
                        "admin_monitor",
                        {
                            "type": "monitor.update",
                            "message": status_data
                        }
                    )
                except Exception as e:
                    print(f"Error sending admin monitor notification: {e}")
            else:
                # 在后台线程中，只记录消息，不尝试发送
                print(f"Scheduling admin monitor notification from background thread")
        except Exception as e:
            print(f"Error in _notify_admin_monitor: {e}")

# 单例模式获取调度器实例
def get_scheduler_service():
    scheduler = SchedulerService()
    # 确保调度器在任何环境下都能启动
    if scheduler.scheduler_thread is None or not scheduler.scheduler_thread.is_alive():
        scheduler.start_scheduler()
        print("Scheduler has been started automatically")
    return scheduler