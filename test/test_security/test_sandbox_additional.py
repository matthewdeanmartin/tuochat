from __future__ import annotations

import json
import time
from types import ModuleType

from tuochat.sandbox.adapters import base, lupa_adapter, miniracer_adapter
from tuochat.sandbox.protocol import CodeInput, CodeOutput
from tuochat.sandbox.worker import child_main, run_in_worker


class FakeLuaTable(dict):
    def items(self):
        return super().items()

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


class FakeLuaRuntime:
    def __init__(self, unpack_returned_tuples: bool = True) -> None:  # noqa: ARG002
        self.globals_map = FakeLuaTable()

    def execute(self, code: str) -> None:
        if code.endswith(" = nil"):
            return
        if code == "emit-result":
            self.globals_map["print"]("hello", 123)
            self.globals_map["emit"](FakeLuaTable({"value": 7}))
            return
        if code == "explode":
            raise ValueError("lua exploded")
        if code == "sleep":
            time.sleep(0.05)

    def globals(self) -> FakeLuaTable:
        return self.globals_map

    def table(self) -> FakeLuaTable:
        return FakeLuaTable()


class FakeMiniRacer:
    def __init__(self) -> None:
        self.stdout: list[str] = []
        self.did_emit = False
        self.result = None

    def eval(self, code: str, timeout: int | None = None):  # noqa: ARG002
        if code == miniracer_adapter.JS_BOOTSTRAP:
            return None
        if code.startswith("globalThis.input = JSON.parse("):
            return None
        if code == "emit-result":
            self.stdout = ["hello 1"]
            self.did_emit = True
            self.result = {"value": 3}
            return None
        if code == "runtime-error":
            raise Exception("boom")
        if code == "timeout-error":
            raise Exception("execution terminated by timeout")
        if code == "globalThis.__didEmit":
            return self.did_emit
        if code == "JSON.stringify(globalThis.__stdout)":
            return json.dumps(self.stdout)
        if code == "JSON.stringify(globalThis.__result)":
            return json.dumps(self.result)
        raise AssertionError(f"unexpected code: {code}")


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put(self, item: dict) -> None:
        self.items.append(item)

    def empty(self) -> bool:
        return not self.items

    def get_nowait(self) -> dict:
        if not self.items:
            raise RuntimeError("empty")
        return self.items.pop(0)


class FakeProcess:
    def __init__(self, *, alive: bool, exitcode: int | None, queue: FakeQueue, raw_result: dict | None = None) -> None:
        self.alive = alive
        self.exitcode = exitcode
        self.queue = queue
        self.raw_result = raw_result
        self.started = False
        self.killed = False

    def start(self) -> None:
        self.started = True
        if self.raw_result is not None:
            self.queue.put(self.raw_result)

    def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
        return None

    def is_alive(self) -> bool:
        return self.alive

    def kill(self) -> None:
        self.killed = True
        self.alive = False


class FakeContext:
    def __init__(self, process: FakeProcess, queue: FakeQueue) -> None:
        self.process = process
        self.queue = queue

    def Queue(self, maxsize: int = 1) -> FakeQueue:  # noqa: N802, ARG002
        return self.queue

    def Process(self, target, args, daemon: bool) -> FakeProcess:  # noqa: N802, ARG002
        return self.process


def fake_module(name: str, **attrs) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def test_sandbox_adapter_protocol_is_runtime_checkable():
    assert getattr(base.SandboxAdapter, "__annotations__", {})["language_name"] == "str"
    assert callable(base.SandboxAdapter.run)


def test_lua_table_helpers_convert_arrays_and_dicts():
    array_like = FakeLuaTable({1: "a", 2: "b"})
    dict_like = FakeLuaTable({"name": "value"})
    runtime = FakeLuaRuntime()

    assert lupa_adapter.lua_table_to_python(array_like) == ["a", "b"]
    assert lupa_adapter.lua_table_to_python(dict_like) == {"name": "value"}
    assert lupa_adapter.python_to_lua_table(runtime, {"items": [1, "x"]}) == {"items": {1: 1, 2: "x"}}


