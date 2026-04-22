from __future__ import annotations

from typing import Optional

from . import router_config
from .node_registry import CBTNodeRegistry
from .state import CBTGraphState
from ..runtime.interfaces import TechniqueRouter
from ..runtime.types import TechniqueSelection


class CBTTechniqueRouter(TechniqueRouter[CBTGraphState]):
    def __init__(self, registry: Optional[CBTNodeRegistry] = None):
        self.registry = registry or CBTNodeRegistry()

    def route(self, state: CBTGraphState) -> TechniqueSelection:
        if state.get('safety_status') == 'crisis_override':
            return TechniqueSelection(
                track='safety_override',
                technique_id='',
                reason='high_risk_content_detected',
                fallback_action='handoff_to_safety',
            )

        exception_selection = self._select_first_matching(router_config.EXCEPTION_ROUTE_RULES, state)
        if exception_selection:
            return exception_selection

        if router_config.AGENDA_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.AGENDA_ROUTE_RULE)

        fallback_selection = self._route_circuit_breaker_fallback(state)
        if fallback_selection:
            return fallback_selection

        if router_config.DEEP_EXPLORATION_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.DEEP_EXPLORATION_ROUTE_RULE)

        behavioral = self._route_behavioral_track(state)
        if behavioral:
            return behavioral

        if router_config.COGNITIVE_RESPONSE_ROUTE_RULE.predicate(state):
            return self._build_selection_from_rule(router_config.COGNITIVE_RESPONSE_ROUTE_RULE)

        evaluation_selection = self._select_first_matching(router_config.COGNITIVE_EVALUATION_ROUTE_RULES, state)
        if evaluation_selection:
            return evaluation_selection

        return self._route_identification_track(state)

    def get_same_track_fallbacks(self, technique_id: str) -> tuple[str, ...]:
        return router_config.SAME_TRACK_FALLBACKS.get(technique_id, ())

    def _route_behavioral_track(self, state: CBTGraphState) -> Optional[TechniqueSelection]:
        return self._route_behavioral_track_with_exclusions(state)

    def _route_circuit_breaker_fallback(self, state: CBTGraphState) -> Optional[TechniqueSelection]:
        if not state.get('circuit_breaker_open'):
            return None

        current_technique_id = (state.get('current_technique_id') or '').strip()
        fallback_action = (state.get('next_fallback_action') or '').strip()
        if not current_technique_id or fallback_action in router_config.TERMINAL_FALLBACK_ACTIONS:
            return None

        if fallback_action == 'switch_same_track':
            for candidate in self.get_same_track_fallbacks(current_technique_id):
                if candidate == current_technique_id:
                    continue
                return self._build_selection_from_technique(
                    technique_id=candidate,
                    reason=f'fallback_after_{current_technique_id}',
                )

        if fallback_action == 'handoff_to_behavioral_track':
            behavioral_selection = self._select_first_matching(
                router_config.BEHAVIORAL_ROUTE_RULES,
                state,
                excluded_technique_ids={current_technique_id},
            )
            if behavioral_selection:
                return behavioral_selection
            for candidate in router_config.BEHAVIORAL_FALLBACK_CANDIDATES:
                if candidate == current_technique_id:
                    continue
                return self._build_selection_from_technique(
                    technique_id=candidate,
                    reason=f'fallback_after_{current_technique_id}',
                    fallback_action=router_config.BEHAVIORAL_FALLBACK_ACTION,
                )

        if fallback_action == 'jump_to_exception':
            exception_selection = self._select_first_matching(
                router_config.EXCEPTION_ROUTE_RULES,
                state,
                excluded_technique_ids={current_technique_id},
            )
            if exception_selection:
                return exception_selection
            return self._build_selection_from_technique(
                technique_id=router_config.DEFAULT_EXCEPTION_FALLBACK_TECHNIQUE,
                reason=f'fallback_after_{current_technique_id}',
                fallback_action='wrap_up_now',
            )

        return None

    def _route_behavioral_track_with_exclusions(
        self,
        state: CBTGraphState,
        *,
        excluded_technique_ids: set[str] | None = None,
    ) -> Optional[TechniqueSelection]:
        return self._select_first_matching(
            router_config.BEHAVIORAL_ROUTE_RULES,
            state,
            excluded_technique_ids=excluded_technique_ids,
        )

    def _route_identification_track(self, state: CBTGraphState) -> TechniqueSelection:
        selection = self._select_first_matching(router_config.IDENTIFICATION_ROUTE_RULES, state)
        assert selection is not None, 'identification_rules_must_have_default'
        return selection

    def _select_first_matching(
        self,
        rules: tuple[router_config.TechniqueRouteRule, ...],
        state: CBTGraphState,
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
            track=self._track_for_technique(technique_id),
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
        fallback_action: str = 'retry_same_technique',
    ) -> TechniqueSelection:
        candidates = router_config.TRACK_CANDIDATES.get(track, ())
        if technique_id:
            self.registry.get_node(technique_id)
        return TechniqueSelection(
            track=track,
            technique_id=technique_id,
            reason=reason,
            fallback_action=fallback_action,
            candidates=candidates,
            metadata={
                'same_track_fallbacks': self.get_same_track_fallbacks(technique_id),
            },
        )

    def _track_for_technique(self, technique_id: str) -> str:
        try:
            return router_config.TECHNIQUE_TRACKS[technique_id]
        except KeyError as exc:
            raise KeyError(f'unknown_track_for_technique:{technique_id}') from exc
