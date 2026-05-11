from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    actions = ['raise_to_1m', 'reset_used_tokens']
    fieldsets = (
        ('⚠ 真实配额（保存即生效，无需重启）', {
            'fields': ('subject_key', 'subject_type', 'user', 'anon_id',
                       'used_tokens', 'quota_limit', 'last_warn_level'),
        }),
        ('时间戳', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('subject_key', 'subject_type', 'user', 'anon_id',
                       'created_at', 'updated_at')

    @admin.action(description='把配额提升到 1,000,000（并清零警告等级）')
    def raise_to_1m(self, request, queryset):
        updated = queryset.update(quota_limit=1000000, last_warn_level=0)
        self.message_user(request, f'已为 {updated} 条记录提额至 1,000,000')

    @admin.action(description='清零已用 tokens（已用归 0，配额上限不变）')
    def reset_used_tokens(self, request, queryset):
        updated = queryset.update(used_tokens=0, last_warn_level=0)
        self.message_user(request, f'已为 {updated} 条记录清零已用 tokens')


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
        'state_link',
    )
    list_filter = ('status', 'subject_type')
    search_fields = ('subject_key', 'anon_id', 'contact', 'message')
    ordering = ('-created_at',)
    readonly_fields = (
        'subject_key', 'subject_type', 'user', 'anon_id',
        'contact', 'message', 'used_tokens', 'quota_limit',
        'created_at', 'updated_at', 'state_link',
    )
    fieldsets = (
        ('👉 要给用户提额请点这里（跳转到真实配额状态）', {
            'fields': ('state_link',),
            'description': '⚠ 本页所有字段都是申请那一刻的<b>历史快照</b>，改这里不会让用户提额生效。处理流程：① 先点上面链接去改真实配额；② 回来把 Status 标记为 resolved 并填 Admin note 留痕。',
        }),
        ('申请内容', {'fields': ('subject_key', 'subject_type', 'user', 'anon_id',
                                  'contact', 'message')}),
        ('提交时快照（只读）', {'fields': ('used_tokens', 'quota_limit')}),
        ('处理记录', {'fields': ('status', 'admin_note', 'resolved_at')}),
        ('时间戳', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='→ 真实配额状态')
    def state_link(self, obj):
        if not obj or not obj.subject_key:
            return '-'
        state = TokenQuotaState.objects.filter(subject_key=obj.subject_key).first()
        if not state:
            return format_html(
                '<span style="color:#c00;">无对应 state（subject_key={}）</span>',
                obj.subject_key,
            )
        url = reverse('admin:roundtable_tokenquotastate_change', args=[state.id])
        return format_html(
            '<a href="{}" style="background:#ffc;padding:4px 10px;border-radius:4px;'
            'text-decoration:none;font-weight:600;">→ 去改真实配额 '
            '(目前 {}/{})</a>',
            url, state.used_tokens, state.quota_limit,
        )
