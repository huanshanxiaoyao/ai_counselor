from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TechniqueNode:
    node_id: str
    name: str
    category: str
    book_reference: str
    trigger_intent: tuple[str, ...]
    prerequisites: tuple[str, ...]
    system_instruction: str
    examples: tuple[dict[str, str], ...]
    exit_criteria: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TechniqueSelection:
    track: str
    technique_id: str
    reason: str
    fallback_action: str = 'retry_same_technique'
    candidates: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPayload:
    technique_id: str
    system_prompt: str
    user_prompt: str
    visible_reply_hint: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitEvaluationResult:
    done: bool
    confidence: float
    reason: str
    state_patch: dict[str, Any] = field(default_factory=dict)
    progress_marker: str = ''
    stall_detected: bool = False
    technique_attempt_count: int = 0
    technique_stall_count: int = 0
    should_trip_circuit: bool = False
    trip_reason: str = ''
    next_fallback_action: str = 'retry_same_technique'
