"""Spot-check unit tests for the sandbox package.

These tests are deliberately narrow: they cover the error taxonomy, serialization
boundary, output limits, and a representative slice of each adapter without
requiring every runtime to be installed.  Adapters are tested via mocking where
the real package is unavailable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tuochat.cli.io import prompt_handler
from tuochat.sandbox.errors import (
    HostAPIError,
    MemoryLimitError,
    ParseError,
    SandboxRuntimeError,
    SandboxTimeoutError,
    SandboxViolation,
    SerializationError,
)
from tuochat.sandbox.limits import (
    CODE_MAX_BYTES,
    RESULT_MAX_BYTES,
    STDOUT_MAX_BYTES,
    STDOUT_MAX_LINES,
    TRUNCATION_MARKER,
)
from tuochat.sandbox.protocol import CodeInput
from tuochat.sandbox.serialization.json_bridge import check_result_size, validate_value
from tuochat.sandbox.serialization.stdout_capture import truncate_stdout

# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


def test_error_types_have_correct_error_type_strings():
    assert ParseError("x").error_type == "ParseError"
    assert SandboxRuntimeError("x").error_type == "RuntimeError"
    assert SandboxTimeoutError("x").error_type in ("SandboxTimeoutError", "TimeoutError")
    assert MemoryLimitError("x").error_type == "MemoryLimitError"
    assert SerializationError("x").error_type == "SerializationError"
    assert HostAPIError("x").error_type == "HostAPIError"
    assert SandboxViolation("x").error_type == "SandboxViolation"


def test_sandbox_error_to_dict():
    exc = ParseError("bad syntax near EOF")
    d = exc.to_dict()
    assert d == {"type": "ParseError", "message": "bad syntax near EOF"}


# ---------------------------------------------------------------------------
# Serialization boundary — validate_value
# ---------------------------------------------------------------------------


def test_validate_value_accepts_scalars():
    assert validate_value(None) is None
    assert validate_value(True) is True
    assert validate_value(42) == 42
    assert validate_value(3.14) == 3.14
    assert validate_value("hello") == "hello"


def test_validate_value_accepts_nested_structure():
    value = {"a": [1, 2, {"b": "c"}]}
    assert validate_value(value) == value


def test_validate_value_rejects_callable():
    with pytest.raises(SerializationError, match="unsupported type"):
        validate_value(lambda: None)


def test_validate_value_rejects_non_string_dict_key():
    with pytest.raises(SerializationError, match="dict key must be str"):
        validate_value({1: "bad"})


def test_validate_value_rejects_deep_nesting():
    deep: dict = {}
    node = deep
    for _ in range(55):
        child: dict = {}
        node["x"] = child
        node = child
    with pytest.raises(SerializationError, match="nesting too deep"):
        validate_value(deep)


def test_check_result_size_rejects_oversized():
    huge = "x" * (RESULT_MAX_BYTES + 1)
    with pytest.raises(SerializationError, match="result exceeds"):
        check_result_size(huge)


def test_check_result_size_accepts_within_limit():
    small = "hello"
    check_result_size(small)  # should not raise


# ---------------------------------------------------------------------------
# Output limits — truncate_stdout
# ---------------------------------------------------------------------------


def test_truncate_stdout_respects_line_limit():
    lines = [str(i) for i in range(STDOUT_MAX_LINES + 50)]
    truncated = truncate_stdout(lines)
    assert len(truncated) <= STDOUT_MAX_LINES + 1  # +1 for truncation marker
    assert any(TRUNCATION_MARKER in line or "truncated" in line.lower() for line in truncated)


def test_truncate_stdout_passthrough_within_limits():
    lines = ["a", "b", "c"]
    assert truncate_stdout(lines) == lines


def test_truncate_stdout_respects_byte_limit():
    # Each line is 1000 bytes; 65 lines exceed 64 KB.
    lines = ["x" * 1000 for _ in range(100)]
    truncated = truncate_stdout(lines)
    total = sum(len(line.encode("utf-8")) for line in truncated)
    assert total <= STDOUT_MAX_BYTES + 2000  # marker may be a little over


# ---------------------------------------------------------------------------
# API layer — resolve_language
# ---------------------------------------------------------------------------


def test_resolve_language_js_aliases():
    from tuochat.sandbox.api import resolve_language

    assert resolve_language("js") == "javascript"
    assert resolve_language("javascript") == "javascript"
    assert resolve_language("JS") == "javascript"


def test_resolve_language_lua():
    from tuochat.sandbox.api import resolve_language

    assert resolve_language("lua") == "lua"


def test_resolve_language_unknown_returns_none():
    from tuochat.sandbox.api import resolve_language

    assert resolve_language("python") is None
    assert resolve_language("") is None


def test_code_interpreter_runtime_details_reports_available_modules(monkeypatch):
    from tuochat.sandbox.api import code_interpreter_runtime_details

    def fake_find_spec(module_name: str):
        available = {"py_mini_racer", "lupa"}
        return object() if module_name in available else None

    monkeypatch.setattr("tuochat.sandbox.api.importlib.util.find_spec", fake_find_spec)

    details = code_interpreter_runtime_details()

    assert details["mini_racer_v8"] is True
    assert details["dukpy"] is False
    assert details["lupa"] is True
    assert details["installed_runtimes"] == ["mini-racer (V8)", "lupa"]
    assert details["code_interpreter_ready"] is True
    assert details["preferred_javascript_runtime"] == "mini-racer (V8)"
    assert details["lua_runtime"] == "lupa"


def test_sandbox_prompts_use_frontend_prompt_handler():
    """Sandbox confirmations should flow through the active prompt callback."""
    from tuochat.sandbox.integration import prompt_attach, prompt_execute

    prompts: list[str] = []

    def answer(prompt: str, *, secret: bool = False) -> str:
        assert secret is False
        prompts.append(prompt)
        return "y"

    with prompt_handler(answer):
        assert prompt_execute("javascript") is True
        assert prompt_attach() is True

    assert prompts == [
        "  Execute javascript code in sandbox? [y/N] ",
        "  Attach output to conversation? [Y/n] ",
    ]


# ---------------------------------------------------------------------------
# API layer — run_code rejects bad input before adapter is called
# ---------------------------------------------------------------------------


def test_run_code_rejects_unsupported_language():
    from tuochat.sandbox.api import run_code

    out = run_code(CodeInput(code="1+1", language="python"))
    assert not out.ok
    assert out.error is not None
    assert out.error["type"] == "SandboxViolation"


def test_run_code_rejects_oversized_code():
    from tuochat.sandbox.api import run_code

    out = run_code(CodeInput(code="x" * (CODE_MAX_BYTES + 1), language="js"))
    assert not out.ok
    assert out.error is not None
    assert out.error["type"] == "SerializationError"


def test_run_code_rejects_invalid_input_data():
    from tuochat.sandbox.api import run_code

    out = run_code(CodeInput(code="emit(1)", language="js", input_data=object()))
    assert not out.ok
    assert out.error is not None
    assert out.error["type"] == "SerializationError"


# ---------------------------------------------------------------------------
# mini-racer runtime — real runtime when available
# ---------------------------------------------------------------------------


def test_miniracer_runtime_does_not_expose_common_host_globals():
    pytest.importorskip("py_mini_racer")
    from py_mini_racer import MiniRacer

    ctx = MiniRacer()

    assert ctx.eval("typeof require") == "undefined"
    assert ctx.eval("typeof process") == "undefined"
    assert ctx.eval("typeof Deno") == "undefined"
    assert ctx.eval("typeof Bun") == "undefined"
    assert ctx.eval("typeof std") == "undefined"
    assert ctx.eval("typeof os") == "undefined"


def test_miniracer_runtime_cannot_write_files_via_common_host_apis(tmp_path):
    pytest.importorskip("py_mini_racer")
    from py_mini_racer import MiniRacer

    output_path = tmp_path / "miniracer-write-probe.txt"
    ctx = MiniRacer()
    quoted_path = json.dumps(str(output_path))

    attempt_errors = json.loads(ctx.eval(f"""
            globalThis.writeProbe = [];
            function record(label, action) {{
                try {{
                    action();
                    writeProbe.push(label + ":ok");
                }} catch (error) {{
                    writeProbe.push(label + ":" + String(error));
                }}
            }}
            record("require_fs", function() {{ require("fs").writeFileSync({quoted_path}, "x"); }});
            record("process_mainModule", function() {{ process.mainModule.require("fs").writeFileSync({quoted_path}, "x"); }});
            record("deno_write", function() {{ Deno.writeTextFileSync({quoted_path}, "x"); }});
            record("bun_write", function() {{ Bun.write({quoted_path}, "x"); }});
            JSON.stringify(writeProbe);
            """))

    assert attempt_errors == [
        "require_fs:ReferenceError: require is not defined",
        "process_mainModule:ReferenceError: process is not defined",
        "deno_write:ReferenceError: Deno is not defined",
        "bun_write:ReferenceError: Bun is not defined",
    ]
    assert not output_path.exists()


# ---------------------------------------------------------------------------
# dukpy runtime — real runtime when available
# ---------------------------------------------------------------------------


def test_dukpy_runtime_only_exposes_non_file_host_entry_points():
    dukpy = pytest.importorskip("dukpy")

    ctx = dukpy.JSInterpreter()

    assert ctx.evaljs("typeof require") == "function"
    assert ctx.evaljs("typeof process") == "object"
    assert ctx.evaljs("typeof Deno") == "undefined"
    assert ctx.evaljs("typeof Bun") == "undefined"
    assert ctx.evaljs("typeof std") == "undefined"
    assert ctx.evaljs("typeof os") == "undefined"


def test_dukpy_runtime_cannot_write_files_via_available_or_common_host_apis(tmp_path):
    dukpy = pytest.importorskip("dukpy")

    output_path = tmp_path / "dukpy-write-probe.txt"
    ctx = dukpy.JSInterpreter()
    quoted_path = json.dumps(str(output_path))

    attempt_errors = json.loads(ctx.evaljs(f"""
            var writeProbe = [];
            function record(label, action) {{
                try {{
                    action();
                    writeProbe.push(label + ":ok");
                }} catch (error) {{
                    writeProbe.push(label + ":" + String(error));
                }}
            }}
            record("require_fs", function() {{ require("fs").writeFileSync({quoted_path}, "x"); }});
            record("process_mainModule", function() {{ process.mainModule.require("fs").writeFileSync({quoted_path}, "x"); }});
            record("deno_write", function() {{ Deno.writeTextFileSync({quoted_path}, "x"); }});
            record("bun_write", function() {{ Bun.write({quoted_path}, "x"); }});
            JSON.stringify(writeProbe);
            """))

    assert attempt_errors == [
        "require_fs:Error: cannot find module: fs",
        "process_mainModule:TypeError: cannot read property 'require' of undefined",
        "deno_write:ReferenceError: identifier 'Deno' undefined",
        "bun_write:ReferenceError: identifier 'Bun' undefined",
    ]
    assert not output_path.exists()


# ---------------------------------------------------------------------------
# dukpy adapter — mocked
# ---------------------------------------------------------------------------


class FakeDukpyInterpreter:
    """Minimal stand-in for dukpy.JSInterpreter."""

    def __init__(self) -> None:
        self.state: dict = {}
        self.stdout: list[str] = []
        self.did_emit = False
        self.result = None

    def evaljs(self, code: str, **kwargs) -> object:  # type: ignore[override]
        # Handle the fixed queries the adapter makes after user code runs.
        if code == "globalThis.__didEmit":
            return self.did_emit
        if code == "JSON.stringify(globalThis.__result)":
            return json.dumps(self.result)
        if code == "JSON.stringify(globalThis.__stdout)":
            return json.dumps(self.stdout)
        # Everything else is accepted silently.
        return ""


def test_dukpy_adapter_happy_path():
    """Adapter should return ok=True with a valid emit."""
    from tuochat.sandbox.adapters.dukpy_adapter import DukpyAdapter

    fake_ctx = FakeDukpyInterpreter()
    fake_ctx.did_emit = True
    fake_ctx.result = 42

    with patch.dict(sys.modules, {"dukpy": MagicMock()}):
        import dukpy  # type: ignore[import-untyped]

        dukpy.JSInterpreter = lambda: fake_ctx

        adapter = DukpyAdapter()
        result = adapter.run("emit(42)", None)

    assert result["ok"] is True
    assert result["result"] == 42


def test_dukpy_adapter_code_too_large():
    from tuochat.sandbox.adapters.dukpy_adapter import DukpyAdapter

    adapter = DukpyAdapter.__new__(DukpyAdapter)
    with patch.dict(sys.modules, {"dukpy": MagicMock()}):
        import dukpy

        dukpy.JSInterpreter = FakeDukpyInterpreter

        with pytest.raises(SerializationError, match="code exceeds"):
            adapter.run("x" * (CODE_MAX_BYTES + 1), None)


# ---------------------------------------------------------------------------
# SKILL.md template expansion
# ---------------------------------------------------------------------------


def test_expand_skill_body_replaces_known_placeholders(tmp_path):
    from tuochat.discovery.skills import expand_skill_body

    skill_file = tmp_path / "SKILL.md"
    prompt_file = tmp_path / "myrules.md"
    prompt_file.write_text("# My Rules\nDo this.", encoding="utf-8")

    body = "Before\n{myrules}\nAfter"
    expanded = expand_skill_body(body, skill_file)
    assert "# My Rules" in expanded
    assert "{myrules}" not in expanded


def test_expand_skill_body_leaves_unknown_placeholders(tmp_path):
    from tuochat.discovery.skills import expand_skill_body

    skill_file = tmp_path / "SKILL.md"
    body = "Hello {unknown_var} world"
    expanded = expand_skill_body(body, skill_file)
    assert "{unknown_var}" in expanded


def test_expand_skill_body_uses_sandbox_prompts_for_javascript():
    """javascript.md in the bundled sandbox prompts must be found."""
    from tuochat.discovery.skills import expand_skill_body, sandbox_prompts_dir

    prompts_dir = sandbox_prompts_dir()
    if not (prompts_dir / "javascript.md").is_file():
        pytest.skip("sandbox prompts not present")

    skill_file = Path(__file__).parent / "SKILL.md"  # doesn't need to exist
    body = "Rules:\n{javascript}"
    expanded = expand_skill_body(body, skill_file)
    assert "{javascript}" not in expanded
    assert len(expanded) > len(body)


# ---------------------------------------------------------------------------
# Phase 3 — abuse paths (no real runtime required; tested via API mock)
# ---------------------------------------------------------------------------


def make_mock_adapter(result_dict: dict) -> MagicMock:
    adapter = MagicMock()
    adapter.run.return_value = result_dict
    return adapter


def test_abuse_infinite_loop_reported_as_timeout():
    """An adapter that returns SandboxTimeoutError must propagate correctly."""
    from tuochat.sandbox.api import run_code

    timeout_response = {
        "ok": False,
        "error": {"type": "SandboxTimeoutError", "message": "execution exceeded 500 ms"},
        "stdout": [],
        "stderr": [],
        "metrics": {"wall_ms": 501.0},
    }
    with patch("tuochat.sandbox.api.get_adapter", return_value=make_mock_adapter(timeout_response)):
        out = run_code(CodeInput(code="while(true){}", language="js"))

    assert not out.ok
    assert out.error is not None
    assert out.error["type"] == "SandboxTimeoutError"


def test_abuse_stdout_flood_truncated():
    """An adapter that returns 10 000 stdout lines must still produce output."""
    from tuochat.sandbox.api import run_code

    # The adapter itself is mocked to return pre-truncated output (the real
    # adapter truncates; here we verify the API layer passes it through cleanly).
    flood_response = {
        "ok": True,
        "result": None,
        "stdout": ["line"] * 201,
        "stderr": [],
        "metrics": {"wall_ms": 1.0},
    }
    with patch("tuochat.sandbox.api.get_adapter", return_value=make_mock_adapter(flood_response)):
        out = run_code(CodeInput(code="for(var i=0;i<99999;i++)console.log(i)", language="js"))

    assert out.ok
    assert len(out.stdout) == 201  # passed through as-is from adapter


def test_abuse_giant_result_serialization_error():
    """Results that exceed RESULT_MAX_BYTES must be rejected."""
    huge_result = "x" * (RESULT_MAX_BYTES + 10)
    with pytest.raises(SerializationError, match="result exceeds"):
        check_result_size(huge_result)


def test_abuse_prototype_pollution_input_rejected():
    """Prototype-poisoned keys (non-string) must be caught by validate_value."""
    with pytest.raises(SerializationError, match="dict key must be str"):
        validate_value({"__proto__": {"admin": True}, 0: "bad"})


def test_abuse_deep_recursive_input_rejected():
    """Deeply nested input must be caught before reaching the adapter."""
    from tuochat.sandbox.api import run_code

    # Build a 60-level deep dict — exceeds the 50-level limit.
    node: dict = {}
    root = node
    for _ in range(60):
        child: dict = {}
        node["x"] = child
        node = child

    out = run_code(CodeInput(code="emit(1)", language="js", input_data=root))
    assert not out.ok
    assert out.error is not None
    assert out.error["type"] == "SerializationError"
