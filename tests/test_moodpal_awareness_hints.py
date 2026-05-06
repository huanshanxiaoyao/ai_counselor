import pytest
from backend.moodpal.awareness_hints import get_awareness_hint, AWARENESS_HINTS, OPENING_TURN_THRESHOLD


def test_opening_turn_threshold_is_three():
    assert OPENING_TURN_THRESHOLD == 3


def test_returns_empty_during_opening_turns():
    for technique_id in ('cbt_cog_identify_at_basic', 'hum_validate_normalize', 'psa_entry_containment'):
        for turn in range(OPENING_TURN_THRESHOLD):
            result = get_awareness_hint(technique_id, turn)
            assert result == '', f'Expected empty for turn={turn}, technique={technique_id}'


def test_returns_hint_after_opening_turns():
    hint = get_awareness_hint('cbt_cog_identify_at_basic', turn_index=3)
    assert len(hint) > 5
    assert '节点' not in hint
    assert 'technique' not in hint


def test_all_cbt_techniques_have_hints():
    cbt_techniques = [
        'cbt_structure_agenda_setting', 'cbt_cog_identify_at_basic',
        'cbt_cog_identify_at_telegraphic', 'cbt_cog_identify_at_imagery',
        'cbt_cog_eval_socratic', 'cbt_cog_eval_distortion',
        'cbt_cog_response_coping', 'cbt_beh_activation',
        'cbt_beh_experiment', 'cbt_beh_graded_task',
        'cbt_core_downward_arrow', 'cbt_exception_alliance_rupture',
        'cbt_exception_redirecting', 'cbt_exception_homework_obstacle',
        'cbt_exception_yes_but',
    ]
    for tid in cbt_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_all_humanistic_techniques_have_hints():
    hum_techniques = [
        'hum_validate_normalize', 'hum_reflect_feeling', 'hum_body_focus',
        'hum_unconditional_regard', 'hum_exception_alliance_repair',
        'hum_exception_numbness_unfreeze', 'hum_boundary_advice_pull',
    ]
    for tid in hum_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_all_psychoanalysis_techniques_have_hints():
    psa_techniques = [
        'psa_entry_containment', 'psa_association_invite', 'psa_defense_clarification',
        'psa_pattern_linking', 'psa_relational_here_now', 'psa_insight_integration',
        'psa_exception_resistance_soften', 'psa_exception_alliance_repair',
        'psa_boundary_advice_pull', 'psa_reflective_close',
    ]
    for tid in psa_techniques:
        assert tid in AWARENESS_HINTS, f'Missing hint for {tid}'


def test_hints_contain_no_clinical_labels():
    clinical_terms = ['CBT', '精神分析', '人本主义', 'technique_id', '节点', '状态机']
    for tid, hint in AWARENESS_HINTS.items():
        for term in clinical_terms:
            assert term not in hint, f'Hint for {tid} contains clinical term: {term}'


def test_unknown_technique_returns_empty():
    result = get_awareness_hint('unknown_technique', turn_index=10)
    assert result == ''
