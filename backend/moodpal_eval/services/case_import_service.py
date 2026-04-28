from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from backend.moodpal_eval.models import MoodPalEvalCase

VALID_ROLES = {'system', 'user', 'assistant'}
DEFAULT_REAL_DATASET = 'soulchat_multiturn_packing'
DEFAULT_SYNTHETIC_DATASET = 'synthetic_extreme_v1'


class EvalCaseImportError(ValueError):
    pass


class ImportStats(dict):
    def __init__(self):
        super().__init__(created=0, updated=0, skipped=0)


def import_real_cases_from_file(source_path: str | Path) -> dict:
    path = Path(source_path)
    records = json.loads(path.read_text(encoding='utf-8'))
    stats = ImportStats()
    for raw_record in records:
        payload = build_real_case_payload(raw_record)
        _upsert_case(payload, stats)
    return dict(stats)


def import_synthetic_cases_from_dir(directory: str | Path) -> dict:
    path = Path(directory)
    stats = ImportStats()
    for item in sorted(path.glob('*.json')):
        payload = build_synthetic_case_payload(json.loads(item.read_text(encoding='utf-8')))
        _upsert_case(payload, stats)
    return dict(stats)


def build_real_case_payload(raw_record: dict) -> dict:
    record_id = raw_record.get('id')
    if record_id is None:
        raise EvalCaseImportError('missing_real_case_id')
    messages = _normalize_messages(raw_record.get('messages') or [])
    if not messages:
        raise EvalCaseImportError('empty_messages')
    first_user_message = _extract_first_user_message(messages)
    topic_tag = str(raw_record.get('normalizedTag') or '').strip()
    case_id = f'soulchat_real_{record_id}'
    payload = {
        'case_id': case_id,
        'title': f'{topic_tag or "未分类"} #{record_id}',
        'case_type': MoodPalEvalCase.CaseType.DATASET_REAL,
        'source_dataset': DEFAULT_REAL_DATASET,
        'topic_tag': topic_tag,
        'splits': _deterministic_real_case_splits(int(record_id)),
        'full_reference_dialogue': messages,
        'first_user_message': first_user_message,
        'turn_count': _dialogue_turn_count(messages),
        'risk_hint': '',
        'enabled': True,
        'notes': '',
    }
    payload['source_hash'] = _build_source_hash(payload)
    return payload


def build_synthetic_case_payload(raw_record: dict) -> dict:
    case_id = str(raw_record.get('case_id') or '').strip()
    if not case_id:
        raise EvalCaseImportError('missing_synthetic_case_id')
    messages = _normalize_messages(raw_record.get('messages') or raw_record.get('full_reference_dialogue') or [])
    first_user_message = str(raw_record.get('first_user_message') or '').strip() or _extract_first_user_message(messages)
    payload = {
        'case_id': case_id,
        'title': str(raw_record.get('title') or case_id).strip(),
        'case_type': MoodPalEvalCase.CaseType.SYNTHETIC_EXTREME,
        'source_dataset': str(raw_record.get('source_dataset') or DEFAULT_SYNTHETIC_DATASET).strip(),
        'topic_tag': str(raw_record.get('topic_tag') or '').strip(),
        'splits': _normalize_splits(raw_record.get('splits') or ['extreme_cases']),
        'full_reference_dialogue': messages,
        'first_user_message': first_user_message,
        'turn_count': int(raw_record.get('turn_count') or _dialogue_turn_count(messages)),
        'risk_hint': str(raw_record.get('risk_hint') or '').strip(),
        'enabled': bool(raw_record.get('enabled', True)),
        'notes': str(raw_record.get('notes') or '').strip(),
    }
    payload['source_hash'] = _build_source_hash(payload)
    return payload


def _upsert_case(payload: dict, stats: ImportStats) -> MoodPalEvalCase:
    case, created = MoodPalEvalCase.objects.update_or_create(
        case_id=payload['case_id'],
        defaults=payload,
    )
    if created:
        stats['created'] += 1
    else:
        stats['updated'] += 1
    return case


def _normalize_messages(raw_messages: Iterable[dict]) -> list[dict]:
    messages = []
    for index, raw_message in enumerate(raw_messages):
        if not isinstance(raw_message, dict):
            raise EvalCaseImportError(f'invalid_message_at_{index}')
        role = str(raw_message.get('role') or '').strip().lower()
        content = str(raw_message.get('content') or '').strip()
        if role not in VALID_ROLES:
            raise EvalCaseImportError(f'invalid_role_{role or "empty"}')
        if not content:
            raise EvalCaseImportError(f'empty_content_at_{index}')
        messages.append({'role': role, 'content': content})
    return messages


def _extract_first_user_message(messages: list[dict]) -> str:
    for message in messages:
        if message.get('role') == 'user':
            return message.get('content', '')
    raise EvalCaseImportError('missing_first_user_message')


def _dialogue_turn_count(messages: list[dict]) -> int:
    return sum(1 for item in messages if item.get('role') == 'user')


def _normalize_splits(raw_splits: Iterable[str]) -> list[str]:
    seen = set()
    normalized = []
    for item in raw_splits:
        value = str(item or '').strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized or ['extreme_cases']


def _deterministic_real_case_splits(record_id: int) -> list[str]:
    splits = ['core_regression']
    if record_id % 97 < 5:
        splits.append('smoke')
    if record_id % 4 == 0:
        splits.append('long_tail')
    return splits


def _build_source_hash(payload: dict) -> str:
    serialized = json.dumps(
        {
            'case_id': payload['case_id'],
            'title': payload['title'],
            'case_type': payload['case_type'],
            'source_dataset': payload['source_dataset'],
            'topic_tag': payload['topic_tag'],
            'splits': payload['splits'],
            'full_reference_dialogue': payload['full_reference_dialogue'],
            'first_user_message': payload['first_user_message'],
            'turn_count': payload['turn_count'],
            'risk_hint': payload['risk_hint'],
            'enabled': payload['enabled'],
            'notes': payload['notes'],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()
