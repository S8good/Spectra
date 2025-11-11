# nanosense/core/reference_templates.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_TEMPLATE_PATH = Path.home() / ".nanosense" / "reference_templates.json"


def resolve_template_path(custom_path: Optional[str] = None) -> Path:
    path = Path(custom_path).expanduser() if custom_path else DEFAULT_TEMPLATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_reference_templates(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    template_path = resolve_template_path(path)
    if not template_path.exists():
        return {}
    try:
        data = json.loads(template_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_reference_templates(
    templates: Dict[str, Dict[str, Any]], path: Optional[str] = None
) -> Path:
    template_path = resolve_template_path(path)
    template_path.write_text(
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return template_path


__all__ = [
    "DEFAULT_TEMPLATE_PATH",
    "load_reference_templates",
    "save_reference_templates",
    "resolve_template_path",
]
