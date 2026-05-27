"""Local .check file workflows for the CLI and REPL."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tuochat.cli.prompts import prompt_input


@dataclass(frozen=True)
class CheckFileCandidate:
    """A discovered `.check` file and its adjacent non-check path."""

    check_path: Path
    target_path: Path
    target_exists: bool


def workspace_root(root: Path | None = None) -> Path:
    """Return the root used for local `.check` file workflows."""
    return (root or Path.cwd()).resolve()


def relative_label(path: Path, root: Path) -> str:
    """Render a path relative to the active workspace when possible."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def discover_check_files(root: Path | None = None) -> list[CheckFileCandidate]:
    """Return all `.check` files beneath the workspace root."""
    base = workspace_root(root)
    candidates: list[CheckFileCandidate] = []
    for check_path in sorted(base.rglob("*.check"), key=lambda current: str(current.relative_to(base)).casefold()):
        if not check_path.is_file():
            continue
        target_path = check_path.with_name(check_path.name[: -len(".check")])
        candidates.append(
            CheckFileCandidate(
                check_path=check_path,
                target_path=target_path,
                target_exists=target_path.exists(),
            )
        )
    return candidates


def print_path_group(title: str, paths: list[Path], root: Path) -> None:
    """Print a titled list of paths."""
    if not paths:
        return
    print(title)
    for path in paths:
        print(f"  {relative_label(path, root)}")


def run_files_approve(root: Path | None = None) -> int:
    """Rename `.check` files by stripping the suffix when there is no clash."""
    base = workspace_root(root)
    candidates = discover_check_files(base)
    if not candidates:
        print(f"No .check files found under {base}.")
        return 0

    approved: list[Path] = []
    skipped: list[Path] = []
    for candidate in candidates:
        if candidate.target_exists:
            skipped.append(candidate.check_path)
            continue
        candidate.check_path.replace(candidate.target_path)
        approved.append(candidate.target_path)

    if approved:
        print(f"Approved {len(approved)} .check file(s).")
        print_path_group("Renamed:", approved, base)
    else:
        print("No .check files were approved.")
    if skipped:
        print()
        print_path_group("Skipped due to name clashes:", skipped, base)
    return 0


def confirm_delete(
    candidates: list[CheckFileCandidate], root: Path, *, yes: bool, prompt: Callable[[str], str]
) -> bool:
    """Confirm deleting all discovered `.check` files unless forced."""
    if yes:
        return True
    print_path_group("Delete these .check files:", [candidate.check_path for candidate in candidates], root)
    choice = prompt(f"Delete {len(candidates)} .check file(s)? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def run_files_delete(
    root: Path | None = None, *, yes: bool = False, prompt: Callable[[str], str] = prompt_input
) -> int:
    """Delete all discovered `.check` files after confirmation."""
    base = workspace_root(root)
    candidates = discover_check_files(base)
    if not candidates:
        print(f"No .check files found under {base}.")
        return 0
    if not confirm_delete(candidates, base, yes=yes, prompt=prompt):
        print("Delete cancelled.")
        return 0

    deleted: list[Path] = []
    for candidate in candidates:
        candidate.check_path.unlink()
        deleted.append(candidate.check_path)
    print(f"Deleted {len(deleted)} .check file(s).")
    print_path_group("Deleted:", deleted, base)
    return 0


def render_diff(candidate: CheckFileCandidate, root: Path) -> list[str]:
    """Return a unified diff for one adjacent file pair."""
    before = candidate.target_path.read_text(encoding="utf-8", errors="replace").splitlines()
    after = candidate.check_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return list(
        difflib.unified_diff(
            before,
            after,
            fromfile=relative_label(candidate.target_path, root),
            tofile=relative_label(candidate.check_path, root),
            lineterm="",
        )
    )


def run_diff(root: Path | None = None, *, prompt_continue: Callable[[str], str] = prompt_input) -> int:
    """Show diffs for adjacent `.check` files, then list unpaired drafts."""
    base = workspace_root(root)
    candidates = discover_check_files(base)
    if not candidates:
        print(f"No .check files found under {base}.")
        return 0

    paired = [candidate for candidate in candidates if candidate.target_exists]
    unpaired = [candidate.check_path for candidate in candidates if not candidate.target_exists]

    if not paired:
        print("No adjacent file pairs were found for diffing.")
    else:
        for index, candidate in enumerate(paired, start=1):
            print(f"Diff {index}/{len(paired)}")
            print(f"  target: {relative_label(candidate.target_path, base)}")
            print(f"  check:  {relative_label(candidate.check_path, base)}")
            diff_lines = render_diff(candidate, base)
            if diff_lines:
                for line in diff_lines:
                    print(line)
            else:
                print("(no differences)")
            if index < len(paired):
                choice = prompt_continue("Continue to the next diff? [Y/n] ").strip().lower()
                if choice not in {"", "y", "yes"}:
                    remaining = len(paired) - index
                    print(f"Stopped after {index} diff(s); {remaining} paired .check file(s) remain.")
                    break
                print()

    if unpaired:
        if paired:
            print()
        print_path_group("Unpaired .check files:", unpaired, base)
    elif candidates:
        if paired:
            print()
        print("No unpaired .check files.")
    return 0
