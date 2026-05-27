"""Context Browser tab — discover, inspect, and attach prompt-bearing context artifacts."""

# All underscore methods this class are a mistake, do not copy, they are not representative of house style.

from __future__ import annotations

import os
import platform
import shlex
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING, Callable

from tuochat.context.artifacts import ArtifactKind, ContextArtifact, discover_all_artifacts
from tuochat.context.recipes import Recipe, RecipeMatch, expand_recipe, list_recipes

if TYPE_CHECKING:
    from tuochat.cli.models import ReplState

KIND_ORDER = [
    ArtifactKind.WORKSPACE_MEMORY,
    ArtifactKind.AGENT_PROMPT,
    ArtifactKind.SKILL,
    ArtifactKind.TEMPLATE,
    ArtifactKind.CUSTOM_INSTRUCTION,
    ArtifactKind.RECIPE,
    ArtifactKind.FILE_ATTACHMENT,
]

KIND_LABELS: dict[ArtifactKind, str] = {
    ArtifactKind.WORKSPACE_MEMORY: "Workspace Memory (pinned)",
    ArtifactKind.AGENT_PROMPT: "Agent Prompts",
    ArtifactKind.SKILL: "Skills",
    ArtifactKind.TEMPLATE: "Templates",
    ArtifactKind.CUSTOM_INSTRUCTION: "Custom Instructions",
    ArtifactKind.RECIPE: "Recipes",
    ArtifactKind.FILE_ATTACHMENT: "Attached Files",
}

APPLIES_TO_LABELS = {
    "current_turn": "current turn",
    "next_turn": "next turn",
    "next_conversation": "next conversation",
    "session_prompt": "session prompt",
}

# Fallback editors when $EDITOR is not set, keyed by platform.system() value.
FALLBACK_EDITORS: dict[str, str] = {
    "Windows": "notepad",
    "Darwin": "open -t",
    "Linux": "xdg-open",
}


def resolve_editor() -> str | None:
    """Return the editor command to use, or None to fall back to OS default open."""
    return os.environ.get("EDITOR") or os.environ.get("VISUAL")


