from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .route_policy import choose_support_directive, should_hold_for_support, should_prefer_cbt, should_prefer_psychoanalysis
from .routing_signal_extractor import extract_master_guide_routing_signals
from .state import MasterGuideState


@dataclass(frozen=True)
class MasterGuideRouteSelection:
    mode: str
    reason_code: str
    support_mode: str = 'none'
    support_directive: str = ''
    switch_from: str = ''
    switch_to: str = ''
    metadata: dict = field(default_factory=dict)


class MasterGuideRouter:
    def route(self, state: MasterGuideState, signals: Optional[dict] = None) -> MasterGuideRouteSelection:
        signals = signals or extract_master_guide_routing_signals(state)
        previous_track = str(state.get('active_main_track') or '')
        turn_index = int(state.get('turn_index') or 0)
        user_text = str(state.get('last_user_message') or '')

        should_support_only, support_reason = should_hold_for_support(
            turn_index=turn_index,
            repair_needed=bool(signals.get('repair_needed')),
            distress_level=str(signals.get('distress_level') or 'medium'),
            problem_clarity=str(signals.get('problem_clarity') or 'low'),
            recent_track_progress=str(signals.get('recent_track_progress') or 'none'),
        )
        if should_support_only:
            support_mode = 'opening' if support_reason == 'opening_hold' else 'repair'
            return MasterGuideRouteSelection(
                mode='support_only',
                reason_code=support_reason,
                support_mode=support_mode,
                support_directive=choose_support_directive(
                    support_mode=support_mode,
                    previous_track=previous_track,
                    next_mode='support_only',
                ),
                switch_from=previous_track,
                switch_to='support_only',
                metadata={'signals': signals},
            )

        if should_prefer_psychoanalysis(
            pattern_signal_strength=str(signals.get('pattern_signal_strength') or 'low'),
            psychoanalysis_readiness=str(signals.get('psychoanalysis_readiness') or 'low'),
            action_readiness=str(signals.get('action_readiness') or 'low'),
            previous_track=previous_track,
            text=user_text,
        ):
            reason_code = 'continue_psychoanalysis' if previous_track == 'psychoanalysis' else 'psy_repetition_pattern'
            return MasterGuideRouteSelection(
                mode='psychoanalysis',
                reason_code=reason_code,
                support_mode='handoff',
                support_directive=choose_support_directive(
                    support_mode='handoff',
                    previous_track=previous_track,
                    next_mode='psychoanalysis',
                ),
                switch_from=previous_track,
                switch_to='psychoanalysis',
                metadata={'signals': signals},
            )

        if should_prefer_cbt(
            problem_clarity=str(signals.get('problem_clarity') or 'low'),
            action_readiness=str(signals.get('action_readiness') or 'low'),
            previous_track=previous_track,
        ):
            reason_code = 'continue_cbt' if previous_track == 'cbt' else 'cbt_problem_solving'
            return MasterGuideRouteSelection(
                mode='cbt',
                reason_code=reason_code,
                support_mode='handoff',
                support_directive=choose_support_directive(
                    support_mode='handoff',
                    previous_track=previous_track,
                    next_mode='cbt',
                ),
                switch_from=previous_track,
                switch_to='cbt',
                metadata={'signals': signals},
            )

        return MasterGuideRouteSelection(
            mode='support_only',
            reason_code='clarity_hold',
            support_mode='handoff',
            support_directive=choose_support_directive(
                support_mode='handoff',
                previous_track=previous_track,
                next_mode='support_only',
            ),
            switch_from=previous_track,
            switch_to='support_only',
            metadata={'signals': signals},
        )
