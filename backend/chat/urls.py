"""
URL configuration for chat app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.ChatView.as_view(), name='chat'),
    path('api/chat/', views.ChatAPIView.as_view(), name='chat_api'),
]
