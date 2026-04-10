"""
URL configuration for AI Counselor.
"""
from django.urls import path, include

urlpatterns = [
    path('', include('backend.chat.urls')),
]
