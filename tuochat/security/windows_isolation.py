# pylint: disable=redefined-outer-name
"""Lightweight Windows process isolation using restricted tokens and Job Objects.

Requires pywin32.  When pywin32 is not installed every public function is a
safe no-op so callers never need to gate on availability.

Two modes of use:

1. **Self-sandbox** -- call ``apply_isolation()`` early in startup to restrict
   the *current* process.  Useful when the entire app should run with reduced
   privileges.

2. **Child-sandbox** -- call ``spawn_isolated()`` to launch a subprocess that
   inherits only stdin/stdout/stderr, runs under a restricted token, and is
   bound to a kill-on-close Job Object.  This is intended for the
   code-interpreter worker.

If the process is already inside a Job Object with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` we skip re-sandboxing to avoid
nesting issues.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def get_os_file_handle(msvcrt_module: Any, file_descriptor: int) -> int:
    """Return a Windows OS handle for a Python file descriptor."""
    return msvcrt_module.get_osfhandle(file_descriptor)


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------

windows_isolation_available: bool = False
"""True when pywin32 is importable and we are on Windows."""

if sys.platform == "win32":
    try:
        import win32api  # noqa: F401  -- side-effect import test  # pylint: disable=unused-import
        import win32con  # noqa: F401 # pylint: disable=unused-import
        import win32job  # noqa: F401# pylint: disable=unused-import
        import win32process  # noqa: F401# pylint: disable=unused-import
        import win32security  # noqa: F401# pylint: disable=unused-import

        windows_isolation_available = True
    except ImportError:
        pass

if not windows_isolation_available:
    logger.debug(
        "windows_isolation: pywin32 not available (platform=%s) -- all isolation functions will be no-ops",
        sys.platform,
    )

AVAILABLE = windows_isolation_available


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class JobLimits:
    """Tunables for the Job Object that wraps isolated processes."""

    kill_on_close: bool = True
    max_active_processes: int | None = 1
    memory_limit_mb: int | None = 128


@dataclass
class IsolationResult:
    """Describes what ``apply_isolation`` actually did."""

    applied: bool = False
    already_sandboxed: bool = False
    restricted_token: bool = False
    job_object: bool = False
    restrictions: list[str] = field(default_factory=list)
    reason_skipped: str = ""


# ---------------------------------------------------------------------------
# Internal helpers (only called when windows_isolation_available is True)
# ---------------------------------------------------------------------------


def already_in_sandboxed_job() -> bool:
    """Return True if the current process is in a Job with KILL_ON_JOB_CLOSE."""
    import win32api
    import win32job  # noqa: F811

    try:
        ok = win32job.IsProcessInJob(win32api.GetCurrentProcess(), None)  # type: ignore[arg-type]
    except Exception:
        # IsProcessInJob may not be available on very old pywin32 builds.
        return False

    if not ok:
        return False

    # We know we are in *some* job -- check if it has kill-on-close.
    # QueryInformationJobObject on a NULL job handle queries the job that the
    # current process belongs to (Windows 8+).  If it fails we conservatively
    # say "yes, already sandboxed".
    try:
        info = win32job.QueryInformationJobObject(
            0,
            win32job.JobObjectExtendedLimitInformation,
        )
        flags = info["BasicLimitInformation"]["LimitFlags"]
        return bool(flags & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    except Exception:
        return True


def create_restricted_token():  # type: ignore[no-untyped-def]
    """Create a restricted primary token from the current process token.

    The token has ``DISABLE_MAX_PRIVILEGE`` set, which strips *all*
    privileges except ``SeChangeNotifyPrivilege`` (needed for path
    traversal).  No SIDs are disabled or added as restricting SIDs --
    that is left for a future hardening pass.
    """
    import win32api
    import win32con  # noqa: F811
    import win32security  # noqa: F811

    disable_max_privilege = getattr(win32security, "DISABLE_MAX_PRIVILEGE", 0x1)

    process_handle = win32api.GetCurrentProcess()  # type: ignore[attr-defined]
    token = win32security.OpenProcessToken(
        process_handle,
        win32con.TOKEN_DUPLICATE
        | win32con.TOKEN_QUERY
        | win32con.TOKEN_ASSIGN_PRIMARY
        | win32con.TOKEN_ADJUST_DEFAULT
        | win32con.TOKEN_ADJUST_SESSIONID,
    )
    restricted = win32security.CreateRestrictedToken(
        token,
        disable_max_privilege,
        (),  # SIDs to disable
        (),  # privileges to delete
        (),  # restricting SIDs
    )
    return restricted


def create_job_object(limits: JobLimits):  # type: ignore[no-untyped-def]
    """Create a Job Object with the given *limits* and return its handle."""
    import win32job  # noqa: F811

    job = win32job.CreateJobObject(None, "")  # type: ignore[func-returns-value]
    info = win32job.QueryInformationJobObject(
        job,
        win32job.JobObjectExtendedLimitInformation,
    )

    flags = info["BasicLimitInformation"]["LimitFlags"]

    if limits.kill_on_close:
        flags |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    if limits.max_active_processes is not None:
        flags |= win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info["BasicLimitInformation"]["ActiveProcessLimit"] = limits.max_active_processes

    if limits.memory_limit_mb is not None:
        flags |= win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info["ProcessMemoryLimit"] = limits.memory_limit_mb * 1024 * 1024

    info["BasicLimitInformation"]["LimitFlags"] = flags

    win32job.SetInformationJobObject(
        job,
        win32job.JobObjectExtendedLimitInformation,
        info,
    )
    return job


def describe_restrictions(limits: JobLimits) -> list[str]:
    """Return human-readable lines describing what isolation removes."""
    lines = [
        "All token privileges stripped except SeChangeNotifyPrivilege (DISABLE_MAX_PRIVILEGE).",
        "Process cannot escalate privileges or obtain new ones.",
    ]
    if limits.kill_on_close:
        lines.append("Job Object: KILL_ON_JOB_CLOSE -- process dies if parent closes the job handle or exits.")
    if limits.max_active_processes is not None:
        lines.append(
            f"Job Object: ACTIVE_PROCESS limit = {limits.max_active_processes} -- cannot spawn more than {limits.max_active_processes} concurrent child process(es)."
        )
    if limits.memory_limit_mb is not None:
        lines.append(f"Job Object: PROCESS_MEMORY limit = {limits.memory_limit_mb} MiB -- OOM-killed if exceeded.")
    lines.append(
        "NOTE: Restricted tokens do not block filesystem or network access by themselves; that requires ACL changes or AppContainer (future work)."
    )
    return lines


# ---------------------------------------------------------------------------
# Public API -- self-sandbox
# ---------------------------------------------------------------------------


def apply_isolation(
    *,
    limits: JobLimits | None = None,
) -> IsolationResult:
    """Restrict the *current* process in-place.

    Assigns the process to a new Job Object with the given *limits*.  The
    restricted-token step is skipped for self-sandboxing because Windows
    does not allow replacing a running process's primary token; the token
    restriction only applies to *child* processes spawned via
    ``spawn_isolated``.

    Returns an :class:`IsolationResult` describing what happened.
    """
    result = IsolationResult()

    if not windows_isolation_available:
        result.reason_skipped = "pywin32 not available"
        logger.debug("apply_isolation: skipped -- %s", result.reason_skipped)
        return result

    if already_in_sandboxed_job():
        result.already_sandboxed = True
        result.reason_skipped = "already inside a sandboxed Job Object"
        logger.debug("apply_isolation: skipped -- %s", result.reason_skipped)
        return result

    if limits is None:
        limits = JobLimits()

    try:
        import win32api
        import win32job

        job = create_job_object(limits)
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())  # type: ignore[attr-defined]
        result.job_object = True
        # Intentionally leak *job* -- closing it would kill the process.
    except Exception:
        logger.warning("apply_isolation: failed to create/assign Job Object", exc_info=True)
        result.reason_skipped = "Job Object creation or assignment failed"
        return result

    result.applied = True
    result.restrictions = describe_restrictions(limits)

    logger.debug("process isolation ACTIVE -- restrictions applied:")
    for line in result.restrictions:
        logger.debug("  - %s", line)

    return result


# ---------------------------------------------------------------------------
# Public API -- child-sandbox (for code-interpreter worker)
# ---------------------------------------------------------------------------


@dataclass
class ChildHandle:
    """Opaque handle bundle returned by ``spawn_isolated``."""

    process_handle: object
    thread_handle: object
    pid: int
    tid: int
    job_handle: object
    stdin_write_fd: int
    stdout_read_fd: int

    def close(self) -> None:
        """Release all OS handles.  Safe to call multiple times."""
        import os

        for fd_name in ("stdin_write_fd", "stdout_read_fd"):
            fd = getattr(self, fd_name, -1)
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_name, -1)

        for handle_name in ("thread_handle", "process_handle", "job_handle"):
            handle = getattr(self, handle_name, None)
            if handle is not None:
                import win32api

                try:
                    win32api.CloseHandle(handle)  # type: ignore[attr-defined]
                except Exception:
                    pass
                setattr(self, handle_name, None)


def spawn_isolated(
    cmdline: str,
    *,
    limits: JobLimits | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> ChildHandle | None:
    """Launch *cmdline* in an isolated child process.

    The child runs under a restricted token, inherits only stdio handles,
    has an empty environment (unless *env* is provided), and is bound to a
    kill-on-close Job Object.

    Returns a :class:`ChildHandle` on success, or ``None`` if pywin32 is
    unavailable.
    """
    if not windows_isolation_available:
        logger.debug("spawn_isolated: pywin32 not available, returning None")
        return None

    import msvcrt
    import os

    import win32api  # noqa: F811
    import win32con  # noqa: F811
    import win32job  # noqa: F811
    import win32process  # noqa: F811

    if limits is None:
        limits = JobLimits()

    token = create_restricted_token()
    job = create_job_object(limits)

    # Create pipes -- child gets the read-end of stdin, write-end of stdout.
    stdin_r_fd, stdin_w_fd = os.pipe()
    stdout_r_fd, stdout_w_fd = os.pipe()

    os.set_inheritable(stdin_r_fd, True)
    os.set_inheritable(stdin_w_fd, False)
    os.set_inheritable(stdout_r_fd, False)
    os.set_inheritable(stdout_w_fd, True)

    si = win32process.STARTUPINFO()
    si.dwFlags |= win32con.STARTF_USESTDHANDLES
    si.hStdInput = get_os_file_handle(msvcrt, stdin_r_fd)
    si.hStdOutput = get_os_file_handle(msvcrt, stdout_w_fd)
    si.hStdError = get_os_file_handle(msvcrt, stdout_w_fd)

    creation_flags = win32con.CREATE_NO_WINDOW

    # Empty environment by default -- prevents inheriting parent env vars.
    child_env = env if env is not None else {}

    try:
        h_process, h_thread, pid, tid = win32process.CreateProcessAsUser(
            token,
            None,  # type: ignore[arg-type] # appName
            cmdline,  # command line
            None,  # type: ignore[arg-type] # process security
            None,  # type: ignore[arg-type] # thread security
            True,  # inherit handles (for stdio)
            creation_flags,
            child_env,
            cwd,  # type: ignore[arg-type] # working directory
            si,
        )
        win32job.AssignProcessToJobObject(job, h_process)
    except Exception:
        # Clean up on failure.
        for fd in (stdin_r_fd, stdin_w_fd, stdout_r_fd, stdout_w_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            win32api.CloseHandle(job)  # type: ignore[attr-defined]
        except Exception:
            pass
        raise
    finally:
        # Parent never uses the child-side pipe ends.
        for fd in (stdin_r_fd, stdout_w_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    restrictions = describe_restrictions(limits)
    logger.debug(
        "spawn_isolated: child PID %d launched with restricted token and Job Object:",
        pid,
    )
    for line in restrictions:
        logger.debug("  - %s", line)

    return ChildHandle(
        process_handle=h_process,
        thread_handle=h_thread,
        pid=pid,
        tid=tid,
        job_handle=job,
        stdin_write_fd=stdin_w_fd,
        stdout_read_fd=stdout_r_fd,
    )


# ---------------------------------------------------------------------------
# Convenience query
# ---------------------------------------------------------------------------


def is_isolated() -> bool:
    """Return True if the current process appears to be inside a sandbox.

    Checks for a Job Object with KILL_ON_JOB_CLOSE.  Returns False when
    pywin32 is not available (non-Windows or not installed).
    """
    if not windows_isolation_available:
        return False
    return already_in_sandboxed_job()
