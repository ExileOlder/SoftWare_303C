from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, datetime
from unittest.mock import patch, MagicMock

from hotel_ac.core.models import Room, Queue, ACUsage, Bill
from hotel_ac.core.services.queue_manager_service import QueueManagerService
from hotel_ac.core.services.scheduler_service import get_scheduler_service # 如果需要交互

class QueueManagerServiceTests(TestCase):
    def setUp(self):
        self.queue_manager = QueueManagerService() # 直接实例化进行测试

        # 创建测试房间和队列记录
        self.room1 = Room.objects.create(
            room_number="101", 
            current_temperature=25.0, 
            target_temperature=22.0, 
            ac_mode="COOL", 
            fan_speed="HIGH",
            is_ac_on=True
        )
        self.queue1 = Queue.objects.create(
            room=self.room1,
            request_time=timezone.now() - timedelta(minutes=30),
            target_temperature=22.0,
            fan_speed="HIGH",
            ac_mode="COOL",
            priority=1,
            is_active=True # 假设这是一个活动的服务请求
        )
        
        # 确保 get_scheduler_service 被mock掉，以避免其在测试中意外运行或影响
        # (如果 QueueManagerService 内部直接调用了 get_scheduler_service().settings 或者类似)
        self.scheduler_patcher = patch('hotel_ac.core.services.queue_manager_service.get_scheduler_service')
        self.mock_get_scheduler = self.scheduler_patcher.start()
        # 配置mock_scheduler的返回值，使其有一个settings属性
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.settings = {
            'price_per_degree_high': 0.1,
            'price_per_degree_medium': 0.08,
            'price_per_degree_low': 0.05,
            'max_service_temp_diff_low': 1.0, #一度以内低风档
            'max_service_temp_diff_medium': 2.0, #二度以内中风档
        }
        self.mock_get_scheduler.return_value = mock_scheduler_instance


    def tearDown(self):
        self.scheduler_patcher.stop()

    def test_start_ac_usage_record(self):
        """测试开始空调使用记录的创建"""
        initial_usage_count = ACUsage.objects.count()
        
        usage_record = self.queue_manager.start_ac_usage_record(
            room_id=self.room1.id,
            queue_id=self.queue1.id,
            start_temp=self.room1.current_temperature,
            target_temp=self.queue1.target_temperature,
            fan_speed=self.queue1.fan_speed,
            ac_mode=self.queue1.ac_mode
        )
        
        self.assertIsNotNone(usage_record)
        self.assertEqual(ACUsage.objects.count(), initial_usage_count + 1)
        self.assertEqual(usage_record.room, self.room1)
        self.assertEqual(usage_record.queue_request, self.queue1)
        self.assertEqual(usage_record.fan_speed, self.queue1.fan_speed)
        self.assertEqual(usage_record.ac_mode, self.queue1.ac_mode)
        self.assertEqual(usage_record.start_temperature, self.room1.current_temperature)
        self.assertEqual(usage_record.target_temperature, self.queue1.target_temperature)
        self.assertIsNotNone(usage_record.start_time)
        self.assertIsNone(usage_record.end_time)
        self.assertEqual(usage_record.total_cost, 0)

    def test_stop_ac_usage_record_calculates_cost_and_duration(self):
        """测试停止空调使用记录会计算费用和时长，并创建账单条目"""
        # 先创建一个使用记录
        usage_record = self.queue_manager.start_ac_usage_record(
            room_id=self.room1.id,
            queue_id=self.queue1.id,
            start_temp=25.0,
            target_temp=22.0,
            fan_speed="HIGH",
            ac_mode="COOL"
        )
        self.assertIsNone(usage_record.end_time)
        initial_bill_count = Bill.objects.count()

        # 模拟一段时间的使用
        usage_record.start_time = timezone.now() - timedelta(minutes=10) # 假设服务了10分钟
        usage_record.save()
        
        # 模拟温度变化和费用计算 (stop_ac_usage_record 内部会调用 _calculate_cost)
        # 为了测试 _calculate_cost 的效果，我们需要确保其使用的费率是可预测的
        # 假设在 "HIGH" fan_speed, COOL mode, 每分钟 (或每次调用) 产生特定费用
        # 这里我们不直接测试 _calculate_cost 的内部细节，而是其对 usage_record 的影响
        
        # 模拟服务结束时的温度
        final_temp = 22.0
        self.room1.current_temperature = final_temp
        self.room1.save()

        updated_usage_record = self.queue_manager.stop_ac_usage_record(
            room_id=self.room1.id,
            queue_id=self.queue1.id
        )
        
        self.assertIsNotNone(updated_usage_record)
        self.assertIsNotNone(updated_usage_record.end_time)
        self.assertGreater(updated_usage_record.duration_minutes, 0) # 应该有服务时长
        self.assertGreater(updated_usage_record.total_cost, 0) # 应该产生费用
        self.assertEqual(updated_usage_record.end_temperature, final_temp)
        
        # 验证账单条目是否创建
        self.assertEqual(Bill.objects.count(), initial_bill_count + 1)
        bill_entry = Bill.objects.latest('id')
        self.assertEqual(bill_entry.room, self.room1)
        self.assertEqual(bill_entry.ac_usage, updated_usage_record)
        self.assertEqual(bill_entry.amount, updated_usage_record.total_cost)
        self.assertFalse(bill_entry.is_paid)

    def test_stop_ac_usage_record_no_active_usage(self):
        """测试当没有活动的 ACUsage 记录时，stop_ac_usage_record 的行为"""
        # 确保没有与 room1 和 queue1 相关的活动 ACUsage
        ACUsage.objects.filter(room=self.room1, queue_request=self.queue1, end_time__isnull=True).delete()
        
        updated_usage_record = self.queue_manager.stop_ac_usage_record(
            room_id=self.room1.id,
            queue_id=self.queue1.id
        )
        self.assertIsNone(updated_usage_record) # 不应返回记录，或应有错误处理

    # _calculate_cost 的测试比较复杂，因为它依赖于模拟的时间流逝和温度变化
    # 以及与 SchedulerService 的费率设置。这里我们只做一个基本集成测试。
    def test_calculate_cost_integration_in_stop_record(self):
        usage = ACUsage.objects.create(
            room=self.room1,
            queue_request=self.queue1,
            start_time=timezone.now() - timedelta(minutes=5),
            start_temperature=26.0,
            target_temperature=22.0,
            fan_speed="HIGH",
            ac_mode="COOL"
        )
        # 假设HIGH风速，每分钟（或每次模拟迭代）成本为 X
        # SchedulerService 的模拟设置是 price_per_degree_high = 0.1
        # _calculate_cost 基于温度变化和风速档位价格
        # 假设温度从26降到22，变化了4度。
        # 费用 = 4度 * 0.1/度 = 0.4 (如果按总温差一次性计算)
        # 或者，如果按时间片逐步计算，则需要更复杂的模拟
        
        # 当前 _calculate_cost 实现是基于 duration_minutes 和 fan_speed 的费率
        # 它不是基于温度变化的，这可能需要调整模型或测试
        # 假设 scheduler_service.settings['price_high_fan'] = 1.0 (每分钟)
        # 为了让这个测试有意义，我们需要让 _get_current_price_rate 返回一个已知值
        
        with patch.object(self.queue_manager, '_get_current_price_rate', return_value=1.0): # 假设每分钟1元
            usage = self.queue_manager.stop_ac_usage_record(self.room1.id, self.queue1.id, current_temp=22.0)
        
        self.assertIsNotNone(usage)
        self.assertAlmostEqual(usage.duration_minutes, 5.0, delta=0.1)
        self.assertAlmostEqual(usage.total_cost, 5.0 * 1.0, delta=0.01) # 5 分钟 * 1元/分钟


    def test_calculate_room_bill_for_period(self):
        """测试计算指定房间在某时间段内的总账单"""
        now = timezone.now()
        usage1_start_time = now - timedelta(days=2, hours=1)
        usage1_end_time = now - timedelta(days=2)
        usage2_start_time = now - timedelta(days=1, hours=1)
        usage2_end_time = now - timedelta(days=1)
        usage3_start_time = now - timedelta(hours=1) # 在时间段内，但属于其他房间
        usage3_end_time = now

        room2 = Room.objects.create(room_number="102")

        # 创建一些 ACUsage 和 Bill 记录
        u1 = ACUsage.objects.create(room=self.room1, queue_request=self.queue1, start_time=usage1_start_time, end_time=usage1_end_time, total_cost=10.0)
        Bill.objects.create(room=self.room1, ac_usage=u1, amount=10.0, created_at=usage1_end_time)
        
        u2 = ACUsage.objects.create(room=self.room1, queue_request=self.queue1, start_time=usage2_start_time, end_time=usage2_end_time, total_cost=15.0)
        Bill.objects.create(room=self.room1, ac_usage=u2, amount=15.0, created_at=usage2_end_time)

        u3 = ACUsage.objects.create(room=room2, start_time=usage3_start_time, end_time=usage3_end_time, total_cost=5.0)
        Bill.objects.create(room=room2, ac_usage=u3, amount=5.0, created_at=usage3_end_time)

        # 时间段覆盖 u1 和 u2
        period_start = now - timedelta(days=3)
        period_end = now - timedelta(hours=12) # 在u2之后，在u3之前
        
        total_bill, bill_details = self.queue_manager.calculate_room_bill_for_period(self.room1.id, period_start, period_end)
        
        self.assertEqual(total_bill, 25.0) # 10.0 + 15.0
        self.assertEqual(len(bill_details), 2)
        self.assertIn(u1, [b.ac_usage for b in bill_details])
        self.assertIn(u2, [b.ac_usage for b in bill_details])

        # 时间段不覆盖任何账单
        period_start_no_bill = now + timedelta(days=1)
        period_end_no_bill = now + timedelta(days=2)
        total_bill_none, bill_details_none = self.queue_manager.calculate_room_bill_for_period(self.room1.id, period_start_no_bill, period_end_no_bill)
        self.assertEqual(total_bill_none, 0)
        self.assertEqual(len(bill_details_none), 0)
        
    def test_get_current_price_rate(self):
        """测试获取当前费率的逻辑"""
        # HIGH 风速
        rate_high = self.queue_manager._get_current_price_rate(self.room1, fan_speed="HIGH", ac_mode="COOL")
        self.assertEqual(rate_high, self.mock_get_scheduler.return_value.settings['price_per_degree_high'])
        
        # MEDIUM 风速 (假设当前温度与目标温度差在 medium 范围内)
        self.room1.current_temperature = 23.5 # 目标 22, 差 1.5 (在 1 到 2 之间 -> medium)
        self.room1.save()
        rate_medium = self.queue_manager._get_current_price_rate(self.room1, fan_speed="MEDIUM", ac_mode="COOL") # fan_speed 参数优先
        self.assertEqual(rate_medium, self.mock_get_scheduler.return_value.settings['price_per_degree_medium'])
        
        # 自动判断风速档位（不传 fan_speed）
        rate_auto_medium = self.queue_manager._get_current_price_rate(self.room1, ac_mode="COOL") # fan_speed=None
        self.assertEqual(rate_auto_medium, self.mock_get_scheduler.return_value.settings['price_per_degree_medium'])

        # LOW 风速
        self.room1.current_temperature = 22.5 # 目标 22, 差 0.5 (小于 1 -> low)
        self.room1.save()
        rate_low = self.queue_manager._get_current_price_rate(self.room1, fan_speed="LOW", ac_mode="COOL") # fan_speed 参数优先
        self.assertEqual(rate_low, self.mock_get_scheduler.return_value.settings['price_per_degree_low'])

        rate_auto_low = self.queue_manager._get_current_price_rate(self.room1, ac_mode="COOL") # fan_speed=None
        self.assertEqual(rate_auto_low, self.mock_get_scheduler.return_value.settings['price_per_degree_low'])
        
        # 默认/最大风速档 （温差较大）
        self.room1.current_temperature = 25.0 # 目标 22, 差 3.0 (大于 2 -> high)
        self.room1.save()
        rate_auto_high = self.queue_manager._get_current_price_rate(self.room1, ac_mode="COOL")
        self.assertEqual(rate_auto_high, self.mock_get_scheduler.return_value.settings['price_per_degree_high'])

    # _simulate_temperature_change_and_calculate_cost 的测试较为复杂，因为它涉及到状态的改变和时间。
    # 它的主要职责是更新房间温度，并基于此计算费用片段。
    # 单元测试中可以mock其依赖，例如时间流逝和费率。

    # 这里可以添加一个简单的测试，确保它至少被 stop_ac_usage_record 调用（如果适用）
    # 或者测试它是否正确地更新了 ACUsage 记录中的某些字段（如果它直接修改的话）
    # 但目前 stop_ac_usage_record 直接计算总费用，而不是依赖 simulate。
    # simulate 方法更可能在 SchedulerService 的主循环中被调用。
    
    # 如果 QueueManagerService 负责周期性更新服务中房间的费用和温度，则需要相应测试。
    # 目前看，QueueManagerService 主要是记录开始/结束，并计算最终费用。
    # 实时温度模拟和费用计算似乎在 SchedulerService 的 _run_scheduler_iteration 中处理了一部分。 