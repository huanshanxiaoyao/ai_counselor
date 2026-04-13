"""
URL configuration for roundtable app.
"""
from django.urls import path
from . import views

app_name = 'roundtable'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('setup/', views.SetupView.as_view(), name='setup'),
    path('d/<int:discussion_id>/', views.DiscussionView.as_view(), name='discussion'),
    path('characters/', views.ProfileListView.as_view(), name='profiles'),
    path('api/suggestions/', views.SuggestionsView.as_view(), name='suggestions'),
    path('api/configure/', views.ConfigureView.as_view(), name='configure'),
    path('api/start/', views.DiscussionStartView.as_view(), name='start'),
    path('api/d/<int:discussion_id>/message/', views.DiscussionMessageView.as_view(), name='message'),
    path('api/d/<int:discussion_id>/poll/', views.DiscussionPollView.as_view(), name='poll'),
    path('api/profiles/', views.ProfileListApiView.as_view(), name='profile_list'),
    path('api/profiles/<str:name>/', views.ProfileDetailApiView.as_view(), name='profile_detail'),
    path('api/cache/stats/', views.CacheStatsApiView.as_view(), name='cache_stats'),
    path('api/cache/delete/', views.CacheDeleteApiView.as_view(), name='cache_delete'),
    path('api/cache/clear/', views.CacheClearApiView.as_view(), name='cache_clear'),
    # 候选队列管理
    path('api/candidates/', views.CandidateQueueListApiView.as_view(), name='candidate_list'),
    path('api/candidates/trigger/', views.CandidateQueueTriggerApiView.as_view(), name='candidate_trigger'),
    path('api/candidates/reset/', views.CandidateQueueResetApiView.as_view(), name='candidate_reset'),
    path('api/candidates/delete/', views.CandidateQueueDeleteApiView.as_view(), name='candidate_delete'),
    path('api/candidates/clear/', views.CandidateQueueClearApiView.as_view(), name='candidate_clear'),
    # 历史讨论
    path('api/history/', views.HistoryListApiView.as_view(), name='history_list'),
    path('api/restart/<int:discussion_id>/', views.RestartApiView.as_view(), name='restart'),
]