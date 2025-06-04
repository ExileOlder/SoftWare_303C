"""
重置数据库并创建初始数据
"""
import os
import django
import sys

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_ac.settings')
django.setup()

from django.db import connection
from django.contrib.auth.models import User, Group
from hotel_ac.core.models import Room, UserProfile

def reset_database():
    """清空数据库并重新创建基础数据"""
    # 确认操作
    confirm = input("此操作将清空所有数据并重新初始化数据库。是否继续? (y/n): ")
    if confirm.lower() != 'y':
        print("操作已取消")
        return
    
    # 获取所有表名
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'django_migrations';")
        tables = [row[0] for row in cursor.fetchall()]
    
    # 清空表数据
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys = OFF;")
        for table in tables:
            print(f"清空表: {table}")
            cursor.execute(f"DELETE FROM {table};")
        cursor.execute("PRAGMA foreign_keys = ON;")
    
    # 重置SQLite序列
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}';")
    
    print("数据库已清空")
    
    # 创建基础数据
    create_initial_data()

def create_initial_data():
    """创建初始数据"""
    # 创建角色组
    roles = ['reception', 'admin', 'manager']
    for role in roles:
        Group.objects.get_or_create(name=role)
    print("已创建角色组")
    
    # 创建房间
    for i in range(101, 121):
        room_number = f"{i}"
        Room.objects.create(
            room_number=room_number,
            is_occupied=False,
            current_temperature=25.0,
            target_temperature=25.0
        )
    print("已创建20个房间 (101-120)")
    
    # 创建超级管理员
    if not User.objects.filter(username='admin').exists():
        admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123456',
            first_name='系统管理员'
        )
        # 创建对应的用户资料
        UserProfile.objects.create(
            user=admin_user,
            role='admin'
        )
        print("已创建超级管理员账号 (用户名: admin, 密码: admin123456)")
    
    print("初始化数据完成！")

if __name__ == "__main__":
    reset_database() 