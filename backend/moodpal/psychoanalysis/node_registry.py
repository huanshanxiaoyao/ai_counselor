from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

from ..runtime.interfaces import NodeRegistry
from ..runtime.types import TechniqueNode


PSYCHOANALYSIS_DOCS_DIR = Path(__file__).resolve().parents[3] / 'docs' / 'moodpal' / 'Psychoanalysis'


def _to_node(payload: dict) -> TechniqueNode:
    return TechniqueNode(
        node_id=payload['node_id'],
        name=payload['name'],
        category=payload['category'],
        book_reference=payload.get('book_reference', ''),
        trigger_intent=tuple(payload.get('trigger_intent') or []),
        prerequisites=tuple(payload.get('prerequisites') or []),
        system_instruction=payload.get('system_instruction', ''),
        examples=tuple(payload.get('examples') or []),
        exit_criteria=payload.get('exit_criteria', ''),
        metadata={},
    )


@lru_cache(maxsize=1)
def load_psychoanalysis_nodes() -> dict[str, TechniqueNode]:
    nodes = {}
    for file_path in sorted(PSYCHOANALYSIS_DOCS_DIR.glob('*.json')):
        with file_path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
        for item in payload:
            node = _to_node(item)
            nodes[node.node_id] = node
    return nodes


class PsychoanalysisNodeRegistry(NodeRegistry[dict]):
    def __init__(self, nodes: Optional[dict[str, TechniqueNode]] = None):
        self._nodes = nodes or load_psychoanalysis_nodes()

    def all_nodes(self) -> list[TechniqueNode]:
        return list(self._nodes.values())

    def get_node(self, technique_id: str) -> TechniqueNode:
        try:
            return self._nodes[technique_id]
        except KeyError as exc:
            raise KeyError(f'unknown_technique:{technique_id}') from exc

    def get_many(self, technique_ids: Sequence[str]) -> list[TechniqueNode]:
        return [self.get_node(technique_id) for technique_id in technique_ids]
