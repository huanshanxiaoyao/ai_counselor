"""
URL configuration for chat app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('counselor/', views.ChatView.as_view(), name='counselor'),
    path('api/counselor/', views.ChatAPIView.as_view(), name='counselor_api'),
]
