from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'statistics', views.StatisticsViewSet, basename='statistics')
router.register(r'manager', views.ManagerViewSet, basename='manager')

urlpatterns = [
    path('dashboard/', views.ManagerViewSet.as_view({'get': 'dashboard'}), name='manager_dashboard'),
    path('statistics/', views.ManagerViewSet.as_view({'get': 'statistics'}), name='manager_statistics'),
    path('reports/', views.ManagerViewSet.as_view({'get': 'reports'}), name='manager_reports'),
    path('users/', views.ManagerViewSet.as_view({'get': 'get_users'}), name='manager_users'),
    path('settings/', views.ManagerViewSet.as_view({'post': 'save_settings'}), name='manager_settings'),
    path('records/<int:pk>/', views.ManagerViewSet.as_view({'delete': 'delete_record'}), name='delete_record'),
    path('records/clear/', views.ManagerViewSet.as_view({'delete': 'clear_records'}), name='clear_records'),
]

urlpatterns += router.urls 