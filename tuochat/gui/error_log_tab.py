"""Error log tab: displays WARNING/ERROR log entries captured to SQLite.

Shows a Treeview of recent log entries with delete and clear-all buttons.
Double-clicking a row opens a detail dialog with the full message, exception
type/value, traceback, source location, and timestamp.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

COLOR_WARNING = "#b45309"  # amber
COLOR_ERROR = "#dc2626"  # red
COLOR_CRITICAL = "#7c3aed"  # purple
COLOR_DEFAULT = "#374151"  # dark gray


def level_color(level: int) -> str:
    if level >= logging.CRITICAL:
        return COLOR_CRITICAL
    if level >= logging.ERROR:
        return COLOR_ERROR
    if level >= logging.WARNING:
        return COLOR_WARNING
    return COLOR_DEFAULT


def short_ts(recorded_at: str) -> str:
    """Trim ISO timestamp to HH:MM:SS on same day, else MM-DD HH:MM."""
    if len(recorded_at) >= 19:
        return recorded_at[11:19]
    return recorded_at


class ErrorDetailDialog(simpledialog.Dialog):
    """Non-modal detail window for one error log entry."""

    def __init__(self, parent: tk.Misc, entry: dict) -> None:
        self.entry = entry
        super().__init__(parent, title="Error Detail")

    def body(self, master: tk.Misc) -> tk.Widget:
        outer = tk.Frame(master)
        outer.pack(fill="both", expand=True, padx=10, pady=8)

        def row(label: str, value: str | None, *, monospace: bool = False) -> None:
            if not value:
                return
            tk.Label(outer, text=label + ":", font=("TkDefaultFont", 9, "bold"), anchor="w").pack(fill="x")
            font = ("TkFixedFont", 9) if monospace else ("TkDefaultFont", 9)
            txt = tk.Text(outer, wrap="word", height=3, font=font, relief="flat", bg=master["bg"])
            txt.insert("end", value)
            txt.configure(state="disabled")
            txt.pack(fill="x", pady=(0, 6))

        e = self.entry
        row("Timestamp", e.get("recorded_at"))
        row("Level", e.get("level_name"))
        row("Logger", e.get("logger_name"))
        row("Source", f"{e.get('filename', '')}:{e.get('lineno', '')}  {e.get('func_name', '')}")
        row("Message", e.get("message"), monospace=True)

        if e.get("exc_type") or e.get("exc_value"):
            row("Exception", f"{e.get('exc_type', '')}: {e.get('exc_value', '')}", monospace=True)

        if e.get("exc_traceback"):
            tk.Label(outer, text="Traceback:", font=("TkDefaultFont", 9, "bold"), anchor="w").pack(fill="x")
            tb_frame = tk.Frame(outer)
            tb_frame.pack(fill="both", expand=True)
            tb_scroll = tk.Scrollbar(tb_frame, orient="vertical")
            tb_text = tk.Text(
                tb_frame,
                wrap="none",
                height=10,
                font=("TkFixedFont", 8),
                yscrollcommand=tb_scroll.set,
            )
            tb_scroll.configure(command=tb_text.yview)
            tb_scroll.pack(side="right", fill="y")
            tb_text.pack(side="left", fill="both", expand=True)
            tb_text.insert("end", e.get("exc_traceback", ""))
            tb_text.configure(state="disabled")

        return outer

    def buttonbox(self) -> None:
        box = tk.Frame(self)
        tk.Button(box, text="Close", width=10, command=self.ok, default="active").pack(padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.ok)
        box.pack()


class ErrorLogTabView:
    """Treeview-based error log tab."""

    COLUMNS = ("ts", "level", "logger", "message")
    COLUMN_HEADERS = ("Time", "Level", "Logger", "Message")
    COLUMN_WIDTHS = (80, 70, 160, 400)

    def __init__(self, parent: tk.Misc, store: Any) -> None:
        self.parent = parent
        self.store = store
        self.entries: list[dict] = []
        self.min_level = logging.WARNING
        self.build_ui()

    def build_ui(self) -> None:
        outer = tk.Frame(self.parent)
        outer.pack(fill="both", expand=True)

        # Toolbar
        toolbar = tk.Frame(outer)
        toolbar.pack(fill="x", padx=6, pady=4)

        tk.Label(toolbar, text="Min level:").pack(side="left")
        self.level_var = tk.StringVar(value="WARNING")
        level_menu = ttk.Combobox(
            toolbar,
            textvariable=self.level_var,
            values=["WARNING", "ERROR", "CRITICAL"],
            state="readonly",
            width=10,
        )
        level_menu.pack(side="left", padx=(4, 12))
        level_menu.bind("<<ComboboxSelected>>", self.on_level_change)

        tk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="left", padx=2)
        tk.Button(toolbar, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=2)
        tk.Button(toolbar, text="Clear All", command=self.clear_all).pack(side="left", padx=2)

        self.count_var = tk.StringVar(value="")
        tk.Label(toolbar, textvariable=self.count_var, fg=COLOR_DEFAULT).pack(side="right", padx=4)

        # Treeview with scrollbars
        tree_frame = tk.Frame(outer)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        yscroll = tk.Scrollbar(tree_frame, orient="vertical")
        xscroll = tk.Scrollbar(tree_frame, orient="horizontal")

        self.tree = ttk.Treeview(
            tree_frame,
            columns=self.COLUMNS,
            show="headings",
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
            selectmode="browse",
        )
        yscroll.configure(command=self.tree.yview)
        xscroll.configure(command=self.tree.xview)

        for col, header, width in zip(self.COLUMNS, self.COLUMN_HEADERS, self.COLUMN_WIDTHS):
            self.tree.heading(col, text=header)
            self.tree.column(col, width=width, minwidth=40, stretch=col == "message")

        # Tag colors for severity
        self.tree.tag_configure("WARNING", foreground=COLOR_WARNING)
        self.tree.tag_configure("ERROR", foreground=COLOR_ERROR)
        self.tree.tag_configure("CRITICAL", foreground=COLOR_CRITICAL)

        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Return>", self.on_double_click)

    def on_level_change(self, _event: object = None) -> None:
        name = self.level_var.get()
        self.min_level = getattr(logging, name, logging.WARNING)
        self.refresh()

    def refresh(self) -> None:
        entries = self.store.get_error_log_entries(limit=500, min_level=self.min_level)
        self.entries = entries

        self.tree.delete(*self.tree.get_children())
        for entry in entries:
            level_name = entry.get("level_name", "")
            short_msg = (entry.get("message") or "")[:200].replace("\n", " ")
            iid = str(entry["id"])
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    short_ts(entry.get("recorded_at", "")),
                    level_name,
                    entry.get("logger_name", ""),
                    short_msg,
                ),
                tags=(level_name,),
            )

        count = len(entries)
        self.count_var.set(f"{count} entr{'y' if count == 1 else 'ies'}")

    def on_double_click(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        iid = selected[0]
        entry = next((e for e in self.entries if str(e["id"]) == iid), None)
        if entry is None:
            return
        ErrorDetailDialog(self.parent, entry)

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        iid = selected[0]
        try:
            entry_id = int(iid)
        except ValueError:
            return
        self.store.delete_error_log_entry(entry_id)
        self.refresh()

    def clear_all(self) -> None:
        if not messagebox.askyesno(
            "Clear error log",
            "Delete all error log entries? This cannot be undone.",
            icon="warning",
        ):
            return
        self.store.clear_error_log()
        self.refresh()


def build_error_log_tab(parent: tk.Misc, store: Any) -> ErrorLogTabView:
    """Build and return an ErrorLogTabView, refreshed immediately."""
    view = ErrorLogTabView(parent, store)
    view.refresh()
    return view
