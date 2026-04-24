from backend.moodpal.psychoanalysis import (
    PsychoanalysisGraph,
    PsychoanalysisNodeRegistry,
    PsychoanalysisTechniqueRouter,
)
from backend.moodpal.psychoanalysis.state import make_initial_psychoanalysis_state


def test_psychoanalysis_node_registry_loads_all_json_nodes():
    registry = PsychoanalysisNodeRegistry()
    nodes = registry.all_nodes()
    node_ids = {node.node_id for node in nodes}

    assert len(nodes) == 10
    assert 'psa_entry_containment' in node_ids
    assert 'psa_pattern_linking' in node_ids
    assert 'psa_reflective_close' in node_ids


def test_psychoanalysis_router_prioritizes_alliance_repair_override():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '你根本没懂我，别分析我了。'
    state['alliance_rupture_detected'] = True
    state['resistance_level'] = 'high'

    selection = router.route(state)

    assert selection.track == 'repair'
    assert selection.technique_id == 'psa_exception_alliance_repair'


def test_psychoanalysis_router_selects_boundary_repair_for_advice_pull():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '别分析了，直接告诉我怎么办。'

    selection = router.route(state)

    assert selection.track == 'boundary'
    assert selection.technique_id == 'psa_boundary_advice_pull'


def test_psychoanalysis_router_selects_containment_for_guarded_high_intensity_state():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '我现在一想到这个就整个人都缩起来了。'
    state['association_openness'] = 'guarded'
    state['emotional_intensity'] = 8

    selection = router.route(state)

    assert selection.track == 'containment'
    assert selection.technique_id == 'psa_entry_containment'


def test_psychoanalysis_router_selects_defense_clarification_before_pattern_linking():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '其实也没什么，大家都这样。'
    state['active_defense'] = 'intellectualization'
    state['repetition_theme_candidate'] = 'authority_tension'
    state['resistance_level'] = 'medium'

    selection = router.route(state)

    assert selection.track == 'defense_clarification'
    assert selection.technique_id == 'psa_defense_clarification'


def test_psychoanalysis_router_selects_pattern_linking_when_repetition_candidate_is_ready():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '不只是这次，我每次遇到这种场面都会先怪自己。'
    state['repetition_theme_candidate'] = 'self_blame_under_authority'
    state['alliance_strength'] = 'strong'

    selection = router.route(state)

    assert selection.track == 'pattern_linking'
    assert selection.technique_id == 'psa_pattern_linking'


def test_psychoanalysis_router_selects_relational_reflection_on_here_and_now_signal():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['last_user_message'] = '你这么说，我就更不想讲了。'
    state['here_and_now_triggered'] = True
    state['alliance_strength'] = 'medium'

    selection = router.route(state)

    assert selection.track == 'relational_reflection'
    assert selection.technique_id == 'psa_relational_here_now'


def test_psychoanalysis_router_selects_insight_integration_when_working_hypothesis_is_ready():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['working_hypothesis'] = '一感到关系紧张，就会先把问题收回到自己身上。'
    state['pattern_confidence'] = 0.82
    state['alliance_strength'] = 'strong'
    state['resistance_level'] = 'low'

    selection = router.route(state)

    assert selection.track == 'insight_integration'
    assert selection.technique_id == 'psa_insight_integration'


def test_psychoanalysis_router_uses_same_phase_fallback_after_pattern_link_trip():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['current_technique_id'] = 'psa_pattern_linking'
    state['circuit_breaker_open'] = True
    state['next_fallback_action'] = 'switch_same_phase'

    selection = router.route(state)

    assert selection.track == 'association'
    assert selection.technique_id == 'psa_association_invite'


def test_psychoanalysis_router_regresses_to_containment_on_fallback_signal():
    router = PsychoanalysisTechniqueRouter()
    state = make_initial_psychoanalysis_state()
    state['current_technique_id'] = 'psa_insight_integration'
    state['circuit_breaker_open'] = True
    state['next_fallback_action'] = 'regress_to_containment'

    selection = router.route(state)

    assert selection.track == 'containment'
    assert selection.technique_id == 'psa_entry_containment'


def test_psychoanalysis_graph_returns_closing_node_for_wrap_up_stage():
    graph = PsychoanalysisGraph()
    state = make_initial_psychoanalysis_state()
    state['current_stage'] = 'wrap_up'
    state['working_hypothesis'] = '一感觉到别人不高兴，就会先把自己收回去'

    plan = graph.plan_turn(state)

    assert plan.selection.track == 'closing'
    assert plan.selection.technique_id == 'psa_reflective_close'
    assert plan.payload is not None
    assert '只留下一个轻量观察锚点' in plan.payload.system_prompt
