from __future__ import annotations

from django import forms

from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.model_option_service import get_default_selected_model, get_model_options
from backend.moodpal_eval.models import MoodPalEvalRun
from backend.moodpal_eval.services.run_service import (
    MAX_CONCURRENCY_LIMIT,
    MAX_PER_TURN_TIMEOUT_SECONDS,
    MAX_RETRIES,
    MAX_RUN_CASE_COUNT,
    MAX_RUNTIME_SECONDS,
    MAX_TURNS_LIMIT,
    list_completed_runs,
    list_split_options,
)


class MoodPalEvalRunCreateForm(forms.Form):
    name = forms.CharField(label='Run 名称', max_length=255, required=False)
    target_mode = forms.ChoiceField(label='目标模式', choices=MoodPalEvalRun.TargetMode.choices)
    target_persona_id = forms.ChoiceField(label='目标角色', choices=MoodPalSession.Persona.choices)
    dataset_split = forms.ChoiceField(label='样本分片', required=False)
    case_count = forms.IntegerField(label='Case 数量', min_value=1, max_value=MAX_RUN_CASE_COUNT, initial=10)
    target_model = forms.ChoiceField(label='被测模型')
    patient_model = forms.ChoiceField(label='Patient Agent 模型')
    judge_model = forms.ChoiceField(label='Judge 模型')
    threshold_score = forms.IntegerField(label='总分门槛', min_value=0, max_value=100, initial=80)
    baseline_run_id = forms.ChoiceField(label='稳定基线 Run', required=False)
    max_turns = forms.IntegerField(label='最大轮数', min_value=1, max_value=MAX_TURNS_LIMIT, initial=12)
    concurrency = forms.IntegerField(label='并发数', min_value=1, max_value=MAX_CONCURRENCY_LIMIT, initial=4)
    per_turn_timeout_seconds = forms.IntegerField(label='单轮超时秒数', min_value=5, max_value=MAX_PER_TURN_TIMEOUT_SECONDS, initial=45)
    max_runtime_seconds = forms.IntegerField(label='总运行超时秒数', min_value=60, max_value=MAX_RUNTIME_SECONDS, initial=900)
    max_retries = forms.IntegerField(label='最大重试次数', min_value=0, max_value=MAX_RETRIES, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        split_choices = [(item['value'], item['label']) for item in list_split_options()]
        self.fields['dataset_split'].choices = split_choices

        model_choices = [(item['value'], item['label']) for item in get_model_options()]
        default_model = get_default_selected_model()
        for field_name in ['target_model', 'patient_model', 'judge_model']:
            self.fields[field_name].choices = model_choices
            self.fields[field_name].initial = default_model

        baseline_choices = [('', '不比较基线')]
        for run in list_completed_runs()[:50]:
            score = (run.summary_metrics or {}).get('overall_avg_score')
            score_text = f' / {score}' if score not in [None, ''] else ''
            baseline_choices.append((str(run.id), f'{run.name or run.id}{score_text}'))
        self.fields['baseline_run_id'].choices = baseline_choices
        self.fields['target_mode'].initial = MoodPalEvalRun.TargetMode.MASTER_GUIDE
        self.fields['target_persona_id'].initial = MoodPalSession.Persona.MASTER_GUIDE

    def clean(self):
        cleaned = super().clean()
        target_mode = cleaned.get('target_mode')
        target_persona_id = cleaned.get('target_persona_id')
        if target_mode == MoodPalEvalRun.TargetMode.MASTER_GUIDE and target_persona_id != MoodPalSession.Persona.MASTER_GUIDE:
            self.add_error('target_persona_id', '全能主理人模式只能选择 master_guide。')
        if target_mode == MoodPalEvalRun.TargetMode.SINGLE_ROLE and target_persona_id == MoodPalSession.Persona.MASTER_GUIDE:
            self.add_error('target_persona_id', '单角色模式不能选择 master_guide。')
        return cleaned
