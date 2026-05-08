from django.contrib import admin
from django.urls import path

from backend.moodpal.models import MoodPalSession
from backend.roundtable.models import Discussion

from .views import moodpal_daily_view, moodpal_user_detail_view, moodpal_users_view
from .views_roundtable import rt_daily_view, rt_user_detail_view, rt_users_view

# Both proxy models are named 'Da' via type() so admin URLs become
# /admin/moodpal/da/...  and  /admin/roundtable/da/...
MoodPalDa = type('Da', (MoodPalSession,), {
    '__module__': __name__,
    'Meta': type('Meta', (), {
        'proxy': True,
        'app_label': 'moodpal',
        'verbose_name': 'MoodPal Analytics',
        'verbose_name_plural': 'MoodPal Analytics',
    }),
})

RtDa = type('Da', (Discussion,), {
    '__module__': __name__,
    'Meta': type('Meta', (), {
        'proxy': True,
        'app_label': 'roundtable',
        'verbose_name': 'Roundtable Analytics',
        'verbose_name_plural': 'Roundtable Analytics',
    }),
})


@admin.register(MoodPalDa)
class MoodPalAnalyticsAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('daily/', self.admin_site.admin_view(moodpal_daily_view), name='moodpal_analytics_daily'),
            path('users/', self.admin_site.admin_view(moodpal_users_view), name='moodpal_analytics_users'),
            path('user/<str:subject_key>/', self.admin_site.admin_view(moodpal_user_detail_view), name='moodpal_analytics_user_detail'),
        ]
        return custom + urls

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RtDa)
class RoundtableAnalyticsAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('daily/', self.admin_site.admin_view(rt_daily_view), name='rt_analytics_daily'),
            path('users/', self.admin_site.admin_view(rt_users_view), name='rt_analytics_users'),
            path('user/<str:subject_key>/', self.admin_site.admin_view(rt_user_detail_view), name='rt_analytics_user_detail'),
        ]
        return custom + urls

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
