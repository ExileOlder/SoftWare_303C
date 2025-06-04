from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.contrib.auth.models import User, Group
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.sessions.models import Session
from django.views.decorators.csrf import csrf_exempt

from hotel_ac.core.models import Room, UserProfile, Guest

def login_page_view(request):
    """显示登录页面"""
    return render(request, 'accounts/login.html')

def register_page_view(request):
    """显示注册页面"""
    return render(request, 'accounts/register.html')

def register_process_view(request):
    """处理员工用户注册"""
    if request.method == 'POST':
        username = request.POST.get('username')
        real_name = request.POST.get('real_name')
        password = request.POST.get('password')
        email = request.POST.get('email', '')  # 邮箱是可选的
        role = request.POST.get('role')
        
        # 基本验证
        if not username or not real_name or not password or not role:
            messages.error(request, '请填写所有必填字段')
            return render(request, 'accounts/register.html', {'error_message': '请填写所有必填字段'})
        
        # 验证是否选择了有效的员工角色
        if role not in ['reception', 'admin', 'manager']:
            messages.error(request, '请选择有效的员工角色')
            return render(request, 'accounts/register.html', {'error_message': '请选择有效的员工角色'})
        
        # 检查用户名是否已存在
        if User.objects.filter(username=username).exists():
            messages.error(request, '用户名已存在')
            return render(request, 'accounts/register.html', {'error_message': '用户名已存在'})
        
        # 如果提供了邮箱，检查邮箱是否已存在
        if email and User.objects.filter(email=email).exists():
            messages.error(request, '邮箱已被注册')
            return render(request, 'accounts/register.html', {'error_message': '邮箱已被注册'})
        
        # 创建用户和角色信息
        try:
            with transaction.atomic():
                # 创建用户
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=real_name  # 将员工姓名保存到first_name字段
                )
                
                # 创建或获取角色组
                group, created = Group.objects.get_or_create(name=role)
                user.groups.add(group)
                
                # 创建用户资料
                UserProfile.objects.create(
                    user=user,
                    role=role
                )
                
                messages.success(request, '注册成功，请登录')
                return redirect('login_page')
                
        except Exception as e:
            messages.error(request, f'注册过程中出现错误: {str(e)}')
            return render(request, 'accounts/register.html', {'error_message': f'注册过程中出现错误: {str(e)}'})
    
    # 如果不是POST请求，返回注册页面
    return redirect('register_page')

