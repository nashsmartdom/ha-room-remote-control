from __future__ import annotations

import json
from typing import Any


def actions_from_bridge_devices(payload: str, friendly_name: str) -> list[str]:
    try:
        devices = json.loads(payload)
    except ValueError:
        return []
    if not isinstance(devices, list):
        return []
    for device in devices:
        if isinstance(device, dict) and device.get("friendly_name") == friendly_name:
            exposes = ((device.get("definition") or {}).get("exposes") or [])
            return sorted(set(_find_actions(exposes)))
    return []


def _find_actions(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, list):
        for item in obj:
            out += _find_actions(item)
    elif isinstance(obj, dict):
        if obj.get("property") == "action":
            vals = obj.get("values") or []
            if isinstance(vals, list):
                out += [str(v) for v in vals]
        out += _find_actions(obj.get("features") or [])
        out += _find_actions(obj.get("exposes") or [])
    return out
