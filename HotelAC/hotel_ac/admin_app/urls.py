from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'monitor', views.MonitorViewSet, basename='monitor')
router.register(r'logs', views.LogViewSet, basename='logs')
router.register(r'settings', views.SettingsViewSet, basename='settings')

urlpatterns = [
    path('', include(router.urls)),
] 