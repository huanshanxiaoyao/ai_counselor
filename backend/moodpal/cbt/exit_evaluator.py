from __future__ import annotations

from . import exit_rule_config
from .state import CBTGraphState
from ..runtime.interfaces import ExitEvaluator
from ..runtime.types import ExitEvaluationResult


class CBTExitEvaluator(ExitEvaluator[CBTGraphState]):
    MAX_ATTEMPTS = 3
    MAX_STALLS = 2

    def evaluate(self, state: CBTGraphState, technique_id: str) -> ExitEvaluationResult:
        rule = exit_rule_config.get_exit_rule(technique_id)
        done, confidence, reason, progress_marker = rule.evaluator(state)

        previous_progress = state.get('last_progress_marker', '')
        attempt_count = int(state.get('technique_attempt_count') or 0) + 1
        stall_detected = (not done) and (not progress_marker or progress_marker == previous_progress)
        stall_count = int(state.get('technique_stall_count') or 0) + 1 if stall_detected else 0

        should_trip_circuit = bool(state.get('circuit_breaker_open'))
        trip_reason = ''
        next_fallback_action = 'retry_same_technique'

        if not done and (attempt_count >= self.MAX_ATTEMPTS or stall_count >= self.MAX_STALLS):
            should_trip_circuit = True
            trip_reason = 'attempt_limit_reached' if attempt_count >= self.MAX_ATTEMPTS else 'stall_limit_reached'
            next_fallback_action = rule.trip_action
        elif done:
            next_fallback_action = rule.done_action

        state_patch = {
            'technique_attempt_count': attempt_count,
            'technique_stall_count': stall_count,
            'last_progress_marker': progress_marker or previous_progress,
            'circuit_breaker_open': should_trip_circuit,
            'next_fallback_action': next_fallback_action,
        }
        return ExitEvaluationResult(
            done=done,
            confidence=confidence,
            reason=reason,
            state_patch=state_patch,
            progress_marker=progress_marker,
            stall_detected=stall_detected,
            technique_attempt_count=attempt_count,
            technique_stall_count=stall_count,
            should_trip_circuit=should_trip_circuit,
            trip_reason=trip_reason,
            next_fallback_action=next_fallback_action,
        )
