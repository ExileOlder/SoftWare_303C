import os
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_ac.settings')
django.setup()

# 导入模型
from hotel_ac.core.models import Room

def create_rooms():
    """创建初始房间"""
    # 检查是否已有房间
    if Room.objects.count() > 0:
        print("数据库中已有房间，跳过初始化...")
        return
    
    # 创建20个房间（101-120）
    for i in range(101, 121):
        room_number = f"{i}"
        Room.objects.create(
            room_number=room_number,
            is_occupied=False,
            current_temperature=25.0,
            target_temperature=25.0
        )
        print(f"创建房间: {room_number}")
    
    print(f"成功创建{20}个房间!")

if __name__ == "__main__":
    create_rooms() 