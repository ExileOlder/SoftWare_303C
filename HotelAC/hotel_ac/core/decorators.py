from functools import wraps
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required as django_login_required

def guest_login_required(view_func):
    """
    检查访客是否已登录的装饰器。
    如果访客未登录，则重定向到登录页面。
    支持两种登录方式：会话验证(客户)和Django认证(员工)
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # 首先检查Django用户是否登录
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        
        # 然后检查会话中是否包含必要的信息(客户登录)
        if request.session.get('is_authenticated'):
            return view_func(request, *args, **kwargs)
            
        # 都未登录，重定向到登录页面
        return redirect('login_page')
    return _wrapped_view

def room_access_required(view_func):
    """
    检查访客是否有权访问特定房间的装饰器。
    确保访客只能访问自己的房间控制面板。
    支持会话验证的客户角色和Django认证的用户。
    """
    @wraps(view_func)
    def _wrapped_view(request, room_number=None, *args, **kwargs):
        # 检查Django用户是否登录并有权限访问该房间
        if request.user.is_authenticated:
            # 检查用户是否有关联的profile和room_number
            if hasattr(request.user, 'profile') and request.user.profile.room_number == room_number:
                return view_func(request, room_number=room_number, *args, **kwargs)
            # 管理员、经理和前台可以访问所有房间
            elif hasattr(request.user, 'profile') and request.user.profile.role in ['admin', 'manager', 'reception']:
                return view_func(request, room_number=room_number, *args, **kwargs)
                
        # 检查会话中的房间号是否与请求的房间号匹配
        if request.session.get('is_authenticated') and request.session.get('room_number') == room_number:
            return view_func(request, room_number=room_number, *args, **kwargs)
            
        # 无权限访问，重定向到登录页面
        return redirect('login_page')
    return _wrapped_view

def staff_role_required(roles):
    """
    检查员工角色权限的装饰器。
    确保只有特定角色的员工可以访问。
    
    Args:
        roles: 字符串或字符串列表，允许访问的角色
    """
    def decorator(view_func):
        @wraps(view_func)
        @django_login_required
        def _wrapped_view(request, *args, **kwargs):
            if not hasattr(request.user, 'profile'):
                return redirect('login_page')
                
            allowed_roles = roles if isinstance(roles, list) else [roles]
            
            if request.user.profile.role not in allowed_roles:
                return redirect('login_page')
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator 