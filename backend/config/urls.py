"""
URL configuration for AI Counselor.
"""
from django.contrib import admin
from django.urls import path, include
from backend.config.auth_views import SignupView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', SignupView.as_view(), name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('moodpal/', include('backend.moodpal.urls')),
    path('api/moodpal/', include('backend.moodpal.api_urls')),
    path('', include('backend.chat.urls')),
    path('roundtable/', include('backend.roundtable.urls')),
]
