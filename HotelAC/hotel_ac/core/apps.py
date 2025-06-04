from django.apps import AppConfig
import atexit # 导入atexit模块
import sys


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hotel_ac.core'
    verbose_name = '中央空调核心'

    def ready(self):
        """在应用准备就绪时执行"""
        try:
            # 避免在manage.py的某些命令（如makemigrations）中执行
            # 因为此时可能模型还未完全加载或数据库不可用
            is_manage_py = any(arg.endswith('manage.py') for arg in sys.argv)
            is_runserver = 'runserver' in sys.argv
            is_daphne = 'daphne' in sys.argv[0] if sys.argv else False # 兼容daphne启动

            print(f"Command info: manage.py={is_manage_py}, runserver={is_runserver}, daphne={is_daphne}")
            print(f"System arguments: {sys.argv}")

            # 只在运行服务器相关的命令时启动调度器
            if (is_manage_py and is_runserver) or is_daphne:
                print("Attempting to start SchedulerService...")
                from .services import get_scheduler_service # 延迟导入
                
                # 确保在导入服务前，所有模型都已加载
                from .models import Room, Queue, ACUsage 
                print("Models imported successfully")

                scheduler = get_scheduler_service()
                print("Scheduler service instance obtained")
                
                scheduler.start_scheduler()
                print("SchedulerService started automatically via AppConfig.")

                # 确保在应用退出时优雅地停止调度器
                def stop_scheduler_on_exit():
                    try:
                        print("Shutting down SchedulerService...")
                        scheduler.stop_scheduler()
                        print("SchedulerService shutdown complete.")
                    except Exception as e:
                        print(f"Error during scheduler shutdown: {e}")
                
                atexit.register(stop_scheduler_on_exit)
                print("Registered SchedulerService shutdown hook.")
            else:
                print("SchedulerService not started (not a runserver or daphne command).")
        except Exception as e:
            print(f"Error in CoreConfig.ready(): {e}")
            import traceback
            traceback.print_exc() 