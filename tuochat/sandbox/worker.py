"""Subprocess-isolated sandbox worker.

Each execution is delegated to a fresh child process.  The child applies
OS-level resource limits (rlimits on POSIX, Job Objects on Windows) before
running the adapter, so runaway code cannot starve the parent process.

Usage
-----
    from tuochat.sandbox.worker import run_in_worker
    from tuochat.sandbox.protocol import CodeInput

    output = run_in_worker(CodeInput(code="emit(1+1)", language="js"))

The child communicates through a shared ``multiprocessing.Queue``.  If the
child is killed (OOM, timeout, SIGKILL) the parent converts the absence of a
result into a ``SandboxTimeoutError`` / ``MemoryLimitError`` response.
"""

from __future__ import annotations

import multiprocessing
import sys
from typing import Any

from tuochat.sandbox.protocol import CodeInput, CodeOutput

# How much slack to add on top of the user-supplied timeout_ms when waiting for
# the child process (covers process start-up overhead).
PROCESS_OVERHEAD_MS = 2_000


def apply_rlimits(memory_limit_mb: int | None) -> None:
    """Apply POSIX rlimits in the child process (no-op on non-POSIX)."""
    if sys.platform == "win32":
        return
    try:
        import resource  # POSIX only

        # Limit address space when a memory cap is requested.
        if memory_limit_mb is not None:
            limit_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

        # Prevent core dumps.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        # Prevent new file creation (no filesystem output).
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

        # Cap the number of open file descriptors.
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    except Exception:  # noqa: BLE001 — rlimits may not be available in all environments
        pass


def apply_windows_job_limits(memory_limit_mb: int | None) -> None:
    """Apply Windows process isolation in the child process.

    Uses the pywin32-based isolation from ``tuochat.security.windows_isolation``
    when available, applying a restricted Job Object with memory limits and
    kill-on-close.  Falls back to a no-op if pywin32 is not installed.
    """
    if sys.platform != "win32":
        return
    try:
        from tuochat.security.windows_isolation import AVAILABLE, JobLimits, apply_isolation, is_isolated

        if not AVAILABLE:
            return
        if is_isolated():
            return

        limits = JobLimits(
            kill_on_close=True,
            max_active_processes=1,
            memory_limit_mb=memory_limit_mb,
        )
        apply_isolation(limits=limits)
    except Exception:  # noqa: BLE001
        pass


def child_main(
    request_dict: dict[str, Any],
    result_queue: Any,
) -> None:
    """Entry point for the worker child process."""
    memory_limit_mb: int | None = request_dict.get("memory_limit_mb")

    # Apply OS-level resource limits before importing or running anything.
    apply_rlimits(memory_limit_mb)
    apply_windows_job_limits(memory_limit_mb)

    from tuochat.sandbox.api import run_code

    request = CodeInput(
        code=request_dict["code"],
        language=request_dict["language"],
        input_data=request_dict.get("input_data"),
        timeout_ms=request_dict.get("timeout_ms", 500),
        memory_limit_mb=memory_limit_mb,
    )
    output = run_code(request)
    result_queue.put(output.to_dict())


def run_in_worker(request: CodeInput) -> CodeOutput:
    """Run *request* inside an isolated child process and return the output.

    The child is forcibly terminated if it does not respond within
    ``request.timeout_ms + PROCESS_OVERHEAD_MS`` milliseconds.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue(maxsize=1)

    request_dict: dict[str, Any] = {
        "code": request.code,
        "language": request.language,
        "input_data": request.input_data,
        "timeout_ms": request.timeout_ms,
        "memory_limit_mb": request.memory_limit_mb,
    }

    process = ctx.Process(
        target=child_main,
        args=(request_dict, result_queue),
        daemon=True,
    )
    process.start()

    deadline_seconds = (request.timeout_ms + PROCESS_OVERHEAD_MS) / 1000
    process.join(timeout=deadline_seconds)

    if process.is_alive():
        process.kill()
        process.join(timeout=2)
        return CodeOutput(
            ok=False,
            error={
                "type": "SandboxTimeoutError",
                "message": f"worker process exceeded {request.timeout_ms + PROCESS_OVERHEAD_MS} ms deadline",
            },
        )

    exit_code = process.exitcode
    if exit_code != 0 and result_queue.empty():
        # Child was killed (OOM, signal) without writing a result.
        error_type = "MemoryLimitError" if exit_code == -9 else "RuntimeError"
        return CodeOutput(
            ok=False,
            error={
                "type": error_type,
                "message": f"worker process terminated with exit code {exit_code}",
            },
        )

    try:
        raw = result_queue.get_nowait()
    except Exception:  # noqa: BLE001 — queue.Empty or pickling error
        return CodeOutput(
            ok=False,
            error={"type": "RuntimeError", "message": "worker process produced no result"},
        )

    return CodeOutput(
        ok=raw.get("ok", False),
        result=raw.get("result"),
        error=raw.get("error"),
        stdout=raw.get("stdout", []),
        stderr=raw.get("stderr", []),
        metrics=raw.get("metrics", {}),
    )
