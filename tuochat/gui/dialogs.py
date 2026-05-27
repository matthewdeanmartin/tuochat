"""Tk dialog classes and small widget helpers for the tuochat GUI."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, simpledialog

from tuochat.cli.setup import get_valid_classifications
from tuochat.config import TuochatConfig
from tuochat.gui.rendering import classification_dialog_text


@dataclass
class PromptRequest:
    """A prompt request marshalled back to the Tk main thread."""

    prompt: str
    secret: bool = False
    ready: threading.Event = field(default_factory=threading.Event)
    response: str = ""


class DialogCancelledError(Exception):
    """Raised when the user cancels a blocking GUI dialog."""


class ToolTip:
    """Very small hover tooltip for compact Tk controls."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show_tip, add="+")
        widget.bind("<Leave>", self.hide_tip, add="+")
        widget.bind("<ButtonPress>", self.hide_tip, add="+")

    def show_tip(self, event=None) -> None:
        # pylint: disable=unused-argument
        if self.tip_window is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip_window = tk.Toplevel(self.widget)
        tip_window.wm_overrideredirect(True)
        tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tip_window,
            text=self.text,
            justify="left",
            relief="solid",
            borderwidth=1,
            background="#ffffe0",
            padx=6,
            pady=3,
        )
        label.pack()
        self.tip_window = tip_window

    def hide_tip(self, event=None) -> None:
        # pylint: disable=unused-argument
        if self.tip_window is None:
            return
        self.tip_window.destroy()
        self.tip_window = None


class ClassificationDialog(simpledialog.Dialog):
    """Modal classification chooser that mirrors the CLI options list."""

    def __init__(
        self,
        parent: tk.Misc,
        cfg: TuochatConfig,
        *,
        current: str | None = None,
        upcoming: bool = False,
    ) -> None:
        self.cfg = cfg
        self.current = current
        self.upcoming = upcoming
        self.response = ""
        self.options = get_valid_classifications(cfg)
        self.entry: tk.Entry | None = None
        self.result: str | None = None
        super().__init__(parent, title="Choose classification")

    def body(self, master: tk.Misc):
        instructions = tk.Label(
            master,
            justify="left",
            anchor="w",
            text=classification_dialog_text(self.cfg, current=self.current, upcoming=self.upcoming),
        )
        instructions.pack(fill="x", padx=10, pady=(10, 6))

        self.entry = tk.Entry(master, width=48)
        self.entry.pack(fill="x", padx=10, pady=(0, 10))
        return self.entry

    def buttonbox(self) -> None:
        box = tk.Frame(self)
        confirm_button = tk.Button(box, text="OK", width=10, command=self.ok, default="active")
        confirm_button.pack(side="left", padx=5, pady=5)
        cancel_button = tk.Button(box, text="Cancel", width=10, command=self.cancel)
        cancel_button.pack(side="left", padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self) -> None:
        if self.entry is None:
            raise TypeError("self.entry is None and can't be.")
        self.response = self.entry.get().strip()
        self.result = self.response


class AttachmentSummaryDialog(simpledialog.Dialog):
    """Modal summary of the files queued by the GUI file picker."""

    def __init__(self, parent: tk.Misc, body_text: str) -> None:
        self.body_text = body_text
        super().__init__(parent, title="Attached files")

    def body(self, master: tk.Misc):
        instructions = tk.Label(master, justify="left", anchor="w", text=self.body_text)
        instructions.pack(fill="x", padx=10, pady=(10, 10))
        return instructions

    def buttonbox(self) -> None:
        box = tk.Frame(self)
        confirm_button = tk.Button(box, text="OK", width=10, command=self.ok, default="active")
        confirm_button.pack(side="left", padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()


class FontPickerDialog(simpledialog.Dialog):
    """Scrollable font family picker showing all fonts available on this system.

    result is set to the chosen family string (empty string = use default),
    or None if the user cancelled.
    """

    def __init__(self, parent: tk.Misc, *, current_family: str = "") -> None:
        self.current_family = current_family
        self.result: str | None = None
        self.filter_var: tk.StringVar | None = None
        self.listbox: tk.Listbox | None = None
        self.all_families: list[str] = []
        super().__init__(parent, title="Choose Font Family")

    def body(self, master: tk.Misc):
        raw_families = sorted(tkfont.families(), key=str.casefold)
        self.all_families = raw_families

        tk.Label(master, text="Filter:", anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self.filter_var = tk.StringVar()
        filter_entry = tk.Entry(master, textvariable=self.filter_var, width=40)
        filter_entry.pack(fill="x", padx=10, pady=(0, 4))
        self.filter_var.trace_add("write", self.on_filter_change)

        list_frame = tk.Frame(master)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, width=44, height=14, exportselection=False)
        scrollbar.configure(command=self.listbox.yview)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.listbox.bind("<Double-1>", self.ok)

        self.populate_listbox(self.all_families)

        # Preselect current family
        if self.current_family:
            lower_families = [f.casefold() for f in self.all_families]
            try:
                idx = lower_families.index(self.current_family.casefold())
                self.listbox.selection_set(idx)
                self.listbox.see(idx)
            except ValueError:
                pass

        # "Other / type manually" entry at the bottom
        tk.Label(master, text="Or type a family name manually:", anchor="w").pack(fill="x", padx=10, pady=(4, 2))
        self.manual_var = tk.StringVar(value=self.current_family)
        manual_entry = tk.Entry(master, textvariable=self.manual_var, width=40)
        manual_entry.pack(fill="x", padx=10, pady=(0, 8))

        # Sync listbox selection -> manual entry
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        return filter_entry

    def populate_listbox(self, families: list[str]) -> None:
        if self.listbox is None:
            return
        self.listbox.delete(0, "end")
        self.listbox.insert("end", "(default monospace)")
        for family in families:
            self.listbox.insert("end", family)

    def on_filter_change(self, *args) -> None:  # pylint: disable=unused-argument
        if self.filter_var is None:
            return
        query = self.filter_var.get().casefold()
        filtered = [f for f in self.all_families if query in f.casefold()] if query else self.all_families
        self.populate_listbox(filtered)

    def on_listbox_select(self, _event=None) -> None:
        if self.listbox is None:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        value = self.listbox.get(selection[0])
        if value == "(default monospace)":
            self.manual_var.set("")
        else:
            self.manual_var.set(value)

    def apply(self) -> None:
        chosen = self.manual_var.get().strip()
        self.result = chosen  # empty string = use default monospace


def prompt_for_template_code_path(parent: tk.Misc | None, *, initialdir: Path | None = None) -> str:
    """Open a file picker for the ATTACHED_CODE template token."""
    selected = filedialog.askopenfilename(
        parent=parent,
        title="Select code file for template",
        initialdir=str(initialdir or Path.cwd()),
    )
    if not selected:
        return ""
    return str(Path(selected).expanduser())
