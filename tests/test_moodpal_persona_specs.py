import pytest
from backend.moodpal.persona_specs import get_persona_spec, PERSONA_SPECS


def test_all_four_personas_defined():
    for pid in ('logic_brother', 'empathy_sister', 'insight_mentor', 'master_guide'):
        assert pid in PERSONA_SPECS
        assert len(PERSONA_SPECS[pid]) > 100


def test_get_persona_spec_returns_correct_text():
    spec = get_persona_spec('logic_brother')
    assert '逻辑哥哥' in spec
    assert '李诞' in spec
    assert '足球' in spec


def test_get_persona_spec_empathy_sister():
    spec = get_persona_spec('empathy_sister')
    assert '共情学姐' in spec
    assert '旅行' in spec


def test_get_persona_spec_insight_mentor():
    spec = get_persona_spec('insight_mentor')
    assert '心理学前辈' in spec
    assert '我在想' in spec


def test_get_persona_spec_master_guide():
    spec = get_persona_spec('master_guide')
    assert '主理人' in spec
    assert '蔡康永' in spec


def test_get_persona_spec_unknown_returns_fallback():
    spec = get_persona_spec('unknown_persona')
    assert len(spec) > 10
    assert spec != ''


def test_persona_specs_contain_no_clinical_labels():
    clinical_terms = ['CBT', '精神分析', '人本主义', '节点', '状态机', 'technique_id']
    for pid, spec in PERSONA_SPECS.items():
        for term in clinical_terms:
            assert term not in spec, f'{pid} spec contains clinical term: {term}'
