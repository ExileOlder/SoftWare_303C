from django.utils import timezone
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP
import threading

from hotel_ac.core.models import Room, ACUsage, FanSpeed, ACMode

# 默认配置 (可以在 settings.py 中覆盖)
# 温度变化率 (摄氏度/秒)
# 这些值可以根据实际空调效率调整
DEFAULT_TEMP_CHANGE_RATE_COOL = getattr(settings, 'DEFAULT_TEMP_CHANGE_RATE_COOL', 0.5 / 3) # 修改为每3秒0.5度
DEFAULT_TEMP_CHANGE_RATE_HEAT = getattr(settings, 'DEFAULT_TEMP_CHANGE_RATE_HEAT', 0.6 / 3) # 修改为每3秒0.6度

# 风速对温度变化的影响因子
FAN_SPEED_TEMP_FACTOR = {
    FanSpeed.LOW: 0.8,
    FanSpeed.MEDIUM: 1.0,
    FanSpeed.HIGH: 1.2,
}

# 费用计算参数
# 基础费率 (元/秒)，可以设为0，如果费用只基于能耗
BASE_RATE_PER_SECOND = getattr(settings, 'BASE_RATE_PER_SECOND', Decimal('0.001')) # 增加基础费率
# 能耗费率 (元/单位能耗)，单位能耗可以自己定义，这里假设风速即代表一种能耗级别
ENERGY_RATE_PER_SECOND = {
    FanSpeed.LOW: getattr(settings, 'ENERGY_RATE_LOW_PER_SECOND', Decimal('1.5') / (60*3)),    # 提高费率并修改为每3秒计费
    FanSpeed.MEDIUM: getattr(settings, 'ENERGY_RATE_MEDIUM_PER_SECOND', Decimal('2.0') / (60*3)), # 提高费率并修改为每3秒计费
    FanSpeed.HIGH: getattr(settings, 'ENERGY_RATE_HIGH_PER_SECOND', Decimal('2.5') / (60*3)),   # 提高费率并修改为每3秒计费
}
# 模式对费用的影响因子 (例如，制热可能更贵)
AC_MODE_COST_FACTOR = {
    ACMode.COOL: 1.0,
    ACMode.HEAT: 1.1, 
}

DEFAULT_TARGET_TEMP_REACHED_THRESHOLD = 1.0 # 当实际温度与目标温度差小于此值时，认为已达到

# 环境因素影响
AMBIENT_TEMP_INFLUENCE_FACTOR = getattr(settings, 'AMBIENT_TEMP_INFLUENCE_FACTOR', 0.05 / 60)  # 每分钟环境温度影响因子
AMBIENT_DEFAULT_TEMPERATURE = getattr(settings, 'AMBIENT_DEFAULT_TEMPERATURE', 28.0)  # 默认环境温度（夏季）

# 能耗计算相关配置
ENERGY_PRICE_PER_UNIT_CONSUMPTION = getattr(settings, 'ENERGY_PRICE_PER_UNIT_CONSUMPTION', Decimal('0.5'))

