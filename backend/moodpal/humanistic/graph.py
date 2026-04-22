from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .executor import HumanisticTechniqueExecutor
from .resonance_evaluator import HumanisticResonanceEvaluator
from .router import HumanisticTechniqueRouter
from .state import HumanisticGraphState
from ..runtime.interfaces import GraphRunner
from ..runtime.types import ExecutionPayload, ExitEvaluationResult, TechniqueSelection


@dataclass(frozen=True)
class HumanisticGraphTurnPlan:
    selection: TechniqueSelection
    payload: Optional[ExecutionPayload]


class HumanisticGraph(GraphRunner[HumanisticGraphState]):
    def __init__(
        self,
        *,
        router: Optional[HumanisticTechniqueRouter] = None,
        executor: Optional[HumanisticTechniqueExecutor] = None,
        resonance_evaluator: Optional[HumanisticResonanceEvaluator] = None,
    ):
        self.router = router or HumanisticTechniqueRouter()
        self.executor = executor or HumanisticTechniqueExecutor(self.router.registry)
        self.resonance_evaluator = resonance_evaluator or HumanisticResonanceEvaluator()

    def plan_turn(self, state: HumanisticGraphState) -> HumanisticGraphTurnPlan:
        selection = self.router.route(state)
        payload = None
        if selection.technique_id:
            payload = self.executor.build_payload(state, selection.technique_id)
        return HumanisticGraphTurnPlan(selection=selection, payload=payload)

    def evaluate_turn(self, state: HumanisticGraphState, technique_id: str) -> ExitEvaluationResult:
        return self.resonance_evaluator.evaluate(state, technique_id)
