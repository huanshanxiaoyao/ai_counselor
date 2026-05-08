from __future__ import annotations

from functools import lru_cache
from pathlib import Path

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_SOULS_DIR = Path(__file__).parent / 'souls'
_FALLBACK_SPEC = '你是一个温和、稳定的对话伙伴，尊重对方节奏，不说教，不预设结论。'


def _parse_soul_file(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        return {}, text.strip()
    try:
        end_idx = text.index('\n---\n', 4)
    except ValueError:
        return {}, text.strip()
    yaml_text = text[4:end_idx]
    body = text[end_idx + 5:].strip()
    meta: dict = {}
    if _HAS_YAML:
        try:
            meta = _yaml.safe_load(yaml_text) or {}
        except Exception:
            meta = {}
    return meta, body


@lru_cache(maxsize=None)
def _load_all_souls() -> dict[str, tuple[dict, str]]:
    souls: dict[str, tuple[dict, str]] = {}
    if not _SOULS_DIR.exists():
        return souls
    for path in _SOULS_DIR.glob('*.soul.md'):
        soul_id = path.stem.replace('.soul', '')
        meta, body = _parse_soul_file(path)
        resolved_id = meta.get('id') or soul_id
        souls[resolved_id] = (meta, body)
    return souls


# Module-level dict for backward compatibility with existing imports
PERSONA_SPECS: dict[str, str] = {
    soul_id: body
    for soul_id, (_, body) in _load_all_souls().items()
}


def get_persona_spec(persona_id: str) -> str:
    souls = _load_all_souls()
    if persona_id in souls:
        return souls[persona_id][1]
    return _FALLBACK_SPEC


def get_soul_metadata(persona_id: str) -> dict:
    souls = _load_all_souls()
    if persona_id in souls:
        return souls[persona_id][0]
    return {}
