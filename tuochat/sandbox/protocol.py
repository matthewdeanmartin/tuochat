"""Input/output dataclasses for the sandbox contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeInput:
    """Input payload for sandboxed code execution."""

    code: str
    language: str
    input_data: Any = None
    timeout_ms: int = 500
    memory_limit_mb: int | None = 64


@dataclass
class CodeOutput:
    """Result of a sandboxed code execution."""

    ok: bool
    result: Any = None
    error: dict[str, str] | None = None
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the sandbox output contract."""
        out: dict[str, Any] = {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "metrics": self.metrics,
        }
        if self.ok:
            out["result"] = self.result
        else:
            out["error"] = self.error
        return out
