"""GitLab info tab — MRs, issues, pipelines, and resource/context management."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

STATUS_ICONS = {
    "success": "✓",
    "passed": "✓",
    "failed": "✗",
    "running": "▶",
    "pending": "…",
    "canceled": "—",
    "skipped": "—",
    "created": "○",
}

STATUS_COLORS = {
    "success": "#16a34a",
    "passed": "#16a34a",
    "failed": "#dc2626",
    "running": "#2563eb",
    "pending": "#d97706",
    "canceled": "#6b7280",
    "skipped": "#6b7280",
    "created": "#6b7280",
}

MR_STATE_COLORS = {
    "opened": "#2563eb",
    "merged": "#16a34a",
    "closed": "#6b7280",
}


def pipeline_tag(status: str) -> str:
    return f"pipeline_{status}" if status in STATUS_COLORS else "pipeline_other"


class GitLabTab:
    """Notebook tab showing GitLab project MRs, issues, and pipelines."""

    def __init__(
        self,
        parent: tk.Misc,
        cfg: TuochatConfig,
        *,
        on_set_resource: Callable[[str | None], None] | None = None,
        on_attach_context: Callable[[str, str], None] | None = None,
    ) -> None:
        self.parent = parent
        self.cfg = cfg
        self.on_set_resource = on_set_resource
        self.on_attach_context = on_attach_context

        self.project_id: str | int | None = None
        self.project_path: str | None = None
        self.mrs: list[dict] = []
        self.issues: list[dict] = []
        self.pipelines: list[dict] = []
        self.loading = False

        self.build(parent)

    def build(self, parent: tk.Misc) -> None:
        outer = tk.Frame(parent)
        outer.pack(fill="both", expand=True)

        # Project selector bar
        selector = tk.Frame(outer)
        selector.pack(fill="x", padx=8, pady=(6, 2))

        tk.Label(selector, text="Project path:").pack(side="left")
        self.project_var = tk.StringVar(master=parent)
        self.project_entry = tk.Entry(selector, textvariable=self.project_var, width=40)
        self.project_entry.pack(side="left", padx=(4, 0))
        tk.Label(selector, text="(e.g. group/repo)").pack(side="left", padx=(2, 0))
        tk.Button(selector, text="Load", command=self.load_project).pack(side="left", padx=(8, 0))
        self.refresh_btn = tk.Button(selector, text="Refresh", command=self.refresh_data, state="disabled")
        self.refresh_btn.pack(side="left", padx=(4, 0))

        # Active resource bar
        resource_bar = tk.Frame(outer)
        resource_bar.pack(fill="x", padx=8, pady=(0, 2))
        tk.Label(resource_bar, text="Active resource:").pack(side="left")
        self.resource_label = tk.Label(resource_bar, text="(none)", anchor="w", fg="#6b7280")
        self.resource_label.pack(side="left", padx=(4, 0))
        self.set_resource_btn = tk.Button(
            resource_bar,
            text="Set as resource",
            state="disabled",
            command=self.set_project_as_resource,
        )
        self.set_resource_btn.pack(side="left", padx=(8, 0))
        self.clear_resource_btn = tk.Button(
            resource_bar,
            text="Clear resource",
            command=self.clear_resource,
        )
        self.clear_resource_btn.pack(side="left", padx=(4, 0))

        # Status bar
        self.status_var = tk.StringVar(master=parent, value="Enter a project path and click Load.")
        tk.Label(outer, textvariable=self.status_var, anchor="w", fg="#6b7280", padx=8).pack(fill="x")

        # Main paned area: MRs + issues left, pipelines right
        paned = tk.PanedWindow(outer, orient="horizontal", sashwidth=5, sashrelief="groove")
        paned.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        left = tk.Frame(paned)
        paned.add(left, minsize=300)

        right = tk.Frame(paned)
        paned.add(right, minsize=220)

        # MRs (top-left)
        mr_frame = tk.LabelFrame(left, text="Open Merge Requests", padx=4, pady=4)
        mr_frame.pack(fill="both", expand=True, pady=(0, 4))

        self.mr_tree = ttk.Treeview(
            mr_frame,
            columns=("iid", "title", "branch"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.mr_tree.heading("iid", text="#")
        self.mr_tree.heading("title", text="Title")
        self.mr_tree.heading("branch", text="Branch")
        self.mr_tree.column("iid", width=40, stretch=False)
        self.mr_tree.column("title", width=240, stretch=True)
        self.mr_tree.column("branch", width=120, stretch=False)
        mr_vsb = ttk.Scrollbar(mr_frame, orient="vertical", command=self.mr_tree.yview)
        self.mr_tree.configure(yscrollcommand=mr_vsb.set)
        mr_vsb.pack(side="right", fill="y")
        self.mr_tree.pack(fill="both", expand=True)
        self.mr_tree.bind("<<TreeviewSelect>>", self.on_mr_select)

        mr_actions = tk.Frame(left)
        mr_actions.pack(fill="x", pady=(0, 4))
        self.attach_mr_btn = tk.Button(
            mr_actions, text="Attach MR to context", state="disabled", command=self.attach_mr_to_context
        )
        self.attach_mr_btn.pack(side="left")

        # Issues (bottom-left)
        issue_frame = tk.LabelFrame(left, text="Open Issues", padx=4, pady=4)
        issue_frame.pack(fill="both", expand=True)

        self.issue_tree = ttk.Treeview(
            issue_frame,
            columns=("iid", "title"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.issue_tree.heading("iid", text="#")
        self.issue_tree.heading("title", text="Title")
        self.issue_tree.column("iid", width=40, stretch=False)
        self.issue_tree.column("title", width=340, stretch=True)
        issue_vsb = ttk.Scrollbar(issue_frame, orient="vertical", command=self.issue_tree.yview)
        self.issue_tree.configure(yscrollcommand=issue_vsb.set)
        issue_vsb.pack(side="right", fill="y")
        self.issue_tree.pack(fill="both", expand=True)
        self.issue_tree.bind("<<TreeviewSelect>>", self.on_issue_select)

        issue_actions = tk.Frame(left)
        issue_actions.pack(fill="x", pady=(4, 0))
        self.attach_issue_btn = tk.Button(
            issue_actions, text="Attach issue to context", state="disabled", command=self.attach_issue_to_context
        )
        self.attach_issue_btn.pack(side="left")

        # Pipelines (right)
        pipeline_frame = tk.LabelFrame(right, text="Recent Pipelines", padx=4, pady=4)
        pipeline_frame.pack(fill="both", expand=True)

        self.pipeline_tree = ttk.Treeview(
            pipeline_frame,
            columns=("status", "ref", "id"),
            show="headings",
            selectmode="none",
            height=20,
        )
        self.pipeline_tree.heading("status", text="Status")
        self.pipeline_tree.heading("ref", text="Branch/Tag")
        self.pipeline_tree.heading("id", text="ID")
        self.pipeline_tree.column("status", width=90, stretch=False)
        self.pipeline_tree.column("ref", width=140, stretch=True)
        self.pipeline_tree.column("id", width=60, stretch=False)
        pipe_vsb = ttk.Scrollbar(pipeline_frame, orient="vertical", command=self.pipeline_tree.yview)
        self.pipeline_tree.configure(yscrollcommand=pipe_vsb.set)
        pipe_vsb.pack(side="right", fill="y")
        self.pipeline_tree.pack(fill="both", expand=True)

        for status, color in STATUS_COLORS.items():
            self.pipeline_tree.tag_configure(f"pipeline_{status}", foreground=color)

        # Initialise resource label from config
        self.refresh_resource_display()

    def load_project(self) -> None:
        path = self.project_var.get().strip()
        if not path:
            messagebox.showwarning("GitLab", "Enter a project path first.", parent=self.parent)
            return
        self.project_path = path
        self.project_id = path  # python-gitlab accepts path strings
        self.set_resource_btn.configure(state="normal")
        self.refresh_btn.configure(state="normal")
        self.refresh_data()

    def refresh_data(self) -> None:
        if self.project_id is None or self.loading:
            return
        self.loading = True
        self.status_var.set("Loading…")
        thread = threading.Thread(target=self.fetch_data, daemon=True)
        thread.start()

    def fetch_data(self) -> None:
        try:
            from tuochat.gitlab_client import GitLabMetaClient

            project_id = self.project_id
            if project_id is None:
                return
            client = GitLabMetaClient(
                host=self.cfg.gitlab.host,
                token=self.cfg.gitlab.token,
                token_type=self.cfg.gitlab.token_type,
                user_agent=getattr(self.cfg.gitlab, "user_agent", None),
            )
            mrs = client.list_mrs(project_id)
            issues = client.list_issues(project_id)
            pipelines = client.list_pipelines(project_id)
            self.mrs = mrs
            self.issues = issues
            self.pipelines = pipelines
            self.parent.after(0, self.populate_ui)
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.status_var.set(f"Error: {msg}"))
        finally:
            self.loading = False

    def populate_ui(self) -> None:
        self.populate_mrs()
        self.populate_issues()
        self.populate_pipelines()
        # total = len(self.mrs) + len(self.issues)
        pass_count = sum(1 for p in self.pipelines if p.get("status") in ("success", "passed"))
        fail_count = sum(1 for p in self.pipelines if p.get("status") == "failed")
        self.status_var.set(
            f"Loaded: {len(self.mrs)} open MRs, {len(self.issues)} open issues, "
            f"{len(self.pipelines)} recent pipelines "
            f"({pass_count} passed, {fail_count} failed)"
        )

    def populate_mrs(self) -> None:
        self.mr_tree.delete(*self.mr_tree.get_children())
        for mr in self.mrs:
            self.mr_tree.insert(
                "",
                "end",
                iid=str(mr["iid"]),
                values=(f"!{mr['iid']}", mr["title"], mr.get("source_branch", "")),
            )
        self.attach_mr_btn.configure(state="disabled")

    def populate_issues(self) -> None:
        self.issue_tree.delete(*self.issue_tree.get_children())
        for issue in self.issues:
            self.issue_tree.insert(
                "",
                "end",
                iid=str(issue["iid"]),
                values=(f"#{issue['iid']}", issue["title"]),
            )
        self.attach_issue_btn.configure(state="disabled")

    def populate_pipelines(self) -> None:
        self.pipeline_tree.delete(*self.pipeline_tree.get_children())
        for p in self.pipelines:
            status = p.get("status", "unknown")
            icon = STATUS_ICONS.get(status, "?")
            tag = pipeline_tag(status)
            self.pipeline_tree.insert(
                "",
                "end",
                values=(f"{icon} {status}", p.get("ref", ""), p.get("id", "")),
                tags=(tag,),
            )

    def on_mr_select(self, event=None) -> None:
        # pylint: disable=unused-argument
        sel = self.mr_tree.selection()
        self.attach_mr_btn.configure(state="normal" if sel else "disabled")

    def on_issue_select(self, event=None) -> None:
        # pylint: disable=unused-argument
        sel = self.issue_tree.selection()
        self.attach_issue_btn.configure(state="normal" if sel else "disabled")

    def set_project_as_resource(self) -> None:
        if self.project_id is None:
            return
        # Build GID — we need the numeric project id. If we only have path, look it up.
        resource_id = self.resolve_resource_id()
        if resource_id is None:
            messagebox.showwarning(
                "GitLab",
                "Could not resolve a resource GID. Try loading the project first.",
                parent=self.parent,
            )
            return
        if self.on_set_resource:
            self.on_set_resource(resource_id)
        self.refresh_resource_display(resource_id)

    def resolve_resource_id(self) -> str | None:
        """Try to find gid://gitlab/Project/<id> for the loaded project."""
        if self.project_id is None:
            return None
        try:
            from tuochat.gitlab_client import GitLabMetaClient

            client = GitLabMetaClient(
                host=self.cfg.gitlab.host,
                token=self.cfg.gitlab.token,
                token_type=self.cfg.gitlab.token_type,
                user_agent=getattr(self.cfg.gitlab, "user_agent", None),
            )
            descriptor = client.get_project_by_path(str(self.project_id))
            if descriptor:
                return descriptor.resource_id
        except Exception:
            pass
        # Fallback: if it's already a numeric id
        try:
            numeric = int(self.project_id)  # type: ignore[arg-type]
            return f"gid://gitlab/Project/{numeric}"
        except (ValueError, TypeError):
            return None

    def clear_resource(self) -> None:
        if self.on_set_resource:
            self.on_set_resource(None)
        self.refresh_resource_display(None)

    def refresh_resource_display(self, resource_id: str | None = None) -> None:
        if resource_id is None:
            resource_id = self.cfg.chat.default_resource_id
        if resource_id:
            self.resource_label.configure(text=resource_id, fg="#1d4ed8")
        else:
            self.resource_label.configure(text="(none)", fg="#6b7280")

    def attach_mr_to_context(self) -> None:
        sel = self.mr_tree.selection()
        if not sel or self.on_attach_context is None:
            return
        try:
            mr_iid = int(sel[0])
        except ValueError:
            return
        mr = next((m for m in self.mrs if m["iid"] == mr_iid), None)
        if mr is None:
            return
        label = f"MR !{mr['iid']}: {mr['title']}"
        body = (
            f"## Merge Request !{mr['iid']}: {mr['title']}\n\n"
            f"**Branch:** {mr.get('source_branch', '?')} → {mr.get('target_branch', '?')}\n"
            f"**State:** {mr.get('state', '?')}\n"
            f"**URL:** {mr.get('url', '')}\n\n"
            f"### Description\n\n{mr.get('description', '(none)')}"
        )
        self.on_attach_context(label, body)

    def attach_issue_to_context(self) -> None:
        sel = self.issue_tree.selection()
        if not sel or self.on_attach_context is None:
            return
        try:
            issue_iid = int(sel[0])
        except ValueError:
            return
        issue = next((i for i in self.issues if i["iid"] == issue_iid), None)
        if issue is None:
            return
        label = f"Issue #{issue['iid']}: {issue['title']}"
        body = (
            f"## Issue #{issue['iid']}: {issue['title']}\n\n"
            f"**State:** {issue.get('state', '?')}\n"
            f"**URL:** {issue.get('url', '')}\n\n"
            f"### Description\n\n{issue.get('description', '(none)')}"
        )
        self.on_attach_context(label, body)