@csrf_exempt
def login_process_view(request):
    """处理不同角色的登录请求并重定向"""
    if request.method == 'POST':
        role = request.POST.get('role')
        
        # 添加调试日志
        print(f"登录请求: 角色={role}, POST数据={request.POST}")
        
        # 基本验证
        if not role:
            messages.error(request, '请选择角色')
            print("错误: 未选择角色")
            return render(request, 'accounts/login.html', {'error_message': '请选择角色'})
        
        # 客户登录流程 - 使用房间号和姓名
        if role == 'customer':
            room_number = request.POST.get('room_number')
            guest_name = request.POST.get('guest_name')
            id_number = request.POST.get('id_number')
            
            print(f"客户登录: 房间号={room_number}, 姓名={guest_name}, 身份证号={id_number}")
            
            if not room_number or not guest_name or not id_number:
                messages.error(request, '请填写房间号、入住人姓名和身份证号')
                print("错误: 客户信息不完整")
                return render(request, 'accounts/login.html', {'error_message': '请填写房间号、入住人姓名和身份证号'})
            
            # 检查房间是否存在
            try:
                room = Room.objects.get(room_number=room_number)
                print(f"找到房间: {room.id} - {room.room_number}, 入住状态: {room.is_occupied}")
            except Room.DoesNotExist:
                messages.error(request, f'房间号 {room_number} 不存在')
                print(f"错误: 房间号 {room_number} 不存在")
                return render(request, 'accounts/login.html', {'error_message': f'房间号 {room_number} 不存在'})
            
            # 检查房间是否已入住
            if not room.is_occupied:
                messages.error(request, f'房间 {room_number} 未入住，请联系前台')
                print(f"错误: 房间 {room_number} 未入住")
                return render(request, 'accounts/login.html', {'error_message': f'房间 {room_number} 未入住，请联系前台'})
            
            # 验证入住人姓名和身份证号
            try:
                # 查看该房间的所有访客记录
                all_guests = Guest.objects.filter(room=room)
                print(f"房间 {room_number} 的访客记录数量: {all_guests.count()}")
                for i, g in enumerate(all_guests):
                    print(f"访客 {i+1}: ID={g.id}, 姓名={g.name}, 身份证号={g.id_number}, 入住时间={g.check_in_time}")
                
                # 修改为获取最新的入住记录，避免MultipleObjectsReturned错误
                guest = Guest.objects.filter(room=room).order_by('-check_in_time').first()
                if guest:
                    print(f"选择的访客记录: ID={guest.id}, 姓名={guest.name}, 身份证号={guest.id_number}")
                
                # 检查是否找到了访客记录
                if not guest:
                    messages.error(request, f'房间 {room_number} 未找到入住记录，请联系前台')
                    print(f"错误: 房间 {room_number} 未找到访客记录")
                    return render(request, 'accounts/login.html', {'error_message': f'房间 {room_number} 未找到入住记录，请联系前台'})
                
                # 严格验证姓名和身份证号是否匹配
                if guest.name != guest_name:
                    messages.error(request, f'入住人姓名不匹配，请确认后重试')
                    print(f"错误: 入住人姓名不匹配. 期望={guest.name}, 输入={guest_name}")
                    return render(request, 'accounts/login.html', {'error_message': f'入住人姓名不匹配，请确认后重试'})
                
                if guest.id_number != id_number:
                    messages.error(request, f'身份证号不匹配，请确认后重试')
                    print(f"错误: 身份证号不匹配. 期望={guest.id_number}, 输入={id_number}")
                    return render(request, 'accounts/login.html', {'error_message': f'身份证号不匹配，请确认后重试'})
                
                # 更新登录时间
                guest.save()  # 这将自动更新last_login字段，因为它有auto_now=True
                print(f"访客登录成功: {guest.name}")
                
            except Exception as e:
                messages.error(request, f'登录验证错误: {str(e)}')
                print(f"登录验证异常: {str(e)}")
                return render(request, 'accounts/login.html', {'error_message': f'登录验证错误: {str(e)}'})
            
            # 在会话中存储房间号和访客姓名
            request.session['room_number'] = room_number
            request.session['guest_name'] = guest_name
            request.session['is_authenticated'] = True
            request.session['user_role'] = 'customer'
            
            # 重定向到房间控制面板
            return redirect(reverse('room_control_panel', kwargs={'room_number': room_number}))
            
        # 员工登录流程 - 使用用户名和密码
        else:
            username = request.POST.get('username')
            password = request.POST.get('password')
            
            if not username or not password:
                messages.error(request, '请填写用户名和密码')
                return render(request, 'accounts/login.html', {'error_message': '请填写用户名和密码'})
            
            # 验证用户身份
            user = authenticate(request, username=username, password=password)
            
            if not user:
                messages.error(request, '用户名或密码错误')
                return render(request, 'accounts/login.html', {'error_message': '用户名或密码错误'})
            
            # 验证用户角色
            try:
                profile = UserProfile.objects.get(user=user)
                if profile.role != role:
                    messages.error(request, '所选角色与注册角色不符')
                    return render(request, 'accounts/login.html', {'error_message': '所选角色与注册角色不符'})
            except UserProfile.DoesNotExist:
                messages.error(request, '用户资料不存在，请联系管理员')
                return render(request, 'accounts/login.html', {'error_message': '用户资料不存在，请联系管理员'})
            
            # 登录用户
            login(request, user)
            
            # 根据角色重定向
            if role == 'reception':
                return redirect(reverse('reception_dashboard'))
            elif role == 'admin':
                return redirect(reverse('admin_monitor'))
            elif role == 'manager':
                return redirect(reverse('manager_dashboard'))
            else:
                messages.error(request, '无效的角色选择')
                return render(request, 'accounts/login.html', {'error_message': '无效的角色选择'})
    
    # 如果不是POST请求，则重定向回登录页
    return redirect(reverse('login_page'))

def logout_view(request):
    """处理用户登出"""
    # 判断登录类型
    if request.user.is_authenticated:
        # Django 认证用户登出
        logout(request)
    else:
        # 会话认证用户登出，清除会话数据
        request.session.flush()
    
    return redirect('login_page')

def clear_demo_accounts(request):
    """清除示例账户，仅限超级用户访问"""
    # 安全检查，确保只有超级用户可以执行此操作
    if not request.user.is_superuser:
        return JsonResponse({
            'status': 'error',
            'message': '只有超级用户可以执行此操作'
        }, status=403)
    
    # 要删除的示例用户名列表
    demo_usernames = ['guest1', 'guest2', 'receptionist1', 'admin1', 'manager1']
    
    try:
        # 查找匹配的用户
        users_to_delete = User.objects.filter(username__in=demo_usernames)
        count = users_to_delete.count()
        
        # 删除用户
        users_to_delete.delete()
        
        # 返回操作结果
        return JsonResponse({
            'status': 'success',
            'message': f'已成功删除 {count} 个示例账户',
            'deleted_users': demo_usernames
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'删除过程中出现错误: {str(e)}'
        }, status=500) 