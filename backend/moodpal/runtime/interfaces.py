from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from .types import ExecutionPayload, ExitEvaluationResult, TechniqueNode, TechniqueSelection


StateT = TypeVar('StateT')


class NodeRegistry(ABC, Generic[StateT]):
    @abstractmethod
    def all_nodes(self) -> list[TechniqueNode]:
        raise NotImplementedError

    @abstractmethod
    def get_node(self, technique_id: str) -> TechniqueNode:
        raise NotImplementedError


class TechniqueRouter(ABC, Generic[StateT]):
    @abstractmethod
    def route(self, state: StateT) -> TechniqueSelection:
        raise NotImplementedError


class TechniqueExecutor(ABC, Generic[StateT]):
    @abstractmethod
    def build_payload(self, state: StateT, technique_id: str) -> ExecutionPayload:
        raise NotImplementedError


class ExitEvaluator(ABC, Generic[StateT]):
    @abstractmethod
    def evaluate(self, state: StateT, technique_id: str) -> ExitEvaluationResult:
        raise NotImplementedError


class GraphRunner(ABC, Generic[StateT]):
    @abstractmethod
    def plan_turn(self, state: StateT):
        raise NotImplementedError
