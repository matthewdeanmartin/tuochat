"""Lightweight git working-tree inspector using only non-interactive git commands.

Collects repo root, branch, staged/unstaged/untracked counts, and a dirty/clean
summary.  Non-git directories are treated as neutral (returns None).  Never
raises — all errors become None or empty values.
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("tuochat.git_info")


@dataclass
class GitStatus:
    """Snapshot of git working-tree state."""

    root: Path
    branch: str | None  # current branch name or None (detached HEAD)
    staged: int = 0  # files with staged changes
    unstaged: int = 0  # tracked files with unstaged modifications
    untracked: int = 0  # untracked files
    ahead: int | None = None  # commits ahead of upstream (None if unavailable)
    behind: int | None = None  # commits behind upstream (None if unavailable)
    notes: list[str] = field(default_factory=list)

    @property
    def dirty(self) -> bool:
        """True if there are any staged, unstaged, or untracked changes."""
        return bool(self.staged or self.unstaged or self.untracked)

    def summary(self) -> str:
        """One-line human-readable summary."""
        branch_str = self.branch or "(detached HEAD)"
        state = (
            "clean"
            if not self.dirty
            else (f"dirty — {self.staged} staged, {self.unstaged} unstaged, {self.untracked} untracked")
        )
        sync = ""
        if self.ahead or self.behind:
            parts = []
            if self.ahead:
                parts.append(f"+{self.ahead}")
            if self.behind:
                parts.append(f"-{self.behind}")
            sync = f" [{', '.join(parts)}]"
        return f"{branch_str}{sync}: {state}"


def run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a git command, returning (returncode, stdout). Never raises."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode, result.stdout.strip()
    except Exception as exc:
        logger.debug("git %s failed: %s", " ".join(args), exc)
        return 1, ""


def get_git_status(cwd: Path | None = None) -> GitStatus | None:
    """Return a GitStatus for *cwd*, or None if not inside a git repo."""
    work_dir = cwd or Path.cwd()

    # Confirm we're in a repo and get root
    rc, root_str = run_git("rev-parse", "--show-toplevel", cwd=work_dir)
    if rc != 0 or not root_str:
        return None
    root = Path(root_str)

    # Branch
    rc_b, branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    branch_name: str | None = branch if rc_b == 0 and branch and branch != "HEAD" else None

    # Ahead/behind (best-effort, skip if no upstream)
    ahead: int | None = None
    behind: int | None = None
    rc_ab, ab_str = run_git("rev-list", "--left-right", "--count", "@{u}...HEAD", cwd=root)
    if rc_ab == 0 and ab_str:
        parts = ab_str.split()
        if len(parts) == 2:
            try:
                behind = int(parts[0])
                ahead = int(parts[1])
            except ValueError:
                pass

    # Staged / unstaged / untracked via porcelain
    rc_s, status_out = run_git("status", "--porcelain", cwd=root)
    staged = 0
    unstaged = 0
    untracked = 0
    if rc_s == 0 and status_out:
        for line in status_out.splitlines():
            if len(line) < 2:
                continue
            xy = line[:2]
            index_char = xy[0]
            worktree_char = xy[1]
            if xy == "??":
                untracked += 1
            else:
                if index_char not in (" ", "?"):
                    staged += 1
                if worktree_char not in (" ", "?"):
                    unstaged += 1

    return GitStatus(
        root=root,
        branch=branch_name,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        ahead=ahead,
        behind=behind,
    )
