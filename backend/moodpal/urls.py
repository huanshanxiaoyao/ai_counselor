from django.urls import path

from . import views

app_name = 'moodpal'

urlpatterns = [
    path('', views.MoodPalHomeView.as_view(), name='index'),
    path('session/<uuid:session_id>/', views.MoodPalSessionView.as_view(), name='session'),
    path('session/<uuid:session_id>/summary/', views.MoodPalSummaryView.as_view(), name='summary'),
]

