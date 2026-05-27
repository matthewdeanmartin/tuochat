from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tuochat.config import TuochatConfig
from tuochat.models import Conversation, ConversationSearchResult
from tuochat.persistence import ConversationStore, NullConversationStore
from tuochat.provider.duo import DuoProvider
from tuochat.provider.eliza import ElizaProvider
from tuochat.provider.openrouter import OpenRouterProvider

if TYPE_CHECKING:
    from tuochat.git_info import GitStatus
    from tuochat.resources import ResourceDescriptor


@dataclass
class ReplState:
    """Mutable REPL session state."""

    conv: Conversation
    store: ConversationStore | NullConversationStore
    provider: DuoProvider | ElizaProvider | OpenRouterProvider
    cfg: TuochatConfig
    streaming: bool
    config_path: Path | None = None
    timeout_override: int | None = None
    quiet: bool = False
    no_banner: bool = False
    blind_mode: bool = False
    debug: bool = False
    base_system_prompt: str | None = None
    base_resource_id: str | None = None
    last_user_input: str | None = None
    last_include_path: Path | None = None
    last_include_hash: str | None = None
    last_include_size: int | None = None
    last_include_message: str | None = None
    pending_attachment_messages: list[str] = field(default_factory=list)
    pending_attachment_names: list[str] = field(default_factory=list)
    last_candidates: list[Path] | None = None
    resume_candidates: list[Conversation] | None = None
    search_candidates: list[ConversationSearchResult] | None = None
    custom_candidates: list[Path] | None = None
    skill_candidates: list[Path] | None = None
    template_candidates: list[Path] | None = None
    pending_custom_path: Path | None = None
    pending_custom_name: str | None = None
    active_system_prompt_sources: list[str] | None = None
    pending_template_metadata: dict[str, Any] | None = None
    pending_nuke: bool = False
    mask_output: bool = True
    dot_timer_enabled: bool = False
    no_code_mode: bool = False
    code_interpreter_enabled: bool = False
    verbose: bool = False
    active_model: str = "duo"
    active_duo_model: str | None = None
    active_openrouter_model: str | None = None
    command_log: list[dict[str, Any]] | None = None
    session_input_tokens: int = 0
    session_output_tokens: int = 0
    session_turns: int = 0
    last_saved_markdown_path: Path | None = None
    last_saved_extracted_count: int = 0
    last_saved_virtual_file_notice: bool = False
    resumed_context_pending: bool = False
    active_classification: str | None = None
    last_classification: str | None = None
    server_context: list[dict[str, str]] = field(default_factory=list)
    context_view_mode: str | None = "brief"
    local_writes_enabled: bool = True
    include_agents_file: bool = True
    gui_mode: bool = False
    last_turn_elapsed_seconds: float | None = None
    # Phase 1: resource selection
    active_resource: ResourceDescriptor | None = None
    resource_candidates: list[ResourceDescriptor] = field(default_factory=list)
    # Phase 2: git awareness
    git_status: GitStatus | None = None
    # Agent prompt selection
    available_agent_prompts: list[Path] = field(default_factory=list)
    active_agent_prompt_path: Path | None = None
    active_agent_prompt_mode: str = "auto"  # "none" | "auto" | "selected"
