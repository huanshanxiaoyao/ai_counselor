from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .router import MasterGuideRouteSelection, MasterGuideRouter
from .routing_signal_extractor import extract_master_guide_routing_signals
from .state import MasterGuideState


@dataclass(frozen=True)
class MasterGuideTurnPlan:
    selection: MasterGuideRouteSelection
    signals: dict


class MasterGuideGraph:
    def __init__(self, *, router: Optional[MasterGuideRouter] = None):
        self.router = router or MasterGuideRouter()

    def plan_turn(self, state: MasterGuideState) -> MasterGuideTurnPlan:
        signals = extract_master_guide_routing_signals(state)
        selection = self.router.route(state, signals)
        return MasterGuideTurnPlan(selection=selection, signals=signals)
