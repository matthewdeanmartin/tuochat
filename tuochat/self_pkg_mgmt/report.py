"""Report dataclasses and text rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class VersionInfo:
    name: str
    installed: str
    latest: str | None
    latest_published: datetime | None
    age_days: float | None
    is_upgrade_available: bool
    is_in_cooloff: bool

    @property
    def actionable(self) -> bool:
        """True if there is an upgrade the user should actually take."""
        return self.is_upgrade_available and not self.is_in_cooloff


@dataclass(frozen=True)
class Vulnerability:
    name: str
    installed: str
    advisory_id: str
    severity: str | None
    fix_versions: tuple[str, ...]
    source: str

    @property
    def actionable(self) -> bool:
        return bool(self.fix_versions)


@dataclass(frozen=True)
class Report:
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    host_dist: VersionInfo | None = None
    dependencies: tuple[VersionInfo, ...] = ()
    vulnerabilities: tuple[Vulnerability, ...] = ()
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        if self.host_dist and self.host_dist.actionable:
            return False
        if any(dep.actionable for dep in self.dependencies):
            return False
        if any(vuln.actionable for vuln in self.vulnerabilities):
            return False
        return True

    def render_text(self) -> str:
        lines: list[str] = []
        if self.host_dist and self.host_dist.actionable:
            hd = self.host_dist
            lines.append(f"[update] {hd.name} {hd.installed} -> {hd.latest} is available")
        upgradable = [d for d in self.dependencies if d.actionable]
        if upgradable:
            lines.append(f"[update] {len(upgradable)} dependencies have upgrades available:")
            for dep in upgradable:
                lines.append(f"  - {dep.name} {dep.installed} -> {dep.latest}")
        actionable_vulns = [v for v in self.vulnerabilities if v.actionable]
        if actionable_vulns:
            lines.append(f"[security] {len(actionable_vulns)} vulnerabilities with available fixes:")
            for vuln in actionable_vulns:
                fix = ", ".join(vuln.fix_versions) or "n/a"
                sev = vuln.severity or "unknown"
                lines.append(f"  - {vuln.name} {vuln.installed} {vuln.advisory_id} [{sev}] fix: {fix}")
        for note in self.notes:
            lines.append(f"[note] {note}")
        for err in self.errors:
            lines.append(f"[warn] {err}")
        return "\n".join(lines)
