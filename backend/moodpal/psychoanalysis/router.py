from __future__ import annotations

from typing import Optional

from . import router_config
from .node_registry import PsychoanalysisNodeRegistry
from .state import PsychoanalysisGraphState
from ..runtime.interfaces import TechniqueRouter
from ..runtime.types import TechniqueSelection


class PsychoanalysisTechniqueRouter(TechniqueRouter[PsychoanalysisGraphState]):
    def __init__(self, registry: Optional[PsychoanalysisNodeRegistry] = None):
        self.registry = registry or PsychoanalysisNodeRegistry()

    def route(self, state: PsychoanalysisGraphState) -> TechniqueSelection:
        if state.get('safety_status') == 'crisis_override':
            return TechniqueSelection(
                track='safety_override',
                technique_id='',
                reason='high_risk_content_detected',
                fallback_action='handoff_to_safety',
            )

        if router_config.CLOSING_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.CLOSING_ROUTE_RULE)

        repair_selection = self._select_first_matching(router_config.REPAIR_ROUTE_RULES, state)
        if repair_selection:
            return repair_selection

        if router_config.BOUNDARY_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.BOUNDARY_ROUTE_RULE)

        if router_config.CONTAINMENT_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.CONTAINMENT_ROUTE_RULE)

        fallback_selection = self._route_circuit_breaker_fallback(state)
        if fallback_selection:
            return fallback_selection

        if router_config.RELATIONAL_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.RELATIONAL_ROUTE_RULE)

        if router_config.INSIGHT_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.INSIGHT_ROUTE_RULE)

        if router_config.DEFENSE_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.DEFENSE_ROUTE_RULE)

        if router_config.PATTERN_LINK_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.PATTERN_LINK_ROUTE_RULE)

        return self._build_selection_from_rule(router_config.ASSOCIATION_ROUTE_RULE)

    def get_same_phase_fallbacks(self, technique_id: str) -> tuple[str, ...]:
        return router_config.SAME_PHASE_FALLBACKS.get(technique_id, ())

    def _route_circuit_breaker_fallback(self, state: PsychoanalysisGraphState) -> Optional[TechniqueSelection]:
        if not state.get('circuit_breaker_open'):
            return None

        current_technique_id = (state.get('current_technique_id') or '').strip()
        fallback_action = (state.get('next_fallback_action') or '').strip()
        if not current_technique_id or fallback_action in router_config.TERMINAL_FALLBACK_ACTIONS:
            return None

        if fallback_action == 'switch_same_phase':
            for candidate in self.get_same_phase_fallbacks(current_technique_id):
                if candidate == current_technique_id:
                    continue
                return self._build_selection_from_technique(
                    technique_id=candidate,
                    reason=f'fallback_after_{current_technique_id}',
                )

        if fallback_action == 'regress_to_containment':
            return self._build_selection_from_rule(router_config.CONTAINMENT_ROUTE_RULE)

        if fallback_action == 'jump_to_repair':
            repair_selection = self._select_first_matching(
                router_config.REPAIR_ROUTE_RULES,
                state,
                excluded_technique_ids={current_technique_id},
            )
            if repair_selection:
                return repair_selection
            return self._build_selection_from_technique(
                technique_id=router_config.DEFAULT_REPAIR_FALLBACK_TECHNIQUE,
                reason=f'fallback_after_{current_technique_id}',
                fallback_action='wrap_up_now',
            )

        if fallback_action == 'wrap_up_now':
            return self._build_selection_from_rule(router_config.CLOSING_ROUTE_RULE)

        return None

    def _select_first_matching(
        self,
        rules: tuple[router_config.TechniqueRouteRule, ...],
        state: PsychoanalysisGraphState,
        *,
        excluded_technique_ids: set[str] | None = None,
    ) -> Optional[TechniqueSelection]:
        excluded = excluded_technique_ids or set()
        for rule in rules:
            if rule.technique_id in excluded:
                continue
            if rule.predicate(state):
                return self._build_selection_from_rule(rule)
        return None

    def _build_selection_from_rule(self, rule: router_config.TechniqueRouteRule) -> TechniqueSelection:
        return self._build_selection(
            track=rule.track,
            technique_id=rule.technique_id,
            reason=rule.reason,
            fallback_action=rule.fallback_action,
        )

    def _build_selection_from_technique(
        self,
        *,
        technique_id: str,
        reason: str,
        fallback_action: str = router_config.DEFAULT_FALLBACK_ACTION,
    ) -> TechniqueSelection:
        return self._build_selection(
            track=self._phase_for_technique(technique_id),
            technique_id=technique_id,
            reason=reason,
            fallback_action=fallback_action,
        )

    def _build_selection(
        self,
        *,
        track: str,
        technique_id: str,
        reason: str,
        fallback_action: str = router_config.DEFAULT_FALLBACK_ACTION,
    ) -> TechniqueSelection:
        candidates = router_config.PHASE_CANDIDATES.get(track, ())
        if technique_id:
            self.registry.get_node(technique_id)
        return TechniqueSelection(
            track=track,
            technique_id=technique_id,
            reason=reason,
            fallback_action=fallback_action,
            candidates=candidates,
            metadata={
                'same_phase_fallbacks': self.get_same_phase_fallbacks(technique_id),
            },
        )

    def _phase_for_technique(self, technique_id: str) -> str:
        try:
            return router_config.TECHNIQUE_PHASES[technique_id]
        except KeyError as exc:
            raise KeyError(f'unknown_phase_for_technique:{technique_id}') from exc
