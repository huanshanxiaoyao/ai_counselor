from django.urls import path

from . import views

app_name = 'moodpal_api'

urlpatterns = [
    path('session/start', views.MoodPalSessionStartApiView.as_view(), name='session_start'),
    path('session/<uuid:session_id>', views.MoodPalSessionDetailApiView.as_view(), name='session_detail'),
    path('session/<uuid:session_id>/message', views.MoodPalSessionMessageApiView.as_view(), name='session_message'),
    path('session/<uuid:session_id>/end', views.MoodPalSessionEndApiView.as_view(), name='session_end'),
    path('session/<uuid:session_id>/summary/save', views.MoodPalSummarySaveApiView.as_view(), name='summary_save'),
    path('session/<uuid:session_id>/summary/destroy', views.MoodPalSummaryDestroyApiView.as_view(), name='summary_destroy'),
]

