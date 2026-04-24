from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .executor import PsychoanalysisTechniqueExecutor
from .insight_evaluator import PsychoanalysisInsightEvaluator
from .router import PsychoanalysisTechniqueRouter
from .state import PsychoanalysisGraphState
from ..runtime.interfaces import GraphRunner
from ..runtime.types import ExecutionPayload, ExitEvaluationResult, TechniqueSelection


@dataclass(frozen=True)
class PsychoanalysisGraphTurnPlan:
    selection: TechniqueSelection
    payload: Optional[ExecutionPayload]


class PsychoanalysisGraph(GraphRunner[PsychoanalysisGraphState]):
    def __init__(
        self,
        *,
        router: Optional[PsychoanalysisTechniqueRouter] = None,
        executor: Optional[PsychoanalysisTechniqueExecutor] = None,
        insight_evaluator: Optional[PsychoanalysisInsightEvaluator] = None,
    ):
        self.router = router or PsychoanalysisTechniqueRouter()
        self.executor = executor or PsychoanalysisTechniqueExecutor(self.router.registry)
        self.insight_evaluator = insight_evaluator or PsychoanalysisInsightEvaluator()

    def plan_turn(self, state: PsychoanalysisGraphState) -> PsychoanalysisGraphTurnPlan:
        selection = self.router.route(state)
        payload = None
        if selection.technique_id:
            payload = self.executor.build_payload(state, selection.technique_id)
        return PsychoanalysisGraphTurnPlan(selection=selection, payload=payload)

    def evaluate_turn(self, state: PsychoanalysisGraphState, technique_id: str) -> ExitEvaluationResult:
        return self.insight_evaluator.evaluate(state, technique_id)
