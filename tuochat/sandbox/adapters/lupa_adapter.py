"""Lupa (Lua/LuaJIT) sandbox adapter."""

from __future__ import annotations

import time
from typing import Any

from tuochat.sandbox.errors import SandboxRuntimeError, SandboxTimeoutError, SerializationError
from tuochat.sandbox.limits import CODE_MAX_BYTES
from tuochat.sandbox.serialization.json_bridge import check_result_size, validate_value
from tuochat.sandbox.serialization.stdout_capture import truncate_stdout

# Lua globals that must be removed before user code runs.
FORBIDDEN_GLOBALS = (
    "io",
    "os",
    "package",
    "require",
    "debug",
    "dofile",
    "loadfile",
    "collectgarbage",
    "coroutine",
)


def lua_table_to_python(obj: Any) -> Any:
    """Recursively convert a lupa Lua table to Python dicts/lists."""
    # Check if it's a lua table by trying to iterate
    if not hasattr(obj, "items") and not hasattr(obj, "values"):
        return obj

    # Try dict-style first
    try:
        pairs = list(obj.items())
    except (AttributeError, TypeError):
        return obj

    if not pairs:
        return {}

    # Check if it's a sequential array (keys are 1..n)
    keys = [k for k, _ in pairs]
    is_array = all(isinstance(k, (int, float)) for k in keys)
    if is_array:
        int_keys = sorted(int(k) for k in keys)
        if int_keys == list(range(1, len(int_keys) + 1)):
            return [lua_table_to_python(dict(pairs)[k]) for k in sorted(keys)]

    return {str(k): lua_table_to_python(v) for k, v in pairs}


def python_to_lua_table(runtime: Any, value: Any) -> Any:
    """Convert a Python value to Lua-compatible types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        tbl = runtime.table()
        for i, item in enumerate(value, 1):
            tbl[i] = python_to_lua_table(runtime, item)
        return tbl
    if isinstance(value, dict):
        tbl = runtime.table()
        for k, v in value.items():
            tbl[str(k)] = python_to_lua_table(runtime, v)
        return tbl
    raise SerializationError(f"cannot convert {type(value).__name__} to Lua")


class LupaAdapter:
    """Execute Lua code in a sandboxed lupa runtime."""

    language_name = "lua"

    def run(
        self,
        code: str,
        input_data: Any,
        *,
        timeout_ms: int = 500,
        memory_limit_mb: int | None = None,  # noqa # nosec # pylint: disable=unused-argument
    ) -> dict[str, Any]:
        # pylint: disable=no-name-in-module
        from lupa import LuaRuntime

        if len(code.encode("utf-8")) > CODE_MAX_BYTES:
            raise SerializationError(f"code exceeds {CODE_MAX_BYTES} byte limit")

        stdout_lines: list[str] = []
        emit_called = False
        emit_value: Any = None

        def lua_print(*args: Any) -> None:
            stdout_lines.append(" ".join(str(a) for a in args))

        def lua_emit(value: Any) -> None:
            nonlocal emit_called, emit_value
            if emit_called:
                raise SandboxRuntimeError("emit() called more than once")
            emit_called = True
            emit_value = value

        def lua_fail(message: Any) -> None:
            raise SandboxRuntimeError(str(message))

        started = time.perf_counter()

        runtime = LuaRuntime(unpack_returned_tuples=True)

        # Strip forbidden globals
        for name in FORBIDDEN_GLOBALS:
            runtime.execute(f"{name} = nil")

        # Install host API
        g = runtime.globals()
        g.print = lua_print
        g.emit = lua_emit
        g.fail = lua_fail

        # Inject input
        safe_input = validate_value(input_data, label="input")
        g.input = python_to_lua_table(runtime, safe_input)

        # Execute with wall-clock timeout via threading
        import threading

        error_holder: list[Exception | None] = [None]

        def target() -> None:
            try:
                runtime.execute(code)
            except Exception as exc:
                error_holder[0] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_ms / 1000)

        if thread.is_alive():
            # Can't truly kill the Lua thread, but we report timeout
            wall_ms = (time.perf_counter() - started) * 1000
            return error_output(
                SandboxTimeoutError(f"execution exceeded {timeout_ms} ms"),
                stdout_lines,
                started,
            )

        if error_holder[0] is not None:
            exc = error_holder[0]
            msg = str(exc)
            if isinstance(exc, SandboxRuntimeError):
                return error_output(exc, stdout_lines, started)
            return error_output(SandboxRuntimeError(msg), stdout_lines, started)

        wall_ms = (time.perf_counter() - started) * 1000

        if emit_called:
            result = lua_table_to_python(emit_value)
            try:
                result = validate_value(result, label="result")
                check_result_size(result)
            except SerializationError as exc:
                return error_output(exc, stdout_lines, started)
        else:
            result = None

        return {
            "ok": True,
            "result": result,
            "stdout": truncate_stdout(stdout_lines),
            "stderr": [],
            "metrics": {"wall_ms": round(wall_ms, 1)},
        }


def error_output(exc: Exception, stdout_lines: list[str], started: float) -> dict[str, Any]:
    wall_ms = (time.perf_counter() - started) * 1000
    error_type = getattr(exc, "error_type", "RuntimeError")
    return {
        "ok": False,
        "error": {"type": error_type, "message": str(exc)},
        "stdout": truncate_stdout(stdout_lines),
        "stderr": [],
        "metrics": {"wall_ms": round(wall_ms, 1)},
    }
