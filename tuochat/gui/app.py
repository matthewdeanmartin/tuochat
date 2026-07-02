"""Minimal Tkinter chat window built on the existing CLI/session flow."""

from __future__ import annotations

import io
import logging
import os
import queue
import re
import threading
import tkinter as tk
import traceback
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Literal

from tuochat.cli.io import NullTextIO, prompt_handler, redirect_standard_io
from tuochat.cli.models import ReplState
from tuochat.cli.rendering import humanize_report_key, print_masked_conversation_transcript, print_system_prompt_sources
from tuochat.cli.repl import (
    delete_path,
    maybe_prune_expired_conversations,
    nuke_targets,
    print_expiration_warning,
    print_session_intro,
    process_repl_submission,
)
from tuochat.cli.session import (
    apply_git_repo_write_here_default,
    approve_writes_enabled,
    build_provider,
    build_store,
    no_write_enabled,
    open_path,
    print_chat_summary,
    print_saved_conversation_files,
    reset_repl_state,
    switch_to_conversation,
    sync_conversation_artifacts,
    toggle_approve_writes,
    toggle_no_write,
    toggle_write_here_mode,
    update_saved_conversation_artifacts,
    write_here_mode_enabled,
)
from tuochat.cli.setup import maybe_run_first_run_setup, prompt_classification
from tuochat.config import GUI_THEMES, GUI_TTK_THEMES, TuochatConfig, save_config
from tuochat.constants import MODEL_LABELS, classification_help_label
from tuochat.context.attachments import (
    clear_pending_attachments,
    list_include_candidates_under,
    prepare_include,
    queue_attachment,
    read_include_file,
)
from tuochat.context.composer import (
    ATTACHED_CODE_PROMPT,
    compose_system_prompt,
    load_custom_instruction_sections,
    strip_agents_instructions_prefix,
    system_prompt_includes_agents_instructions,
)
from tuochat.discovery.agent_prompts import (
    auto_select_agent_prompt,
    describe_agent_prompt_path,
    list_available_agent_prompts,
    load_agent_prompt_content,
)
from tuochat.discovery.custom_instructions import describe_custom_instruction_path, list_available_custom_instructions
from tuochat.discovery.skills import describe_skill_path, list_available_skills, render_skill_message
from tuochat.discovery.templates import (
    describe_template_path,
    list_available_templates,
    render_template_prompt_from_path,
)
from tuochat.gui.dialogs import (
    AttachmentSummaryDialog,
    ClassificationDialog,
    DialogCancelledError,
    FontPickerDialog,
    PromptRequest,
    ToolTip,
    prompt_for_template_code_path,
)
from tuochat.gui.rendering import (
    MIT_LICENSE_TEXT,
    about_dialog_text,
    attached_files_dialog_text,
    attachment_speedbar_labels,
    configured_gui_model,
    confirm_nuke,
    conversation_menu_label,
    default_export_filename,
    format_info_line,
    format_sandbox_runtime_summary,
    format_writing_directory_line,
    humanize_date,
    is_attached_code_prompt,
    is_classification_prompt,
    keyboard_shortcuts_text,
    next_model_key,
    next_model_toggle_label,
    render_attached_files_text,
    render_context_text,
    render_conversation_markdown,
    render_help_text,
    render_weekly_usage_text,
    render_wire_transcript_text,
    response_warning_text,
    submit_shortcut_sequences,
    theme_colors,
    window_title_text,
)
from tuochat.gui.streams import MultiTextIO, TranscriptStream
from tuochat.models import Conversation
from tuochat.persistence.archive import check_archive_bagit_status, conversation_archive_dir
from tuochat.provider.duo import DuoProvider
from tuochat.sandbox.api import code_interpreter_runtime_details
from tuochat.self_pkg_mgmt import api as spm_api
from tuochat.self_pkg_mgmt.host import default_host as spm_default_host


