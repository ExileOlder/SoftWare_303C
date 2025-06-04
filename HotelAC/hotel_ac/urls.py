"""
URL配置
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

# 导入各个应用的views
from hotel_ac.room import views as room_views
from hotel_ac.reception import views as reception_views
from hotel_ac.admin_app import views as admin_app_views
# from hotel_ac.accounts import views as account_views # login_page_view is directly referenced below

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Accounts app URLs for login
    path('accounts/', include('hotel_ac.accounts.urls')), 

    # API路由
    path('api/room/', include('hotel_ac.room.urls')),
    path('api/admin/', include('hotel_ac.admin_app.urls')),
    path('api/reception/', include('hotel_ac.reception.urls')),
    path('api/manager/', include('hotel_ac.manager.urls')),
    path('api/core/', include('hotel_ac.core.urls')),
    
    # 页面路由
    # 客户控制面板
    # path('room/<str:room_number>/', 
    #      RedirectView.as_view(pattern_name='room_control_panel', permanent=False),
    #      name='room_redirect'), # This redirect might be less useful now with login
    path('room/<str:room_number>/control/', 
         room_views.RoomControlViewSet.as_view({'get': 'control_panel'}), 
         name='room_control_panel'),
    
    # 前台页面
    # path('reception/', 
    #      RedirectView.as_view(pattern_name='reception_dashboard', permanent=False),
    #      name='reception_redirect'), # This redirect might be less useful now
    path('reception/dashboard/', 
         reception_views.CheckInViewSet.as_view({'get': 'dashboard'}), 
         name='reception_dashboard'),
    path('reception/checkout/<str:room_number>/', 
         reception_views.CheckOutViewSet.as_view({'get': 'checkout_page'}), 
         name='checkout_page'),
    
    # 管理员页面
    # path('admin-panel/', 
    #      RedirectView.as_view(pattern_name='admin_monitor', permanent=False),
    #      name='admin_redirect'), # This redirect might be less useful now
    path('admin-panel/monitor/', 
         admin_app_views.MonitorViewSet.as_view({'get': 'monitor_page'}), 
         name='admin_monitor'),
    path('admin-panel/logs/', 
         admin_app_views.LogViewSet.as_view({'get': 'log_page'}), 
         name='admin_logs'),
    path('admin-panel/settings/', 
         admin_app_views.SettingsViewSet.as_view({'get': 'settings_page'}), 
         name='admin_settings'),
    
    # 首页指向登录页
    path('', include('hotel_ac.accounts.urls')), # This will make /login/ the effective root for now or use a specific view
    # A more direct way to set the root to the login page:
    # from hotel_ac.accounts.views import login_page_view
    # path('', login_page_view, name='home'), 
    # For now, I will make the accounts.urls available at root, and /accounts/login will be login_page
    # The login.html form posts to {% url 'login_process' %} which is in accounts.urls
    # So let's make the root path go to login_page_view directly
]

# Corrected root path:
from hotel_ac.accounts.views import login_page_view
urlpatterns.append(path('', login_page_view, name='home'))

# 在开发环境中添加静态文件和媒体文件的服务
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 