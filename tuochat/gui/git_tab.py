"""Git status tab — shows working-tree state for the current directory."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING, Callable

from tuochat.git_info import GitStatus, get_git_status, run_git

if TYPE_CHECKING:
    pass

COLOR_CLEAN = "#16a34a"
COLOR_DIRTY = "#dc2626"
COLOR_NEUTRAL = "#6b7280"
COLOR_STAGED = "#2563eb"
COLOR_AHEAD = "#7c3aed"
COLOR_BEHIND = "#ea580c"


def get_porcelain_lines(root: Path) -> list[tuple[str, str]]:
    """Return [(xy_code, filepath)] from git status --porcelain."""
    rc, out = run_git("status", "--porcelain", cwd=root)
    if rc != 0 or not out:
        return []
    result = []
    for line in out.splitlines():
        if len(line) < 3:
            continue
        xy = line[:2]
        path = line[3:].strip().strip('"')
        result.append((xy, path))
    return result


def get_recent_commits(root: Path, n: int = 10) -> list[str]:
    """Return the last n commit one-liners."""
    rc, out = run_git("log", f"--max-count={n}", "--oneline", cwd=root)
    if rc != 0 or not out:
        return []
    return out.splitlines()


def describe_xy(xy: str) -> str:
    index_char = xy[0]
    worktree_char = xy[1]
    if xy == "??":
        return "untracked"
    parts = []
    index_map = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "unmerged",
    }
    worktree_map = {
        "M": "modified (unstaged)",
        "D": "deleted (unstaged)",
        "U": "unmerged",
    }
    if index_char not in (" ", "?"):
        parts.append(index_map.get(index_char, f"index:{index_char}"))
    if worktree_char not in (" ", "?"):
        parts.append(worktree_map.get(worktree_char, f"worktree:{worktree_char}"))
    return ", ".join(parts) if parts else "unknown"


def tag_for_xy(xy: str) -> str:
    if xy == "??":
        return "untracked"
    if xy[0] != " " and xy[0] != "?":
        return "staged"
    return "unstaged"


class GitStatusTab:
    """Notebook tab showing live git working-tree status."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_attach_context: Callable[[str, str], None] | None = None,
    ) -> None:
        self.parent = parent
        self.on_attach_context = on_attach_context
        self.git_status: GitStatus | None = None
        self.cwd = Path.cwd()

        self.build(parent)
        self.refresh()

    def build(self, parent: tk.Misc) -> None:
        outer = tk.Frame(parent)
        outer.pack(fill="both", expand=True)

        # Top: summary bar + refresh
        header = tk.Frame(outer)
        header.pack(fill="x", padx=8, pady=(6, 0))

        self.status_label = tk.Label(
            header,
            text="",
            anchor="w",
            font=("TkFixedFont", 10, "bold"),
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        tk.Button(header, text="Refresh", command=self.refresh).pack(side="right")

        # Dirty-state banner
        self.dirty_banner = tk.Label(
            outer,
            text="",
            anchor="w",
            font=("TkDefaultFont", 9),
            padx=8,
        )
        self.dirty_banner.pack(fill="x")

        # Ahead/behind
        self.sync_label = tk.Label(outer, text="", anchor="w", font=("TkDefaultFont", 9), padx=8)
        self.sync_label.pack(fill="x")

        # Paned: file list left, recent commits right
        paned = tk.PanedWindow(outer, orient="horizontal", sashwidth=5, sashrelief="groove")
        paned.pack(fill="both", expand=True, padx=8, pady=6)

        # Left: changed files
        left = tk.Frame(paned)
        paned.add(left, minsize=240)

        tk.Label(left, text="Changed files", font=("TkDefaultFont", 9, "bold"), anchor="w").pack(fill="x")

        tree_frame = tk.Frame(left)
        tree_frame.pack(fill="both", expand=True)

        self.file_tree = ttk.Treeview(
            tree_frame,
            columns=("status", "path"),
            show="headings",
            selectmode="browse",
        )
        self.file_tree.heading("status", text="Status")
        self.file_tree.heading("path", text="File")
        self.file_tree.column("status", width=120, stretch=False)
        self.file_tree.column("path", width=300, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.file_tree.pack(fill="both", expand=True)

        self.file_tree.tag_configure("staged", foreground=COLOR_STAGED)
        self.file_tree.tag_configure("unstaged", foreground=COLOR_DIRTY)
        self.file_tree.tag_configure("untracked", foreground=COLOR_NEUTRAL)

        # Action bar below file tree
        act = tk.Frame(left)
        act.pack(fill="x", pady=(4, 0))
        self.attach_diff_btn = tk.Button(
            act,
            text="Attach diff to context",
            state="disabled",
            command=self.attach_diff_to_context,
        )
        self.attach_diff_btn.pack(side="left")

        # Right: recent commits
        right = tk.Frame(paned)
        paned.add(right, minsize=200)

        tk.Label(right, text="Recent commits", font=("TkDefaultFont", 9, "bold"), anchor="w").pack(fill="x")

        self.commits_text = ScrolledText(right, wrap="none", state="disabled", height=12)
        self.commits_text.pack(fill="both", expand=True)

    def refresh(self) -> None:
        self.cwd = Path.cwd()
        self.git_status = get_git_status(self.cwd)
        self.update_ui()

    def update_ui(self) -> None:
        status = self.git_status

        if status is None:
            self.status_label.configure(text="Not a git repository", fg=COLOR_NEUTRAL)
            self.dirty_banner.configure(text="", bg="SystemButtonFace")
            self.sync_label.configure(text="")
            self.clear_file_tree()
            self.set_commits_text("(no git repo)")
            self.attach_diff_btn.configure(state="disabled")
            return

        branch_str = status.branch or "(detached HEAD)"
        self.status_label.configure(text=f"  {branch_str}  —  {status.root}", fg=COLOR_NEUTRAL)

        if status.dirty:
            banner = (
                f"  DIRTY  —  {status.staged} staged,  " f"{status.unstaged} unstaged,  {status.untracked} untracked"
            )
            self.dirty_banner.configure(text=banner, fg=COLOR_DIRTY, bg="#fef2f2")
        else:
            self.dirty_banner.configure(text="  Working tree is clean", fg=COLOR_CLEAN, bg="#f0fdf4")

        sync_parts = []
        if status.ahead is not None and status.ahead > 0:
            sync_parts.append(f"+{status.ahead} ahead of upstream")
        if status.behind is not None and status.behind > 0:
            sync_parts.append(f"{status.behind} behind upstream")
        self.sync_label.configure(text=("  " + "  |  ".join(sync_parts)) if sync_parts else "")

        lines = get_porcelain_lines(status.root)
        self.populate_file_tree(lines)
        self.attach_diff_btn.configure(state="normal" if status.dirty else "disabled")

        commits = get_recent_commits(status.root)
        self.set_commits_text("\n".join(commits) if commits else "(no commits)")

    def clear_file_tree(self) -> None:
        self.file_tree.delete(*self.file_tree.get_children())

    def populate_file_tree(self, lines: list[tuple[str, str]]) -> None:
        self.clear_file_tree()
        for xy, path in sorted(lines, key=lambda t: (t[0], t[1])):
            desc = describe_xy(xy)
            tag = tag_for_xy(xy)
            self.file_tree.insert("", "end", values=(desc, path), tags=(tag,))

    def set_commits_text(self, text: str) -> None:
        self.commits_text.configure(state="normal")
        self.commits_text.delete("1.0", "end")
        self.commits_text.insert("1.0", text)
        self.commits_text.configure(state="disabled")

    def attach_diff_to_context(self) -> None:
        status = self.git_status
        if status is None or self.on_attach_context is None:
            return
        rc, diff = run_git("diff", "HEAD", cwd=status.root)
        if rc != 0:
            rc, diff = run_git("diff", cwd=status.root)
        if not diff:
            _, diff = run_git("status", "--short", cwd=status.root)
            label = "Git status (no diff available)"
        else:
            label = f"Git diff ({status.branch or 'HEAD'})"
        payload = f"```\n{diff}\n```"
        self.on_attach_context(label, payload)