class QueueManagerService:
    """服务队列管理，包括温度更新、费用计算等"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD = DEFAULT_TARGET_TEMP_REACHED_THRESHOLD
            self._lock = threading.RLock()  # 添加可重入锁保护共享资源

    def start_room_ac_usage(self, room: Room):
        """当房间开始使用空调时，创建或更新一条ACUsage记录"""
        with self._lock:  # 使用锁保护共享资源
            if not room.is_ac_on:
                print(f"AC for room {room.room_number} is off. Not starting usage record.")
                return None

            # 检查是否有未结束的旧记录
            existing_record = ACUsage.objects.filter(room=room, end_time__isnull=True).order_by('-start_time').first()
            if existing_record:
                print(f"Room {room.room_number} already has active usage record ID: {existing_record.id}. Using it.")
                return existing_record

            # 创建新使用记录
            try:
                usage = ACUsage.objects.create(
                    room=room,
                    start_time=timezone.now(),
                    start_temperature=room.current_temperature,
                    mode=room.ac_mode,
                    fan_speed=room.fan_speed,
                    cost=Decimal('0.0'),
                    energy_consumption=0.0
                    # energy_consumption 和 cost 会在服务过程中或结束时更新
                )
                print(f"Started AC usage record for room {room.room_number}. Usage ID: {usage.id}")
                return usage
            except Exception as e:
                print(f"Error creating AC usage record: {e}")
                return None

    def stop_room_ac_usage(self, room: Room, usage_record: ACUsage = None):
        """当房间停止使用空调或服务暂停时，结束当前的ACUsage记录"""
        with self._lock:  # 使用锁保护共享资源
            if not usage_record:
                usage_record = ACUsage.objects.filter(room=room, end_time__isnull=True).order_by('-start_time').first()
            
            if usage_record and usage_record.end_time is None:
                try:
                    # 检查记录是否已存在足够长的时间（至少5秒），避免过早关闭
                    now = timezone.now()
                    duration = (now - usage_record.start_time).total_seconds()
                    
                    if duration < 5:  # 5秒的最小计费时间
                        print(f"AC usage record {usage_record.id} for room {room.room_number} is too new ({duration} seconds). Not stopping yet.")
                        return None
                        
                    usage_record.end_time = now
                    usage_record.end_temperature = room.current_temperature
                    # 最终的费用和能耗在save方法中计算（如果尚未计算完毕）
                    usage_record.save() # 调用save会触发能耗和费用计算
                    print(f"Stopped AC usage record for room {room.room_number}. Usage ID: {usage_record.id}")
                    return usage_record
                except Exception as e:
                    print(f"Error stopping AC usage record: {e}")
                    return None
            elif usage_record:
                print(f"AC usage record {usage_record.id} for room {room.room_number} already stopped.")
                return usage_record
            else:
                print(f"No active AC usage record found for room {room.room_number} to stop.")
                return None

    def update_temperature_and_calculate_fee(self, room, time_delta):
        """
        更新房间温度并计算费用
        
        Args:
            room: 房间对象
            time_delta: 时间间隔（秒）
            
        Returns:
            tuple: (温度是否改变, 新温度)
        """
        # 如果空调未开启，不更新温度和费用
        if not room.is_ac_on:
            return False, room.current_temperature
            
        # 获取当前使用记录
        current_usage = self.get_current_usage(room)
        if not current_usage:
            # 如果没有使用记录但空调开启，创建一个
            current_usage = self.start_room_ac_usage(room)
            if not current_usage:
                return False, room.current_temperature
            
        # 计算温度变化
        # 修改为每3秒温度变化0.5度
        temp_change_per_three_seconds = 0.5
        
        # 根据风速调整温度变化速率
        if room.fan_speed == FanSpeed.LOW:
            speed_factor = 0.6
        elif room.fan_speed == FanSpeed.MEDIUM:
            speed_factor = 1.0
        else:  # HIGH
            speed_factor = 1.5
            
        # 计算实际温度变化
        # 时间因子：将秒转换为3秒单位
        time_factor = time_delta / 3
            
        actual_temp_change = temp_change_per_three_seconds * speed_factor * time_factor
        
        # 根据模式决定温度变化方向
        target_reached = False
        if room.ac_mode == ACMode.COOL:
            # 制冷模式，温度下降
            if room.current_temperature > room.target_temperature:
                new_temp = max(room.target_temperature, room.current_temperature - actual_temp_change)
                # 检查是否已达到目标温度
                target_reached = abs(new_temp - room.target_temperature) < self.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD
            else:
                # 已达到或低于目标温度，保持不变
                new_temp = room.current_temperature
                target_reached = True
        else:  # 制热模式
            # 制热模式，温度上升
            if room.current_temperature < room.target_temperature:
                # 修复：确保在制热模式下温度一定上升而不是下降
                new_temp = min(room.target_temperature, room.current_temperature + actual_temp_change)
                # 检查是否已达到目标温度
                target_reached = abs(new_temp - room.target_temperature) < self.DEFAULT_TARGET_TEMP_REACHED_THRESHOLD
            else:
                # 已达到或高于目标温度，保持不变
                new_temp = room.current_temperature
                target_reached = True
                
        # 计算费用 - 即使温度不变也要计算费用
        # 费用计算：根据风速和时间计算
        if room.fan_speed == FanSpeed.HIGH:
            rate = 1.5  # 每3秒1.5度电
        elif room.fan_speed == FanSpeed.MEDIUM:
            rate = 1.0  # 每3秒1.0度电
        else:  # LOW
            rate = 0.5  # 每3秒0.5度电
            
        # 正常计算能耗
        energy_consumed = rate * (time_factor)  # 修改为使用time_factor而不是time_delta/3
        
        # 计算费用 - 加上基础费率和能耗费率
        # 修改为使用3秒为基本计费单位，而不是每秒
        base_fee = Decimal(str(time_factor)) * (BASE_RATE_PER_SECOND * 3)
        energy_fee = Decimal(str(energy_consumed)) * (ENERGY_RATE_PER_SECOND[room.fan_speed] * 3)
        mode_factor = AC_MODE_COST_FACTOR[room.ac_mode]
        
        # 综合考虑模式和能耗计算总费用
        total_fee = (base_fee + energy_fee) * Decimal(str(mode_factor))
        
        # 确保费用增长速度更快
        total_fee = total_fee * Decimal('1.5')
        
        # 确保每次调用此方法都增加费用
        if current_usage:
            try:
                # 获取最新的使用记录以确保数据一致性
                fresh_usage = ACUsage.objects.get(id=current_usage.id)
            
                # 计算新的总费用和能耗
                new_cost = Decimal(fresh_usage.cost) + total_fee.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                new_energy = float(fresh_usage.energy_consumption) + float(energy_consumed)
                
                # 使用原子操作更新费用和能耗
                ACUsage.objects.filter(id=current_usage.id).update(
                    cost=new_cost,
                    energy_consumption=new_energy
                )
                print(f"Room {room.room_number} - Added fee: {total_fee}, total: {new_cost}")
                
                # 更新当前使用记录的内存值，确保后续操作使用最新数据
                current_usage.cost = new_cost
                current_usage.energy_consumption = new_energy
            except Exception as e:
                print(f"Error updating usage fees: {e}")
                import traceback
                traceback.print_exc()
        
        # 更新房间温度并返回结果
        if room.current_temperature != new_temp:
            room.current_temperature = new_temp
            room.save(update_fields=['current_temperature'])
            return True, new_temp
        
        return False, room.current_temperature

    def _update_ambient_temperature(self, room: Room, time_delta_seconds: int):
        """更新房间环境温度 (空调关闭时的温度)"""
        # 获取当前季节和外界温度
        current_datetime = timezone.now()
        season_temperature = self._get_season_temperature(current_datetime)
        
        # 计算温度变化
        current_temp = room.current_temperature
        ambient_change = self._calculate_ambient_influence(room, time_delta_seconds, current_temp)
        
        # 温度向季节温度趋近
        if current_temp < season_temperature:
            new_temp = min(season_temperature, current_temp + ambient_change)
        else:
            new_temp = max(season_temperature, current_temp - ambient_change)
            
        # 更新房间温度
        room.current_temperature = new_temp
        room.save(update_fields=['current_temperature'])
        
        return True, new_temp
    
    def _get_season_temperature(self, current_datetime):
        """
        根据当前日期获取季节温度
        这个方法在原代码中被调用但未实现，添加该方法以修复错误
        """
        # 简单起见，使用默认的环境温度
        return AMBIENT_DEFAULT_TEMPERATURE
    
    def _calculate_ambient_influence(self, room: Room, time_delta_seconds: int, current_temp: float):
        """计算环境对正在工作的空调的影响"""
        ambient_temp = AMBIENT_DEFAULT_TEMPERATURE
        
        # 环境影响因子（较弱，因为空调正在工作）
        influence_factor = AMBIENT_TEMP_INFLUENCE_FACTOR * 0.2
        
        if abs(ambient_temp - current_temp) > 5.0:
            # 如果温差很大，环境影响会更强
            direction = 1 if ambient_temp > current_temp else -1
            return direction * influence_factor * time_delta_seconds
        
        return 0.0

    def calculate_bill(self, room: Room, check_in_time, check_out_time=None):
        """计算指定房间在给定时间段内的账单"""
        if not check_out_time:
            check_out_time = timezone.now()
            
        # 获取该房间在指定时间段内的所有空调使用记录
        usages = ACUsage.objects.filter(
            room=room,
            start_time__gte=check_in_time,
            start_time__lte=check_out_time
        ).order_by('start_time')
        
        # 计算总费用和总能耗
        total_cost = Decimal('0.00')
        total_energy = 0.0
        total_duration = 0  # 总使用时间（秒）
        
        for usage in usages:
            # 确保每条记录都有结束时间
            end_time = usage.end_time if usage.end_time else check_out_time
            
            # 计算使用时长
            duration = (end_time - usage.start_time).total_seconds()
            total_duration += duration
            
            # 累加费用和能耗
            if usage.cost is not None:
                total_cost += usage.cost
            if usage.energy_consumption is not None:
                total_energy += usage.energy_consumption
        
        # 将未结算的记录标记为已结算
        usages.update(is_billed=True)
        
        # 返回账单信息
        return {
            'room_number': room.room_number,
            'check_in_time': check_in_time,
            'check_out_time': check_out_time,
            'total_cost': total_cost,
            'total_energy': total_energy,
            'total_duration': total_duration,
            'usage_count': usages.count()
        }

    def get_current_usage(self, room):
        """获取房间当前的空调使用记录"""
        return ACUsage.objects.filter(room=room, end_time__isnull=True).order_by('-start_time').first()

# 可以在settings.py中配置ENERGY_PRICE_PER_UNIT_CONSUMPTION，例如：
# ENERGY_PRICE_PER_UNIT_CONSUMPTION = Decimal('0.5') # 每单位能耗0.5元 (假设单位是kWh) 