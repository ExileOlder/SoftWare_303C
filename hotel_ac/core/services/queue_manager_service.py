# 环境因素影响
AMBIENT_TEMP_INFLUENCE_FACTOR = getattr(settings, 'AMBIENT_TEMP_INFLUENCE_FACTOR', 0.05 / 60)  # 每分钟环境温度影响因子

ENERGY_PRICE_PER_UNIT_CONSUMPTION = getattr(settings, 'ENERGY_PRICE_PER_UNIT_CONSUMPTION', Decimal('0.5'))

class QueueManagerService:
    """服务队列管理，包括温度更新、费用计算等"""
    DEFAULT_TARGET_TEMP_REACHED_THRESHOLD = 0.1 # 设为类属性，方便外部访问
    _instance = None
    _lock = threading.Lock()