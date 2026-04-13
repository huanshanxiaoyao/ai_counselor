"""
WebSocket URL routing for roundtable.
"""
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/roundtable/d/<int:discussion_id>/', consumers.DiscussionConsumer.as_asgi()),
]