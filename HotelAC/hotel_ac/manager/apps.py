from django.apps import AppConfig


class ManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hotel_ac.manager'
    verbose_name = '经理报表' 