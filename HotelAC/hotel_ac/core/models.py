from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from decimal import Decimal, ROUND_HALF_UP


class ACMode(models.TextChoices):
    """空调模式选项"""
    COOL = 'COOL', '制冷'
    HEAT = 'HEAT', '制热'


class FanSpeed(models.TextChoices):
    """风速选项"""
    LOW = 'LOW', '低速'
    MEDIUM = 'MEDIUM', '中速'
    HIGH = 'HIGH', '高速'


class Room(models.Model):
    """房间模型"""
    room_number = models.CharField(max_length=10, unique=True, verbose_name='房间号')
    is_occupied = models.BooleanField(default=False, verbose_name='是否入住')
    current_temperature = models.FloatField(
        default=26.0, 
        validators=[MinValueValidator(16.0), MaxValueValidator(30.0)],
        verbose_name='当前温度'
    )
    target_temperature = models.FloatField(
        default=26.0, 
        validators=[MinValueValidator(16.0), MaxValueValidator(30.0)],
        verbose_name='目标温度'
    )
    ac_mode = models.CharField(
        max_length=10,
        choices=ACMode.choices,
        default=ACMode.COOL,
        verbose_name='空调模式'
    )
    fan_speed = models.CharField(
        max_length=10,
        choices=FanSpeed.choices,
        default=FanSpeed.MEDIUM,
        verbose_name='风速'
    )
    is_ac_on = models.BooleanField(default=False, verbose_name='空调状态')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '房间'
        verbose_name_plural = '房间'
        ordering = ['room_number']

    def __str__(self):
        return f"房间 {self.room_number}"


class Guest(models.Model):
    """访客模型"""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='guests', verbose_name='房间')
    name = models.CharField(max_length=50, verbose_name='访客姓名')
    id_number = models.CharField(max_length=18, verbose_name='身份证号', default='')
    check_in_time = models.DateTimeField(auto_now_add=True, verbose_name='登记时间')
    check_out_time = models.DateTimeField(null=True, blank=True, verbose_name='退房时间')
    last_login = models.DateTimeField(auto_now=True, verbose_name='最后登录时间')
    check_in_count = models.IntegerField(default=1, verbose_name='入住次数')
    
    class Meta:
        verbose_name = '访客'
        verbose_name_plural = '访客'
        ordering = ['-last_login']
    
    def __str__(self):
        return f"{self.name} - 房间 {self.room.room_number}"


class QueuePriority(models.TextChoices):
    """队列优先级选项"""
    LOW = 'LOW', '低'
    MEDIUM = 'MEDIUM', '中'
    HIGH = 'HIGH', '高'


class Queue(models.Model):
    """服务队列模型"""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='queue_requests', verbose_name='房间')
    priority = models.CharField(
        max_length=10,
        choices=QueuePriority.choices,
        default=QueuePriority.MEDIUM,
        verbose_name='优先级'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否活跃')
    target_temperature = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(16.0), MaxValueValidator(30.0)],
        verbose_name='请求目标温度'
    )
    fan_speed = models.CharField(
        max_length=10,
        choices=FanSpeed.choices,
        null=True, blank=True,
        verbose_name='请求风速'
    )
    ac_mode = models.CharField(
        max_length=10,
        choices=ACMode.choices,
        null=True, blank=True,
        verbose_name='请求模式'
    )
    request_time = models.DateTimeField(default=timezone.now, verbose_name='请求时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='记录创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='记录更新时间')

    class Meta:
        verbose_name = '服务队列请求'
        verbose_name_plural = '服务队列请求'
        ordering = ['priority', 'request_time']

    def __str__(self):
        return f"队列请求 {self.room.room_number} ({self.priority}) @ {self.request_time.strftime('%Y-%m-%d %H:%M')}"


class ACUsage(models.Model):
    """空调使用记录模型"""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='ac_usages', verbose_name='房间')
    start_time = models.DateTimeField(verbose_name='开始时间')
    end_time = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    start_temperature = models.FloatField(verbose_name='起始温度')
    end_temperature = models.FloatField(null=True, blank=True, verbose_name='结束温度')
    mode = models.CharField(
        max_length=10,
        choices=ACMode.choices,
        verbose_name='模式'
    )
    fan_speed = models.CharField(
        max_length=10,
        choices=FanSpeed.choices,
        verbose_name='风速'
    )
    duration = models.DurationField(null=True, blank=True, verbose_name='持续时间')
    energy_consumption = models.FloatField(default=0.0, verbose_name='能耗(kWh)')
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name='费用')
    is_billed = models.BooleanField(default=False, verbose_name='是否已结算')

    class Meta:
        verbose_name = '空调使用记录'
        verbose_name_plural = '空调使用记录'
        ordering = ['-start_time']

    def __str__(self):
        return f"使用记录 {self.room.room_number} - {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}"

    def save(self, *args, **kwargs):
        # 计算持续时间
        if self.end_time and self.start_time:
            self.duration = self.end_time - self.start_time
        elif self.start_time:
            # 对于正在进行中的使用，计算临时持续时间
            self.duration = timezone.now() - self.start_time
            
        # 注意：费用计算已经在QueueManagerService.update_temperature_and_calculate_fee中完成
        # 这里不再重复计算费用，避免费用被重复累加
        
        super().save(*args, **kwargs)


class Bill(models.Model):
    """账单模型"""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='bills', verbose_name='房间')
    check_in_time = models.DateTimeField(verbose_name='入住时间')
    check_out_time = models.DateTimeField(null=True, blank=True, verbose_name='退房时间')
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name='总费用')
    is_paid = models.BooleanField(default=False, verbose_name='是否已支付')
    payment_time = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '账单'
        verbose_name_plural = '账单'
        ordering = ['-check_in_time']

    def __str__(self):
        return f"账单 {self.room.room_number} - {self.check_in_time.strftime('%Y-%m-%d')}"

    def calculate_total(self):
        """计算总费用"""
        # 获取该房间在入住期间的所有空调使用记录
        usages = ACUsage.objects.filter(
            room=self.room,
            start_time__gte=self.check_in_time,
            is_billed=False
        )
        
        # 如果已经退房，则只计算退房前的记录
        if self.check_out_time:
            usages = usages.filter(start_time__lt=self.check_out_time)
            
        # 计算总费用
        total = sum(usage.cost for usage in usages)
        self.total_cost = total
        
        # 标记这些使用记录为已结算
        for usage in usages:
            usage.is_billed = True
            usage.save()
            
        return self.total_cost


class UserProfile(models.Model):
    """用户资料模型，扩展Django内置User模型"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=[
        ('customer', '客户'),
        ('reception', '前台'),
        ('admin', '管理员'),
        ('manager', '经理'),
    ])
    room_number = models.CharField(max_length=10, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})" 