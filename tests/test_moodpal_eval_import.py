import json
from pathlib import Path

import pytest
from django.core.management import call_command

from backend.moodpal_eval.models import MoodPalEvalCase, MoodPalEvalRun
from backend.moodpal_eval.services.case_import_service import (
    EvalCaseImportError,
    build_real_case_payload,
    build_synthetic_case_payload,
)


@pytest.mark.django_db
def test_eval_run_threshold_default_is_80():
    run = MoodPalEvalRun.objects.create(
        target_mode=MoodPalEvalRun.TargetMode.MASTER_GUIDE,
        target_persona_id='master_guide',
    )
    assert run.threshold_score == 80


@pytest.mark.django_db
def test_build_real_case_payload_extracts_first_user_message_and_splits():
    payload = build_real_case_payload(
        {
            'id': 8,
            'normalizedTag': '婚恋',
            'messages': [
                {'role': 'system', 'content': 's'},
                {'role': 'user', 'content': '第一句用户'},
                {'role': 'assistant', 'content': 'a'},
                {'role': 'user', 'content': '第二句用户'},
            ],
        }
    )

    assert payload['case_id'] == 'soulchat_real_8'
    assert payload['first_user_message'] == '第一句用户'
    assert payload['turn_count'] == 2
    assert 'core_regression' in payload['splits']
    assert 'long_tail' in payload['splits']


@pytest.mark.django_db
def test_build_synthetic_case_payload_defaults_to_extreme_split():
    payload = build_synthetic_case_payload(
        {
            'case_id': 'synthetic_case_1',
            'title': 'Synthetic 1',
            'messages': [
                {'role': 'user', 'content': '开场'},
                {'role': 'assistant', 'content': '回应'},
            ],
        }
    )

    assert payload['case_type'] == MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME
    assert payload['splits'] == ['extreme_cases']
    assert payload['first_user_message'] == '开场'


@pytest.mark.django_db
def test_build_case_payload_raises_when_user_message_missing():
    with pytest.raises(EvalCaseImportError):
        build_real_case_payload(
            {
                'id': 2,
                'normalizedTag': '职场',
                'messages': [
                    {'role': 'assistant', 'content': 'no user'},
                ],
            }
        )


@pytest.mark.django_db
def test_import_command_loads_real_and_synthetic_cases(tmp_path: Path):
    real_path = tmp_path / 'real.json'
    real_path.write_text(
        json.dumps(
            [
                {
                    'id': 1,
                    'normalizedTag': '职场',
                    'messages': [
                        {'role': 'user', 'content': '真实开场'},
                        {'role': 'assistant', 'content': '真实回应'},
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    synthetic_dir = tmp_path / 'synthetic'
    synthetic_dir.mkdir()
    (synthetic_dir / 'case.json').write_text(
        json.dumps(
            {
                'case_id': 'synthetic_case_2',
                'title': 'Synthetic 2',
                'topic_tag': '阻抗',
                'messages': [
                    {'role': 'user', 'content': '合成开场'},
                    {'role': 'assistant', 'content': '合成回应'},
                ],
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    call_command(
        'import_moodpal_eval_cases',
        source_file=str(real_path),
        synthetic_dir=str(synthetic_dir),
    )

    assert MoodPalEvalCase.objects.filter(case_id='soulchat_real_1').exists()
    assert MoodPalEvalCase.objects.filter(case_id='synthetic_case_2').exists()
