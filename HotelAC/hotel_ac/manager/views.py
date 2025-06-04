from rest_framework import viewsets, status
from rest_framework.response import Response
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import action
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.db.models import Sum, Avg, Count, F, ExpressionWrapper, DurationField, Case, When, Value, CharField, DecimalField
from django.db.models.functions import TruncDate, TruncHour, TruncDay, TruncMonth, TruncWeek, Cast
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db.models.deletion import transaction

from hotel_ac.core.models import Room, ACUsage, Queue, Guest, UserProfile, Bill, ACMode, FanSpeed

# 稍后会实现具体视图
class ReportViewSet(viewsets.ViewSet):
    """报表视图集"""
    pass

class StatisticsViewSet(viewsets.ViewSet):
    """统计视图集"""
    pass 

class ManagerViewSet(viewsets.ViewSet):
    """经理管理视图集"""
    
    # 为整个视图集添加CSRF豁免
    @method_decorator(csrf_exempt, name='dispatch')
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_dashboard_card_statistics(self):
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Today's total revenue from finalized bills or ACUsage for ongoing stays
        daily_revenue_today = Bill.objects.filter(
            payment_time__date=today
        ).aggregate(total=Sum('total_cost'))['total'] or 0
        # Add cost from AC usages not yet billed for today
        # This logic might need refinement based on how revenue is truly calculated
        # For simplicity, let's stick to billed revenue for today or sum of AC costs
        current_ac_costs_today = ACUsage.objects.filter(
            start_time__date=today, is_billed=False, cost__isnull=False
        ).aggregate(total=Sum('cost'))['total'] or 0
        # Let's assume daily_revenue is based on ACUsage for simplicity as in dashboard cards
        daily_revenue_today = ACUsage.objects.filter(
             start_time__date=today, cost__isnull=False
        ).aggregate(total_revenue=Sum('cost'))['total_revenue'] or 0


        daily_revenue_yesterday = ACUsage.objects.filter(
            start_time__date=yesterday,
            cost__isnull=False
        ).aggregate(total_revenue=Sum('cost'))['total_revenue'] or 0
        
        revenue_change_percentage = 0
        if daily_revenue_yesterday > 0:
            revenue_change_percentage = ((float(daily_revenue_today) - float(daily_revenue_yesterday)) / float(daily_revenue_yesterday)) * 100
        elif daily_revenue_today > 0:
            revenue_change_percentage = 100

        total_rooms = Room.objects.count()
        occupied_rooms_count = Room.objects.filter(is_occupied=True).count()
        occupancy_rate = (occupied_rooms_count / total_rooms) * 100 if total_rooms > 0 else 0

        ac_on_rooms_count = Room.objects.filter(is_ac_on=True).count()
        # AC usage rate could be defined as rooms with AC on / occupied rooms, or / total rooms.
        # The dashboard showed "15 间客房正在使用空调", let's use ac_on_rooms_count for the direct number.
        # The percentage can be ac_on_rooms_count / total_rooms
        ac_usage_percentage = (ac_on_rooms_count / total_rooms) * 100 if total_rooms > 0 else 0
        
        # Average AC cost: total AC cost today / number of occupied rooms that used AC today
        occupied_rooms_that_used_ac_today = ACUsage.objects.filter(
            start_time__date=today, cost__isnull=False, cost__gt=0
        ).values('room_id').distinct().count()

        average_ac_cost_per_room_today = (float(daily_revenue_today) / occupied_rooms_that_used_ac_today) if occupied_rooms_that_used_ac_today > 0 else 0

        return {
            'today_total_revenue': float(daily_revenue_today),
            'revenue_change_percentage': round(revenue_change_percentage, 1),
            'room_occupancy_rate': round(occupancy_rate, 0),
            'occupied_rooms_count': occupied_rooms_count,
            'total_rooms': total_rooms,
            'ac_on_rooms_count': ac_on_rooms_count,
            'ac_usage_percentage': round(ac_usage_percentage, 0), # Example: (15/20)*100 = 75%
            'average_ac_cost_per_room': round(average_ac_cost_per_room_today, 2)
        }

    def get_chart_data(self, period='week'):
        """获取图表所需数据"""
        today = date.today()
        revenue_labels = []
        revenue_data = []
        usage_labels_mode = [dict(ACMode.choices).get(ACMode.COOL), dict(ACMode.choices).get(ACMode.HEAT)]
        usage_data_mode = [0, 0]
        usage_labels_fan = [dict(FanSpeed.choices).get(FanSpeed.LOW), dict(FanSpeed.choices).get(FanSpeed.MEDIUM), dict(FanSpeed.choices).get(FanSpeed.HIGH)]
        usage_data_fan = [0, 0, 0]

        # Revenue Chart Data
        if period == 'day':
            start_dt = datetime.combine(today, datetime.min.time())
            for i in range(24): # Hourly for the current day
                hour_start = start_dt + timedelta(hours=i)
                hour_end = start_dt + timedelta(hours=i+1)
                hourly_revenue = ACUsage.objects.filter(
                    start_time__gte=hour_start, start_time__lt=hour_end, cost__isnull=False
                ).aggregate(total=Sum('cost'))['total'] or 0
                revenue_labels.append(f'{i:02d}:00')
                revenue_data.append(float(hourly_revenue))
        elif period == 'week':
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                daily_revenue = ACUsage.objects.filter(
                    start_time__date=day, cost__isnull=False
                ).aggregate(total=Sum('cost'))['total'] or 0
                revenue_labels.append(day.strftime('%a')) # Mon, Tue
                revenue_data.append(float(daily_revenue))
        elif period == 'month':
            # Monthly for past 4 weeks for simplicity
            for i in range(3, -1, -1): # last 4 weeks
                week_start = today - timedelta(days=today.weekday(), weeks=i) 
                week_end = week_start + timedelta(days=6)
                weekly_revenue = ACUsage.objects.filter(
                    start_time__date__gte=week_start, start_time__date__lte=week_end, cost__isnull=False
                ).aggregate(total=Sum('cost'))['total'] or 0
                revenue_labels.append(f'W{week_start.isocalendar()[1]}') # Week number
                revenue_data.append(float(weekly_revenue))

        # AC Usage Data (Mode & Fan Speed for all time for simplicity, can be scoped by date too)
        mode_counts = ACUsage.objects.filter(is_billed=False, room__is_ac_on=True).values('mode').annotate(count=Count('id'))
        for item in mode_counts:
            if item['mode'] == ACMode.COOL:
                usage_data_mode[0] = item['count']
            elif item['mode'] == ACMode.HEAT:
                usage_data_mode[1] = item['count']
        
        fan_counts = ACUsage.objects.filter(is_billed=False, room__is_ac_on=True).values('fan_speed').annotate(count=Count('id'))
        for item in fan_counts:
            if item['fan_speed'] == FanSpeed.LOW:
                usage_data_fan[0] = item['count']
            elif item['fan_speed'] == FanSpeed.MEDIUM:
                usage_data_fan[1] = item['count']
            elif item['fan_speed'] == FanSpeed.HIGH:
                usage_data_fan[2] = item['count']

        return {
            'revenue_labels': revenue_labels,
            'revenue_data': revenue_data,
            'usage_labels_mode': usage_labels_mode,
            'usage_data_mode': usage_data_mode,
            'usage_labels_fan': usage_labels_fan,
            'usage_data_fan': usage_data_fan,
        }

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """渲染经理仪表盘页面"""
        user_stats = self.get_user_statistics()
        dashboard_card_stats = self.get_dashboard_card_statistics()
        # Default chart period to 'week' for revenue
        chart_data = self.get_chart_data(period='week') 
        
        context = {
            'user_stats': user_stats,
            'dashboard_card_stats': dashboard_card_stats,
            'chart_data': chart_data
        }
        return render(request, 'manager/dashboard.html', context)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取统计数据"""
        try:
            # 获取统计数据
            # 这里只是示例，实际应该根据参数查询数据库
            data = {
                'daily_revenue': [1250, 1380, 1490, 1320, 1650, 1820, 1560],
                'room_usage': {
                    'occupied': 17,
                    'total': 20,
                    'rate': 85
                },
                'ac_usage': {
                    'active': 15,
                    'total': 20,
                    'rate': 75
                },
                'average_cost': 78.4
            }
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def reports(self, request):
        """获取报表数据"""
        try:
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')
            room_number_filter = request.query_params.get('room') # e.g. '101' or '' for all
            report_type = request.query_params.get('type', 'daily')

            # Parse dates
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else date.today() - timedelta(days=7)
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else date.today()
            
            # Ensure end_date includes the whole day for filtering DateTimeFields
            end_datetime = datetime.combine(end_date, datetime.max.time())

            # 修改查询条件，包含正在使用空调的记录（end_time为空的记录）
            queryset = ACUsage.objects.filter(
                start_time__date__gte=start_date,
                start_time__date__lte=end_date, # Use start_time for date range as end_time can be null for ongoing
            ).select_related('room')

            if room_number_filter:
                queryset = queryset.filter(room__room_number=room_number_filter)

            # 创建usages字典，存储重新计算过的费用
            updated_usages = {}
            # 重新计算所有查询到的ACUsage记录的费用，确保与前台显示一致
            for usage in queryset:
                # 直接使用数据库中存储的费用和持续时间
                if usage.end_time:
                    duration = usage.end_time - usage.start_time
                else:
                    duration = timezone.now() - usage.start_time
                
                # 存储数据库中的费用和持续时间
                updated_usages[usage.id] = {
                    'cost': usage.cost,
                    'energy_consumption': usage.energy_consumption,
                    'duration': duration
                }

            report_data = []
            summary_data = {}

            if report_type == 'daily':
                # 使用Python逻辑手动生成daily_summary
                daily_room_summary = {}  # 使用字典按日期和房间分组
                
                for usage in queryset:
                    day_key = usage.start_time.date().strftime('%Y-%m-%d')
                    room_key = usage.room.room_number
                    group_key = f"{day_key}_{room_key}"
                    
                    if group_key not in daily_room_summary:
                        daily_room_summary[group_key] = {
                            'day': usage.start_time.date(),
                            'room__room_number': room_key,
                            'total_duration': timedelta(0),
                            'avg_temp_sum': 0,
                            'avg_temp_count': 0,
                            'total_cost': Decimal('0.00'),
                            'mode_val': usage.mode,
                            'fan_speed_val': usage.fan_speed
                        }
                    
                    # 使用我们重新计算的费用和持续时间
                    updated_info = updated_usages[usage.id]
                    daily_room_summary[group_key]['total_duration'] += updated_info['duration']
                    daily_room_summary[group_key]['total_cost'] += updated_info['cost']
                    
                    # 温度平均值计算
                    daily_room_summary[group_key]['avg_temp_sum'] += usage.start_temperature
                    daily_room_summary[group_key]['avg_temp_count'] += 1
                
                # 转换为列表
                daily_summary = []
                for group_info in daily_room_summary.values():
                    # 计算平均温度
                    avg_temp = None
                    if group_info['avg_temp_count'] > 0:
                        avg_temp = group_info['avg_temp_sum'] / group_info['avg_temp_count']
                    
                    daily_summary.append({
                        'day': group_info['day'],
                        'room__room_number': group_info['room__room_number'],
                        'total_duration': group_info['total_duration'],
                        'avg_temp': avg_temp,
                        'total_cost': group_info['total_cost'],
                        'mode_val': group_info['mode_val'],
                        'fan_speed_val': group_info['fan_speed_val']
                    })
                    
                # 按日期降序和房间号升序排序
                daily_summary.sort(key=lambda x: (-x['day'].toordinal(), x['room__room_number']))
                
                for item in daily_summary:
                    duration_td = item['total_duration']
                    hours, remainder = divmod(duration_td.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    report_data.append({
                        'date': item['day'].strftime('%Y-%m-%d'),
                        'room': item['room__room_number'],
                        'duration': f'{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒',
                        'mode': dict(ACMode.choices).get(item['mode_val'], item['mode_val']),
                        'fan_speed': dict(FanSpeed.choices).get(item['fan_speed_val'], item['fan_speed_val']),
                        'avg_temp': f"{item['avg_temp']:.1f}°C" if item['avg_temp'] else 'N/A',
                        'cost': float(item['total_cost'] or 0)
                    })
                overall_total_cost = sum(item['cost'] for item in report_data)
                summary_data = {'total_cost': round(overall_total_cost, 2), 'record_count': len(report_data)}

            elif report_type == 'room':
                # 使用Python逻辑手动生成room_summary
                room_summary_dict = {}
                
                for usage in queryset:
                    room_key = usage.room.room_number
                    
                    if room_key not in room_summary_dict:
                        room_summary_dict[room_key] = {
                            'room__room_number': room_key,
                            'total_duration_seconds': timedelta(0),
                            'total_cost': Decimal('0.00'),
                            'usage_count': 0
                        }
                    
                    # 使用重新计算的费用和持续时间
                    updated_info = updated_usages[usage.id]
                    room_summary_dict[room_key]['total_duration_seconds'] += updated_info['duration']
                    room_summary_dict[room_key]['total_cost'] += updated_info['cost']
                    room_summary_dict[room_key]['usage_count'] += 1
                
                # 转换为列表
                room_summary = [v for v in room_summary_dict.values()]
                # 按房间号排序
                room_summary.sort(key=lambda x: x['room__room_number'])
                
                for item in room_summary:
                    duration_td = item['total_duration_seconds']
                    hours, remainder = divmod(duration_td.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    report_data.append({
                        'room': item['room__room_number'],
                        'total_duration': f'{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒',
                        'usage_count': item['usage_count'],
                        'total_cost': float(item['total_cost'] or 0)
                    })
                overall_total_cost = sum(item['total_cost'] for item in report_data)
                summary_data = {'total_cost': round(overall_total_cost, 2), 'record_count': len(report_data)}

            elif report_type == 'detailed':
                # 生成详细报表，直接使用重新计算的数据
                detailed_usages = list(queryset)
                # 按开始时间降序排序
                detailed_usages.sort(key=lambda x: x.start_time, reverse=True)
                
                # 只显示前100条记录
                detailed_usages = detailed_usages[:100]
                
                for usage in detailed_usages:
                    # 使用重新计算的费用和持续时间
                    updated_info = updated_usages[usage.id]
                    hours, remainder = divmod(updated_info['duration'].total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    report_data.append({
                        'id': usage.id,  # 添加记录ID
                        'date': usage.start_time.strftime('%Y-%m-%d'),
                        'time': usage.start_time.strftime('%H:%M:%S'),
                        'room': usage.room.room_number,
                        'action': '使用中' if not usage.end_time else '已结束', # Simplified
                        'mode': dict(ACMode.choices).get(usage.mode, usage.mode),
                        'fan_speed': dict(FanSpeed.choices).get(usage.fan_speed, usage.fan_speed),
                        'target_temp': f'{usage.start_temperature}°C to {usage.end_temperature}°C' if usage.end_temperature else f'{usage.start_temperature}°C',
                        'duration': f'{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒',
                        'cost': float(updated_info['cost'])
                    })
                
                overall_total_cost = sum(float(updated_usages[u.id]['cost']) for u in detailed_usages)
                summary_data = {'total_cost': round(overall_total_cost, 2), 'record_count': len(report_data)}
            
            return Response({'report': report_data, 'summary': summary_data})
        except Exception as e:
            # Log the error for debugging
            print(f"Error generating report: {str(e)}") 
            import traceback
            traceback.print_exc()
            return Response({'error': str(e), 'report': [], 'summary': {}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def get_users(self, request):
        """获取用户列表数据"""
        try:
            user_type = request.query_params.get('type', 'all')
            
            if user_type == 'all':
                # 获取所有用户
                users = User.objects.all().select_related('profile')
                data = [{
                    'id': user.id,
                    'username': user.username,
                    'name': user.first_name or user.username,
                    'role': user.profile.get_role_display() if hasattr(user, 'profile') else '未知',
                    'email': user.email or '待录入',
                    'phone': '待录入',  # 可以扩展UserProfile模型添加电话字段
                    'createdAt': user.date_joined.strftime('%Y-%m-%d')
                } for user in users]
            
            elif user_type == 'guests':
                # 获取客户数据
                guests = Guest.objects.all().select_related('room')
                data = [{
                    'id': guest.id,
                    'name': guest.name,
                    'room': guest.room.room_number,
                    'id_number': guest.id_number,
                    'checkIn': guest.check_in_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'checkOut': guest.check_out_time.strftime('%Y-%m-%d %H:%M:%S') if guest.check_out_time else '-',
                    'check_in_count': guest.check_in_count
                } for guest in guests]
            
            elif user_type == 'staff':
                # 获取特定角色的员工
                role = request.query_params.get('role')
                if role:
                    profiles = UserProfile.objects.filter(role=role).select_related('user')
                    users = [profile.user for profile in profiles]
                else:
                    users = []
                
                data = [{
                    'id': user.id,
                    'username': user.username,
                    'name': user.first_name or user.username,
                    'email': user.email or '待录入',
                    'phone': '待录入',
                    'createdAt': user.date_joined.strftime('%Y-%m-%d')
                } for user in users]
            
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'])
    def merge_guest_accounts(self, request):
        """合并姓名和身份证号相同的客户账号"""
        try:
            with transaction.atomic():
                # 获取所有客户
                guests = Guest.objects.all()
                
                # 创建一个字典来存储合并后的客户信息
                merged_guests = {}
                
                # 遍历所有客户，根据姓名和身份证号进行分组
                for guest in guests:
                    key = f"{guest.name}_{guest.id_number}"
                    
                    if key in merged_guests:
                        # 已存在相同姓名和身份证号的客户，更新入住次数
                        merged_guests[key]['count'] += 1
                        merged_guests[key]['ids'].append(guest.id)
                    else:
                        # 第一次遇到此客户
                        merged_guests[key] = {
                            'guest': guest,
                            'count': 1,
                            'ids': [guest.id]
                        }
                
                # 处理合并
                merged_count = 0
                for key, data in merged_guests.items():
                    if data['count'] > 1:
                        # 需要合并的客户
                        primary_guest = data['guest']
                        primary_guest.check_in_count = data['count']
                        primary_guest.save()
                        
                        # 删除重复的客户记录，保留主记录
                        ids_to_delete = data['ids'][1:]  # 排除主记录ID
                        Guest.objects.filter(id__in=ids_to_delete).delete()
                        
                        merged_count += len(ids_to_delete)
                    else:
                        # 设置入住次数为1
                        guest = data['guest']
                        guest.check_in_count = 1
                        guest.save()
                
                return Response({
                    'message': f'成功合并了 {merged_count} 个重复客户账号',
                    'merged_count': merged_count
                })
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({
                'error': f'合并客户账号失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get_user_statistics(self):
        """获取用户统计数据"""
        try:
            # 获取总用户数
            total_users = User.objects.count()
            
            # 获取客户数
            guests_count = Guest.objects.count()
            
            # 获取各角色员工数
            reception_count = UserProfile.objects.filter(role='reception').count()
            admin_count = UserProfile.objects.filter(role='admin').count()
            manager_count = UserProfile.objects.filter(role='manager').count()
            
            return {
                'total': total_users + guests_count,  # 包括Django用户和访客
                'guests': guests_count,
                'reception': reception_count,
                'admin': admin_count,
                'manager': manager_count
            }
        except Exception as e:
            print(f"获取用户统计出错: {str(e)}")
            # 出错时返回默认值
            return {
                'total': 0,
                'guests': 0,
                'reception': 0,
                'admin': 0,
                'manager': 0
            }
    
    @action(detail=False, methods=['post'])
    def save_settings(self, request):
        """保存系统设置"""
        try:
            # 获取设置参数
            max_service_rooms = request.data.get('max_service_rooms')
            waiting_time_slice = request.data.get('waiting_time_slice')
            scheduling_strategy = request.data.get('scheduling_strategy')
            cooling_range = request.data.get('cooling_range')
            heating_range = request.data.get('heating_range')
            fee_rate = request.data.get('fee_rate')
            
            # 更新系统设置
            # 这里只是示例，实际应该更新系统设置
            
            return Response({'message': '设置已保存'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['delete'])
    def delete_record(self, request, pk=None):
        """删除单条空调使用记录"""
        try:
            # 获取并删除指定的记录
            usage = get_object_or_404(ACUsage, pk=pk)
            room_number = usage.room.room_number
            usage.delete()
            
            print(f"成功删除记录: ID={pk}, 房间={room_number}")
            
            return Response({
                "message": f"已成功删除房间 {room_number} 的使用记录",
                "deleted_id": pk
            })
        except Exception as e:
            import traceback
            print(f"删除记录失败: ID={pk}, 错误={str(e)}")
            traceback.print_exc()
            
            return Response({
                "error": f"删除记录失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['delete'])
    def clear_records(self, request):
        """清空所有空调使用记录"""
        try:
            # 获取日期范围参数（可选）
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')
            
            print(f"清空记录请求: 开始日期={start_date_str}, 结束日期={end_date_str}")
            
            # 创建基本查询
            query = ACUsage.objects.all()
            
            # 应用日期过滤器（如果提供）
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                query = query.filter(start_time__date__gte=start_date)
                
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(start_time__date__lte=end_date)
            
            # 获取记录数量并删除
            count = query.count()
            query.delete()
            
            print(f"成功清空 {count} 条记录")
            
            return Response({
                "message": f"已成功清空 {count} 条使用记录",
                "deleted_count": count
            })
        except Exception as e:
            import traceback
            print(f"清空记录失败: 错误={str(e)}")
            traceback.print_exc()
            
            return Response({
                "error": f"清空记录失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 