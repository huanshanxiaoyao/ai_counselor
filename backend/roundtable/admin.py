from django.contrib import admin

from .models import QuotaFeedback, TokenQuotaState, TokenUsageLedger


@admin.register(TokenQuotaState)
class TokenQuotaStateAdmin(admin.ModelAdmin):
    list_display = (
        'subject_key',
        'subject_type',
        'used_tokens',
        'quota_limit',
        'last_warn_level',
        'updated_at',
    )
    list_filter = ('subject_type', 'last_warn_level')
    search_fields = ('subject_key', 'anon_id', 'user__username')
    ordering = ('-updated_at',)


@admin.register(TokenUsageLedger)
class TokenUsageLedgerAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'subject_key',
        'source',
        'provider',
        'model',
        'total_tokens',
    )
    list_filter = ('source', 'subject_type', 'provider')
    search_fields = ('subject_key', 'anon_id', 'model', 'request_id')
    ordering = ('-created_at',)


@admin.register(QuotaFeedback)
class QuotaFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'subject_key',
        'status',
        'used_tokens',
        'quota_limit',
        'contact',
    )
    list_filter = ('status', 'subject_type')
    search_fields = ('subject_key', 'anon_id', 'contact', 'message')
    ordering = ('-created_at',)
