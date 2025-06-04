from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'bills', views.BillViewSet, basename='bills')
router.register(r'checkin', views.CheckInViewSet, basename='checkin')
router.register(r'checkout', views.CheckOutViewSet, basename='checkout')

urlpatterns = [
    path('', include(router.urls)),
    path('bills/<int:pk>/print/', views.CheckOutViewSet.as_view({'get': 'print_bill'}), name='print_bill'),
] 