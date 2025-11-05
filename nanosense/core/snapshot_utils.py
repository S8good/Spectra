import hashlib
import json
from typing import Any, Dict, Optional


def _normalize_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_mapping(val) for key, val in sorted(value.items()) if val is not None}
    if isinstance(value, list):
        return [_normalize_mapping(item) for item in value]
    return value


def canonicalize_instrument_info(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not info:
        return {}

    payload: Dict[str, Any] = {}
    for key in ("device_serial", "integration_time_ms", "averaging", "temperature"):
        value = info.get(key)
        if value is not None:
            payload[key] = value

    config = info.get("config")
    if config:
        payload["config"] = _normalize_mapping(config)

    return payload


def canonicalize_processing_info(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not info:
        return {}

    payload: Dict[str, Any] = {}
    name = info.get("name")
    version = info.get("version")
    if name is not None:
        payload["name"] = name
    if version is not None:
        payload["version"] = version

    parameters: Dict[str, Any] = {}
    for key, value in info.items():
        if key in ("name", "version") or value is None:
            continue
        parameters[key] = _normalize_mapping(value)

    if parameters:
        payload["parameters"] = parameters

    return payload


def serialize_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def compute_fingerprint(payload: Dict[str, Any]) -> str:
    serialized = serialize_payload(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "canonicalize_instrument_info",
    "canonicalize_processing_info",
    "compute_fingerprint",
    "serialize_payload",
]
