import json

import pytest
from django.test import Client

from backend.moodpal.models import MoodPalSession
from backend.moodpal.services.model_option_service import (
    MODEL_SCOPE_ASSISTANT,
    MODEL_SCOPE_JUDGE,
    get_default_selected_model,
    get_model_options,
)
from backend.moodpal_eval.forms import MoodPalEvalRunCreateForm
from backend.moodpal_eval.models import MoodPalEvalCase
from backend.moodpal_eval.services.run_service import EvalRunValidationError, RunCreateInput, create_run


@pytest.mark.django_db
def test_assistant_model_options_exclude_judge_only_and_minimax():
    values = {item['value'] for item in get_model_options(scope=MODEL_SCOPE_ASSISTANT)}

    assert 'doubao:doubao-seed-2-0-lite-260215' in values
    assert 'doubao:doubao-seed-2-0-mini-260215' in values
    assert 'doubao:doubao-seed-2-0-pro-260215' not in values
    assert 'qwen:qwen3.5-plus' not in values
    assert all(not value.startswith('minimax:') for value in values)


@pytest.mark.django_db
def test_judge_model_options_include_judge_only_but_still_exclude_minimax():
    values = {item['value'] for item in get_model_options(scope=MODEL_SCOPE_JUDGE)}

    assert 'doubao:doubao-seed-2-0-pro-260215' in values
    assert 'qwen:qwen3.5-plus' in values
    assert 'doubao:doubao-seed-2-0-lite-260215' in values
    assert all(not value.startswith('minimax:') for value in values)


@pytest.mark.django_db
def test_eval_form_uses_scoped_model_choices():
    form = MoodPalEvalRunCreateForm()
    target_values = {value for value, _label in form.fields['target_model'].choices}
    patient_values = {value for value, _label in form.fields['patient_model'].choices}
    judge_values = {value for value, _label in form.fields['judge_model'].choices}

    assert 'doubao:doubao-seed-2-0-pro-260215' not in target_values
    assert 'qwen:qwen3.5-plus' not in patient_values
    assert 'doubao:doubao-seed-2-0-pro-260215' in judge_values
    assert 'qwen:qwen3.5-plus' in judge_values


@pytest.mark.django_db
def test_session_start_disallowed_assistant_model_falls_back_to_default():
    client = Client()
    client.cookies['anon_usage_id'] = 'anon-model-scope-fallback'

    response = client.post(
        '/api/moodpal/session/start',
        data=json.dumps(
            {
                'persona_id': MoodPalSession.Persona.LOGIC_BROTHER,
                'selected_model': 'doubao:doubao-seed-2-0-pro-260215',
                'privacy_acknowledged': True,
            }
        ),
        content_type='application/json',
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload['session']['selected_model'] == get_default_selected_model(scope=MODEL_SCOPE_ASSISTANT)


@pytest.mark.django_db
def test_eval_run_rejects_disallowed_target_model_but_allows_judge_only_for_judge():
    MoodPalEvalCase.objects.create(
        case_id='model-scope-case-1',
        title='Model Scope Case 1',
        case_type=MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        first_user_message='开场',
        enabled=True,
    )

    with pytest.raises(EvalRunValidationError) as excinfo:
        create_run(
            created_by=None,
            payload=RunCreateInput(
                target_mode='single_role',
                target_persona_id=MoodPalSession.Persona.LOGIC_BROTHER,
                dataset_split='',
                case_count=1,
                target_model='doubao:doubao-seed-2-0-pro-260215',
                patient_model='qwen:qwen-plus',
                judge_model='qwen:qwen3.5-plus',
            ),
        )

    assert str(excinfo.value) == 'invalid_target_model'
