#!/usr/bin/env python
"""
从SQLite迁移数据到MySQL的辅助脚本
使用方法：
1. 先确保您的MySQL数据库已经创建
2. 在settings.py中配置好MySQL连接信息
3. 运行此脚本：python migrate_to_mysql.py
"""

import os
import sys
import traceback
import django
import MySQLdb
from django.conf import settings
from django.core.management import call_command

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_ac.settings')
django.setup()

def main():
    print("开始迁移数据库从SQLite到MySQL...")
    print(f"当前数据库配置：")
    print(f"  - 引擎: {settings.DATABASES['default']['ENGINE']}")
    print(f"  - 数据库名: {settings.DATABASES['default']['NAME']}")
    print(f"  - 用户名: {settings.DATABASES['default']['USER']}")
    print(f"  - 主机: {settings.DATABASES['default']['HOST']}")
    print(f"  - 端口: {settings.DATABASES['default']['PORT']}")
    
    # 检查MySQL连接
    try:
        print("尝试连接MySQL...")
        conn = MySQLdb.connect(
            host=settings.DATABASES['default']['HOST'],
            user=settings.DATABASES['default']['USER'],
            passwd=settings.DATABASES['default']['PASSWORD'],
            port=int(settings.DATABASES['default']['PORT'])
        )
        conn.close()
        print("MySQL连接成功!")
    except Exception as e:
        print(f"MySQL连接失败: {e}")
        print("详细错误信息:")
        traceback.print_exc()
        print("\n请检查settings.py中的数据库配置，确保用户名和密码正确。")
        return False

    # 创建数据库（如果不存在）
    try:
        print("\n尝试创建数据库...")
        conn = MySQLdb.connect(
            host=settings.DATABASES['default']['HOST'],
            user=settings.DATABASES['default']['USER'],
            passwd=settings.DATABASES['default']['PASSWORD'],
            port=int(settings.DATABASES['default']['PORT'])
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {settings.DATABASES['default']['NAME']} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        conn.close()
        print(f"成功创建或确认数据库 {settings.DATABASES['default']['NAME']} 存在!")
    except Exception as e:
        print(f"创建数据库失败: {e}")
        print("详细错误信息:")
        traceback.print_exc()
        return False

    # 连接到新创建的数据库
    try:
        print("\n尝试连接到新创建的数据库...")
        conn = MySQLdb.connect(
            host=settings.DATABASES['default']['HOST'],
            user=settings.DATABASES['default']['USER'],
            passwd=settings.DATABASES['default']['PASSWORD'],
            port=int(settings.DATABASES['default']['PORT']),
            db=settings.DATABASES['default']['NAME']
        )
        conn.close()
        print(f"成功连接到数据库 {settings.DATABASES['default']['NAME']}!")
    except Exception as e:
        print(f"连接数据库失败: {e}")
        print("详细错误信息:")
        traceback.print_exc()
        return False

    # 运行迁移
    try:
        print("\n正在执行数据库迁移...")
        call_command('migrate')
        print("数据库迁移成功完成!")
        return True
    except Exception as e:
        print(f"数据库迁移失败: {e}")
        print("详细错误信息:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ 所有操作成功完成!")
    else:
        print("\n❌ 操作失败，请检查以上错误信息。") 