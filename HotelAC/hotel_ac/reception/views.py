from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import transaction
import json
from datetime import timedelta
import os
from django.template.loader import render_to_string
from django.conf import settings
import csv
from io import StringIO
from decimal import Decimal

from hotel_ac.core.models import Room, Bill, ACUsage, Guest, ACMode, FanSpeed
from hotel_ac.core.services.queue_manager_service import QueueManagerService
from hotel_ac.core.services.scheduler_service import get_scheduler_service
from hotel_ac.core.serializers import RoomSerializer, BillSerializer

class BillViewSet(viewsets.ViewSet):
    """账单视图集，处理账单生成和查询"""
    
    def list(self, request):
        """获取所有账单"""
        bills = Bill.objects.all().order_by('-created_at')
        serializer = BillSerializer(bills, many=True)
        return Response(serializer.data)
    
    def retrieve(self, request, pk=None):
        """获取单个账单的详细信息"""
        bill = get_object_or_404(Bill, pk=pk)
        serializer = BillSerializer(bill)
        
        # 获取该账单对应的空调使用记录
        usages = ACUsage.objects.filter(
            room=bill.room,
            start_time__gte=bill.check_in_time,
            end_time__lte=bill.check_out_time
        ).order_by('start_time')
        
        # 构建使用详情
        usage_details = []
        for usage in usages:
            if not usage.duration:
                continue
                
            usage_details.append({
                'id': usage.id,
                'start_time': usage.start_time,
                'end_time': usage.end_time,
                'duration': usage.duration.total_seconds(),
                'mode': usage.mode,
                'fan_speed': usage.fan_speed,
                'energy_consumption': usage.energy_consumption,
                'cost': float(usage.cost)
            })
        
        # 添加使用详情到响应数据
        data = serializer.data
        data['usage_details'] = usage_details
        
        return Response(data)
    
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """标记账单为已支付状态"""
        bill = get_object_or_404(Bill, pk=pk)
        
        if bill.is_paid:
            return Response({"message": "该账单已经是已支付状态"}, status=status.HTTP_400_BAD_REQUEST)
        
        bill.is_paid = True
        bill.payment_time = timezone.now()
        bill.save()
        
        return Response({
            "message": "账单已标记为已支付",
            "bill_id": bill.id,
            "payment_time": bill.payment_time
        })
    
    @action(detail=True, methods=['get'])
    def generate_pdf(self, request, pk=None):
        """生成PDF账单（模拟）"""
        bill = get_object_or_404(Bill, pk=pk)
        
        # 实际项目中，这里会调用PDF生成库创建PDF文件
        # 这里仅返回一个模拟的响应
        
        return Response({
            "message": "PDF账单已生成",
            "download_url": f"/api/bills/{bill.id}/download-pdf/"
        })

    @action(detail=True, methods=['get'])
    def print_bill(self, request, pk=None):
        """生成并下载账单文件"""
        try:
            room = get_object_or_404(Room, pk=pk)
            
            # 查找未结算的账单
            bill = Bill.objects.filter(
                room=room,
                is_paid=False
            ).order_by('-check_in_time').first()
            
            if not bill:
                return Response({
                    "error": f"找不到房间 {room.room_number} 的未结算账单"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # 从数据库直接获取空调使用记录
            usages = ACUsage.objects.filter(
                room=room,
                start_time__gte=bill.check_in_time,
                start_time__lte=timezone.now() if not bill.check_out_time else bill.check_out_time
            ).order_by('start_time')
            
            # 创建CSV文件内容
            csv_buffer = StringIO()
            csv_writer = csv.writer(csv_buffer)
            
            # 写入账单头部信息
            csv_writer.writerow(['波特普大学快捷廉价酒店 - 客户账单'])
            csv_writer.writerow([])
            csv_writer.writerow(['房间号', room.room_number])
            csv_writer.writerow(['入住时间', bill.check_in_time.strftime('%Y-%m-%d %H:%M:%S')])
            csv_writer.writerow(['结账时间', (bill.check_out_time or timezone.now()).strftime('%Y-%m-%d %H:%M:%S')])
            csv_writer.writerow([])
            
            # 写入空调使用详情表头
            csv_writer.writerow(['空调使用详情'])
            csv_writer.writerow(['开始时间', '结束时间', '模式', '风速', '温度', '费用(元)'])
            
            # 写入每条使用记录
            total_cost = Decimal('0.00')
            for usage in usages:
                end_time = usage.end_time.strftime('%Y-%m-%d %H:%M:%S') if usage.end_time else '使用中'
                cost = usage.cost if usage.cost is not None else Decimal('0.00')
                csv_writer.writerow([
                    usage.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time,
                    dict(ACMode.choices).get(usage.mode, usage.mode),
                    dict(FanSpeed.choices).get(usage.fan_speed, usage.fan_speed),
                    f"{usage.start_temperature}°C",
                    f"{float(cost):.2f}"
                ])
                total_cost += cost
            
            # 写入账单总结
            csv_writer.writerow([])
            csv_writer.writerow(['总费用(元)', f"{float(total_cost):.2f}"])
            
            # 设置响应头，让浏览器下载文件
            response = HttpResponse(csv_buffer.getvalue(), content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="账单_{room.room_number}_{timezone.now().strftime("%Y%m%d%H%M%S")}.csv"'
            
            return response
            
        except Exception as e:
            return Response({
                "error": f"生成账单文件失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CheckInViewSet(viewsets.ViewSet):
    """入住视图集，处理客房入住操作"""
    
    def list(self, request):
        """获取所有可入住的房间"""
        available_rooms = Room.objects.filter(is_occupied=False)
        serializer = RoomSerializer(available_rooms, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def occupied_rooms(self, request):
        """获取所有已入住的房间"""
        occupied_rooms = Room.objects.filter(is_occupied=True)
        serializer = RoomSerializer(occupied_rooms, many=True)
        
        # 丰富房间数据，添加入住人信息
        rooms_data = serializer.data
        for room_data in rooms_data:
            # 获取该房间最近的访客
            guest = Guest.objects.filter(room_id=room_data['id']).order_by('-check_in_time').first()
            if guest:
                room_data['guest_name'] = guest.name
                room_data['guest_id_number'] = guest.id_number
                room_data['guest_check_in_time'] = guest.check_in_time
            else:
                room_data['guest_name'] = None
                room_data['guest_id_number'] = None
                room_data['guest_check_in_time'] = None
        
        return Response(rooms_data)
    
    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        """办理入住"""
        room = get_object_or_404(Room, pk=pk)
        
        if room.is_occupied:
            return Response({
                "error": f"房间 {room.room_number} 已被占用，无法办理入住"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取客户姓名参数
        guest_name = request.data.get('guest_name')
        id_number = request.data.get('id_number')
        
        if not guest_name:
            return Response({
                "error": "请提供入住客户姓名"
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not id_number:
            return Response({
                "error": "请提供入住客户身份证号"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # 更新房间状态
                room.is_occupied = True
                room.save()
                
                # 创建账单记录
                bill = Bill.objects.create(
                    room=room,
                    check_in_time=timezone.now(),
                    total_cost=0.0,
                    is_paid=False
                )
                
                # 创建访客记录，方便客户登录
                guest = Guest.objects.create(
                    room=room,
                    name=guest_name,
                    id_number=id_number
                )
                
                return Response({
                    "message": f"房间 {room.room_number} 入住成功",
                    "room_id": room.id,
                    "guest_id": guest.id,
                    "bill_id": bill.id,
                    "room_number": room.room_number,
                    "guest_name": guest_name
                })
                
        except Exception as e:
            return Response({
                "error": f"入住处理失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def dashboard(self, request):
        """前台管理员仪表板页面"""
        return render(request, 'reception/dashboard.html')

class CheckOutViewSet(viewsets.ViewSet):
    """退房视图集，处理退房和结账操作"""
    
    @action(detail=True, methods=['post'])
    def check_out(self, request, pk=None):
        """办理退房"""
        room = get_object_or_404(Room, pk=pk)
        
        if not room.is_occupied:
            return Response({
                "error": f"房间 {room.room_number} 未被占用，无法办理退房"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # 关闭空调
                if room.is_ac_on:
                    scheduler = get_scheduler_service()
                    scheduler.remove_request(room_id=room.id)
                    room.is_ac_on = False
                
                # 查找未结算的账单
                bill = Bill.objects.filter(
                    room=room,
                    check_out_time__isnull=True,
                    is_paid=False
                ).order_by('-check_in_time').first()
                
                if not bill:
                    # 创建一个新账单，以防万一没有现有账单
                    bill = Bill.objects.create(
                        room=room,
                        check_in_time=timezone.now() - timedelta(days=1),
                        check_out_time=timezone.now(),
                        total_cost=0.0,
                        is_paid=False
                    )
                
                # 更新退房时间
                bill.check_out_time = timezone.now()
                
                # 直接从数据库获取费用信息，不再重新计算
                usage_records = ACUsage.objects.filter(
                    room=room,
                    start_time__gte=bill.check_in_time,
                    start_time__lt=bill.check_out_time
                )
                
                # 计算总费用
                total_cost = Decimal('0.00')
                for record in usage_records:
                    if record.cost is not None:
                        total_cost += record.cost
                
                # 更新账单金额
                bill.total_cost = total_cost
                bill.save()
                
                # 更新房间状态
                room.is_occupied = False
                room.save()
                
                # 获取当前房间的所有访客记录，确保相关账单结账后标记为已结账
                guests = Guest.objects.filter(room=room)
                for guest in guests:
                    # 更新访客退房时间
                    if not guest.check_out_time:
                        guest.check_out_time = timezone.now()
                        guest.save()
                
                return Response({
                    "message": f"房间 {room.room_number} 退房成功",
                    "bill_id": bill.id,
                    "total_cost": float(total_cost),
                    "check_out_time": bill.check_out_time
                })
                
        except Exception as e:
            return Response({
                "error": f"退房处理失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def bill_preview(self, request, pk=None):
        """预览退房账单，但不实际办理退房"""
        room = get_object_or_404(Room, pk=pk)
        
        if not room.is_occupied:
            return Response({
                "error": f"房间 {room.room_number} 未被占用"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 查找该房间的入住账单
            bill = Bill.objects.filter(
                room=room,
                check_out_time__isnull=True
            ).order_by('-check_in_time').first()
            
            if not bill:
                return Response({
                    "error": f"找不到房间 {room.room_number} 的入住记录"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # 直接从数据库获取费用信息，不再重新计算
            usage_records = ACUsage.objects.filter(
                room=room,
                start_time__gte=bill.check_in_time
            )
            
            # 计算总费用和使用详情
            total_cost = Decimal('0.00')
            usage_details = []
            
            for record in usage_records:
                # 计算结束时间
                end_time = record.end_time if record.end_time else timezone.now()
                
                # 计算持续时间（小时）
                duration = (end_time - record.start_time).total_seconds() / 3600
                
                # 确保费用不为None
                if record.cost is not None:
                    total_cost += record.cost
                
                # 添加详细使用记录
                usage_details.append({
                    'id': record.id,
                    'start_time': record.start_time,
                    'end_time': end_time,
                    'duration_hours': round(duration, 2),
                    'mode': record.mode,
                    'fan_speed': record.fan_speed,
                    'cost': float(record.cost) if record.cost is not None else 0.0,
                    'energy_consumption': float(record.energy_consumption) if record.energy_consumption is not None else 0.0
                })
            
            # 构建预览响应
            stay_duration = (timezone.now() - bill.check_in_time).total_seconds() / 3600  # 小时
            
            preview_data = {
                "room_number": room.room_number,
                "check_in_time": bill.check_in_time,
                "estimated_check_out_time": timezone.now(),
                "stay_duration_hours": round(stay_duration, 1),
                "ac_usage_cost": float(total_cost),
                "total_cost": float(total_cost),
                "usage_details": usage_details,
                "bill_id": bill.id
            }
            
            return Response(preview_data)
            
        except Exception as e:
            return Response({
                "error": f"生成账单预览失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    def checkout_page(self, request, room_number):
        """退房结账页面"""
        try:
            room = Room.objects.get(room_number=room_number)
            return render(request, 'reception/checkout.html', {'room': room})
        except Room.DoesNotExist:
            return JsonResponse({"error": "房间不存在"}, status=404) 