class TkChatApp:
    """Small queue-backed Tkinter shell for the existing REPL logic."""

    def __init__(self, state: ReplState, store: Any) -> None:
        self.state = state
        self.store = store
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.prompt_queue: queue.Queue[PromptRequest] = queue.Queue()
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stream = TranscriptStream(self.output_queue)
        self.busy = False
        self.close_when_idle = False
        self.finalized = False
        self.last_search_query: str | None = None
        self.last_help_command: str = "/help"
        self.custom_menu_paths: list[Path] = []
        self.skill_menu_paths: list[Path] = []
        self.template_menu_paths: list[Path] = []
        self.input_history: list[str] = []
        self.input_history_index: int = -1
        self.input_history_draft: str = ""
        self.conversations_tree: ttk.Treeview | None = None
        self.archived_tree: ttk.Treeview | None = None
        self.search_tree: ttk.Treeview | None = None

        self.root = tk.Tk()
        self.root.title(window_title_text(self.state.conv.title))
        self.root.geometry("900x700")
        self.root.minsize(640, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.request_quit)

        self.model_var = tk.StringVar(master=self.root, value=self.state.active_model)
        self.build_menu_bar()
        self.build_tabbed_views()

        self.info_var = tk.StringVar(master=self.root)
        self.warning_var = tk.StringVar(master=self.root)
        self.writing_directory_var = tk.StringVar(master=self.root)
        self.model_toggle_var = tk.StringVar(master=self.root)
        self.build_info_panel()

        controls = tk.Frame(self.root)
        self.controls = controls
        # Packed later in pack_main_layout() so the notebook gets what's left.

        self.send_button = tk.Button(controls, text="Send", underline=0, command=self.submit_current_text)
        self.send_button.pack(side="left")
        self.primary_separator = ttk.Separator(controls, orient="vertical")
        self.primary_separator.pack(side="left", fill="y", padx=8, pady=2)

        self.approve_writes_var = tk.BooleanVar(master=self.root, value=approve_writes_enabled(self.state.cfg))
        self.write_here_var = tk.BooleanVar(master=self.root, value=write_here_mode_enabled(self.state.cfg))
        self.streaming_var = tk.BooleanVar(master=self.root, value=self.state.streaming)
        self.mask_output_var = tk.BooleanVar(master=self.root, value=self.state.mask_output)
        self.verbose_var = tk.BooleanVar(master=self.root, value=self.state.verbose)
        self.no_write_var = tk.BooleanVar(master=self.root, value=no_write_enabled(self.state.cfg))
        self.include_agents_var = tk.BooleanVar(master=self.root, value=self.state.include_agents_file)
        self.code_interpreter_var = tk.BooleanVar(master=self.root, value=self.state.code_interpreter_enabled)
        (
            attach_group_label,
            attach_files_text,
            attach_folder_text,
            attach_skills_text,
            attach_initial_instr_text,
            attach_template_text,
            attach_changed_text,
            detach_all_text,
            include_all_text,
        ) = attachment_speedbar_labels()

        self.attach_group_label = tk.Label(controls, text=attach_group_label)
        self.attach_group_label.pack(side="left")
        self.attach_files_button = tk.Button(controls, text=attach_files_text, command=self.attach_files_from_dialog)
        self.attach_files_button.pack(side="left", padx=(4, 0))
        self.attach_folder_button = tk.Button(controls, text=attach_folder_text, command=self.attach_folder_from_dialog)
        self.attach_folder_button.pack(side="left", padx=(4, 0))
        self.attach_skill_button = tk.Menubutton(controls, text=attach_skills_text, relief="raised")
        self.attach_skill_menu = tk.Menu(
            self.attach_skill_button, tearoff=False, postcommand=self.refresh_attach_skill_menu
        )
        self.attach_skill_button.configure(menu=self.attach_skill_menu)
        self.attach_skill_button.pack(side="left", padx=(4, 0))
        self.attach_custom_button = tk.Menubutton(controls, text=attach_initial_instr_text, relief="raised")
        self.attach_custom_menu = tk.Menu(
            self.attach_custom_button,
            tearoff=False,
            postcommand=self.refresh_attach_custom_menu,
        )
        self.attach_custom_button.configure(menu=self.attach_custom_menu)
        self.attach_custom_button.pack(side="left", padx=(4, 0))
        self.attach_template_button = tk.Menubutton(controls, text=attach_template_text, relief="raised")
        self.attach_template_menu = tk.Menu(
            self.attach_template_button,
            tearoff=False,
            postcommand=self.refresh_attach_template_menu,
        )
        self.attach_template_button.configure(menu=self.attach_template_menu)
        self.attach_template_button.pack(side="left", padx=(4, 0))
        self.reinclude_changed_button = tk.Button(
            controls, text=attach_changed_text, command=self.reinclude_changed_file
        )
        self.reinclude_changed_button.pack(side="left", padx=(4, 0))
        self.attach_group_separator = ttk.Separator(controls, orient="vertical")
        self.attach_group_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.detach_all_button = tk.Button(controls, text=detach_all_text, command=self.detach_all_attachments)
        self.detach_all_button.pack(side="left")
        self.agent_prompt_menu = tk.Menu(self.root, tearoff=False, postcommand=self.refresh_agent_prompt_menu)
        self.include_agents_button = tk.Menubutton(
            controls,
            text=include_all_text,
            relief="raised",
            menu=self.agent_prompt_menu,
        )
        self.include_agents_button.pack(side="left", padx=(4, 0))
        self.file_actions_separator = ttk.Separator(controls, orient="vertical")
        self.file_actions_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.clear_button = tk.Button(controls, text="Clear", command=self.confirm_and_start_new_conversation)
        self.clear_button.pack(side="left")
        self.secondary_separator = ttk.Separator(controls, orient="vertical")
        self.secondary_separator.pack(side="left", fill="y", padx=8, pady=2)

        self.streaming_button = tk.Checkbutton(
            controls,
            text="Stream",
            indicatoron=False,
            variable=self.streaming_var,
            command=self.toggle_streaming_button,
        )
        self.streaming_button.pack(side="left", padx=(0, 0))
        self.mask_button = tk.Checkbutton(
            controls,
            text="Mask",
            indicatoron=False,
            variable=self.mask_output_var,
            command=self.toggle_mask_button,
        )
        self.mask_button.pack(side="left", padx=(4, 0))
        self.verbose_button = tk.Checkbutton(
            controls,
            text="Verbose",
            indicatoron=False,
            variable=self.verbose_var,
            command=self.toggle_verbose_button,
        )
        self.verbose_button.pack(side="left", padx=(4, 0))
        self.write_group_separator = ttk.Separator(controls, orient="vertical")
        self.write_group_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.approve_writes_button = tk.Checkbutton(
            controls,
            text="Approve writes",
            indicatoron=False,
            variable=self.approve_writes_var,
            command=self.toggle_approve_writes_button,
        )
        self.approve_writes_button.pack(side="left", padx=(0, 0))
        self.write_here_button = tk.Checkbutton(
            controls,
            text="Write here",
            indicatoron=False,
            variable=self.write_here_var,
            command=self.toggle_write_here_button,
        )
        self.write_here_button.pack(side="left", padx=(4, 0))
        self.no_write_button = tk.Checkbutton(
            controls,
            text="Plan/No Writes",
            indicatoron=False,
            variable=self.no_write_var,
            command=self.toggle_no_write_button,
        )
        self.no_write_button.pack(side="left", padx=(4, 0))
        self.code_interpreter_button = tk.Checkbutton(
            controls,
            text="Code Int",
            indicatoron=False,
            variable=self.code_interpreter_var,
            command=self.toggle_code_interpreter_button,
        )
        self.code_interpreter_button.pack(side="left", padx=(4, 0))
        self.model_group_separator = ttk.Separator(controls, orient="vertical")
        self.model_group_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.model_toggle_button = tk.Button(
            controls,
            textvariable=self.model_toggle_var,
            command=self.toggle_active_model_button,
        )
        self.model_toggle_button.pack(side="left", padx=(0, 4))
        self.action_buttons_separator = ttk.Separator(controls, orient="vertical")
        self.action_buttons_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.help_button = tk.Button(controls, text="Help", underline=0, command=self.show_help_tab)
        self.help_button.pack(side="left")
        self.status_button = tk.Button(
            controls,
            text="Status",
            underline=1,
            command=lambda: self.submit_command("/status"),
        )
        self.status_button.pack(side="left", padx=(4, 0))
        self.memory_separator = ttk.Separator(controls, orient="vertical")
        self.memory_separator.pack(side="left", fill="y", padx=8, pady=2)
        self.memory_button = tk.Button(
            controls,
            text="Memory",
            command=lambda: self.submit_command("/memory"),
        )
        self.memory_button.pack(side="left")
        self.compact_button = tk.Button(
            controls,
            text="Compact",
            command=lambda: self.submit_command("/compact"),
        )
        self.compact_button.pack(side="left", padx=(4, 0))
        self.todo_button = tk.Button(
            controls,
            text="Todo",
            command=lambda: self.submit_command("/todo"),
        )
        self.todo_button.pack(side="left", padx=(4, 0))
        self.quit_button = tk.Button(controls, text="Quit", underline=0, command=self.request_quit)
        self.quit_button.pack(side="right")

        self.input_box = tk.Text(self.root, height=8, wrap="word", undo=True)
        self.input_box.focus_set()

        self.pack_main_layout()

        for sequence in submit_shortcut_sequences():
            self.root.bind_all(sequence, self.submit_current_text)
        self.root.bind_all("<Alt-h>", lambda event: self.show_help_tab())  # pylint: disable=unused-argument
        self.root.bind_all("<Alt-H>", lambda event: self.show_help_tab())  # pylint: disable=unused-argument
        self.root.bind_all("<Alt-t>", lambda event: self.submit_command("/status"))  # pylint: disable=unused-argument
        self.root.bind_all("<Alt-T>", lambda event: self.submit_command("/status"))  # pylint: disable=unused-argument
        self.root.bind_all("<Alt-q>", self.request_quit)
        self.root.bind_all("<Alt-Q>", self.request_quit)
        self.input_box.bind("<Up>", self.history_prev)
        self.input_box.bind("<Down>", self.history_next)
        self.install_tooltips()
        self.apply_theme_and_font()
        self.refresh_info_panel()

    def build_tabbed_views(self) -> None:
        """Create the notebook and text views for chat and supporting tabs."""
        from tuochat.gui.context_browser import ContextBrowserTab

        self.notebook = ttk.Notebook(self.root)
        # Packed last in __init__ so fixed-height widgets below it get priority.

        self.chat_tab = ttk.Frame(self.notebook)
        self.files_tab = ttk.Frame(self.notebook)
        self.context_tab = ttk.Frame(self.notebook)
        self.context_browser_tab = ttk.Frame(self.notebook)
        self.conversations_tab = ttk.Frame(self.notebook)
        self.archived_tab = ttk.Frame(self.notebook)
        self.search_tab = ttk.Frame(self.notebook)
        self.help_tab = ttk.Frame(self.notebook)
        self.usage_tab = ttk.Frame(self.notebook)
        self.observability_tab = ttk.Frame(self.notebook)
        self.git_tab_frame = ttk.Frame(self.notebook)
        self.gitlab_tab_frame = ttk.Frame(self.notebook)
        self.jira_tab_frame = ttk.Frame(self.notebook)
        self.wire_transcript_tab = ttk.Frame(self.notebook)
        self.error_log_tab_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.chat_tab, text="Chat")
        self.notebook.add(self.files_tab, text="Files")
        self.notebook.add(self.context_tab, text="Effective Context")
        self.notebook.add(self.context_browser_tab, text="Context Browser")
        self.notebook.add(self.conversations_tab, text="Conversations")
        self.notebook.add(self.archived_tab, text="Archive")
        self.notebook.add(self.search_tab, text="Search")
        self.notebook.add(self.help_tab, text="Help")
        self.notebook.add(self.usage_tab, text="Usage")
        self.notebook.add(self.observability_tab, text="Observability")
        self.notebook.add(self.git_tab_frame, text="Git")
        self.notebook.add(self.gitlab_tab_frame, text="GitLab")
        self.notebook.add(self.jira_tab_frame, text="Jira")
        self.notebook.add(self.wire_transcript_tab, text="Transcript")
        self.notebook.add(self.error_log_tab_frame, text="Errors")

        self.transcript = self.build_tab_text_box(self.chat_tab, state="disabled")
        files_btn_frame = tk.Frame(self.files_tab)
        files_btn_frame.pack(fill="x", padx=4, pady=4)
        tk.Button(files_btn_frame, text="Remove Attachment...", command=self.remove_pending_attachment_dialog).pack(
            side="left", padx=2
        )
        self.files_view = self.build_tab_text_box(self.files_tab)
        self.context_view = self.build_tab_text_box(self.context_tab)
        self.build_conversations_tab_widgets()
        self.build_archived_tab_widgets()
        self.build_search_tab_widgets()
        self.help_view = self.build_tab_text_box(self.help_tab)
        self.usage_view = self.build_tab_text_box(self.usage_tab)
        self.wire_transcript_view = self.build_tab_text_box(self.wire_transcript_tab)

        self.context_browser = ContextBrowserTab(
            self.context_browser_tab,
            self.state,
            on_attach_next_request=self.browser_attach_next_request,
            on_attach_next_conversation=self.browser_attach_next_conversation,
            on_set_agent_prompt=self.browser_set_agent_prompt,
        )

        from tuochat.gui.observability_tab import build_observability_tab

        self.observability_tab_view = build_observability_tab(self.observability_tab, self.store)

        from tuochat.gui.error_log_tab import build_error_log_tab

        self.error_log_tab_view = build_error_log_tab(self.error_log_tab_frame, self.store)

        from tuochat.gui.git_tab import GitStatusTab

        self.git_status_tab = GitStatusTab(
            self.git_tab_frame,
            on_attach_context=self.repo_attach_context,
        )

        from tuochat.gui.gitlab_tab import GitLabTab

        self.gitlab_info_tab = GitLabTab(
            self.gitlab_tab_frame,
            self.state.cfg,
            on_set_resource=self.gitlab_set_resource,
            on_attach_context=self.repo_attach_context,
        )

        from tuochat.gui.jira_tab import JiraTab

        self.jira_info_tab = JiraTab(
            self.jira_tab_frame,
            self.state.cfg,
            on_attach_context=self.jira_attach_context,
        )

    def build_tab_text_box(self, parent: tk.Misc, *, state: Literal["normal", "disabled"] = "disabled") -> ScrolledText:
        """Create a read-only scrolled text view for a notebook tab."""
        text_box = ScrolledText(parent, wrap="word")
        text_box.pack(fill="both", expand=True)
        text_box.configure(state=state)
        return text_box

    def build_conversations_tab_widgets(self) -> None:
        """Build the Conversations tab with a Treeview list and action buttons."""
        btn_frame = tk.Frame(self.conversations_tab)
        btn_frame.pack(fill="x", padx=4, pady=4)
        tk.Button(btn_frame, text="Resume", command=self.conversations_resume_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Archive", command=self.conversations_archive_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Delete", command=self.conversations_delete_selected).pack(side="left", padx=2)

        columns = ("title", "updated", "bag", "folder", "id")
        self.conversations_tree = ttk.Treeview(
            self.conversations_tab,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.conversations_tree.heading("title", text="Title")
        self.conversations_tree.heading("updated", text="Updated")
        self.conversations_tree.heading("bag", text="Bag")
        self.conversations_tree.heading("folder", text="Folder")
        self.conversations_tree.heading("id", text="ID")
        self.conversations_tree.column("title", width=220, stretch=True)
        self.conversations_tree.column("updated", width=80, stretch=False)
        self.conversations_tree.column("bag", width=70, stretch=False)
        self.conversations_tree.column("folder", width=160, stretch=False)
        self.conversations_tree.column("id", width=90, stretch=False)
        scrollbar = ttk.Scrollbar(self.conversations_tab, orient="vertical", command=self.conversations_tree.yview)
        self.conversations_tree.configure(yscrollcommand=scrollbar.set)
        self.conversations_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.conversations_tree.bind("<Double-1>", lambda _e: self.conversations_resume_selected())

    def build_archived_tab_widgets(self) -> None:
        """Build the Archive tab with archived conversations and an Unarchive button."""
        btn_frame = tk.Frame(self.archived_tab)
        btn_frame.pack(fill="x", padx=4, pady=4)
        tk.Button(btn_frame, text="Resume", command=self.archived_resume_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Unarchive", command=self.archived_unarchive_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Delete", command=self.archived_delete_selected).pack(side="left", padx=2)

        columns = ("title", "updated", "bag", "folder", "id")
        self.archived_tree = ttk.Treeview(
            self.archived_tab,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.archived_tree.heading("title", text="Title")
        self.archived_tree.heading("updated", text="Updated")
        self.archived_tree.heading("bag", text="Bag")
        self.archived_tree.heading("folder", text="Folder")
        self.archived_tree.heading("id", text="ID")
        self.archived_tree.column("title", width=220, stretch=True)
        self.archived_tree.column("updated", width=80, stretch=False)
        self.archived_tree.column("bag", width=70, stretch=False)
        self.archived_tree.column("folder", width=160, stretch=False)
        self.archived_tree.column("id", width=90, stretch=False)
        scrollbar = ttk.Scrollbar(self.archived_tab, orient="vertical", command=self.archived_tree.yview)
        self.archived_tree.configure(yscrollcommand=scrollbar.set)
        self.archived_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.archived_tree.bind("<Double-1>", lambda _e: self.archived_resume_selected())

    def build_search_tab_widgets(self) -> None:
        """Build the Search tab with a Treeview list and action buttons."""
        btn_frame = tk.Frame(self.search_tab)
        btn_frame.pack(fill="x", padx=4, pady=4)
        tk.Button(btn_frame, text="Resume", command=self.search_resume_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Archive", command=self.search_archive_selected).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Delete", command=self.search_delete_selected).pack(side="left", padx=2)

        columns = ("title", "updated", "snippet", "id")
        self.search_tree = ttk.Treeview(
            self.search_tab,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.search_tree.heading("title", text="Title")
        self.search_tree.heading("updated", text="Updated")
        self.search_tree.heading("snippet", text="Snippet")
        self.search_tree.heading("id", text="ID")
        self.search_tree.column("title", width=200, stretch=False)
        self.search_tree.column("updated", width=80, stretch=False)
        self.search_tree.column("snippet", width=300, stretch=True)
        self.search_tree.column("id", width=90, stretch=False)
        scrollbar = ttk.Scrollbar(self.search_tab, orient="vertical", command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=scrollbar.set)
        self.search_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.search_tree.bind("<Double-1>", lambda _e: self.search_resume_selected())

    def conversations_selected_id(self) -> str | None:
        """Return the conversation ID of the selected Conversations row, or None."""
        tree = self.require_conversations_tree()
        sel = tree.selection()
        if not sel:
            return None
        return tree.set(sel[0], "id") or None

    def conversations_resume_selected(self) -> None:
        """Resume the conversation selected in the Conversations tab."""
        conv_id = self.conversations_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        self.notebook.select(self.chat_tab)
        self.resume_conversation(conv_id)

    def conversations_archive_selected(self) -> None:
        """Archive the conversation selected in the Conversations tab."""
        conv_id = self.conversations_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        self.store.set_conversation_archived(conv_id, True)
        self.append_transcript(f"Archived conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def conversations_delete_selected(self) -> None:
        """Delete the conversation selected in the Conversations tab after confirmation."""
        conv_id = self.conversations_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        if conv_id == self.state.conv.id:
            messagebox.showerror("tuochat", "Cannot delete the active conversation.", parent=self.root)
            return
        if not messagebox.askyesno("tuochat", f"Delete conversation {conv_id[:8]}?", parent=self.root):
            return
        self.store.delete_conversation(conv_id)
        self.append_transcript(f"Deleted conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def archived_selected_id(self) -> str | None:
        """Return the conversation ID of the selected Archive row, or None."""
        tree = self.require_archived_tree()
        sel = tree.selection()
        if not sel:
            return None
        return tree.set(sel[0], "id") or None

    def archived_resume_selected(self) -> None:
        """Resume the conversation selected in the Archive tab."""
        conv_id = self.archived_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        self.notebook.select(self.chat_tab)
        self.resume_conversation(conv_id)

    def archived_unarchive_selected(self) -> None:
        """Unarchive the conversation selected in the Archive tab."""
        conv_id = self.archived_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        self.store.set_conversation_archived(conv_id, False)
        self.append_transcript(f"Unarchived conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def archived_delete_selected(self) -> None:
        """Delete the conversation selected in the Archive tab after confirmation."""
        conv_id = self.archived_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a conversation first.", parent=self.root)
            return
        if conv_id == self.state.conv.id:
            messagebox.showerror("tuochat", "Cannot delete the active conversation.", parent=self.root)
            return
        if not messagebox.askyesno("tuochat", f"Delete conversation {conv_id[:8]}?", parent=self.root):
            return
        self.store.delete_conversation(conv_id)
        self.append_transcript(f"Deleted conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def search_selected_id(self) -> str | None:
        """Return the conversation ID of the selected Search row, or None."""
        tree = self.require_search_tree()
        sel = tree.selection()
        if not sel:
            return None
        return tree.set(sel[0], "id") or None

    def search_resume_selected(self) -> None:
        """Resume the conversation selected in the Search tab."""
        conv_id = self.search_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a result first.", parent=self.root)
            return
        self.notebook.select(self.chat_tab)
        self.resume_conversation(conv_id)

    def search_archive_selected(self) -> None:
        """Archive the conversation selected in the Search tab."""
        conv_id = self.search_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a result first.", parent=self.root)
            return
        self.store.set_conversation_archived(conv_id, True)
        self.append_transcript(f"Archived conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def search_delete_selected(self) -> None:
        """Delete the conversation selected in the Search tab after confirmation."""
        conv_id = self.search_selected_id()
        if conv_id is None:
            messagebox.showinfo("tuochat", "Select a result first.", parent=self.root)
            return
        if conv_id == self.state.conv.id:
            messagebox.showerror("tuochat", "Cannot delete the active conversation.", parent=self.root)
            return
        if not messagebox.askyesno("tuochat", f"Delete conversation {conv_id[:8]}?", parent=self.root):
            return
        self.store.delete_conversation(conv_id)
        self.append_transcript(f"Deleted conversation: {conv_id[:8]}\n")
        self.refresh_tab_views()

    def all_text_widgets(self) -> list[tk.Text]:
        """Return all text widgets that should receive font/theme updates."""
        widgets: list[tk.Text] = [
            self.transcript,
            self.files_view,
            self.context_view,
            self.help_view,
            self.usage_view,
        ]
        if hasattr(self, "input_box"):
            widgets.append(self.input_box)
        if hasattr(self, "context_browser") and hasattr(self.context_browser, "preview_text"):
            widgets.append(self.context_browser.preview_text)
        return widgets

    def apply_theme_and_font(self) -> None:
        """Apply the current theme and font settings from config to all widgets."""
        cfg_gui = self.state.cfg.gui
        font_family = cfg_gui.font_family or "TkFixedFont"
        font_size = cfg_gui.font_size if cfg_gui.font_size > 0 else 10
        font_spec = (font_family, font_size)

        active_theme = cfg_gui.theme
        if active_theme.startswith("ttk:"):
            ttk_name = active_theme[4:]
            try:
                ttk.Style(self.root).theme_use(ttk_name)
            except tk.TclError:
                pass
            # Apply light-mode colors to non-ttk widgets so they don't clash
            # with the bright-white ttk themes.
            light_colors = theme_colors("light")
            if light_colors is None:
                raise TypeError("ligth_colors can't be None")
            bg, fg, input_bg, input_fg, select_bg = light_colors
            for widget in self.all_text_widgets():
                widget.configure(font=font_spec)
                if widget is getattr(self, "input_box", None):
                    widget.configure(
                        background=input_bg,
                        foreground=input_fg,
                        insertbackground=input_fg,
                        selectbackground=select_bg,
                    )
                else:
                    widget.configure(background=bg, foreground=fg, selectbackground=select_bg)
            self.root.configure(background=bg)
            self.apply_theme_to_widget(self.root, bg, fg, input_bg, input_fg)
            return

        colors = theme_colors(active_theme)
        for widget in self.all_text_widgets():
            widget.configure(font=font_spec)
            if colors is not None:
                bg, fg, input_bg, input_fg, select_bg = colors
                if widget is getattr(self, "input_box", None):
                    widget.configure(
                        background=input_bg, foreground=input_fg, insertbackground=input_fg, selectbackground=select_bg
                    )
                else:
                    widget.configure(background=bg, foreground=fg, selectbackground=select_bg)

        if colors is not None:
            bg, fg, input_bg, input_fg, select_bg = colors
            self.root.configure(background=bg)
            self.apply_theme_to_chrome(bg, fg, input_bg, input_fg)

    def apply_theme_to_chrome(self, bg: str, fg: str, input_bg: str, input_fg: str) -> None:
        """Apply theme colors to buttons, labels, frames, and the notebook."""
        style = ttk.Style(self.root)
        style.theme_use("default")
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=bg, foreground=fg, padding=[6, 3])
        style.map("TNotebook.Tab", background=[("selected", input_bg)], foreground=[("selected", input_fg)])
        style.configure("TFrame", background=bg)
        style.configure("TPanedwindow", background=bg)
        style.configure("Treeview", background=input_bg, foreground=input_fg, fieldbackground=input_bg)
        style.map("Treeview", background=[("selected", bg)], foreground=[("selected", fg)])
        style.configure("TScrollbar", background=bg, troughcolor=input_bg)
        self.apply_theme_to_widget(self.root, bg, fg, input_bg, input_fg)

    def apply_theme_to_widget(self, widget: tk.Misc, bg: str, fg: str, input_bg: str, input_fg: str) -> None:
        """Recursively apply theme colors to a widget and all its children."""
        widget_class = widget.winfo_class()
        try:
            if widget_class in ("Button", "Menubutton"):
                widget.configure(  # type: ignore[call-arg]
                    background=bg,
                    foreground=fg,
                    activebackground=input_bg,
                    activeforeground=input_fg,
                )
            elif widget_class == "Checkbutton":
                widget.configure(  # type: ignore[call-arg]
                    background=bg,
                    foreground=fg,
                    activebackground=input_bg,
                    activeforeground=input_fg,
                    selectcolor="#606060",
                )
            elif widget_class == "Radiobutton":
                widget.configure(  # type: ignore[call-arg]
                    background=bg,
                    foreground=fg,
                    activebackground=input_bg,
                    activeforeground=input_fg,
                    selectcolor=input_bg,
                )
            elif widget_class == "Label":
                widget.configure(background=bg, foreground=fg)  # type: ignore[call-arg]
            elif widget_class in ("Frame", "Labelframe"):
                widget.configure(background=bg)  # type: ignore[call-arg]
            elif widget_class == "Tk":
                widget.configure(background=bg)  # type: ignore[call-arg]
            elif widget_class == "PanedWindow":
                widget.configure(background=bg)  # type: ignore[call-arg]
            elif widget_class == "Entry":
                widget.configure(background=input_bg, foreground=input_fg, insertbackground=input_fg)  # type: ignore[call-arg]
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self.apply_theme_to_widget(child, bg, fg, input_bg, input_fg)

    def pick_font(self) -> None:
        """Show a scrollable font family picker and apply the chosen font."""
        current = self.state.cfg.gui.font_family or ""
        dialog = FontPickerDialog(self.root, current_family=current)
        chosen = dialog.result
        if chosen is None:
            return
        self.state.cfg.gui.font_family = chosen
        self.apply_theme_and_font()
        self.save_gui_config()

    def pick_font_size(self) -> None:
        """Show a font size picker dialog and apply the chosen size."""
        current = self.state.cfg.gui.font_size if self.state.cfg.gui.font_size > 0 else 10
        chosen = simpledialog.askinteger(
            "Font size",
            "Enter font size (points, 6–72):",
            initialvalue=current,
            minvalue=6,
            maxvalue=72,
            parent=self.root,
        )
        if chosen is None:
            return
        self.state.cfg.gui.font_size = chosen
        self.apply_theme_and_font()
        self.save_gui_config()

    def set_theme(self, theme_key: str) -> None:
        """Switch to the selected theme and persist the choice."""
        self.state.cfg.gui.theme = theme_key
        self.theme_var.set(theme_key)
        self.apply_theme_and_font()
        self.save_gui_config()

    def save_gui_config(self) -> None:
        """Persist the current GUI config (font/theme) to disk."""
        try:
            save_config(self.state.cfg, self.state.config_path)
        except Exception:
            pass

    def history_prev(self, event=None):
        # pylint: disable=unused-argument
        """Navigate to the previous history entry in the input box."""
        if not self.input_history:
            return "break"
        if self.input_history_index == -1:
            self.input_history_draft = self.input_box.get("1.0", "end-1c")
            self.input_history_index = len(self.input_history) - 1
        elif self.input_history_index > 0:
            self.input_history_index -= 1
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", self.input_history[self.input_history_index])
        return "break"

    def history_next(self, event=None):
        # pylint: disable=unused-argument
        """Navigate to the next history entry (or restore the draft) in the input box."""
        if self.input_history_index == -1:
            return "break"
        if self.input_history_index < len(self.input_history) - 1:
            self.input_history_index += 1
            self.input_box.delete("1.0", "end")
            self.input_box.insert("1.0", self.input_history[self.input_history_index])
        else:
            self.input_history_index = -1
            self.input_box.delete("1.0", "end")
            self.input_box.insert("1.0", self.input_history_draft)
        return "break"

    def build_menu_bar(self) -> None:
        """Create the application menu bar."""
        self.menu_bar = tk.Menu(self.root)

        self.file_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.file_menu.add_command(label="Export conversation...", command=self.export_conversation)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Open conversation folder", command=self.open_conversation_folder)
        self.file_menu.add_command(label="Open config folder", command=self.open_config_folder)
        self.file_menu.add_command(label="Open cwd folder", command=self.open_cwd_folder)
        self.file_menu.add_command(label="Select new working directory (cwd)...", command=self.select_working_directory)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Nuke...", command=self.request_nuke)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.request_quit)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)

        self.resume_menu = tk.Menu(self.menu_bar, tearoff=False, postcommand=self.refresh_resume_menu)
        self.menu_bar.add_cascade(label="Resume", menu=self.resume_menu)

        self.conversation_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.conversation_menu.add_command(label="Clear/New", command=self.start_new_conversation)
        self.conversation_menu.add_command(label="Classify...", command=self.choose_classification)
        self.menu_bar.add_cascade(label="Conversation", menu=self.conversation_menu)

        self.model_menu = tk.Menu(self.menu_bar, tearoff=False)
        for model_key, model_label in MODEL_LABELS.items():
            self.model_menu.add_radiobutton(
                label=model_label,
                value=model_key,
                variable=self.model_var,
                command=partial(self.set_active_model, model_key),
            )
        self.menu_bar.add_cascade(label="Model", menu=self.model_menu)

        self.skill_menu = tk.Menu(self.menu_bar, tearoff=False, postcommand=self.refresh_skill_menu)
        self.menu_bar.add_cascade(label="Skill", menu=self.skill_menu)

        self.appearance_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.appearance_menu.add_command(label="Font...", command=self.pick_font)
        self.appearance_menu.add_command(label="Font size...", command=self.pick_font_size)
        self.appearance_menu.add_separator()
        self.theme_var = tk.StringVar(master=self.root, value=self.state.cfg.gui.theme)
        for theme_key, theme_label in GUI_THEMES.items():
            self.appearance_menu.add_radiobutton(
                label=theme_label,
                value=theme_key,
                variable=self.theme_var,
                command=partial(self.set_theme, theme_key),
            )
        self.appearance_menu.add_separator()
        available_ttk_themes = ttk.Style().theme_names()
        for ttk_theme in GUI_TTK_THEMES:
            if ttk_theme in available_ttk_themes:
                self.appearance_menu.add_radiobutton(
                    label=f"ttk: {ttk_theme}",
                    value=f"ttk:{ttk_theme}",
                    variable=self.theme_var,
                    command=partial(self.set_theme, f"ttk:{ttk_theme}"),
                )
        self.menu_bar.add_cascade(label="Appearance", menu=self.appearance_menu)

        self.menu_bar.add_command(label="Search", state="disabled")
        self.menu_bar.add_command(label="Tutorial", state="disabled")
        self.menu_bar.add_command(label="Configure", command=lambda: self.submit_command("/config"))

        self.help_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.help_menu.add_command(label="Slash Commands...", command=self.show_slash_commands_dialog)
        self.help_menu.add_command(label="Keyboard Shortcuts...", command=self.show_keyboard_shortcuts_dialog)
        self.help_menu.add_command(label="Doctor", command=lambda: self.submit_command("/doctor"))
        self.help_menu.add_separator()
        self.help_menu.add_command(label="Check for Updates...", command=self.show_check_for_updates_dialog)
        self.help_menu.add_command(label="Audit, Self-Check & Tamper...", command=self.show_audit_self_check_dialog)
        self.help_menu.add_command(label="Self-Upgrade...", command=self.show_self_upgrade_dialog)
        self.help_menu.add_separator()
        self.help_menu.add_command(label="About...", command=self.show_about_dialog)
        self.help_menu.add_command(label="License...", command=self.show_license_dialog)
        self.menu_bar.add_cascade(label="Help", menu=self.help_menu)

        self.root.config(menu=self.menu_bar)

    def run(self) -> int:
        self.root.after(30, self.process_gui_queues)
        self.run_startup_messages()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.handle_keyboard_interrupt()
        return 0

    def build_info_panel(self) -> None:
        """Render a compact session info strip under the transcript."""
        self.info_panel = tk.Frame(self.root, bd=1, relief="groove")
        # Packed later in pack_main_layout() so the notebook gets what's left.
        self.info_label = tk.Label(self.info_panel, anchor="w", textvariable=self.info_var)
        self.info_label.pack(fill="x", padx=8, pady=(6, 0))
        self.warning_label = tk.Label(self.info_panel, anchor="w", textvariable=self.warning_var)
        self.writing_directory_label = tk.Label(self.info_panel, anchor="w", textvariable=self.writing_directory_var)

    def pack_main_layout(self) -> None:
        """Pack the main root-level widgets in the correct order.

        Bottom-anchored widgets are packed first so they always get their
        declared height even when the window is small.  The notebook is packed
        last with expand=True so it takes whatever space remains.

        Desired top-to-bottom order: notebook | info panel | controls | input box
        """
        # Bottom-anchored items — pack in reverse visual order so the last
        # packed ends up at the very bottom.
        self.input_box.pack(fill="x", padx=8, pady=(0, 8), side="bottom")
        self.controls.pack(fill="x", padx=8, pady=4, side="bottom")
        self.info_panel.pack(fill="x", padx=8, pady=(0, 4), side="bottom")
        # Notebook fills all remaining space at the top.
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4), side="top")

    def install_tooltips(self) -> None:
        """Attach compact hover help to the main controls."""
        ToolTip(self.send_button, "Send the current draft.")
        ToolTip(self.help_button, "Show slash-command help.")
        ToolTip(self.status_button, "Show current conversation status.")
        ToolTip(self.attach_files_button, "Pick one or more files for the next request.")
        ToolTip(self.attach_folder_button, "Pick a folder and attach its include-able files for the next request.")
        ToolTip(self.attach_skill_button, "Attach a discovered skill to the next request.")
        ToolTip(self.attach_custom_button, "Pick custom instructions to apply at the top of the next new conversation.")
        ToolTip(self.attach_template_button, "Attach a rendered template prompt to the next request.")
        ToolTip(self.detach_all_button, "Remove every pending attachment from the next request.")
        ToolTip(self.include_agents_button, "Choose which agent prompt file (AGENTS.md, CLAUDE.md, etc.) to include.")
        ToolTip(self.reinclude_changed_button, "Re-attach the last included file if it changed on disk.")
        ToolTip(self.clear_button, "Start a new conversation after confirmation.")
        ToolTip(self.approve_writes_button, "Ask before write-here mode writes a named file into the cwd.")
        ToolTip(self.write_here_button, "Write named generated files into the current working directory.")
        ToolTip(self.streaming_button, "Toggle streaming responses for this session.")
        ToolTip(self.mask_button, "Toggle on-screen masking for this session.")
        ToolTip(self.verbose_button, "Toggle verbose context reporting for future turns.")
        ToolTip(self.no_write_button, "Disable local database, filesystem, and file-log writes for this session.")
        ToolTip(self.code_interpreter_button, "Toggle sandbox/code-interpreter prompts for this session.")
        ToolTip(self.model_toggle_button, "Cycle between Duo, Eliza, and OpenRouter.")
        ToolTip(
            self.memory_button, "Ask the bot what to remember and save to .tuochat/memory.md (pinned to future convos)."
        )
        ToolTip(self.compact_button, "Summarize the conversation, save to .tuochat/compact.md, and start fresh.")
        ToolTip(self.todo_button, "Ask the bot for a task list and save to .tuochat/todo.md (pinned to future convos).")
        ToolTip(self.quit_button, "Close tuochat after showing the final summary.")

    def run_startup_messages(self) -> None:
        with redirect_standard_io(stdout=self.stream, stderr=self.stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            print_expiration_warning(self.state.cfg)
            maybe_prune_expired_conversations(self.store, self.state.cfg)
            print_session_intro(self.state)
            print_system_prompt_sources(self.state)
        classification_cfg = getattr(self.state.cfg, "classification", None)
        if getattr(classification_cfg, "enabled", False) and getattr(
            classification_cfg,
            "ask_per_conversation",
            True,
        ):
            # Suppress the CLI list output — the GUI shows a dialog instead.
            null_io = NullTextIO()
            with redirect_standard_io(stdout=null_io, stderr=null_io), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
                chosen = prompt_classification(self.state.cfg, upcoming=True)
            if chosen:
                self.state.active_classification = chosen
        self.drain_output_queue()
        self.refresh_info_panel()

    def append_transcript(self, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def close_open_code_block_in_transcript(self) -> None:
        """Append a closing ``` fence if the transcript has an unclosed code block."""
        content = self.transcript.get("1.0", "end")
        fence_count = sum(1 for line in content.splitlines() if re.match(r"^```", line))
        if fence_count % 2 == 1:
            self.append_transcript("```\n")

    def clear_transcript(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

    def append_user_message(self, text: str) -> None:
        self.append_transcript(f"you>\n{text}\n\n")

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        button_state: Literal["normal", "disabled"] = "disabled" if busy else "normal"
        self.send_button.configure(state=button_state)
        self.help_button.configure(state=button_state)
        self.status_button.configure(state=button_state)
        self.attach_files_button.configure(state=button_state)
        self.attach_folder_button.configure(state=button_state)
        self.attach_skill_button.configure(state=button_state)
        self.attach_custom_button.configure(state=button_state)
        self.attach_template_button.configure(state=button_state)
        self.detach_all_button.configure(state=button_state)
        self.include_agents_button.configure(state=button_state)
        self.reinclude_changed_button.configure(state=button_state)
        self.clear_button.configure(state=button_state)
        self.approve_writes_button.configure(state=button_state)
        self.write_here_button.configure(state=button_state)
        self.streaming_button.configure(state=button_state)
        self.mask_button.configure(state=button_state)
        self.verbose_button.configure(state=button_state)
        self.no_write_button.configure(state=button_state)
        self.code_interpreter_button.configure(state=button_state)
        self.model_toggle_button.configure(state=button_state)
        self.input_box.configure(state=button_state)
        if not busy:
            self.input_box.focus_set()

    def refresh_info_panel(self) -> None:
        """Refresh the compact session summary shown in the info strip."""
        sandbox_runtime_summary = format_sandbox_runtime_summary(code_interpreter_runtime_details())
        self.info_var.set(
            format_info_line(
                input_tokens=self.state.session_input_tokens,
                output_tokens=self.state.session_output_tokens,
                active_model=self.state.active_model,
                working_directory=Path.cwd(),
                classification=self.state.active_classification,
                elapsed_seconds=self.state.last_turn_elapsed_seconds,
                sandbox_runtime_summary=sandbox_runtime_summary,
            )
        )
        warning_text = response_warning_text(self.state.cfg)
        self.warning_var.set(warning_text)
        self.writing_directory_var.set(format_writing_directory_line(self.current_writing_directory()))
        self.warning_label.pack_forget()
        self.writing_directory_label.pack_forget()
        if warning_text:
            self.warning_label.pack(fill="x", padx=8, pady=(0, 0))
        self.writing_directory_label.pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_toggle_controls()
        self.model_toggle_var.set(next_model_toggle_label(self.state.active_model))
        self.refresh_window_title()
        self.refresh_tab_views()

    def refresh_window_title(self) -> None:
        """Sync the window title with the active conversation title."""
        self.root.title(window_title_text(self.state.conv.title))

    def replace_text_view_contents(self, text_view: ScrolledText, text: str) -> None:
        """Replace a read-only text view with new rendered content."""
        text_view.configure(state="normal")
        text_view.delete("1.0", "end")
        text_view.insert("1.0", text)
        text_view.configure(state="disabled")

    def refresh_tab_views(self) -> None:
        """Refresh the non-chat notebook tabs from the latest session state."""
        self.replace_text_view_contents(self.files_view, render_attached_files_text(self.state))
        self.replace_text_view_contents(self.context_view, render_context_text(self.state))
        bag_status = self.load_bag_status()
        self.refresh_conversations_tree(bag_status)
        self.refresh_archived_tree(bag_status)
        self.refresh_search_tree()
        self.replace_text_view_contents(
            self.help_view,
            render_help_text(self.last_help_command, blind_mode=self.state.blind_mode),
        )
        self.replace_text_view_contents(self.usage_view, render_weekly_usage_text(self.store))
        self.replace_text_view_contents(self.wire_transcript_view, render_wire_transcript_text(self.state))
        self.observability_tab_view.refresh()

    def load_bag_status(self) -> dict[str, str]:
        """Return a mapping of conversation_id -> bag status label."""
        try:
            results, _ = check_archive_bagit_status(self.state.cfg)
        except Exception:
            return {}
        return {r.conversation_id: r.status for r in results}

    def require_conversations_tree(self) -> ttk.Treeview:
        """Return the Conversations tree after widget construction."""
        assert self.conversations_tree is not None
        return self.conversations_tree

    def require_archived_tree(self) -> ttk.Treeview:
        """Return the Archive tree after widget construction."""
        assert self.archived_tree is not None
        return self.archived_tree

    def require_search_tree(self) -> ttk.Treeview:
        """Return the Search tree after widget construction."""
        assert self.search_tree is not None
        return self.search_tree

    def refresh_conversations_tree(self, bag_status: dict[str, str] | None = None) -> None:
        """Repopulate the Conversations Treeview from stored conversations."""
        if bag_status is None:
            bag_status = self.load_bag_status()
        tree = self.require_conversations_tree()
        for item in tree.get_children():
            tree.delete(item)
        if no_write_enabled(self.state.cfg):
            tree.insert("", "end", values=("(unavailable in no-write mode)", "", "", "", ""))
            return
        conversations = self.store.list_conversations(limit=50)
        if not conversations:
            tree.insert("", "end", values=("No saved conversations yet.", "", "", "", ""))
            return
        current_id = self.state.conv.id
        for conv in conversations:
            title = (conv.title or "Untitled")[:60]
            if current_id and conv.id == current_id:
                title = f"* {title}"
            updated = humanize_date(conv.updated_at)
            raw_bag = bag_status.get(conv.id, "")
            bag = "pristine" if raw_bag == "valid" else raw_bag
            folder = Path(conv.cwd).name if conv.cwd else ""
            tree.insert("", "end", values=(title, updated, bag, folder, conv.id), tags=(conv.id,))

    def refresh_archived_tree(self, bag_status: dict[str, str] | None = None) -> None:
        """Repopulate the Archive Treeview from stored archived conversations."""
        if bag_status is None:
            bag_status = self.load_bag_status()
        tree = self.require_archived_tree()
        for item in tree.get_children():
            tree.delete(item)
        if no_write_enabled(self.state.cfg):
            tree.insert("", "end", values=("(unavailable in no-write mode)", "", "", "", ""))
            return
        conversations = self.store.list_archived_conversations(limit=200)
        if not conversations:
            tree.insert("", "end", values=("No archived conversations.", "", "", "", ""))
            return
        for conv in conversations:
            title = (conv.title or "Untitled")[:60]
            updated = humanize_date(conv.updated_at)
            raw_bag = bag_status.get(conv.id, "")
            bag = "pristine" if raw_bag == "valid" else raw_bag
            folder = Path(conv.cwd).name if conv.cwd else ""
            tree.insert("", "end", values=(title, updated, bag, folder, conv.id), tags=(conv.id,))

    def refresh_search_tree(self) -> None:
        """Repopulate the Search Treeview from the current search results."""
        tree = self.require_search_tree()
        for item in tree.get_children():
            tree.delete(item)
        results = self.state.search_candidates
        if not results:
            query = self.last_search_query
            msg = f"No results for {query!r}." if query else "No search results yet. Run /search to populate."
            tree.insert("", "end", values=(msg, "", "", ""))
            return
        for match in results:
            title = (match.title or "Untitled")[:40]
            updated = humanize_date(match.updated_at)
            snippet = re.sub(r"\s+", " ", (match.snippet or "").strip())[:80]
            tree.insert(
                "", "end", values=(title, updated, snippet, match.conversation_id), tags=(match.conversation_id,)
            )

    def refresh_toggle_controls(self) -> None:
        """Sync the toggle button states from the current session state."""
        self.approve_writes_var.set(approve_writes_enabled(self.state.cfg))
        self.write_here_var.set(write_here_mode_enabled(self.state.cfg))
        self.streaming_var.set(self.state.streaming)
        self.mask_output_var.set(self.state.mask_output)
        self.verbose_var.set(self.state.verbose)
        self.no_write_var.set(no_write_enabled(self.state.cfg))
        self.include_agents_var.set(self.state.include_agents_file)
        agent_label = "Agent Prompt" + (" (on)" if self.state.include_agents_file else " (off)")
        self.include_agents_button.configure(text=agent_label)
        self.code_interpreter_var.set(self.state.code_interpreter_enabled)

    def path_within_cwd(self, path: Path) -> bool:
        """Return whether a selected file-system path stays inside the current cwd."""
        try:
            path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            return False
        return True

    def current_writing_directory(self) -> str:
        """Return the current effective write target shown in the info bar."""
        if no_write_enabled(self.state.cfg):
            return "(disabled)"
        if write_here_mode_enabled(self.state.cfg):
            return str(Path.cwd())
        if self.state.last_saved_markdown_path is not None:
            return str(self.state.last_saved_markdown_path.parent)
        return str(conversation_archive_dir(self.state.cfg, self.state.conv, create=False))

    def refresh_skill_menu(self) -> None:
        """Populate the Skill menu from the currently available skill files."""
        self.skill_menu.delete(0, "end")
        self.skill_menu_paths = list_available_skills(self.state.cfg)
        if not self.skill_menu_paths:
            self.skill_menu.add_command(label="No skills found", state="disabled")
            return
        for path in self.skill_menu_paths:
            self.skill_menu.add_command(
                label=describe_skill_path(path, self.state.cfg),
                command=partial(self.attach_skill_to_conversation, path),
            )

    def refresh_attach_skill_menu(self) -> None:
        """Populate the speed-bar skill attachment dropdown."""
        self.attach_skill_menu.delete(0, "end")
        self.skill_menu_paths = list_available_skills(self.state.cfg)
        if not self.skill_menu_paths:
            self.attach_skill_menu.add_command(label="No skills found", state="disabled")
            return
        for path in self.skill_menu_paths:
            self.attach_skill_menu.add_command(
                label=describe_skill_path(path, self.state.cfg),
                command=partial(self.attach_skill_for_next_request, path),
            )

    def refresh_attach_custom_menu(self) -> None:
        """Populate the custom-instructions dropdown for the next new conversation."""
        self.attach_custom_menu.delete(0, "end")
        self.custom_menu_paths = list_available_custom_instructions(self.state.cfg)
        if self.state.pending_custom_path is not None:
            self.attach_custom_menu.add_command(
                label="Clear pending custom instructions", command=self.clear_pending_custom_instruction
            )
            self.attach_custom_menu.add_separator()
        if not self.custom_menu_paths:
            self.attach_custom_menu.add_command(label="No custom instructions found", state="disabled")
            return
        for path in self.custom_menu_paths:
            self.attach_custom_menu.add_command(
                label=describe_custom_instruction_path(path, self.state.cfg),
                command=partial(self.attach_custom_instruction_for_next_conversation, path),
            )

    def refresh_attach_template_menu(self) -> None:
        """Populate the speed-bar template attachment dropdown."""
        self.attach_template_menu.delete(0, "end")
        self.template_menu_paths = list_available_templates(self.state.cfg)
        if not self.template_menu_paths:
            self.attach_template_menu.add_command(label="No templates found", state="disabled")
            return
        for path in self.template_menu_paths:
            self.attach_template_menu.add_command(
                label=describe_template_path(path, self.state.cfg),
                command=partial(self.attach_template_for_next_request, path),
            )

    def queue_virtual_attachment(self, *, label: str, payload: str, attachment_kind: str) -> None:
        """Queue a generated skill or template payload for the next request."""
        queue_attachment(self.state, Path(f"[{attachment_kind}] {label}"), payload)
        self.append_transcript(f"Attached {attachment_kind} for next request: {label}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def clear_pending_custom_instruction(self) -> None:
        """Clear the custom instructions queued for the next new conversation."""
        if not self.require_idle("clearing custom instructions"):
            return
        self.state.pending_custom_path = None
        self.state.pending_custom_name = None
        self.append_transcript("Cleared pending custom instructions.\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def attach_custom_instruction_for_next_conversation(self, custom_path: Path) -> None:
        """Queue custom instructions for the next new conversation."""
        if not self.require_idle("selecting custom instructions"):
            return
        try:
            read_include_file(custom_path)
        except UnicodeDecodeError:
            messagebox.showerror(
                "tuochat", f"Custom instruction file is not valid UTF-8 text: {custom_path}", parent=self.root
            )
            return
        self.state.pending_custom_path = custom_path
        self.state.pending_custom_name = describe_custom_instruction_path(custom_path, self.state.cfg)
        self.append_transcript(
            "Selected custom instructions for the next new conversation: "
            f"{self.state.pending_custom_name}\n"
            "Start a new conversation to apply them at the top of the system prompt.\n"
        )
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def attach_skill_for_next_request(self, skill_path: Path) -> None:
        """Queue a discovered skill as an attachment for the next request."""
        if not self.require_idle("attaching a skill"):
            return
        try:
            label, payload = render_skill_message(skill_path, self.state.cfg)
        except UnicodeDecodeError:
            messagebox.showerror("tuochat", f"Skill file is not valid UTF-8 text: {skill_path}", parent=self.root)
            return
        except ValueError as exc:
            messagebox.showerror("tuochat", str(exc), parent=self.root)
            return
        self.queue_virtual_attachment(label=label, payload=payload, attachment_kind="skill")

    def prompt_for_template_attachment_value(self, prompt_or_variable: str) -> str:
        """Prompt for a template variable value while attaching a template."""
        if prompt_or_variable == ATTACHED_CODE_PROMPT:
            selected_path = prompt_for_template_code_path(self.root, initialdir=Path.cwd())
            if not selected_path:
                raise DialogCancelledError()
            return selected_path
        prompt = (
            prompt_or_variable if prompt_or_variable.endswith(": ") else f"{humanize_report_key(prompt_or_variable)}: "
        )
        response = simpledialog.askstring("Attach template", prompt.rstrip(), parent=self.root)
        if response is None:
            raise DialogCancelledError()
        return response

    def attach_template_for_next_request(self, template_path: Path) -> None:
        """Queue a rendered template prompt as an attachment for the next request."""
        if not self.require_idle("attaching a template"):
            return
        try:
            label, rendered_prompt, _metadata = render_template_prompt_from_path(
                template_path,
                self.state.cfg,
                prompt_for_value=self.prompt_for_template_attachment_value,
                cwd=Path.cwd(),
            )
        except DialogCancelledError:
            self.append_transcript("Template attachment cancelled.\n")
            return
        except ValueError as exc:
            messagebox.showerror("tuochat", str(exc), parent=self.root)
            return
        payload = f"Rendered template: {label}\n```text\n{rendered_prompt}\n```"
        self.queue_virtual_attachment(label=label, payload=payload, attachment_kind="template")

    def attach_skill_to_conversation(self, skill_path: Path) -> None:
        """Load a skill file into the current conversation without a chat turn."""
        if not self.require_idle("loading a skill"):
            return
        try:
            label, payload = render_skill_message(skill_path, self.state.cfg)
        except UnicodeDecodeError:
            messagebox.showerror("tuochat", f"Skill file is not valid UTF-8 text: {skill_path}", parent=self.root)
            return
        except ValueError as exc:
            messagebox.showerror("tuochat", str(exc), parent=self.root)
            return
        message = self.state.conv.add_message("user", payload)
        self.store.save_conversation(self.state.conv)
        self.store.save_message(message)
        self.append_transcript(f"Loaded skill into the current conversation: {label}\n")
        self.notebook.select(self.context_tab)
        self.refresh_info_panel()

    def toggle_verbose_button(self) -> None:
        """Toggle verbose context reporting for future turns."""
        from tuochat.logging_config import set_console_level  # noqa: PLC0415

        if not self.require_idle("changing verbose mode"):
            self.refresh_toggle_controls()
            return
        self.state.verbose = self.verbose_var.get()
        set_console_level(logging.DEBUG if self.state.verbose else logging.WARNING)
        self.refresh_info_panel()

    def selected_attachable_paths(self) -> list[Path]:
        """Return GUI-selected files from the current working directory."""
        return [
            Path(raw).expanduser()
            for raw in filedialog.askopenfilenames(
                parent=self.root,
                title="Attach files for the next request",
                initialdir=str(Path.cwd()),
            )
        ]

    def selected_attachable_folder_paths(self) -> list[Path]:
        """Return include-able files under a GUI-selected folder."""
        selected_folder = filedialog.askdirectory(
            parent=self.root,
            title="Attach folder for the next request",
            initialdir=str(Path.cwd()),
            mustexist=True,
        )
        if not selected_folder:
            return []
        folder_path = Path(selected_folder).expanduser()
        if not folder_path.is_dir():
            return []
        return list_include_candidates_under(folder_path, ignore_root=Path.cwd())

    def attach_paths(self, paths: list[Path]) -> list[Path]:
        """Queue selected files for the next request and return the queued subset."""
        queued_paths: list[Path] = []
        for path in paths:
            if not self.path_within_cwd(path):
                self.append_transcript(f"Skipped path outside cwd: {path}\n")
                continue
            message = prepare_include(path, self.state)
            if message is None:
                continue
            queue_attachment(self.state, path, message)
            queued_paths.append(path)
            self.append_transcript(f"Attached for next request: {path}\n")
        return queued_paths

    def attach_files_from_dialog(self) -> None:
        """Pick files from a Tk dialog and queue them as attachments."""
        if not self.require_idle("attaching files"):
            return
        paths = self.selected_attachable_paths()
        if not paths:
            return
        queued_paths = self.attach_paths(paths)
        self.refresh_info_panel()
        if not queued_paths:
            messagebox.showerror("tuochat", "No files could be attached.", parent=self.root)
            return
        self.notebook.select(self.files_tab)
        AttachmentSummaryDialog(self.root, attached_files_dialog_text(queued_paths))

    def attach_folder_from_dialog(self) -> None:
        """Pick a folder from a Tk dialog and queue its include-able files as attachments."""
        if not self.require_idle("attaching a folder"):
            return
        paths = self.selected_attachable_folder_paths()
        if not paths:
            return
        queued_paths = self.attach_paths(paths)
        self.refresh_info_panel()
        if not queued_paths:
            messagebox.showerror("tuochat", "No files from that folder could be attached.", parent=self.root)
            return
        self.notebook.select(self.files_tab)
        AttachmentSummaryDialog(self.root, attached_files_dialog_text(queued_paths))

    def detach_all_attachments(self) -> None:
        """Clear every currently queued attachment from the next request."""
        if not self.require_idle("detaching files"):
            return
        pending = len(self.state.pending_attachment_names or [])
        if pending == 0:
            self.append_transcript("No pending attachments to detach.\n")
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()
            return
        clear_pending_attachments(self.state)
        self.append_transcript(f"Detached {pending} pending attachment(s).\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def remove_pending_attachment_dialog(self) -> None:
        """Prompt the user to pick a pending attachment to remove."""
        if not self.require_idle("removing an attachment"):
            return
        names = self.state.pending_attachment_names or []
        if not names:
            messagebox.showinfo("tuochat", "No pending attachments to remove.", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Remove Attachment")
        dialog.resizable(False, False)
        tk.Label(dialog, text="Select an attachment to remove:", anchor="w").pack(fill="x", padx=12, pady=(12, 4))
        listbox = tk.Listbox(dialog, selectmode="browse", width=60, height=min(len(names), 15))
        for i, name in enumerate(names, start=1):
            listbox.insert("end", f"[{i}] {name}")
        listbox.pack(padx=12, pady=4)
        if names:
            listbox.selection_set(0)

        def do_remove():
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            name = self.state.pending_attachment_names.pop(idx)
            if self.state.pending_attachment_messages and idx < len(self.state.pending_attachment_messages):
                self.state.pending_attachment_messages.pop(idx)
            self.append_transcript(f"Removed attachment: {name}\n")
            dialog.destroy()
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=(4, 12))
        tk.Button(btn_frame, text="Remove", command=do_remove).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=4)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        dialog.focus_set()
        self.root.wait_window(dialog)

    def toggle_agents_file_button(self) -> None:
        """Toggle whether agent prompt instructions are part of the current session prompt."""
        enabled = self.include_agents_var.get()
        if not self.require_idle("changing agent prompt inclusion"):
            self.refresh_toggle_controls()
            return
        self.state.include_agents_file = enabled
        self.recompose_system_prompt_with_agents(include_agents=enabled)
        agent_label = self.active_agent_prompt_label()
        self.append_transcript(
            f"Agent prompt ({agent_label}) {'included' if enabled else 'excluded'} for this session.\n"
        )
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def active_agent_prompt_label(self) -> str:
        """Return a short label for the currently selected agent prompt."""
        if self.state.active_agent_prompt_path:
            return self.state.active_agent_prompt_path.name
        return "auto"

    def recompose_system_prompt_with_agents(self, *, include_agents: bool) -> None:
        """Recompose the session system prompt using the current agent prompt selection."""
        extra_custom_paths = [self.state.pending_custom_path] if self.state.pending_custom_path is not None else []
        prompt_without_agents = strip_agents_instructions_prefix(
            self.state.conv.system_prompt,
            agent_prompt_path=self.state.active_agent_prompt_path,
        )
        base_prompt = (
            self.state.base_system_prompt if self.state.base_system_prompt is not None else prompt_without_agents
        )
        self.state.conv.system_prompt, self.state.active_system_prompt_sources = compose_system_prompt(
            base_prompt,
            load_custom_instruction_sections(self.state.cfg, extra_paths=extra_custom_paths, mode="gui"),
            include_agents=include_agents,
            agent_prompt_path=self.state.active_agent_prompt_path,
        )

    def browser_attach_next_request(self, label: str, content: str, kind: str) -> None:
        """Callback from Context Browser to queue an artifact for the next request."""
        if not self.require_idle("attaching from Context Browser"):
            return
        queue_attachment(self.state, Path(f"[{kind}] {label}"), content)
        self.append_transcript(f"Attached {kind} for next request: {label}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def browser_attach_next_conversation(self, label: str, _content: str, _kind: str) -> None:
        """Callback from Context Browser to queue a custom instruction for the next conversation."""
        if not self.require_idle("applying from Context Browser"):
            return
        self.append_transcript(
            f"Applied custom instruction for next conversation: {label}\n" "Start a new conversation to use it.\n"
        )
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def browser_set_agent_prompt(self, path_str: str | None) -> None:
        """Callback from Context Browser to set the active agent prompt file."""
        if not self.require_idle("setting agent prompt"):
            return
        if path_str is None:
            return
        agent_path = Path(path_str)
        if not agent_path.is_file():
            messagebox.showerror("tuochat", f"Agent prompt file not found: {agent_path}", parent=self.root)
            return
        self.state.active_agent_prompt_path = agent_path
        self.state.active_agent_prompt_mode = "selected"
        self.state.include_agents_file = True
        self.include_agents_var.set(True)
        self.recompose_system_prompt_with_agents(include_agents=True)
        self.append_transcript(f"Agent prompt set to: {describe_agent_prompt_path(agent_path)}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def repo_attach_context(self, label: str, content: str) -> None:
        """Shared callback for Git/GitLab tabs to attach content to the next request."""
        if not self.require_idle("attaching from repo tab"):
            return
        queue_attachment(self.state, Path(f"[repo] {label}"), content)
        self.append_transcript(f"Attached for next request: {label}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def gitlab_set_resource(self, resource_id: str | None) -> None:
        """Callback from GitLab tab to set or clear the active resource."""
        self.state.conv.resource_id = resource_id
        if resource_id:
            self.append_transcript(f"Active resource set to: {resource_id}\n")
        else:
            self.append_transcript("Active resource cleared.\n")
        self.notebook.select(self.chat_tab)

    def jira_attach_context(self, label: str, content: str) -> None:
        """Callback from Jira tab to attach an issue to the next request."""
        if not self.require_idle("attaching from Jira tab"):
            return
        queue_attachment(self.state, Path(f"[jira] {label}"), content)
        self.append_transcript(f"Attached for next request: {label}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def open_agent_prompt_menu(self) -> None:
        """Show the agent prompt selection menu."""
        self.agent_prompt_menu.post(
            self.include_agents_button.winfo_rootx(),
            self.include_agents_button.winfo_rooty() + self.include_agents_button.winfo_height(),
        )

    def refresh_agent_prompt_menu(self) -> None:
        """Rebuild the agent prompt dropdown from discovered files."""
        self.agent_prompt_menu.delete(0, "end")

        def set_mode_none():
            if not self.require_idle("setting agent prompt to none"):
                return
            self.state.include_agents_file = False
            self.state.active_agent_prompt_mode = "none"
            self.include_agents_var.set(False)
            self.recompose_system_prompt_with_agents(include_agents=False)
            self.append_transcript("Agent prompt: none\n")
            self.refresh_info_panel()

        def set_mode_auto():
            if not self.require_idle("setting agent prompt to auto"):
                return
            self.state.include_agents_file = True
            self.state.active_agent_prompt_mode = "auto"
            self.state.active_agent_prompt_path = None
            self.include_agents_var.set(True)
            self.recompose_system_prompt_with_agents(include_agents=True)
            path, _ = auto_select_agent_prompt()
            label = path.name if path else "none found"
            self.append_transcript(f"Agent prompt: auto (selected: {label})\n")
            self.refresh_info_panel()

        self.agent_prompt_menu.add_command(label="Off", command=set_mode_none)
        self.agent_prompt_menu.add_command(label="Auto", command=set_mode_auto)
        self.agent_prompt_menu.add_separator()

        available = list_available_agent_prompts()
        if available:
            for path in available:
                label = describe_agent_prompt_path(path)
                self.agent_prompt_menu.add_command(
                    label=f"Pick: {path.name} ({label})",
                    command=partial(self.browser_set_agent_prompt, str(path)),
                )
            self.agent_prompt_menu.add_separator()

        # Show effective prompt info
        if self.state.include_agents_file:
            active_path = self.state.active_agent_prompt_path
            if active_path is None:
                auto_path, _ = auto_select_agent_prompt()
                active_path = auto_path
            if active_path and active_path.is_file():
                content = load_agent_prompt_content(active_path)
                preview = (content or "")[:200].replace("\n", " ")
                if len(content or "") > 200:
                    preview += "..."
                self.agent_prompt_menu.add_command(
                    label=f"Active: {active_path.name}  — {preview}",
                    state="disabled",
                )
            else:
                self.agent_prompt_menu.add_command(
                    label="Active: (none found in cwd)",
                    state="disabled",
                )
        else:
            self.agent_prompt_menu.add_command(label="Agent prompt is off", state="disabled")

    def reinclude_changed_file(self) -> None:
        """Re-attach the last included file when it changed on disk."""
        if not self.require_idle("re-including a changed file"):
            return
        if self.state.last_include_path is None:
            self.append_transcript("No previous include to reuse.\n")
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()
            return
        try:
            text, fingerprint, size = read_include_file(self.state.last_include_path)
        except UnicodeDecodeError:
            self.append_transcript(f"Include file is not valid UTF-8 text: {self.state.last_include_path}\n")
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()
            return
        except ValueError as exc:
            self.append_transcript(f"{exc}\n")
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()
            return
        if fingerprint == self.state.last_include_hash:
            self.append_transcript("Last included file is unchanged; not re-including it.\n")
            self.notebook.select(self.files_tab)
            self.refresh_info_panel()
            return
        self.state.last_include_hash = fingerprint
        self.state.last_include_size = size
        self.state.last_include_message = f"Included file: {self.state.last_include_path}\n```text\n{text}\n```"
        queue_attachment(self.state, self.state.last_include_path, self.state.last_include_message)
        self.append_transcript(f"Re-attached changed file for next request: {self.state.last_include_path}\n")
        self.notebook.select(self.files_tab)
        self.refresh_info_panel()

    def show_help_tab(self, command_text: str = "/help"):
        """Render help into the Help tab instead of the chat transcript."""
        if self.busy:
            return "break"
        self.last_help_command = command_text.strip() or "/help"
        self.refresh_tab_views()
        self.notebook.select(self.help_tab)
        return "break"

    def show_usage_tab(self):
        """Render weekly usage into the Usage tab instead of the chat transcript."""
        if self.busy:
            return "break"
        self.refresh_tab_views()
        self.notebook.select(self.usage_tab)
        return "break"

    def show_observability_tab(self):
        """Refresh and display the Observability tab."""
        if self.busy:
            return "break"
        self.observability_tab_view.refresh()
        self.notebook.select(self.observability_tab)
        return "break"

    def show_transcript_tab(self):
        """Render the wire transcript into the Transcript tab."""
        if self.busy:
            return "break"
        self.replace_text_view_contents(self.wire_transcript_view, render_wire_transcript_text(self.state))
        self.notebook.select(self.wire_transcript_tab)
        return "break"

    def confirm_and_start_new_conversation(self) -> None:
        """Ask for confirmation before clearing to a new conversation from the button row."""
        if not self.require_idle("clearing the conversation"):
            return
        confirmed = messagebox.askyesno(
            "Clear conversation",
            "Start a new conversation and clear the current transcript?",
            parent=self.root,
        )
        if not confirmed:
            return
        self.start_new_conversation()

    def present_main_window(self, *, maximize: bool = False) -> None:
        """Bring the main window to the foreground and optionally maximize it."""
        self.root.deiconify()
        if maximize:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(200, partial(self.root.attributes, "-topmost", False))
        except tk.TclError:
            pass
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def prompt_for_classification(self) -> str:
        """Show the GUI classification chooser and return the raw selection."""
        dialog = ClassificationDialog(
            self.root,
            self.state.cfg,
            current=self.state.active_classification,
            upcoming=not self.state.conv.messages and self.state.session_turns == 0,
        )
        return dialog.response

    def show_text_modal(self, *, title: str, body: str, button_text: str) -> None:
        """Display a blocking modal text dialog with a custom dismiss button."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.geometry("760x420")

        body_text = ScrolledText(dialog, wrap="word", height=18)
        body_text.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        body_text.insert("1.0", body.strip())
        body_text.configure(state="disabled")

        dismiss_button = tk.Button(dialog, text=button_text, command=dialog.destroy)
        dismiss_button.pack(pady=(0, 12))

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        self.present_main_window()
        dialog.lift()
        try:
            dialog.attributes("-topmost", True)
            dialog.after(200, lambda: dialog.attributes("-topmost", False))
        except tk.TclError:
            pass
        dialog.grab_set()
        dismiss_button.focus_set()
        self.root.wait_window(dialog)

    def require_idle(self, action_name: str) -> bool:
        """Return whether a menu action can proceed immediately."""
        if not self.busy:
            return True
        messagebox.showinfo("tuochat", f"Finish the current response before {action_name}.", parent=self.root)
        return False

    def apply_session_toggle(self, action_name: str, apply_change) -> None:
        """Run a session toggle through the shared CLI helper path."""
        if not self.require_idle(action_name):
            self.refresh_toggle_controls()
            return
        with redirect_standard_io(stdout=self.stream, stderr=self.stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            apply_change()
        self.drain_output_queue()
        self.refresh_info_panel()

    def toggle_approve_writes_button(self) -> None:
        enabled = self.approve_writes_var.get()
        self.apply_session_toggle(
            "changing approve-writes",
            lambda: toggle_approve_writes(self.state, enabled),
        )

    def toggle_write_here_button(self) -> None:
        enabled = self.write_here_var.get()
        self.apply_session_toggle(
            "changing write-here mode",
            lambda: toggle_write_here_mode(self.state, enabled),
        )

    def toggle_streaming_button(self) -> None:
        enabled = self.streaming_var.get()
        if not self.require_idle("changing streaming"):
            self.refresh_toggle_controls()
            return
        self.state.streaming = enabled
        self.append_transcript(f"Streaming {'enabled' if enabled else 'disabled'} for this session.\n")
        self.refresh_info_panel()

    def toggle_mask_button(self) -> None:
        enabled = self.mask_output_var.get()
        if not self.require_idle("changing masking"):
            self.refresh_toggle_controls()
            return
        self.state.mask_output = enabled
        self.append_transcript(f"On-screen masking {'enabled' if enabled else 'disabled'} for this session.\n")
        self.refresh_info_panel()

    def toggle_no_write_button(self) -> None:
        enabled = self.no_write_var.get()
        self.apply_session_toggle(
            "changing no-write mode",
            lambda: toggle_no_write(self.state, enabled),
        )

    def toggle_code_interpreter_button(self) -> None:
        enabled = self.code_interpreter_var.get()
        if not self.require_idle("changing code interpreter mode"):
            self.refresh_toggle_controls()
            return
        self.state.code_interpreter_enabled = enabled
        self.append_transcript(f"Code interpreter {'enabled' if enabled else 'disabled'} for this session.\n")
        self.refresh_info_panel()

    def toggle_active_model_button(self) -> None:
        self.set_active_model(next_model_key(self.state.active_model))

    def submit_current_text(self, event=None):
        # pylint: disable=unused-argument
        if self.busy:
            return "break"
        raw_input = self.input_box.get("1.0", "end-1c")
        if not raw_input.strip():
            return "break"
        self.input_box.delete("1.0", "end")
        stripped = raw_input.strip()
        if not self.input_history or self.input_history[-1] != stripped:
            self.input_history.append(stripped)
        self.input_history_index = -1
        self.input_history_draft = ""
        self.start_submission(raw_input)
        return "break"

    def submit_command(self, command: str):
        if self.busy:
            return "break"
        self.start_submission(command)
        return "break"

    def start_submission(self, raw_input: str) -> None:
        stripped = raw_input.strip()
        if stripped.startswith("/"):
            command, _, argument = stripped.partition(" ")
            command = command.lower()
            if command in {"/help", "/help-menu"}:
                self.show_help_tab(stripped)
                return
            if command == "/usage":
                self.show_usage_tab()
                return
            if command == "/observability":
                self.show_observability_tab()
                return
            if command == "/transcript":
                self.show_transcript_tab()
                return
            if command == "/search":
                self.run_search_tab(argument.strip())
                return
        self.route_submission_tab(raw_input)
        self.append_user_message(raw_input)
        self.set_busy(True)
        worker = threading.Thread(target=self.process_submission, args=(raw_input,), daemon=True)
        worker.start()

    def run_search_tab(self, query: str) -> None:
        """Run a conversation search and display results in the Search tab without a resume prompt."""
        if not query:
            self.notebook.select(self.search_tab)
            return
        self.last_search_query = query
        from tuochat.cli.pickers import run_conversation_search

        results = run_conversation_search(self.store, query)
        self.state.search_candidates = results
        self.refresh_search_tree()
        self.notebook.select(self.search_tab)

    def route_submission_tab(self, raw_input: str) -> None:
        """Switch to the most relevant tab for the current submission."""
        stripped = raw_input.strip()
        if not stripped.startswith("/"):
            self.notebook.select(self.chat_tab)
            return

        command, _, argument = stripped.partition(" ")
        if command in {"/help", "/help-menu"}:
            self.last_help_command = stripped
            self.notebook.select(self.help_tab)
            return
        if command == "/usage":
            self.notebook.select(self.usage_tab)
            return
        if command == "/observability":
            self.notebook.select(self.observability_tab)
            return
        if command == "/search":
            self.last_search_query = argument.strip() or self.last_search_query
            self.notebook.select(self.search_tab)
            return
        if command == "/context":
            self.notebook.select(self.context_tab)
            return
        if command in {"/attach", "/include", "/include-last", "/detach"}:
            self.notebook.select(self.files_tab)
            return
        self.notebook.select(self.chat_tab)

    def process_submission(self, raw_input: str) -> None:
        should_exit = False
        try:
            with redirect_standard_io(stdout=self.stream, stderr=self.stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
                should_exit = process_repl_submission(raw_input=raw_input, state=self.state)
        except Exception as exc:
            tb_str = traceback.format_exc()
            try:
                self.store.save_error_log_entry(
                    recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    level=logging.ERROR,
                    level_name="ERROR",
                    logger_name="tuochat.gui",
                    message=str(exc),
                    exc_type=type(exc).__name__,
                    exc_value=str(exc),
                    exc_traceback=tb_str,
                    filename=None,
                    lineno=None,
                    func_name="process_submission",
                )
            except Exception:
                pass
            print(
                f"\n[Provider error] {type(exc).__name__}: {exc}\n" "Full details logged to the Errors tab.\n",
                file=self.stream,
            )
            self.event_queue.put(("handle_provider_error", None))
        finally:
            self.event_queue.put(("submission_complete", should_exit))

    def prompt_user(self, prompt: str, *, secret: bool = False) -> str:
        if threading.current_thread() is threading.main_thread():
            response: str | None
            if is_classification_prompt(prompt):
                response = self.prompt_for_classification()
                if response:
                    self.present_main_window(maximize=True)
            elif is_attached_code_prompt(prompt):
                response = prompt_for_template_code_path(self.root)
            else:
                response = simpledialog.askstring(
                    "tuochat",
                    prompt.rstrip(":> "),
                    parent=self.root,
                    show="*" if secret else None,
                )
            return response or ""

        request = PromptRequest(prompt=prompt, secret=secret)
        self.prompt_queue.put(request)
        request.ready.wait()
        return request.response

    def process_gui_queues(self) -> None:
        self.drain_output_queue()
        self.drain_prompt_queue()
        self.drain_event_queue()
        if self.root.winfo_exists():
            self.root.after(30, self.process_gui_queues)

    def drain_output_queue(self) -> None:
        while True:
            try:
                text = self.output_queue.get_nowait()
            except queue.Empty:
                return
            self.append_transcript(text)

    def drain_prompt_queue(self) -> None:
        while True:
            try:
                request = self.prompt_queue.get_nowait()
            except queue.Empty:
                return
            if is_classification_prompt(request.prompt):
                request.response = self.prompt_for_classification() or ""
                if request.response:
                    self.present_main_window(maximize=True)
            elif is_attached_code_prompt(request.prompt):
                request.response = prompt_for_template_code_path(self.root)
            else:
                request.response = (
                    simpledialog.askstring(
                        "tuochat",
                        request.prompt.rstrip(":> "),
                        parent=self.root,
                        show="*" if request.secret else None,
                    )
                    or ""
                )
            request.ready.set()

    def drain_event_queue(self) -> None:
        while True:
            try:
                event_name, event_data = self.event_queue.get_nowait()
            except queue.Empty:
                return
            if event_name == "handle_provider_error":
                self.close_open_code_block_in_transcript()
                if hasattr(self, "error_log_tab_view"):
                    self.error_log_tab_view.refresh()
                continue
            if event_name != "submission_complete":
                continue
            self.set_busy(False)
            self.model_var.set(self.state.active_model)
            self.refresh_info_panel()
            if event_data or self.close_when_idle:
                self.finalize_and_close()

    def refresh_resume_menu(self) -> None:
        """Refresh the Resume menu from recent saved conversations."""
        self.resume_menu.delete(0, "end")
        if no_write_enabled(self.state.cfg):
            self.resume_menu.add_command(label="Unavailable in no-write mode", state="disabled")
            return
        conversations = self.store.list_conversations(limit=20)
        if not conversations:
            self.resume_menu.add_command(label="No saved conversations", state="disabled")
            return
        for conv in conversations:
            self.resume_menu.add_command(
                label=conversation_menu_label(conv, current_id=self.state.conv.id),
                command=partial(self.resume_conversation, conv.id),
            )

    def resume_conversation(self, conversation_id: str) -> None:
        """Load a saved conversation into the GUI session."""
        if not self.require_idle("resuming another conversation"):
            return
        target = self.store.get_conversation(conversation_id)
        if target is None:
            messagebox.showerror("tuochat", f"Conversation {conversation_id} not found.", parent=self.root)
            return
        # Change working directory to the conversation's recorded cwd if available
        cwd_changed = False
        if target.cwd:
            target_cwd = Path(target.cwd)
            current_cwd = Path.cwd()
            if target_cwd.is_dir() and target_cwd.resolve() != current_cwd.resolve():
                os.chdir(target_cwd)
                cwd_changed = True
        if isinstance(self.state.provider, DuoProvider):
            self.state.provider.reset_conversation()
        switch_to_conversation(self.state, target)
        self.state.include_agents_file = system_prompt_includes_agents_instructions(self.state.conv.system_prompt)
        self.clear_transcript()
        with redirect_standard_io(stdout=self.stream, stderr=self.stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            print_session_intro(self.state)
            print_masked_conversation_transcript(self.state)
            if self.state.resumed_context_pending:
                print()
                print("[Resumed conversation — prior context will be replayed to the LLM on your next message.]")
                print()
            if cwd_changed:
                print(f"Working directory changed to: {target.cwd}")
        self.drain_output_queue()
        self.refresh_info_panel()
        self.notebook.select(self.chat_tab)

    def set_active_model(self, selected: str) -> None:
        """Set the active model from the menu radio group."""
        if selected == self.state.active_model:
            return
        if not self.require_idle("changing models"):
            self.model_var.set(self.state.active_model)
            return
        self.state.active_model = selected
        self.model_var.set(selected)
        self.append_transcript(f"Active model: {MODEL_LABELS[selected]}\n")
        self.refresh_info_panel()

    def prompt_working_directory(self) -> None:
        """Ask the user to confirm or pick a working directory for the new conversation.

        Called when the current directory is not a git repository.  The user can
        accept the current directory or browse to a different one.
        """
        from tuochat.git_info import get_git_status

        current_cwd = Path.cwd()
        git = get_git_status(current_cwd)
        if git is not None:
            # We're inside a git repo — no prompt needed
            return

        answer = messagebox.askyesnocancel(
            "Working Directory",
            f"The current directory is not a git repository:\n{current_cwd}\n\n"
            "Would you like to choose a different working directory?\n\n"
            "Yes = browse for directory\n"
            "No = use current directory\n"
            "Cancel = abort new conversation",
            parent=self.root,
        )
        if answer is None:
            # User cancelled — abort
            raise RuntimeError("new conversation cancelled by user")
        if answer:
            chosen = filedialog.askdirectory(
                title="Choose Working Directory",
                initialdir=str(current_cwd),
                parent=self.root,
            )
            if not chosen:
                # User closed the dialog without choosing — use current
                return
            chosen_path = Path(chosen)
            if chosen_path != current_cwd:
                os.chdir(chosen_path)
                self.append_transcript(f"Working directory: {chosen_path}\n")

    def start_new_conversation(self) -> None:
        """Clear the transcript and begin a new conversation."""
        if not self.require_idle("starting a new conversation"):
            return
        try:
            self.prompt_working_directory()
        except RuntimeError:
            return
        silent_stream = NullTextIO()
        with redirect_standard_io(stdout=silent_stream, stderr=silent_stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            reset_repl_state(self.state)
        self.clear_transcript()
        self.append_transcript(f"Working directory: {Path.cwd()}\n")
        self.append_transcript(f"Started new conversation: {self.state.conv.id[:8]}\n")
        if self.state.active_classification:
            self.append_transcript(f"Classification: {classification_help_label(self.state.active_classification)}\n")
        sources = self.state.active_system_prompt_sources or []
        if sources:
            self.append_transcript("System prompt sources:\n")
            for src in sources:
                self.append_transcript(f"  - {src}\n")
        else:
            self.append_transcript("System prompt sources: (none)\n")
        self.append_transcript("\n")
        self.drain_output_queue()
        self.refresh_info_panel()
        self.notebook.select(self.chat_tab)

    def choose_classification(self) -> None:
        """Prompt for a new classification for the current conversation."""
        if not self.require_idle("changing the classification"):
            return
        with redirect_standard_io(stdout=self.stream, stderr=self.stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            chosen = prompt_classification(self.state.cfg, current=self.state.active_classification)
            if chosen is None:
                print("Classification unchanged.")
            else:
                self.state.active_classification = chosen
                print(f"Classification set to: {classification_help_label(chosen)}")
        self.drain_output_queue()
        if self.state.active_classification == chosen and chosen is not None:
            self.present_main_window(maximize=True)
        self.refresh_info_panel()

    def run_spm_task_dialog(self, title: str, task: Any) -> None:
        """Run *task* on a daemon thread and show output in a scrollable dialog.

        *task* must be a zero-argument callable that returns a string.
        The dialog shows a progress indicator while the task runs, then
        displays the result (or any exception message) when it finishes.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.geometry("760x440")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.bind("<Escape>", lambda event: dialog.destroy())

        text_box = ScrolledText(dialog, wrap="word", height=20, state="disabled")
        text_box.pack(fill="both", expand=True, padx=12, pady=(12, 4))

        status_var = tk.StringVar(value="Running\u2026")
        status_label = tk.Label(dialog, textvariable=status_var, anchor="w")
        status_label.pack(fill="x", padx=12)

        close_button = tk.Button(dialog, text="Close", command=dialog.destroy, state="disabled")
        close_button.pack(pady=(4, 12))

        result_holder: list[str] = []

        def worker() -> None:
            try:
                result_holder.append(task())
            except Exception as exc:
                result_holder.append(f"Error: {exc}")

        def poll() -> None:
            if not result_holder:
                dialog.after(100, poll)
                return
            output = result_holder[0]
            text_box.configure(state="normal")
            text_box.delete("1.0", "end")
            text_box.insert("1.0", output.strip() if output.strip() else "(No issues found.)")
            text_box.configure(state="disabled")
            status_var.set("Done.")
            close_button.configure(state="normal")
            close_button.focus_set()

        self.present_main_window()
        dialog.lift()
        try:
            dialog.attributes("-topmost", True)
            dialog.after(200, lambda: dialog.attributes("-topmost", False))
        except tk.TclError:
            pass
        dialog.grab_set()
        threading.Thread(target=worker, daemon=True).start()
        dialog.after(100, poll)
        self.root.wait_window(dialog)

    def show_check_for_updates_dialog(self) -> None:
        """Check PyPI for updates synchronously and display the result."""

        def task() -> str:
            host = spm_default_host()
            report = spm_api.check_for_updates(host=host, position="both", allow_network=True)
            lines: list[str] = []
            if report.host_dist:
                hd = report.host_dist
                if hd.actionable:
                    lines.append(f"Update available: {hd.name} {hd.installed} \u2192 {hd.latest}")
                    if hd.age_days is not None:
                        lines.append(f"  Released {hd.age_days:.0f} day(s) ago.")
                else:
                    lines.append(f"{hd.name} {hd.installed} is up to date.")
            for dep in report.dependencies:
                if dep.actionable:
                    lines.append(f"Dependency update: {dep.name} {dep.installed} \u2192 {dep.latest}")
            for note in report.notes:
                lines.append(f"Note: {note}")
            for err in report.errors:
                lines.append(f"Warning: {err}")
            return "\n".join(lines) if lines else "All packages are up to date."

        self.run_spm_task_dialog("Check for Updates", task)

    def show_audit_self_check_dialog(self) -> None:
        """Run vulnerability audit, integrity self-check, and tamper report."""

        def task() -> str:
            host = spm_default_host()
            sections: list[str] = []

            audit_report = spm_api.run_audit(host=host, force=True)
            audit_lines: list[str] = []
            if audit_report.vulnerabilities:
                for v in audit_report.vulnerabilities:
                    fix = ", ".join(v.fix_versions) or "none"
                    sev = v.severity or "unknown"
                    audit_lines.append(f"  {v.name} {v.installed}  [{v.advisory_id}]  severity={sev}  fix={fix}")
            for note in audit_report.notes:
                audit_lines.append(f"  Note: {note}")
            if audit_lines:
                sections.append("=== Vulnerability Audit ===\n" + "\n".join(audit_lines))
            else:
                sections.append("=== Vulnerability Audit ===\n  No vulnerabilities found.")

            problems = spm_api.self_check(host=host)
            if problems:
                sections.append("=== Integrity Self-Check ===\n" + "\n".join(f"  {p}" for p in problems))
            else:
                sections.append("=== Integrity Self-Check ===\n  All distributions satisfy their requirements.")

            tamper_problems = spm_api.tamper_check(host=host)
            if tamper_problems:
                sections.append("=== Tamper Report ===\n" + "\n".join(f"  {p}" for p in tamper_problems))
            else:
                sections.append("=== Tamper Report ===\n  No modified tuochat package files found.")

            return "\n\n".join(sections)

        self.run_spm_task_dialog("Audit, Self-Check & Tamper", task)

    def show_self_upgrade_dialog(self) -> None:
        """Perform a self-upgrade and display the result."""
        if not messagebox.askyesno(
            "Self-Upgrade",
            "Upgrade tuochat to the latest version now?",
            parent=self.root,
        ):
            return

        def task() -> str:
            host = spm_default_host()
            result = spm_api.self_upgrade(host=host, dry_run=False)
            lines: list[str] = []
            lines.append(f"Install method: {result.method.value}")
            if result.argv:
                lines.append(f"Command: {' '.join(result.argv)}")
            if not result.attempted:
                lines.append("Upgrade not attempted (editable install or unknown install method).")
            elif result.ok:
                lines.append("Upgrade succeeded.")
            else:
                lines.append(f"Upgrade failed (exit code {result.returncode}).")
            if result.stdout.strip():
                lines.append("\n--- stdout ---\n" + result.stdout.strip())
            if result.stderr.strip():
                lines.append("\n--- stderr ---\n" + result.stderr.strip())
            return "\n".join(lines)

        self.run_spm_task_dialog("Self-Upgrade", task)

    def show_about_dialog(self) -> None:
        """Display the About dialog with app metadata and legal text."""
        self.show_text_modal(title="About tuochat", body=about_dialog_text(), button_text="Close")

    def show_license_dialog(self) -> None:
        """Display the MIT license text."""
        self.show_text_modal(title="License — tuochat", body=MIT_LICENSE_TEXT, button_text="Close")

    def show_slash_commands_dialog(self) -> None:
        """Display slash-command help in a popup dialog."""
        body = render_help_text("/help", blind_mode=self.state.blind_mode)
        self.show_text_modal(title="Slash Commands", body=body, button_text="Close")

    def show_keyboard_shortcuts_dialog(self) -> None:
        """Display the keyboard shortcuts reference in a popup dialog."""
        self.show_text_modal(title="Keyboard Shortcuts", body=keyboard_shortcuts_text(), button_text="Close")

    def export_conversation(self) -> None:
        """Export the current conversation to a chosen markdown file."""
        if not self.require_idle("exporting the conversation"):
            return
        target_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export conversation",
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(Path.cwd()),
            initialfile=default_export_filename(self.state.conv),
        )
        if not target_path:
            return
        path = Path(target_path)
        path.write_text(render_conversation_markdown(self.state.conv), encoding="utf-8")
        self.append_transcript(f"Exported conversation markdown to {path}\n")

    def conversation_folder_path(self) -> Path:
        """Return the best available folder for the current conversation."""
        if self.state.last_saved_markdown_path is not None:
            return self.state.last_saved_markdown_path.parent
        if self.state.conv.messages and not no_write_enabled(self.state.cfg):
            conv_dir, md_path, extracted = sync_conversation_artifacts(
                self.state.cfg,
                self.state.conv,
                classification=self.state.active_classification,
            )
            if md_path is not None:
                update_saved_conversation_artifacts(self.state, md_path, extracted)
            if conv_dir is not None:
                return conv_dir
        return self.state.cfg.data_dir

    def open_conversation_folder(self) -> None:
        """Open the current conversation archive folder."""
        if not self.require_idle("opening the conversation folder"):
            return
        target = self.conversation_folder_path()
        opened, message = open_path(target)
        self.append_transcript(f"{message}\n")
        if not opened:
            messagebox.showerror("tuochat", message, parent=self.root)

    def open_config_folder(self) -> None:
        """Open the current config folder."""
        if not self.require_idle("opening the config folder"):
            return
        target = self.state.cfg.config_dir
        opened, message = open_path(target)
        self.append_transcript(f"{message}\n")
        if not opened:
            messagebox.showerror("tuochat", message, parent=self.root)

    def open_cwd_folder(self) -> None:
        """Open the current working directory."""
        if not self.require_idle("opening the current working directory"):
            return
        target = Path.cwd()
        opened, message = open_path(target)
        self.append_transcript(f"{message}\n")
        if not opened:
            messagebox.showerror("tuochat", message, parent=self.root)

    def select_working_directory(self) -> None:
        """Prompt for a new current working directory."""
        if not self.require_idle("changing the working directory"):
            return
        chosen = filedialog.askdirectory(
            parent=self.root,
            title="Select new working directory",
            initialdir=str(Path.cwd()),
            mustexist=True,
        )
        if not chosen:
            return
        os.chdir(chosen)
        with redirect_standard_io(stdout=NullTextIO(), stderr=NullTextIO()), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            toggle_write_here_mode(self.state, True)
        self.append_transcript(f"Working directory: {Path.cwd()}\n")
        if write_here_mode_enabled(self.state.cfg):
            self.append_transcript("Write-here mode enabled for this session.\n")
        self.refresh_info_panel()
        if self.state.conv.messages:
            if messagebox.askyesno(
                "New conversation?",
                f"Working directory changed to:\n{Path.cwd()}\n\nStart a new conversation for this directory?",
                parent=self.root,
            ):
                self.start_new_conversation()

    def request_nuke(self) -> None:
        """Ask for double confirmation, then close and nuke app data."""
        if not confirm_nuke(
            ask_yes_no=lambda title, prompt: messagebox.askyesno(title, prompt, parent=self.root),
            ask_text=lambda title, prompt: simpledialog.askstring(title, prompt, parent=self.root),
        ):
            self.append_transcript("Nuke cancelled.\n")
            return
        self.state.pending_nuke = True
        if self.busy:
            self.close_when_idle = True
            self.append_transcript("\n[Nuke confirmed. Closing after the current response finishes.]\n")
            return
        self.finalize_and_close()

    def request_quit(self, event=None):
        # pylint: disable=unused-argument
        if self.busy:
            if not self.close_when_idle:
                self.close_when_idle = True
                self.append_transcript("\n[Closing after the current response finishes.]\n")
            return "break"
        self.finalize_and_close()
        return "break"

    def handle_keyboard_interrupt(self) -> None:
        """Close the GUI cleanly when Ctrl+C interrupts the Tk mainloop."""
        if not self.root.winfo_exists():
            return
        if self.busy and not self.close_when_idle:
            self.close_when_idle = True
            self.append_transcript("\n[Ctrl+C received. Closing after the current response finishes.]\n")
        elif not self.busy:
            self.finalize_and_close()
        while self.root.winfo_exists():
            try:
                self.root.update()
            except KeyboardInterrupt:
                continue
            except tk.TclError:
                break

    def finalize_and_close(self) -> None:
        """Close stores, optionally nuke app data, and destroy the window."""
        if self.finalized:
            return
        self.finalized = True
        summary_buffer = io.StringIO()
        summary_stream = MultiTextIO(self.stream, summary_buffer)
        with redirect_standard_io(stdout=summary_stream, stderr=summary_stream), prompt_handler(self.prompt_user):  # type: ignore[arg-type]
            if self.state.pending_nuke:
                self.store.close()
                self.execute_nuke()
            else:
                print()
                print_chat_summary(self.state.conv, self.state)
                if self.state.conv.messages:
                    print(f"Conversation saved: {self.state.conv.id}")
                    print_saved_conversation_files(self.state)
                    print(f"\nTo resume:  tuochat resume {self.state.conv.id[:8]}")
                self.store.close()
        self.drain_output_queue()
        summary_text = summary_buffer.getvalue().strip()
        if summary_text and not self.state.pending_nuke:
            self.show_text_modal(title="Session summary", body=summary_text, button_text="Dismiss")
        self.root.after(150, self.root.destroy)

    def execute_nuke(self) -> None:
        """Delete centralized app-state paths after confirmation."""
        from tuochat import winlog  # noqa: PLC0415

        targets = nuke_targets(self.state.cfg)
        if not targets:
            print("Nuke complete: no centralized app data was present.")
            return
        deleted = 0
        failed = 0
        for path in targets:
            if not path.exists():
                continue
            try:
                delete_path(path)
                deleted += 1
            except OSError as exc:
                print(f"Nuke failed to delete {path}: {exc}")
                failed += 1
        if failed:
            print(f"Nuke partial: deleted {deleted} path(s), failed to delete {failed} path(s).")
        else:
            print(f"Nuke complete: deleted {deleted} centralized path(s).")
        print(f"Config kept: {self.state.cfg.config_dir}")
        print(f"Workspace kept: {Path.cwd()}")
        winlog.report_event(
            winlog.EV_ADMIN_NUKE,
            f"tuochat GUI nuke executed: {deleted} path(s) deleted, {failed} failed.",
            logging.WARNING,
        )


def run_gui_app(cfg: TuochatConfig, args: Any) -> int:
    """Run the minimal Tkinter GUI front end."""
    from tuochat import winlog  # noqa: PLC0415
    from tuochat.logging_config import setup_logging  # noqa: PLC0415

    debug = getattr(args, "debug", False)
    setup_logging(
        log_dir=cfg.log_dir,
        debug=debug,
        enable_file_logging=True,
        stdout=True,
    )

    cfg = maybe_run_first_run_setup(cfg, config_path=args.config if hasattr(args, "config") else None)
    warnings = cfg.validate()
    active_model = configured_gui_model(cfg)

    if active_model is None:
        winlog.report_event(
            winlog.EV_CONFIG_MISSING_REQUIRED,
            "tuochat GUI startup aborted: no Duo or OpenRouter provider is configured.",
            logging.ERROR,
        )
        root = tk.Tk()
        root.withdraw()
        details = "\n".join(
            [
                "Configure either GitLab Duo or OpenRouter before starting the GUI.",
                f"Duo: create {cfg.config_file} or set TUOCHAT_GITLAB_HOST and TUOCHAT_GITLAB_TOKEN.",
                "OpenRouter: run `tuochat openrouter login` and set OPENROUTER_MODEL or OPENROUTER_MODELS.",
            ]
        )
        messagebox.showerror("tuochat", details, parent=root)
        root.destroy()
        return 1

    timeout_override = getattr(args, "timeout", None)
    if active_model == "duo":
        provider: Any = build_provider(cfg, timeout_override=timeout_override)
    else:
        from tuochat.cli.session import build_openrouter_provider  # noqa: PLC0415

        provider = build_openrouter_provider(cfg)
        warnings = [warning for warning in warnings if not warning.startswith("GitLab ")]
    store = build_store(cfg)

    from tuochat.logging_config import sqlite_log_handler  # noqa: PLC0415

    sqlite_log_handler.attach_store(store)

    base_system_prompt = args.prompt
    base_resource_id = args.resource_id or cfg.chat.default_resource_id
    system_prompt, prompt_sources = compose_system_prompt(
        base_system_prompt,
        load_custom_instruction_sections(cfg, mode="gui"),
    )
    state = ReplState(
        conv=Conversation(resource_id=base_resource_id, system_prompt=system_prompt),
        store=store,
        provider=provider,
        cfg=cfg,
        streaming=not args.no_stream and cfg.chat.streaming,
        config_path=Path(args.config).expanduser() if getattr(args, "config", None) else None,
        timeout_override=timeout_override,
        quiet=cfg.chat.quiet,
        no_banner=cfg.chat.no_banner,
        blind_mode=cfg.chat.blind,
        debug=getattr(args, "debug", False),
        base_system_prompt=base_system_prompt,
        base_resource_id=base_resource_id,
        mask_output=cfg.chat.mask_output,
        dot_timer_enabled=cfg.chat.dot_timer,
        no_code_mode=False,
        code_interpreter_enabled=True,
        active_model=active_model,
        active_system_prompt_sources=prompt_sources,
        command_log=[],
        local_writes_enabled=not no_write_enabled(cfg),
        include_agents_file=system_prompt_includes_agents_instructions(system_prompt),
        gui_mode=True,
    )
    apply_git_repo_write_here_default(cfg)

    if isinstance(provider, DuoProvider):
        provider.reset_conversation()

    winlog.report_event(winlog.EV_STARTUP, f"tuochat GUI session started (model={active_model!r}).")
    app = TkChatApp(state, store)
    if warnings:
        app.append_transcript("Warnings:\n")
        for warning in warnings:
            app.append_transcript(f"- {warning}\n")
        app.append_transcript("\n")
    result = app.run()
    winlog.report_event(winlog.EV_SHUTDOWN, "tuochat GUI session ended.")
    return result