def open_with_os_default(path: object) -> None:
    """Open a file with the platform's default application."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "Darwin":
        with subprocess.Popen(["open", str(path)]):  # noqa: S603
            pass
    else:
        with subprocess.Popen(["xdg-open", str(path)]):  # noqa: S603
            pass


class ContextBrowserTab:
    """A notebook tab that lists all context artifacts and lets the user preview them."""

    def __init__(
        self,
        parent: tk.Misc,
        state: ReplState,
        *,
        on_attach_next_request: Callable[[str, str, str], None] | None = None,
        on_attach_next_conversation: Callable[[str, str, str], None] | None = None,
        on_set_agent_prompt: Callable[[str | None], None] | None = None,
    ) -> None:
        self.parent = parent
        self.state = state
        self.on_attach_next_request = on_attach_next_request
        self.on_attach_next_conversation = on_attach_next_conversation
        self.on_set_agent_prompt = on_set_agent_prompt

        self.artifacts: list[ContextArtifact] = []
        self.tree_items: dict[str, ContextArtifact | Recipe] = {}
        self.recipes: list[Recipe] = []
        self.selected_artifact: ContextArtifact | None = None
        self.selected_recipe: Recipe | None = None
        self.show_resolved = tk.BooleanVar(master=parent, value=True)
        self.filter_var = tk.StringVar(master=parent)

        self.build(parent)
        self.refresh()

    def build(self, parent: tk.Misc) -> None:
        """Build the two-pane layout: artifact list on left, preview on right."""
        outer = tk.Frame(parent)
        outer.pack(fill="both", expand=True)

        # Filter bar at top
        filter_bar = tk.Frame(outer)
        filter_bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(filter_bar, text="Filter:").pack(side="left")
        filter_entry = tk.Entry(filter_bar, textvariable=self.filter_var, width=30)
        filter_entry.pack(side="left", padx=(4, 0))
        self.filter_var.trace_add("write", lambda *_: self.apply_filter())
        tk.Button(filter_bar, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))

        # Paned window: list left, preview right
        paned = tk.PanedWindow(outer, orient="horizontal", sashwidth=5, sashrelief="groove")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # Left: artifact list
        list_frame = tk.Frame(paned, width=260)
        list_frame.pack_propagate(False)
        paned.add(list_frame, minsize=180)

        self.artifact_tree = ttk.Treeview(list_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.artifact_tree.yview)
        self.artifact_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.artifact_tree.pack(fill="both", expand=True)
        self.artifact_tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # Right: preview pane + action bar
        right_frame = tk.Frame(paned)
        paned.add(right_frame, minsize=300)

        # View toggle
        view_bar = tk.Frame(right_frame)
        view_bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Radiobutton(
            view_bar, text="Raw", variable=self.show_resolved, value=False, command=self.refresh_preview
        ).pack(side="left")
        tk.Radiobutton(
            view_bar, text="Resolved", variable=self.show_resolved, value=True, command=self.refresh_preview
        ).pack(side="left")

        # Metadata strip
        self.meta_label = tk.Label(right_frame, anchor="w", wraplength=500, justify="left")
        self.meta_label.pack(fill="x", padx=4, pady=(2, 0))

        # Preview text
        self.preview_text = ScrolledText(right_frame, wrap="word", state="disabled")
        self.preview_text.pack(fill="both", expand=True, padx=4, pady=(4, 0))

        # Action bar
        action_bar = tk.Frame(right_frame)
        action_bar.pack(fill="x", padx=4, pady=(4, 4))
        self.btn_attach_request = tk.Button(
            action_bar, text="Attach for next request", command=self.action_attach_request
        )
        self.btn_attach_request.pack(side="left")
        self.btn_attach_conversation = tk.Button(
            action_bar, text="Apply to next conversation", command=self.action_attach_conversation
        )
        self.btn_attach_conversation.pack(side="left", padx=(4, 0))
        self.btn_set_agent = tk.Button(action_bar, text="Set as agent prompt", command=self.action_set_agent_prompt)
        self.btn_set_agent.pack(side="left", padx=(4, 0))
        self.btn_copy_path = tk.Button(action_bar, text="Copy path", command=self.action_copy_path)
        self.btn_copy_path.pack(side="left", padx=(4, 0))
        self.btn_open_editor = tk.Button(action_bar, text="Open in editor", command=self.action_open_in_editor)
        self.btn_open_editor.pack(side="left", padx=(4, 0))

    def refresh(self) -> None:
        """Reload artifacts from disk and repopulate the tree."""
        self.artifacts = discover_all_artifacts(self.state.cfg)
        self.recipes = list_recipes()
        self.populate_tree(self.artifacts, self.recipes)
        self.apply_filter()

    def populate_tree(self, artifacts: list[ContextArtifact], recipes: list[Recipe]) -> None:
        """Fill the treeview with artifact groups."""
        self.artifact_tree.delete(*self.artifact_tree.get_children())
        self.tree_items.clear()

        grouped: dict[ArtifactKind, list[ContextArtifact]] = {k: [] for k in KIND_ORDER}
        for artifact in artifacts:
            grouped[artifact.kind].append(artifact)

        for kind in KIND_ORDER:
            if kind == ArtifactKind.RECIPE:
                if not recipes:
                    continue
                group_id = self.artifact_tree.insert("", "end", text=f"Recipes ({len(recipes)})", open=True)
                for recipe in recipes:
                    item_id = self.artifact_tree.insert(group_id, "end", text=recipe.display_name)
                    self.tree_items[item_id] = recipe
                continue

            items = grouped[kind]
            if not items:
                continue
            label = KIND_LABELS.get(kind, kind.value)
            group_id = self.artifact_tree.insert("", "end", text=f"{label} ({len(items)})", open=True)
            for artifact in items:
                item_id = self.artifact_tree.insert(group_id, "end", text=artifact.display_name)
                self.tree_items[item_id] = artifact

    def apply_filter(self) -> None:
        """Filter artifacts by the search term and repopulate the tree."""
        query = self.filter_var.get().strip().lower()
        if not query:
            self.populate_tree(self.artifacts, self.recipes)
            return
        filtered_artifacts = [
            a
            for a in self.artifacts
            if query in a.display_name.lower() or query in a.source_label.lower() or query in a.raw_content.lower()
        ]
        filtered_recipes = [
            r for r in self.recipes if query in r.display_name.lower() or query in r.description.lower()
        ]
        self.populate_tree(filtered_artifacts, filtered_recipes)

    def on_tree_select(self, event=None) -> None:
        # pylint: disable=unused-argument
        """Show the selected artifact or recipe in the preview pane."""
        selected = self.artifact_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        obj = self.tree_items.get(item_id)
        if obj is None:
            self.selected_artifact = None
            self.selected_recipe = None
            self.clear_preview()
            return
        if isinstance(obj, Recipe):
            self.selected_artifact = None
            self.selected_recipe = obj
            self.show_recipe_preview(obj)
        else:
            self.selected_artifact = obj
            self.selected_recipe = None
            self.refresh_preview()

    def refresh_preview(self) -> None:
        """Redisplay the currently selected artifact in raw or resolved view."""
        artifact = self.selected_artifact
        if artifact is None:
            self.clear_preview()
            return

        show_resolved = self.show_resolved.get()
        content = artifact.resolved_content if show_resolved else artifact.raw_content

        meta_parts = [f"Source: {artifact.source_label}"]
        if artifact.path:
            meta_parts.append(f"Path: {artifact.path}")
        meta_parts.append(f"Applies to: {APPLIES_TO_LABELS.get(artifact.applies_to.value, artifact.applies_to.value)}")
        meta_parts.append(f"Size: {artifact.size_chars:,} chars  |  ~{artifact.estimated_tokens:,} tokens")
        if artifact.is_active:
            meta_parts.append("Status: ACTIVE")
        if artifact.was_resolved and show_resolved:
            meta_parts.append("(resolved view — placeholders expanded)")

        self.meta_label.configure(text="  |  ".join(meta_parts))
        self.set_preview_text(content or "(empty)")
        self.update_action_buttons(artifact)

    def show_recipe_preview(self, recipe: Recipe) -> None:
        """Show a recipe description and its matched files."""
        lines = [
            f"Recipe: {recipe.display_name}",
            f"Description: {recipe.description}",
            "",
            f"Globs: {', '.join(recipe.globs)}",
        ]
        if recipe.exclude_globs:
            lines.append(f"Exclude: {', '.join(recipe.exclude_globs)}")
        lines.append("")
        lines.append("(Use 'Preview & Attach' to expand against current directory)")

        self.meta_label.configure(text=f"Recipe: {recipe.name}  |  flavor: {recipe.flavor}")
        self.set_preview_text("\n".join(lines))
        self.update_action_buttons(None, recipe=recipe)

    def clear_preview(self) -> None:
        self.meta_label.configure(text="")
        self.set_preview_text("")
        self.update_action_buttons(None)

    def set_preview_text(self, text: str) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    def update_action_buttons(
        self,
        artifact: ContextArtifact | None,
        *,
        recipe: Recipe | None = None,
    ) -> None:
        """Enable/disable action buttons based on selection."""
        has_artifact = artifact is not None
        has_recipe = recipe is not None

        is_agent = has_artifact and artifact.kind == ArtifactKind.AGENT_PROMPT  # type: ignore[union-attr]
        is_custom = has_artifact and artifact.kind == ArtifactKind.CUSTOM_INSTRUCTION  # type: ignore[union-attr]
        is_attachable = has_artifact and not is_agent and not is_custom

        self.btn_attach_request.configure(state="normal" if (is_attachable or has_recipe) else "disabled")
        self.btn_attach_conversation.configure(state="normal" if is_custom else "disabled")
        self.btn_set_agent.configure(state="normal" if is_agent else "disabled")
        self.btn_copy_path.configure(
            state="normal" if (has_artifact and artifact.path) else "disabled"  # type: ignore[union-attr]
        )
        self.btn_open_editor.configure(
            state="normal" if (has_artifact and artifact.path) else "disabled"  # type: ignore[union-attr]
        )

    def action_attach_request(self) -> None:
        if self.selected_recipe is not None:
            self.attach_recipe(self.selected_recipe)
            return
        artifact = self.selected_artifact
        if artifact is None:
            return
        if self.on_attach_next_request is None:
            messagebox.showinfo("Context Browser", f"Would attach: {artifact.display_name}", parent=self.parent)
            return
        content = artifact.resolved_content or artifact.raw_content
        self.on_attach_next_request(artifact.display_name, content, artifact.kind.value)

    def action_attach_conversation(self) -> None:
        artifact = self.selected_artifact
        if artifact is None:
            return
        if self.on_attach_next_conversation is None:
            messagebox.showinfo("Context Browser", f"Would apply: {artifact.display_name}", parent=self.parent)
            return
        content = artifact.resolved_content or artifact.raw_content
        self.on_attach_next_conversation(artifact.display_name, content, artifact.kind.value)

    def action_set_agent_prompt(self) -> None:
        artifact = self.selected_artifact
        if artifact is None or artifact.path is None:
            return
        if self.on_set_agent_prompt is None:
            messagebox.showinfo(
                "Context Browser",
                f"Would set agent prompt: {artifact.display_name}",
                parent=self.parent,
            )
            return
        self.on_set_agent_prompt(str(artifact.path))

    def action_copy_path(self) -> None:
        artifact = self.selected_artifact
        if artifact is None or artifact.path is None:
            return
        self.parent.clipboard_clear()  # type: ignore[attr-defined]
        self.parent.clipboard_append(str(artifact.path))  # type: ignore[attr-defined]

    def action_open_in_editor(self) -> None:
        artifact = self.selected_artifact
        if artifact is None or artifact.path is None:
            return
        editor = resolve_editor()
        try:
            if editor:
                cmd = shlex.split(editor) + [str(artifact.path)]
                with subprocess.Popen(cmd):  # noqa: S603
                    pass
            else:
                open_with_os_default(artifact.path)
        except Exception as exc:
            messagebox.showerror("Open in editor", f"Failed to open editor:\n{exc}", parent=self.parent)

    def attach_recipe(self, recipe: Recipe) -> None:
        """Expand the recipe and either attach directly or show a preview dialog."""
        match = expand_recipe(recipe)
        if not match.matched_paths:
            messagebox.showinfo(
                "Context Browser",
                f"Recipe '{recipe.display_name}' matched no files in the current directory.",
                parent=self.parent,
            )
            return
        if match.requires_preview:
            self.show_recipe_attach_dialog(match)
        else:
            self.do_attach_recipe(match)

    def show_recipe_attach_dialog(self, match: RecipeMatch) -> None:
        """Show a preview dialog before attaching a large recipe."""
        dialog = tk.Toplevel(self.parent)  # type: ignore[call-overload]
        dialog.title(f"Recipe preview — {match.recipe.display_name}")
        dialog.geometry("700x500")
        dialog.transient(self.parent)  # type: ignore[call-overload]
        dialog.grab_set()

        info_text = (
            f"Matched: {len(match.matched_paths)} files  |  "
            f"Skipped: {len(match.skipped_paths)} files  |  "
            f"~{match.estimated_tokens:,} tokens"
        )
        if match.requires_preview:
            info_text += "  ⚠ Large attachment — review before sending"
        tk.Label(dialog, text=info_text, anchor="w").pack(fill="x", padx=8, pady=(8, 0))

        preview = ScrolledText(dialog, wrap="word", state="normal")
        preview.pack(fill="both", expand=True, padx=8, pady=8)
        file_list = "\n".join(f"  {p}" for p in match.matched_paths)
        preview.insert("1.0", f"Files to attach:\n{file_list}\n\n---\n\n{match.rendered}")
        preview.configure(state="disabled")

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))

        def do_attach():
            dialog.destroy()
            self.do_attach_recipe(match)

        tk.Button(btn_frame, text="Attach", command=do_attach).pack(side="left")
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=(4, 0))

    def do_attach_recipe(self, match: RecipeMatch) -> None:
        if self.on_attach_next_request is None:
            return
        label = match.recipe.display_name
        payload = (
            f"Recipe attachment: {label}\n"
            f"({len(match.matched_paths)} files, ~{match.estimated_tokens:,} tokens)\n\n"
            f"{match.rendered}"
        )
        self.on_attach_next_request(label, payload, ArtifactKind.RECIPE.value)
