from django.apps import AppConfig


class AdminAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hotel_ac.admin_app'
    verbose_name = '系统管理员监控' 