def test_lupa_adapter_run_success_and_errors(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "lupa", fake_module("lupa", LuaRuntime=FakeLuaRuntime))
    adapter = lupa_adapter.LupaAdapter()

    success = adapter.run("emit-result", {"ok": True}, timeout_ms=50)
    runtime_error = adapter.run("explode", None, timeout_ms=50)
    timeout_error = adapter.run("sleep", None, timeout_ms=1)

    assert success["ok"] is True
    assert success["result"] == {"value": 7}
    assert success["stdout"] == ["hello 123"]
    assert runtime_error["ok"] is False
    assert runtime_error["error"]["type"] == "RuntimeError"
    assert "lua exploded" in runtime_error["error"]["message"]
    assert timeout_error["ok"] is False
    assert timeout_error["error"]["type"] in {"SandboxTimeoutError", "TimeoutError"}


def test_lupa_error_output_reports_type():
    result = lupa_adapter.error_output(Exception("boom"), ["line"], started=time.perf_counter())

    assert result["ok"] is False
    assert result["error"]["type"] == "RuntimeError"
    assert result["stdout"] == ["line"]


def test_miniracer_adapter_run_success_and_errors(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules, "py_mini_racer", fake_module("py_mini_racer", MiniRacer=FakeMiniRacer)
    )
    adapter = miniracer_adapter.MiniRacerAdapter()

    success = adapter.run("emit-result", {"ok": True}, timeout_ms=50)
    runtime_error = adapter.run("runtime-error", None, timeout_ms=50)
    timeout_error = adapter.run("timeout-error", None, timeout_ms=50)

    assert success["ok"] is True
    assert success["result"] == {"value": 3}
    assert success["stdout"] == ["hello 1"]
    assert runtime_error["ok"] is False
    assert runtime_error["error"]["type"] == "RuntimeError"
    assert timeout_error["error"]["type"] in {"SandboxTimeoutError", "TimeoutError"}


def test_miniracer_extract_stdout_returns_empty_on_bad_json():
    class BrokenContext:
        def eval(self, code: str):
            raise ValueError("bad json")

    assert miniracer_adapter.extract_stdout(BrokenContext()) == []


def test_child_main_builds_code_input_and_writes_result(monkeypatch):
    queue = FakeQueue()
    seen: list[CodeInput] = []

    monkeypatch.setattr("tuochat.sandbox.worker.apply_rlimits", lambda memory_limit_mb: None)
    monkeypatch.setattr("tuochat.sandbox.worker.apply_windows_job_limits", lambda memory_limit_mb: None)

    def fake_run_code(request: CodeInput) -> CodeOutput:
        seen.append(request)
        return CodeOutput(ok=True, result={"answer": 42}, stdout=["done"])

    monkeypatch.setattr("tuochat.sandbox.api.run_code", fake_run_code)

    child_main(
        {
            "code": "emit(42)",
            "language": "js",
            "input_data": {"x": 1},
            "timeout_ms": 250,
            "memory_limit_mb": 64,
        },
        queue,
    )

    assert seen[0].code == "emit(42)"
    assert queue.get_nowait()["result"] == {"answer": 42}


def test_run_in_worker_returns_timeout(monkeypatch):
    queue = FakeQueue()
    process = FakeProcess(alive=True, exitcode=None, queue=queue)
    monkeypatch.setattr("tuochat.sandbox.worker.multiprocessing.get_context", lambda mode: FakeContext(process, queue))

    result = run_in_worker(CodeInput(code="x", language="js", timeout_ms=10))

    assert result.ok is False
    assert result.error is not None
    assert result.error["type"] == "SandboxTimeoutError"
    assert process.killed is True


def test_run_in_worker_returns_memory_error_when_child_exits_without_result(monkeypatch):
    queue = FakeQueue()
    process = FakeProcess(alive=False, exitcode=-9, queue=queue)
    monkeypatch.setattr("tuochat.sandbox.worker.multiprocessing.get_context", lambda mode: FakeContext(process, queue))

    result = run_in_worker(CodeInput(code="x", language="js", timeout_ms=10))

    assert result.ok is False
    assert result.error == {"type": "MemoryLimitError", "message": "worker process terminated with exit code -9"}


def test_run_in_worker_reads_success_result(monkeypatch):
    queue = FakeQueue()
    process = FakeProcess(
        alive=False,
        exitcode=0,
        queue=queue,
        raw_result={"ok": True, "result": 9, "stdout": ["hello"], "stderr": [], "metrics": {"wall_ms": 1.2}},
    )
    monkeypatch.setattr("tuochat.sandbox.worker.multiprocessing.get_context", lambda mode: FakeContext(process, queue))

    result = run_in_worker(CodeInput(code="emit(9)", language="js", timeout_ms=10))

    assert result.ok is True
    assert result.result == 9
    assert result.stdout == ["hello"]
    assert result.metrics == {"wall_ms": 1.2}
