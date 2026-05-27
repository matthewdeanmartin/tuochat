"""Safe value round-trip across the host/runtime boundary.

Only these types may cross: None, bool, int, float, str, list, dict (str keys).
Everything else raises SerializationError.
"""

from __future__ import annotations

from typing import Any

from tuochat.sandbox.errors import SerializationError
from tuochat.sandbox.limits import RESULT_MAX_BYTES

SAFE_SCALAR = (type(None), bool, int, float, str)


def validate_value(value: Any, *, label: str = "value", depth: int = 0) -> Any:
    """Validate and return a safe-to-serialize value, or raise SerializationError."""
    if depth > 50:
        raise SerializationError(f"{label}: nesting too deep (>50)")
    if isinstance(value, SAFE_SCALAR):
        return value
    if isinstance(value, list):
        return [validate_value(item, label=f"{label}[{i}]", depth=depth + 1) for i, item in enumerate(value)]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise SerializationError(f"{label}: dict key must be str, got {type(k).__name__}")
            out[k] = validate_value(v, label=f"{label}.{k}", depth=depth + 1)
        return out
    raise SerializationError(f"{label}: unsupported type {type(value).__name__}")


def check_result_size(value: Any) -> None:
    """Raise SerializationError if the JSON representation exceeds the limit."""
    import json

    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > RESULT_MAX_BYTES:
        raise SerializationError(f"result exceeds {RESULT_MAX_BYTES} byte limit")
