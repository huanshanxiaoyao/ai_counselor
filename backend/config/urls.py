"""
URL configuration for AI Counselor.
"""
from django.urls import path, include

urlpatterns = [
    path('', include('backend.chat.urls')),
    path('roundtable/', include('backend.roundtable.urls')),
]
