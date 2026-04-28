from django.contrib import admin

from .models import MoodPalEvalCase, MoodPalEvalRun, MoodPalEvalRunItem, MoodPalEvalTokenLedger


@admin.register(MoodPalEvalCase)
class MoodPalEvalCaseAdmin(admin.ModelAdmin):
    list_display = ('case_id', 'title', 'case_type', 'source_dataset', 'topic_tag', 'enabled', 'updated_at')
    list_filter = ('case_type', 'enabled', 'source_dataset', 'topic_tag')
    search_fields = ('case_id', 'title', 'topic_tag', 'notes')
    readonly_fields = ('source_hash', 'created_at', 'updated_at')


@admin.register(MoodPalEvalRun)
class MoodPalEvalRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status', 'target_mode', 'target_persona_id', 'selected_case_count', 'threshold_score', 'gate_passed', 'created_at')
    list_filter = ('status', 'target_mode', 'target_persona_id', 'gate_passed')
    search_fields = ('id', 'name', 'dataset_split')
    readonly_fields = ('started_at', 'finished_at', 'created_at', 'updated_at')


@admin.register(MoodPalEvalRunItem)
class MoodPalEvalRunItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'case', 'status', 'turn_count', 'final_score', 'hard_fail', 'created_at')
    list_filter = ('status', 'hard_fail')
    search_fields = ('run__id', 'case__case_id', 'case__title', 'error_code')
    readonly_fields = ('started_at', 'finished_at', 'created_at', 'updated_at')


@admin.register(MoodPalEvalTokenLedger)
class MoodPalEvalTokenLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'run_item', 'scope', 'provider', 'model', 'total_tokens', 'created_at')
    list_filter = ('scope', 'provider', 'model')
    search_fields = ('run__id', 'run_item__id', 'request_label')
    readonly_fields = ('created_at',)
