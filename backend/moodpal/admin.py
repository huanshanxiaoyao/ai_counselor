from django.contrib import admin

from .models import MoodPalMessage, MoodPalSession, MoodPalSessionEvent


@admin.register(MoodPalSession)
class MoodPalSessionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'persona_id',
        'status',
        'owner',
        'usage_subject',
        'summary_action',
        'close_reason',
        'created_at',
        'last_activity_at',
    )
    list_filter = ('persona_id', 'status', 'summary_action', 'close_reason')
    search_fields = ('id', 'usage_subject', 'anon_id', 'owner__username')
    readonly_fields = ('created_at', 'updated_at', 'activated_at', 'ended_at')


@admin.register(MoodPalMessage)
class MoodPalMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('session__id', 'content')
    readonly_fields = ('created_at',)


@admin.register(MoodPalSessionEvent)
class MoodPalSessionEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'event_type', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('session__id',)
    readonly_fields = ('created_at',)
