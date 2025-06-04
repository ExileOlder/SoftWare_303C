from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'control', views.RoomControlViewSet, basename='control')
router.register(r'status', views.RoomStatusViewSet, basename='status')

urlpatterns = [
    path('', include(router.urls)),
] 