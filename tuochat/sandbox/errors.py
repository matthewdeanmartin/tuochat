"""Normalized error taxonomy for sandbox execution."""

from __future__ import annotations


class SandboxError(Exception):
    """Base class for all sandbox errors."""

    error_type: str = "SandboxError"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.error_type, "message": str(self)}


class ParseError(SandboxError):
    """Code failed to parse / compile."""

    error_type = "ParseError"


class SandboxRuntimeError(SandboxError):
    """Uncaught exception during execution."""

    error_type = "RuntimeError"


class SandboxTimeoutError(SandboxError):
    """Execution exceeded wall-clock limit."""

    error_type = "TimeoutError"


class MemoryLimitError(SandboxError):
    """Execution exceeded memory limit."""

    error_type = "MemoryLimitError"


class SerializationError(SandboxError):
    """Result could not be round-tripped through the value model."""

    error_type = "SerializationError"


class HostAPIError(SandboxError):
    """Misuse of the host API (emit called twice, etc.)."""

    error_type = "HostAPIError"


class SandboxViolation(SandboxError):
    """Attempted to escape the sandbox."""

    error_type = "SandboxViolation"
