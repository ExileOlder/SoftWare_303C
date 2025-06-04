from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_page_view, name='login_page'),
    path('login/process/', views.login_process_view, name='login_process'),
    path('register/', views.register_page_view, name='register_page'),
    path('register/process/', views.register_process_view, name='register_process'),
    path('logout/', views.logout_view, name='logout'),
    path('clear-demo-accounts/', views.clear_demo_accounts, name='clear_demo_accounts'),
] 