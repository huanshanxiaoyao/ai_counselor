"""
URL configuration for AI Counselor.
"""
from django.contrib import admin
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.urls import path, include
from django.urls import re_path
from backend.config.auth_views import SignupView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', SignupView.as_view(), name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('ops/moodpal/evals/', include('backend.moodpal_eval.urls')),
    path('moodpal/', include('backend.moodpal.urls')),
    path('api/moodpal/', include('backend.moodpal.api_urls')),
    path('', include('backend.chat.urls')),
    path('roundtable/', include('backend.roundtable.urls')),
]

# ASGI-only deployments in this project currently have no dedicated front proxy
# for collected assets, so expose staticfiles through Django as a fallback.
urlpatterns += [
    re_path(r'^ac-static/(?P<path>.*)$', staticfiles_serve, {'insecure': True}),
]
