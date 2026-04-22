"""
URL configuration for chat app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('counselor/', views.CounselorLandingView.as_view(), name='counselor'),
    path('llm_test/', views.ChatView.as_view(), name='llm_test'),
    path('api/counselor/', views.ChatAPIView.as_view(), name='counselor_api'),
    path('api/models/', views.ModelsAPIView.as_view(), name='models_api'),
]
