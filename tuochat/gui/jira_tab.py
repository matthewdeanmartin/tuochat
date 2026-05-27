"""Jira browse-and-attach tab for the GUI."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig
    from tuochat.jira_client import JiraMetaClient
    from tuochat.jira_models import JiraIssueDescriptor, JiraProjectDescriptor


class JiraTab:
    """Notebook tab for browsing Jira projects and issues and attaching them as context."""

    def __init__(
        self,
        parent: tk.Misc,
        cfg: TuochatConfig,
        *,
        on_attach_context: Callable[[str, str], None] | None = None,
    ) -> None:
        self.parent = parent
        self.cfg = cfg
        self.on_attach_context = on_attach_context

        self.client: JiraMetaClient | None = None
        self.projects: list[JiraProjectDescriptor] = []
        self.issues: list[JiraIssueDescriptor] = []
        self.loading = False
        self.selected_project_key: str | None = None

        self.build(parent)

    def build(self, parent: tk.Misc) -> None:
        outer = tk.Frame(parent)
        outer.pack(fill="both", expand=True)

        # Connection status bar
        conn_bar = tk.Frame(outer)
        conn_bar.pack(fill="x", padx=8, pady=(6, 2))

        self.connect_btn = tk.Button(conn_bar, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left")
        self.conn_status_var = tk.StringVar(master=parent, value="Not connected.")
        tk.Label(conn_bar, textvariable=self.conn_status_var, anchor="w", fg="#6b7280", padx=8).pack(
            side="left", fill="x", expand=True
        )

        # Config summary bar (host, deployment — never token)
        info_bar = tk.Frame(outer)
        info_bar.pack(fill="x", padx=8, pady=(0, 2))

        host = self.cfg.jira.host or "(not configured)"
        deployment = self.cfg.jira.deployment
        self.config_label = tk.Label(info_bar, text=f"Host: {host}  Deployment: {deployment}", anchor="w", fg="#6b7280")
        self.config_label.pack(side="left")

        # Filter / search bar for projects
        filter_bar = tk.Frame(outer)
        filter_bar.pack(fill="x", padx=8, pady=(4, 2))

        tk.Label(filter_bar, text="Filter projects:").pack(side="left")
        self.project_filter_var = tk.StringVar(master=parent)
        self.project_filter_var.trace_add("write", self.on_project_filter_change)
        self.project_filter_entry = tk.Entry(filter_bar, textvariable=self.project_filter_var, width=30)
        self.project_filter_entry.pack(side="left", padx=(4, 0))

        # Issue filter bar
        tk.Label(filter_bar, text="  Filter issues:").pack(side="left", padx=(16, 0))
        self.issue_filter_var = tk.StringVar(master=parent)
        self.issue_filter_var.trace_add("write", self.on_issue_filter_change)
        self.issue_filter_entry = tk.Entry(filter_bar, textvariable=self.issue_filter_var, width=30)
        self.issue_filter_entry.pack(side="left", padx=(4, 0))

        # Main paned area: projects left, issues right, preview below
        paned = tk.PanedWindow(outer, orient="horizontal", sashwidth=5, sashrelief="groove")
        paned.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        left = tk.Frame(paned)
        paned.add(left, minsize=260)

        right = tk.Frame(paned)
        paned.add(right, minsize=300)

        # Projects (left)
        proj_frame = tk.LabelFrame(left, text="Projects", padx=4, pady=4)
        proj_frame.pack(fill="both", expand=True, pady=(0, 4))

        self.project_tree = ttk.Treeview(
            proj_frame,
            columns=("key", "name"),
            show="headings",
            selectmode="browse",
            height=14,
        )
        self.project_tree.heading("key", text="Key")
        self.project_tree.heading("name", text="Name")
        self.project_tree.column("key", width=80, stretch=False)
        self.project_tree.column("name", width=200, stretch=True)
        proj_vsb = ttk.Scrollbar(proj_frame, orient="vertical", command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=proj_vsb.set)
        proj_vsb.pack(side="right", fill="y")
        self.project_tree.pack(fill="both", expand=True)
        self.project_tree.bind("<<TreeviewSelect>>", self.on_project_select)

        # Issues (right top)
        issue_frame = tk.LabelFrame(right, text="Issues", padx=4, pady=4)
        issue_frame.pack(fill="both", expand=True, pady=(0, 4))

        self.issue_tree = ttk.Treeview(
            issue_frame,
            columns=("key", "summary", "status", "type"),
            show="headings",
            selectmode="browse",
            height=10,
        )
        self.issue_tree.heading("key", text="Key")
        self.issue_tree.heading("summary", text="Summary")
        self.issue_tree.heading("status", text="Status")
        self.issue_tree.heading("type", text="Type")
        self.issue_tree.column("key", width=80, stretch=False)
        self.issue_tree.column("summary", width=260, stretch=True)
        self.issue_tree.column("status", width=90, stretch=False)
        self.issue_tree.column("type", width=80, stretch=False)
        issue_vsb = ttk.Scrollbar(issue_frame, orient="vertical", command=self.issue_tree.yview)
        self.issue_tree.configure(yscrollcommand=issue_vsb.set)
        issue_vsb.pack(side="right", fill="y")
        self.issue_tree.pack(fill="both", expand=True)
        self.issue_tree.bind("<<TreeviewSelect>>", self.on_issue_select)

        issue_actions = tk.Frame(right)
        issue_actions.pack(fill="x", pady=(0, 4))
        self.attach_btn = tk.Button(
            issue_actions, text="Attach issue to context", state="disabled", command=self.attach_issue_to_context
        )
        self.attach_btn.pack(side="left")

        # Preview pane (below issues)
        preview_frame = tk.LabelFrame(right, text="Preview", padx=4, pady=4)
        preview_frame.pack(fill="both", expand=True)

        self.preview_text = tk.Text(preview_frame, wrap="word", height=8, state="disabled")
        preview_vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_vsb.set)
        preview_vsb.pack(side="right", fill="y")
        self.preview_text.pack(fill="both", expand=True)

        # Bottom status bar
        self.status_var = tk.StringVar(master=parent, value="Click Connect to authenticate with Jira.")
        tk.Label(outer, textvariable=self.status_var, anchor="w", fg="#6b7280", padx=8).pack(fill="x", pady=(2, 4))

    # -----------------------------------------------------------------------
    # Connection

    def connect(self) -> None:
        """Build the Jira client and validate credentials in a background thread."""
        if self.loading:
            return
        cfg = self.cfg

        if not cfg.jira.host or not cfg.jira.token:
            messagebox.showwarning(
                "Jira",
                "Jira is not configured.\n\nAdd [jira] host / token to your config.toml\nor set TUOCHAT_JIRA_HOST and TUOCHAT_JIRA_TOKEN.",
                parent=self.parent,
            )
            return

        self.loading = True
        self.connect_btn.configure(state="disabled")
        self.conn_status_var.set("Connecting…")
        self.status_var.set("Authenticating with Jira…")

        threading.Thread(target=self.do_connect, daemon=True).start()

    def do_connect(self) -> None:
        try:
            from tuochat.jira_client import JiraMetaClient  # noqa: PLC0415

            client = JiraMetaClient(
                host=self.cfg.jira.host,
                deployment=self.cfg.jira.deployment,
                email=self.cfg.jira.email,
                token=self.cfg.jira.token,
                ssl_ca_cert=self.cfg.jira.ssl_ca_cert,
            )
            display_name = client.validate_auth()
            self.client = client
            self.parent.after(0, lambda: self.on_connected(display_name))
        except ImportError as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.on_connect_error(msg, install_hint=True))
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.on_connect_error(msg))
        finally:
            self.loading = False

    def on_connected(self, display_name: str) -> None:
        self.conn_status_var.set(f"Connected as: {display_name}")
        self.connect_btn.configure(state="normal", text="Reconnect")
        self.status_var.set("Authenticated. Loading projects…")
        self.fetch_projects()

    def on_connect_error(self, msg: str, *, install_hint: bool = False) -> None:
        self.connect_btn.configure(state="normal")
        host = self.cfg.jira.host or "(unknown)"
        deployment = self.cfg.jira.deployment
        self.conn_status_var.set("Connection failed.")
        detail = msg
        if install_hint:
            detail = f"{msg}\n\nInstall with:  uv sync --extra jira"
        self.status_var.set(f"Error: {msg}  (host={host} deployment={deployment})")
        messagebox.showerror("Jira connection failed", detail, parent=self.parent)

    # -----------------------------------------------------------------------
    # Project loading

    def fetch_projects(self) -> None:
        if self.client is None:
            return
        self.loading = True
        threading.Thread(target=self.do_fetch_projects, daemon=True).start()

    def do_fetch_projects(self) -> None:
        try:
            client = self.client
            if client is None:
                return
            projects = client.list_projects()
            self.projects = projects
            self.parent.after(0, self.populate_projects)
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.status_var.set(f"Failed to load projects: {msg}"))
        finally:
            self.loading = False

    def populate_projects(self) -> None:
        self.repopulate_project_tree(self.project_filter_var.get())
        count = len(self.projects)
        self.status_var.set(f"Loaded {count} project{'s' if count != 1 else ''}.")

    def repopulate_project_tree(self, query: str) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        q = query.strip().lower()
        for proj in self.projects:
            if q and q not in proj.key.lower() and q not in proj.name.lower():
                continue
            self.project_tree.insert("", "end", iid=proj.key, values=(proj.key, proj.name))

    def on_project_filter_change(self, *args) -> None:
        # pylint: disable=unused-argument
        self.repopulate_project_tree(self.project_filter_var.get())

    def on_project_select(self, event=None) -> None:
        # pylint: disable=unused-argument
        sel = self.project_tree.selection()
        if not sel:
            return
        project_key = sel[0]
        if project_key == self.selected_project_key:
            return
        self.selected_project_key = project_key
        self.issues = []
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.attach_btn.configure(state="disabled")
        self.clear_preview()
        self.fetch_issues(project_key)

    # -----------------------------------------------------------------------
    # Issue loading

    def fetch_issues(self, project_key: str) -> None:
        if self.client is None:
            return
        self.loading = True
        self.status_var.set(f"Loading issues for {project_key}…")
        threading.Thread(target=self.do_fetch_issues, args=(project_key,), daemon=True).start()

    def do_fetch_issues(self, project_key: str) -> None:
        try:
            client = self.client
            if client is None:
                return
            issues = client.list_issues(project_key)
            self.issues = issues
            self.parent.after(0, self.populate_issues)
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.status_var.set(f"Failed to load issues for {project_key}: {msg}"))
        finally:
            self.loading = False

    def populate_issues(self) -> None:
        self.repopulate_issue_tree(self.issue_filter_var.get())
        count = len(self.issues)
        project = self.selected_project_key or ""
        if count:
            self.status_var.set(f"Loaded {count} issue{'s' if count != 1 else ''} for {project}.")
        else:
            self.status_var.set(f"No issues found for {project}.")

    def repopulate_issue_tree(self, query: str) -> None:
        self.issue_tree.delete(*self.issue_tree.get_children())
        q = query.strip().lower()
        for issue in self.issues:
            if q and q not in issue.key.lower() and q not in issue.summary.lower() and q not in issue.status.lower():
                continue
            self.issue_tree.insert(
                "",
                "end",
                iid=issue.key,
                values=(issue.key, issue.summary, issue.status, issue.issue_type),
            )
        self.attach_btn.configure(state="disabled")

    def on_issue_filter_change(self, *args) -> None:
        # pylint: disable=unused-argument
        self.repopulate_issue_tree(self.issue_filter_var.get())

    def on_issue_select(self, event=None) -> None:
        # pylint: disable=unused-argument
        sel = self.issue_tree.selection()
        if not sel:
            self.attach_btn.configure(state="disabled")
            return
        self.attach_btn.configure(state="normal")
        issue_key = sel[0]
        self.load_issue_preview(issue_key)

    # -----------------------------------------------------------------------
    # Preview

    def clear_preview(self) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.configure(state="disabled")

    def load_issue_preview(self, issue_key: str) -> None:
        """Fetch full issue detail in background and populate the preview pane."""
        if self.client is None:
            return
        self.set_preview(f"Loading {issue_key}…")
        threading.Thread(target=self.do_load_preview, args=(issue_key,), daemon=True).start()

    def do_load_preview(self, issue_key: str) -> None:
        try:
            client = self.client
            if client is None:
                return
            from tuochat.jira_formatting import format_issue_attachment  # noqa: PLC0415

            detail = client.get_issue(issue_key)
            text = format_issue_attachment(detail)
            self.parent.after(0, lambda: self.set_preview(text))
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.set_preview(f"Failed to load {issue_key}: {msg}"))

    def set_preview(self, text: str) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Attach

    def attach_issue_to_context(self) -> None:
        """Fetch full issue detail and hand it to the attach callback."""
        sel = self.issue_tree.selection()
        if not sel or self.on_attach_context is None or self.client is None:
            return
        issue_key = sel[0]
        self.attach_btn.configure(state="disabled")
        self.status_var.set(f"Fetching {issue_key} for attachment…")
        threading.Thread(target=self.do_attach, args=(issue_key,), daemon=True).start()

    def do_attach(self, issue_key: str) -> None:
        try:
            client = self.client
            if client is None:
                return
            from tuochat.jira_formatting import attachment_name, format_issue_attachment  # noqa: PLC0415

            detail = client.get_issue(issue_key)
            content = format_issue_attachment(detail)
            name = attachment_name(detail.key, detail.summary)
            self.parent.after(0, lambda: self.finish_attach(name, content))
        except Exception as exc:
            msg = str(exc)
            self.parent.after(0, lambda: self.on_attach_error(issue_key, msg))

    def finish_attach(self, name: str, content: str) -> None:
        if self.on_attach_context:
            self.on_attach_context(name, content)
        self.attach_btn.configure(state="normal")
        self.status_var.set(f"Queued: {name}")

    def on_attach_error(self, issue_key: str, msg: str) -> None:
        self.attach_btn.configure(state="normal")
        self.status_var.set(f"Failed to attach {issue_key}: {msg}")
        messagebox.showerror("Jira attach failed", msg, parent=self.parent)
