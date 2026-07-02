"""JSON and TOML serialization helpers with optional fast-path backends."""

# pylint: disable=no-member

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, TextIO, Union

try:
    import orjson

    HAS_ORJSON = True
    JSONDecodeError: Any = orjson.JSONDecodeError
except ImportError:
    HAS_ORJSON = False
    JSONDecodeError = json.JSONDecodeError

try:
    import rtoml  # type: ignore

    HAS_RTOML = True
    # rtoml.TomlParsingError is what it raises
    TOMLDecodeError: Any = rtoml.TomlParsingError
except ImportError:
    HAS_RTOML = False
    # Fallback to tomllib/tomli
    if sys.version_info >= (3, 11):
        import tomllib

        TOMLDecodeError = tomllib.TOMLDecodeError
    else:
        import tomli as tomllib

        TOMLDecodeError = tomllib.TOMLDecodeError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def json_loads(s: Union[str, bytes]) -> Any:
    """Load JSON from string or bytes."""
    if HAS_ORJSON:
        return orjson.loads(s)
    return json.loads(s)


def json_dumps(
    obj: Any, indent: bool = False, sort_keys: bool = False, default: Any = None, ensure_ascii: bool = False
) -> str:
    """Dump object to JSON string."""
    if HAS_ORJSON:
        option = 0
        if indent:
            option |= orjson.OPT_INDENT_2
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS
        return orjson.dumps(obj, option=option, default=default).decode("utf-8")

    return json.dumps(
        obj, indent=2 if indent else None, sort_keys=sort_keys, ensure_ascii=ensure_ascii, default=default
    )


def json_dumps_bytes(
    obj: Any, indent: bool = False, sort_keys: bool = False, default: Any = None, ensure_ascii: bool = False
) -> bytes:
    """Dump object to JSON bytes."""
    if HAS_ORJSON:
        option = 0
        if indent:
            option |= orjson.OPT_INDENT_2
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS
        return orjson.dumps(obj, option=option, default=default)

    return json.dumps(
        obj, indent=2 if indent else None, sort_keys=sort_keys, ensure_ascii=ensure_ascii, default=default
    ).encode("utf-8")


def toml_load(f: Union[TextIO, BinaryIO]) -> dict[str, Any]:
    """Load TOML from file-like object."""
    content = f.read()
    if isinstance(content, bytes):
        return toml_loads(content.decode("utf-8"))
    return toml_loads(content)


def toml_loads(s: str) -> dict[str, Any]:
    """Load TOML from string."""
    if HAS_RTOML:
        return rtoml.loads(s)
    return tomllib.loads(s)
