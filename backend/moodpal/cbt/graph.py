from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .executor import CBTTechniqueExecutor
from .exit_evaluator import CBTExitEvaluator
from .router import CBTTechniqueRouter
from .state import CBTGraphState
from ..runtime.interfaces import GraphRunner
from ..runtime.types import ExecutionPayload, ExitEvaluationResult, TechniqueSelection


@dataclass(frozen=True)
class CBTGraphTurnPlan:
    selection: TechniqueSelection
    payload: Optional[ExecutionPayload]


class CBTGraph(GraphRunner[CBTGraphState]):
    def __init__(
        self,
        *,
        router: Optional[CBTTechniqueRouter] = None,
        executor: Optional[CBTTechniqueExecutor] = None,
        exit_evaluator: Optional[CBTExitEvaluator] = None,
    ):
        self.router = router or CBTTechniqueRouter()
        self.executor = executor or CBTTechniqueExecutor(self.router.registry)
        self.exit_evaluator = exit_evaluator or CBTExitEvaluator()

    def plan_turn(self, state: CBTGraphState) -> CBTGraphTurnPlan:
        selection = self.router.route(state)
        payload = None
        if selection.technique_id:
            payload = self.executor.build_payload(state, selection.technique_id)
        return CBTGraphTurnPlan(selection=selection, payload=payload)

    def evaluate_turn(self, state: CBTGraphState, technique_id: str) -> ExitEvaluationResult:
        return self.exit_evaluator.evaluate(state, technique_id)
