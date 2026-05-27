"""Self-upgrade dispatcher."""

from __future__ import annotations

import subprocess  # noqa: S404
from dataclasses import dataclass

from tuochat.self_pkg_mgmt.install_method import InstallMethod, detect, upgrade_argv

UPGRADE_TIMEOUT = 300


@dataclass(frozen=True)
class UpgradeResult:
    method: InstallMethod
    argv: list[str] | None
    returncode: int | None
    stdout: str
    stderr: str
    attempted: bool

    @property
    def ok(self) -> bool:
        return self.attempted and self.returncode == 0


def perform(dist_name: str, dry_run: bool = False) -> UpgradeResult:
    method = detect(dist_name)
    argv = upgrade_argv(method, dist_name)
    if argv is None or method == InstallMethod.EDITABLE:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr="", attempted=False)
    if dry_run:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr="", attempted=False)
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=UPGRADE_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr=str(exc), attempted=True)
    return UpgradeResult(
        method=method, argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, attempted=True
    )
