"""dukpy (Duktape) sandbox adapter — ES5 compatibility fallback."""

from __future__ import annotations

import json
import time
from typing import Any

from tuochat.sandbox.errors import ParseError, SandboxRuntimeError, SandboxTimeoutError, SerializationError
from tuochat.sandbox.limits import CODE_MAX_BYTES
from tuochat.sandbox.serialization.json_bridge import check_result_size, validate_value
from tuochat.sandbox.serialization.stdout_capture import truncate_stdout

# dukpy has no Python print callback; buffer stdout in the JS heap (same
# approach as mini-racer).  Duktape targets ES5.1, so we stay away from
# arrow functions, let/const, template literals, etc.
JS_BOOTSTRAP = """\
globalThis.__stdout = [];
globalThis.__didEmit = false;
globalThis.__result = undefined;

globalThis.emit = function(value) {
  if (globalThis.__didEmit) { throw new Error("emit() called more than once"); }
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


class DukpyAdapter:
    """Execute JavaScript (ES5) in a Duktape sandbox via dukpy."""

    language_name = "javascript"

    def run(
        self,
        code: str,
        input_data: Any,
        *,
        timeout_ms: int = 500,
        memory_limit_mb: int | None = None,  # noqa # nosec # pylint: disable=unused-argument
    ) -> dict[str, Any]:
        import dukpy

        if len(code.encode("utf-8")) > CODE_MAX_BYTES:
            raise SerializationError(f"code exceeds {CODE_MAX_BYTES} byte limit")

        started = time.perf_counter()

        # dukpy.JSInterpreter is a persistent context; create a fresh one per
        # run to guarantee no state leakage between executions.
        ctx = dukpy.JSInterpreter()

        # Bootstrap
        try:
            ctx.evaljs(JS_BOOTSTRAP)
        except Exception as exc:
            return error_output(ParseError(f"bootstrap failed: {exc}"), [], started)

        # Inject input — serialise through JSON so only safe scalars cross the
        # host/runtime boundary.
        input_json = json.dumps(validate_value(input_data, label="input"))
        ctx.evaljs(f"globalThis.input = JSON.parse({json.dumps(input_json)});")

        # Run user code.  dukpy does not expose a native wall-clock timeout, so
        # we wrap execution in a thread and join with a deadline — the same
        # strategy used by the Lua adapter.
        import threading

        error_holder: list[Exception | None] = [None]

        def target() -> None:
            try:
                ctx.evaljs(code)
            except Exception as exc:
                error_holder[0] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_ms / 1000)

        if thread.is_alive():
            # The Duktape thread cannot be forcibly killed; report timeout and
            # discard the interpreter (it stays alive as a daemon thread but
            # will be collected when the process or owning thread ends).
            return error_output(
                SandboxTimeoutError(f"execution exceeded {timeout_ms} ms"),
                [],
                started,
            )

        if error_holder[0] is not None:
            captured_exc = error_holder[0]
            return error_output(SandboxRuntimeError(str(captured_exc)), [], started)

        # Extract buffered stdout and result.
        stdout_lines = extract_stdout(ctx)

        wall_ms = (time.perf_counter() - started) * 1000
        did_emit = bool(ctx.evaljs("globalThis.__didEmit"))

        if did_emit:
            raw = ctx.evaljs("JSON.stringify(globalThis.__result)")
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
    """Pull the buffered stdout array from the Duktape context."""
    try:
        raw = ctx.evaljs("JSON.stringify(globalThis.__stdout)")
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
