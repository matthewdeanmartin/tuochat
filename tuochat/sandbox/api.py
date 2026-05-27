"""Public entry point: resolve engine, dispatch to adapter, return CodeOutput."""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

from tuochat.sandbox.errors import SandboxError, SandboxViolation, SerializationError
from tuochat.sandbox.limits import CODE_MAX_BYTES
from tuochat.sandbox.protocol import CodeInput, CodeOutput
from tuochat.sandbox.serialization.json_bridge import validate_value

logger = logging.getLogger(__name__)

LANGUAGE_ALIASES: dict[str, str] = {
    "js": "javascript",
    "javascript": "javascript",
    "lua": "lua",
}

SUPPORTED_LANGUAGES = frozenset(LANGUAGE_ALIASES.values())
RUNTIME_MODULES: dict[str, str] = {
    "mini_racer_v8": "py_mini_racer",
    "dukpy": "dukpy",
    "lupa": "lupa",
}


def code_interpreter_runtime_details() -> dict[str, object]:
    """Return installed sandbox-runtime details for doctor and GUI surfaces."""
    availability = {
        name: importlib.util.find_spec(module_name) is not None for name, module_name in RUNTIME_MODULES.items()
    }
    installed_runtimes: list[str] = []
    if availability["mini_racer_v8"]:
        installed_runtimes.append("mini-racer (V8)")
    if availability["dukpy"]:
        installed_runtimes.append("dukpy")
    if availability["lupa"]:
        installed_runtimes.append("lupa")
    preferred_javascript_runtime = "none"
    if availability["mini_racer_v8"]:
        preferred_javascript_runtime = "mini-racer (V8)"
    elif availability["dukpy"]:
        preferred_javascript_runtime = "dukpy"
    return {
        "mini_racer_v8": availability["mini_racer_v8"],
        "dukpy": availability["dukpy"],
        "lupa": availability["lupa"],
        "installed_runtimes": installed_runtimes,
        "code_interpreter_ready": bool(installed_runtimes),
        "preferred_javascript_runtime": preferred_javascript_runtime,
        "lua_runtime": "lupa" if availability["lupa"] else "none",
    }


def resolve_language(tag: str) -> str | None:
    """Normalize a fenced-block info string to a supported language name."""
    return LANGUAGE_ALIASES.get(tag.strip().lower())


def resolve_js_adapter() -> Any:
    """Return the best available JS adapter, following preference order."""
    if importlib.util.find_spec("py_mini_racer"):
        from tuochat.sandbox.adapters.miniracer_adapter import MiniRacerAdapter

        return MiniRacerAdapter()
    if importlib.util.find_spec("dukpy"):
        from tuochat.sandbox.adapters.dukpy_adapter import DukpyAdapter

        return DukpyAdapter()
    raise ImportError(
        "No JavaScript runtime available. Install one of: "
        "mini-racer (pip install mini-racer), "
        "dukpy (pip install dukpy)"
    )


def resolve_lua_adapter() -> Any:
    """Return the Lua adapter or raise ImportError."""
    if importlib.util.find_spec("lupa"):
        from tuochat.sandbox.adapters.lupa_adapter import LupaAdapter

        return LupaAdapter()
    raise ImportError("Lua runtime not available. Install: pip install lupa")


def get_adapter(language: str) -> Any:
    """Return an adapter instance for the given language."""
    if language == "javascript":
        return resolve_js_adapter()
    if language == "lua":
        return resolve_lua_adapter()
    raise SandboxViolation(f"unsupported language: {language}")


def run_code(request: CodeInput) -> CodeOutput:
    """Execute sandboxed code and return a CodeOutput.

    This is the single public entry point for the sandbox package.
    """
    language = resolve_language(request.language)
    if language is None:
        return CodeOutput(
            ok=False,
            error={"type": "SandboxViolation", "message": f"unsupported language: {request.language}"},
        )

    if len(request.code.encode("utf-8")) > CODE_MAX_BYTES:
        return CodeOutput(
            ok=False,
            error={"type": "SerializationError", "message": f"code exceeds {CODE_MAX_BYTES} byte limit"},
        )

    # Validate input data before passing to adapter
    try:
        safe_input = validate_value(request.input_data, label="input")
    except SerializationError as exc:
        return CodeOutput(ok=False, error=exc.to_dict())

    try:
        adapter = get_adapter(language)
    except ImportError as exc:
        return CodeOutput(ok=False, error={"type": "ImportError", "message": str(exc)})

    logger.info("sandbox: running %s code (%d bytes)", language, len(request.code))

    try:
        raw = adapter.run(
            request.code,
            safe_input,
            timeout_ms=request.timeout_ms,
            memory_limit_mb=request.memory_limit_mb,
        )
    except SandboxError as exc:
        return CodeOutput(ok=False, error=exc.to_dict())
    except Exception as exc:
        logger.exception("sandbox: unexpected error in %s adapter", language)
        return CodeOutput(
            ok=False,
            error={"type": "RuntimeError", "message": f"adapter error: {exc}"},
        )

    return CodeOutput(
        ok=raw.get("ok", False),
        result=raw.get("result"),
        error=raw.get("error"),
        stdout=raw.get("stdout", []),
        stderr=raw.get("stderr", []),
        metrics=raw.get("metrics", {}),
    )


def available_languages() -> list[str]:
    """Return the list of languages with an installed runtime."""
    langs = []
    try:
        resolve_js_adapter()
        langs.append("javascript")
    except ImportError:
        pass
    try:
        resolve_lua_adapter()
        langs.append("lua")
    except ImportError:
        pass
    return langs
