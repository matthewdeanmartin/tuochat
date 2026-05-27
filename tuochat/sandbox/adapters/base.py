"""SandboxAdapter protocol — the contract every runtime adapter must satisfy."""

from __future__ import annotations

from typing import Any, Protocol


class SandboxAdapter(Protocol):
    """Minimal interface for a sandboxed code-execution backend."""

    language_name: str

    def run(
        self,
        code: str,
        input_data: Any,
        *,
        timeout_ms: int = 500,
        memory_limit_mb: int | None = None,
    ) -> dict[str, Any]:
        """Execute *code* and return a dict matching the sandbox output contract."""
        ...
