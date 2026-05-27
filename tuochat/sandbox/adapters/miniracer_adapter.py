"""mini-racer (V8) sandbox adapter."""

from __future__ import annotations

import json
import time
from typing import Any

from tuochat.sandbox.errors import ParseError, SandboxRuntimeError, SandboxTimeoutError, SerializationError
from tuochat.sandbox.limits import CODE_MAX_BYTES
from tuochat.sandbox.serialization.json_bridge import check_result_size, validate_value
from tuochat.sandbox.serialization.stdout_capture import truncate_stdout

# mini-racer has no Python callback for console.log, so we buffer in JS.
JS_BOOTSTRAP = """\
globalThis.__stdout = [];
globalThis.__didEmit = false;
globalThis.__result = undefined;

globalThis.emit = function(value) {
  if (globalThis.__didEmit) throw new Error("emit() called more than once");
  globalThis.__didEmit = true;
  globalThis.__result = value;
};
globalThis.fail = function(message) { throw new Error(String(message)); };
globalThis.console = {
  log: function() {
    var parts = [];
    for (var i = 0; i < arguments.length; i++) {
      parts.push(String(arguments[i]));
    }
    globalThis.__stdout.push(parts.join(' '));
  }
};
"""


class MiniRacerAdapter:
    """Execute JavaScript in a V8 sandbox via mini-racer."""

    language_name = "javascript"

    def run(
        self,
        code: str,
        input_data: Any,
        *,
        timeout_ms: int = 500,
        memory_limit_mb: int | None = None,  # noqa # nosec # pylint: disable=unused-argument
    ) -> dict[str, Any]:
        from py_mini_racer import MiniRacer

        if len(code.encode("utf-8")) > CODE_MAX_BYTES:
            raise SerializationError(f"code exceeds {CODE_MAX_BYTES} byte limit")

        started = time.perf_counter()
        ctx = MiniRacer()

        # Bootstrap
        try:
            ctx.eval(JS_BOOTSTRAP)
        except Exception as exc:
            return error_output(ParseError(f"bootstrap failed: {exc}"), [], started)

        # Inject input
        input_json = json.dumps(validate_value(input_data, label="input"))
        ctx.eval(f"globalThis.input = JSON.parse({json.dumps(input_json)});")

        # Run user code with timeout
        try:
            ctx.eval(code, timeout=timeout_ms)
        except Exception as exc:
            msg = str(exc)
            stdout_lines = extract_stdout(ctx)
            if "timeout" in msg.lower() or "terminated" in msg.lower():
                return error_output(SandboxTimeoutError(f"execution exceeded {timeout_ms} ms"), stdout_lines, started)
            return error_output(SandboxRuntimeError(msg), stdout_lines, started)

        # Extract stdout + result
        wall_ms = (time.perf_counter() - started) * 1000
        stdout_lines = extract_stdout(ctx)
        did_emit = bool(ctx.eval("globalThis.__didEmit"))

        if did_emit:
            raw: Any = ctx.eval("JSON.stringify(globalThis.__result)")
            result = json.loads(raw) if raw else None
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


def extract_stdout(ctx: Any) -> list[str]:
    """Pull the buffered stdout array from the V8 context."""
    try:
        raw = ctx.eval("JSON.stringify(globalThis.__stdout)")
        return json.loads(raw) if raw else []
    except Exception:
        return []


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
