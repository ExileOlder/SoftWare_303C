import asyncio
import time
from unittest.mock import patch, MagicMock, call, ANY
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from hotel_ac.core.models import Room, Queue, ACUsage
from hotel_ac.core.services.scheduler_service import SchedulerService, get_scheduler_service
from hotel_ac.core.serializers import RoomSerializer # 确保导入

# 为了测试，我们需要一个全局的 SchedulerService 实例，或者在每个测试中重新创建/重置它
# Django TestCase 会为每个测试方法运行在新的事务中，但单例状态可能跨测试保留
# 我们可以在 setUp 中显式重置或使用一个新的实例

class SchedulerServiceTests(TestCase):
    def setUp(self):
        # 为每个测试重置或获取新的调度服务实例
        # 这里我们假设 get_scheduler_service() 每次都返回同一个实例，需要一种方法来重置它
        # 或者，我们可以直接实例化一个新的 SchedulerService 进行测试，但这不测试单例行为
        
        # 方案1: 尝试重置全局单例 (如果 SchedulerService 提供了 reset 方法)
        # get_scheduler_service().reset() # 假设有此方法
        
        # 方案2: 为测试创建一个新的实例，并patch get_scheduler_service 使其返回这个测试实例
        self.scheduler = SchedulerService() # 创建一个新实例
        self.patcher = patch('hotel_ac.core.services.scheduler_service.get_scheduler_service', return_value=self.scheduler)
        self.mock_get_scheduler_service = self.patcher.start()
        
        # 确保服务在测试开始时是停止的，或者根据需要启动
        # self.scheduler.stop_scheduler() # 确保是停止的
        # self.scheduler.start_scheduler() # 如果测试需要它运行

        # 创建一些测试房间
        self.room1 = Room.objects.create(room_number="101", current_temperature=25.0, target_temperature=22.0, is_ac_on=False)
        self.room2 = Room.objects.create(room_number="102", current_temperature=26.0, target_temperature=20.0, is_ac_on=False)
        self.room3 = Room.objects.create(room_number="103", current_temperature=24.0, target_temperature=21.0, is_ac_on=False)

    def tearDown(self):
        self.scheduler.stop_scheduler() # 确保调度器在测试后停止
        self.patcher.stop() # 停止 patch

    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_add_request_new_room_starts_ac_and_adds_to_queue(self, mock_async_to_sync):
        """测试添加新房间请求会启动空调并加入服务队列（如果未满）或等待队列"""
        self.assertFalse(self.room1.is_ac_on)
        self.assertEqual(len(self.scheduler.service_queue), 0)

        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        
        self.room1.refresh_from_db()
        self.assertTrue(self.room1.is_ac_on)
        self.assertEqual(self.room1.target_temperature, 22.0)
        self.assertEqual(self.room1.ac_mode, "COOL")
        self.assertEqual(self.room1.fan_speed, "HIGH")
        
        self.assertEqual(len(self.scheduler.service_queue), 1)
        self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room1.id)
        
        # 验证 Queue 模型记录被创建
        queue_entry = Queue.objects.get(room=self.room1, is_active=True)
        self.assertIsNotNone(queue_entry)
        self.assertEqual(queue_entry.target_temperature, 22.0)
        
        # 验证通知被发送
        mock_async_to_sync.assert_has_calls([
            call(self.scheduler.channel_layer.group_send)('admin_monitor', ANY),
            call(self.scheduler.channel_layer.group_send)(f'room_{self.room1.room_number}', ANY)
        ], any_order=True)

    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_add_request_updates_existing_request_in_service_queue(self, mock_async_to_sync):
        """测试对已在服务队列中的房间再次请求会更新其参数"""
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        self.assertEqual(len(self.scheduler.service_queue), 1)
        self.assertEqual(self.scheduler.service_queue[0]['target_temperature'], 22.0)

        self.scheduler.add_request(self.room1.room_number, 20.0, "COOL", "LOW")
        self.room1.refresh_from_db()
        self.assertEqual(self.room1.target_temperature, 20.0)
        self.assertEqual(self.room1.fan_speed, "LOW")
        
        self.assertEqual(len(self.scheduler.service_queue), 1) # 仍然只有一个服务项
        self.assertEqual(self.scheduler.service_queue[0]['target_temperature'], 20.0)
        self.assertEqual(self.scheduler.service_queue[0]['fan_speed'], "LOW")

    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_add_request_moves_from_waiting_to_service_if_space(self, mock_async_to_sync):
        """测试当服务队列有空位时，等待队列的请求会移入"""
        # 填满服务队列
        self.scheduler.max_service_capacity = 1 
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        
        # 添加到等待队列
        self.scheduler.add_request(self.room2.room_number, 20.0, "COOL", "HIGH")
        self.assertEqual(len(self.scheduler.service_queue), 1)
        self.assertEqual(len(self.scheduler.waiting_queue), 1)

        # 移除服务队列中的一个，使得等待队列可以进入
        self.scheduler.remove_request(self.room1.room_number, by_system=True) # 模拟服务完成
        
        # 触发一次调度循环 (或者直接调用 _promote_from_waiting)
        # self.scheduler._promote_from_waiting() # 假设这是个内部方法，可能需要重构或通过调度循环触发

        # 在实际的调度循环中，等待队列的项会被自动提升
        # 这里我们手动模拟一下这个逻辑，或者依赖调度线程（如果已启动）
        # 为了单元测试的确定性，最好是能直接调用相关逻辑或模拟其效果

        # 暂时通过再次添加来触发检查 (这不是理想的测试方式，但能模拟效果)
        # 或者，我们可以直接检查等待队列是否在下次调度时被提升
        # 更好的方式是，stop_scheduler 后，手动调用一次 schedule，或检查 _promote_from_waiting
        
        # 假设调度循环会处理
        # 这里我们直接检查效果：room2 应该进入服务队列
        # 需要确保调度服务已启动并运行一次迭代，或者手动调用
        
        # 为了简化，我们直接调用 _promote_from_waiting (如果它存在且可调用)
        # 如果它是 _run_scheduler 的一部分，我们需要模拟时间流逝和线程行为
        
        # 让我们假设 remove_request 内部会尝试提升
        # (在当前 remove_request 实现中，它只在 by_user=False 时调用 _move_next_from_waiting)
        # 所以，当 room1 完成服务 (by_system=True)，应该会触发 _move_next_from_waiting

        self.room1.refresh_from_db()
        self.assertFalse(self.room1.is_ac_on) # room1 服务结束，空调关闭

        self.assertEqual(len(self.scheduler.service_queue), 1)
        self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room2.id)
        self.assertEqual(len(self.scheduler.waiting_queue), 0)
        self.room2.refresh_from_db()
        self.assertTrue(self.room2.is_ac_on)


    def test_time_slice_rotation(self):
        """测试时间片轮转逻辑"""
        self.scheduler.max_service_capacity = 1
        self.scheduler.time_slice_duration = timedelta(seconds=1) # 假设非常短的时间片用于测试
        
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH", priority=1)
        self.scheduler.add_request(self.room2.room_number, 20.0, "COOL", "HIGH", priority=1) # 相同优先级
        
        self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room1.id)
        
        # 模拟时间流逝超过时间片
        # 需要一种方法来触发调度循环并使其感知时间的流逝
        # 我们可以 mock `timezone.now()` 或者让调度循环运行一次
        
        with patch.object(self.scheduler, '_run_scheduler_iteration', wraps=self.scheduler._run_scheduler_iteration) as mock_run_iter, \
             patch('hotel_ac.core.services.scheduler_service.timezone.now') as mock_now:
            
            self.scheduler.start_scheduler() # 启动调度器线程

            # 第一次迭代，room1 服务
            first_call_time = timezone.now()
            mock_now.return_value = first_call_time
            asyncio.run(self.scheduler._run_scheduler_iteration()) # 手动运行一次迭代
            self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room1.id)
            self.assertTrue(self.scheduler.service_queue[0]['is_servicing'])

            # 模拟时间片结束
            mock_now.return_value = first_call_time + self.scheduler.time_slice_duration + timedelta(microseconds=1)
            asyncio.run(self.scheduler._run_scheduler_iteration()) # 再次运行迭代

            # room1 应该被移到服务队列末尾（或等待队列，取决于实现），room2 服务
            # 当前实现是，如果还有其他相同优先级的请求，会轮换
            # 如果服务队列已满，被轮换出去的会回到等待队列，然后最高优先级的等待者进入
            # 在这里，因为 capacity=1, room1会被暂停，room2进入服务
            
            self.assertEqual(len(self.scheduler.service_queue), 1)
            self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room2.id)
            self.assertTrue(self.scheduler.service_queue[0]['is_servicing'])
            
            # room1 应该在等待队列，或者如果 service_queue 允许，则在其后部且 is_servicing=False
            # 根据当前代码，它会回到等待队列，然后被重新评估优先级
            found_room1_in_waiting = any(req['room_id'] == self.room1.id for req in self.scheduler.waiting_queue)
            self.assertTrue(found_room1_in_waiting)
            
            self.scheduler.stop_scheduler()


    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_priority_scheduling(self, mock_async_to_sync):
        """测试高优先级请求会优先服务"""
        self.scheduler.max_service_capacity = 1
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "LOW", priority=2) # 低优先级
        self.scheduler.add_request(self.room2.room_number, 20.0, "COOL", "HIGH", priority=1) # 高优先级
        
        self.assertEqual(len(self.scheduler.service_queue), 1)
        self.assertEqual(self.scheduler.service_queue[0]['room_id'], self.room2.id) # room2 (高优) 应首先服务
        self.assertEqual(len(self.scheduler.waiting_queue), 1)
        self.assertEqual(self.scheduler.waiting_queue[0]['room_id'], self.room1.id) # room1 (低优) 等待

    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_room_reaches_target_temp_stops_ac_and_removes_request(self, mock_async_to_sync):
        """测试当房间达到目标温度时，空调关闭，请求被移除"""
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        self.room1.refresh_from_db()
        self.assertTrue(self.room1.is_ac_on)
        
        # 模拟房间达到目标温度
        self.room1.current_temperature = self.room1.target_temperature
        self.room1.save()
        
        # 触发一次调度循环的迭代来处理这个状态
        # 在真实的调度循环中，_check_serviced_rooms 会被调用
        # 我们需要模拟调用它，或者让调度循环跑一次
        with patch.object(self.scheduler, '_check_serviced_rooms', wraps=self.scheduler._check_serviced_rooms) as mock_check:
            self.scheduler.start_scheduler()
            # 等待一小段时间让调度器至少运行一次检查
            # 或者手动调用
            asyncio.run(self.scheduler._check_serviced_rooms())
            self.scheduler.stop_scheduler()

        self.room1.refresh_from_db()
        self.assertFalse(self.room1.is_ac_on) # 空调应关闭
        self.assertEqual(len(self.scheduler.service_queue), 0)
        self.assertEqual(len(self.scheduler.waiting_queue), 0)
        
        # 验证 Queue 记录被标记为非活动
        q_entry = Queue.objects.get(room=self.room1, target_temperature=22.0) # 找到对应的Queue记录
        self.assertFalse(q_entry.is_active)
        
        # 验证 ACUsage 记录被创建
        usage_entry = ACUsage.objects.filter(room=self.room1, queue_request=q_entry).first()
        self.assertIsNotNone(usage_entry)
        self.assertIsNotNone(usage_entry.end_time)
        self.assertGreater(usage_entry.total_cost, 0) # 假设有使用就会有费用

    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_remove_request_by_user(self, mock_async_to_sync):
        """测试用户手动移除请求"""
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        self.room1.refresh_from_db()
        self.assertTrue(self.room1.is_ac_on)
        
        self.scheduler.remove_request(self.room1.room_number) # by_user=True by default
        
        self.room1.refresh_from_db()
        self.assertFalse(self.room1.is_ac_on) # 空调关闭
        self.assertEqual(len(self.scheduler.service_queue), 0)
        
        q_entry = Queue.objects.get(room=self.room1, target_temperature=22.0)
        self.assertFalse(q_entry.is_active) # 队列记录标记为非活动

    def test_get_status(self):
        """测试 get_status 方法返回正确的状态信息"""
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH", priority=1)
        self.scheduler.max_service_capacity = 1 # 确保只有一个在服务
        self.scheduler.add_request(self.room2.room_number, 20.0, "COOL", "MEDIUM", priority=2)
        
        # 模拟一个房间正在服务
        if self.scheduler.service_queue:
            self.scheduler.service_queue[0]['is_servicing'] = True
            self.scheduler.service_queue[0]['service_start_time'] = timezone.now()

        status = self.scheduler.get_status()

        self.assertIn('is_running', status)
        # self.assertEqual(status['is_running'], self.scheduler.scheduler_thread is not None) #取决于实现
        self.assertEqual(status['max_service_capacity'], self.scheduler.max_service_capacity)
        self.assertEqual(len(status['servicing_rooms']), 1)
        self.assertEqual(status['servicing_rooms'][0]['room_number'], self.room1.room_number)
        self.assertTrue(status['servicing_rooms'][0]['is_servicing'])
        
        self.assertEqual(len(status['waiting_queue']), 1)
        self.assertEqual(status['waiting_queue'][0]['room_number'], self.room2.room_number)

    def test_scheduler_start_stop(self):
        """测试调度器的启动和停止"""
        self.assertIsNone(self.scheduler.scheduler_thread)
        self.assertFalse(self.scheduler.running.is_set())

        self.scheduler.start_scheduler()
        self.assertIsNotNone(self.scheduler.scheduler_thread)
        self.assertTrue(self.scheduler.scheduler_thread.is_alive())
        self.assertTrue(self.scheduler.running.is_set())

        self.scheduler.stop_scheduler()
        # scheduler_thread.join() 应该在 stop_scheduler 中被调用
        # self.assertFalse(self.scheduler.scheduler_thread.is_alive()) # join 后线程结束
        # 对于后台线程的测试，join 的超时很重要
        time.sleep(0.1) # 给线程一点时间停止
        self.assertFalse(self.scheduler.running.is_set())
        if self.scheduler.scheduler_thread: # 线程对象可能在join后被设为None
             self.assertFalse(self.scheduler.scheduler_thread.is_alive())


    @patch('hotel_ac.core.services.scheduler_service.QueueManagerService')
    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_room_reaches_target_temp_calls_queue_manager_stop_usage(self, mock_async_to_sync, MockQueueManagerService):
        """测试达到目标温度时调用 QueueManagerService.stop_ac_usage_record"""
        mock_qms_instance = MockQueueManagerService.return_value
        
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        self.room1.refresh_from_db()
        
        # 获取对应的 Queue 实例
        queue_instance = Queue.objects.get(room=self.room1, is_active=True)

        # 模拟房间达到目标温度
        self.room1.current_temperature = self.room1.target_temperature
        self.room1.save()
        
        with patch.object(self.scheduler, '_check_serviced_rooms', wraps=self.scheduler._check_serviced_rooms):
            self.scheduler.start_scheduler()
            asyncio.run(self.scheduler._check_serviced_rooms()) # 手动调用一次
            self.scheduler.stop_scheduler()

        mock_qms_instance.stop_ac_usage_record.assert_called_once_with(
            room_id=self.room1.id,
            queue_id=queue_instance.id # 确保传递的是Queue实例的ID
        )

    @patch('hotel_ac.core.services.scheduler_service.QueueManagerService')
    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_remove_request_by_user_calls_queue_manager_stop_usage(self, mock_async_to_sync, MockQueueManagerService):
        """测试用户移除请求时调用 QueueManagerService.stop_ac_usage_record"""
        mock_qms_instance = MockQueueManagerService.return_value

        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH")
        self.room1.refresh_from_db()
        queue_instance = Queue.objects.get(room=self.room1, is_active=True)

        self.scheduler.remove_request(self.room1.room_number)

        mock_qms_instance.stop_ac_usage_record.assert_called_once_with(
            room_id=self.room1.id,
            queue_id=queue_instance.id
        )
        
    # 可以添加更多测试，例如：
    # - 等待队列满时的行为
    # - 不同模式 (HEAT/COOL) 的处理 (如果调度逻辑有差异)
    # - 调度服务重启后的状态恢复 (如果需要持久化状态)
    # - 错误处理和边界条件

    # 测试 _get_request_details_for_notification 方法
    def test_get_request_details_for_notification(self):
        self.scheduler.add_request(self.room1.room_number, 22.0, "COOL", "HIGH", priority=1)
        request_in_queue = self.scheduler.service_queue[0] # 假设它在服务队列
        
        self.room1.refresh_from_db() # 确保 room1 的状态是最新的
        
        details = self.scheduler._get_request_details_for_notification(request_in_queue, self.room1)
        
        self.assertEqual(details['room_id'], self.room1.id)
        self.assertEqual(details['room_number'], self.room1.room_number)
        self.assertEqual(details['current_temperature'], self.room1.current_temperature)
        self.assertEqual(details['target_temperature'], request_in_queue['target_temperature'])
        self.assertEqual(details['fan_speed'], request_in_queue['fan_speed'])
        self.assertEqual(details['ac_mode'], request_in_queue['ac_mode'])
        self.assertTrue(details['is_ac_on']) # 因为已加入请求
        self.assertEqual(details['priority'], request_in_queue['priority'])
        self.assertEqual(details['status'], request_in_queue['status']) # e.g., "SERVING" or "WAITING"
        self.assertEqual(details['is_servicing'], request_in_queue['is_servicing'])
        self.assertIsNotNone(details['request_time'])

    # 测试当房间不存在时 add_request 的行为
    @patch('hotel_ac.core.services.scheduler_service.async_to_sync')
    def test_add_request_for_non_existent_room(self, mock_async_to_sync):
        non_existent_room_number = "999"
        with self.assertLogs('hotel_ac.core.services.scheduler_service', level='ERROR') as cm:
            self.scheduler.add_request(non_existent_room_number, 20.0, "COOL", "HIGH")
        
        self.assertTrue(any(f"Room {non_existent_room_number} not found." in message for message in cm.output))
        self.assertEqual(len(self.scheduler.service_queue), 0)
        self.assertEqual(len(self.scheduler.waiting_queue), 0)
        mock_async_to_sync.assert_not_called() # 不应该发送任何通知

    # 测试 _update_room_ac_state 方法
    def test_update_room_ac_state(self):
        self.assertFalse(self.room1.is_ac_on)
        self.scheduler._update_room_ac_state(self.room1, True, 21.0, "HEAT", "MEDIUM")
        self.room1.refresh_from_db()
        
        self.assertTrue(self.room1.is_ac_on)
        self.assertEqual(self.room1.target_temperature, 21.0)
        self.assertEqual(self.room1.ac_mode, "HEAT")
        self.assertEqual(self.room1.fan_speed, "MEDIUM")

        self.scheduler._update_room_ac_state(self.room1, False)
        self.room1.refresh_from_db()
        self.assertFalse(self.room1.is_ac_on)
        # target_temp 等应保持上次设置的值，或者根据业务逻辑清空/重置

    # 测试 _create_or_update_queue_entry 方法
    def test_create_or_update_queue_entry(self):
        request_params = {
            'room_id': self.room1.id, 
            'target_temperature': 23.0, 
            'fan_speed': "LOW", 
            'ac_mode': "COOL", 
            'priority': 1,
            'status': "WAITING", # 假设这是初始状态
            'request_time': timezone.now()
        }
        
        # 创建新的 Queue entry
        queue_entry = self.scheduler._create_or_update_queue_entry(self.room1, request_params, is_active=True)
        self.assertIsNotNone(queue_entry)
        self.assertTrue(queue_entry.is_active)
        self.assertEqual(queue_entry.target_temperature, 23.0)
        self.assertEqual(Queue.objects.filter(room=self.room1, is_active=True).count(), 1)

        # 更新已存在的 Queue entry
        request_params['target_temperature'] = 20.0
        request_params['status'] = "SERVING"
        updated_entry = self.scheduler._create_or_update_queue_entry(self.room1, request_params, is_active=True, existing_queue_entry=queue_entry)
        self.assertEqual(updated_entry.id, queue_entry.id) # 应该是同一个对象
        self.assertEqual(updated_entry.target_temperature, 20.0)
        # self.assertEqual(updated_entry.status, "SERVING") # 如果Queue模型有status字段

        # 停用 Queue entry
        deactivated_entry = self.scheduler._create_or_update_queue_entry(self.room1, request_params, is_active=False, existing_queue_entry=updated_entry)
        self.assertFalse(deactivated_entry.is_active)
        self.assertIsNotNone(deactivated_entry.end_time)

    # 需要确保在 setUp 中 get_scheduler_service 被正确 patch
    # def test_singleton_behavior_is_mocked(self):
    #     s1 = get_scheduler_service()
    #     s2 = get_scheduler_service()
    #     self.assertIs(s1, self.scheduler) # 应该返回我们在 setUp 中创建和 patch 的实例
    #     self.assertIs(s2, self.scheduler)

    # 测试服务启动时 _load_pending_requests_from_db (如果实现)
    # def test_load_pending_requests_on_startup(self):
    #     # 预先创建一些 is_active=True 的 Queue 记录
    #     Queue.objects.create(room=self.room1, request_time=timezone.now(), target_temperature=20, fan_speed="HIGH", ac_mode="COOL", priority=1, is_active=True)
    #     Queue.objects.create(room=self.room2, request_time=timezone.now(), target_temperature=21, fan_speed="LOW", ac_mode="COOL", priority=2, is_active=True)
        
    #     new_scheduler = SchedulerService() # 创建一个全新的实例来测试启动加载
    #     new_scheduler.start_scheduler(load_pending=True) # 假设有此参数或默认行为
        
    #     self.assertTrue(any(r['room_id'] == self.room1.id for r in new_scheduler.service_queue + new_scheduler.waiting_queue))
    #     self.assertTrue(any(r['room_id'] == self.room2.id for r in new_scheduler.service_queue + new_scheduler.waiting_queue))
        
    #     new_scheduler.stop_scheduler()
        
    # 注意: 上述测试 load_pending_requests_on_startup 依赖于 _load_pending_requests_from_db 的具体实现
    # 以及 SchedulerService 如何在初始化时调用它。
    # 如果 _load_pending_requests_from_db 是 start_scheduler 的一部分，则测试如上。
    # 如果是 __init__ 的一部分，则创建实例时就应加载。

    # 确保在测试中使用 asyncio.run() 来运行异步方法
    # 例如，_notify_admin_monitor 和 _notify_room_status 是异步的，
    # 但它们是通过 async_to_sync 从同步代码调用的，所以 mock async_to_sync 就足够了。
    # _run_scheduler_iteration 本身是异步的，所以测试中如果直接调用它，需要 asyncio.run()


</rewritten_file> 