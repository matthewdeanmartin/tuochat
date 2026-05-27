"""Typed command models for the CLI dispatch layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GlobalOptions:
    """Global CLI options applied before subcommand execution."""

    debug: bool = False
    config_path: Path | None = None
    no_banner: bool = False
    quiet: bool = False
    blind: bool = False


@dataclass(frozen=True)
class ChatCommand:
    """Arguments for the interactive chat command."""

    prompt: str | None = None
    resource_id: str | None = None
    no_stream: bool = False
    timeout: int | None = None


@dataclass(frozen=True)
class GuiCommand:
    """Arguments for the minimal Tkinter GUI command."""

    prompt: str | None = None
    resource_id: str | None = None
    no_stream: bool = False
    timeout: int | None = None


@dataclass(frozen=True)
class HistoryCommand:
    """Arguments for the history command."""

    limit: int = 20


@dataclass(frozen=True)
class ResumeCommand:
    """Arguments for the resume command."""

    id: str | None = None


@dataclass(frozen=True)
class SearchCommand:
    """Arguments for the search command."""

    query: list[str]
    limit: int = 20
    title: str | None = None
    after: str | None = None
    before: str | None = None


@dataclass(frozen=True)
class ExportCommand:
    """Arguments for the export command."""

    id: str | None = None
    meta: bool = False


@dataclass(frozen=True)
class ConfigCommand:
    """Arguments for the config command."""

    format: str = "markdown"


@dataclass(frozen=True)
class InitCommand:
    """Arguments for the init command."""

    force: bool = False


@dataclass(frozen=True)
class AuthCommand:
    """Arguments for the auth command."""

    action: str = "login"  # "login", "status", "logout", "refresh"


@dataclass(frozen=True)
class OpenRouterCommand:
    """Arguments for the openrouter subcommand."""

    action: str = "status"  # "login", "status", "logout"


@dataclass(frozen=True)
class DoctorCommand:
    """Arguments for the doctor command."""

    format: str = "text"


@dataclass(frozen=True)
class DiffCommand:
    """Arguments for diffing adjacent .check files against their live files."""


@dataclass(frozen=True)
class UsageCommand:
    """Arguments for the usage command."""

    format: str = "text"


@dataclass(frozen=True)
class ListConversationsCommand:
    """Arguments for listing conversations."""

    limit: int = 20
    archived: bool = False
    format: str = "text"


@dataclass(frozen=True)
class ArchiveConversationCommand:
    """Arguments for archiving a conversation."""

    id: str | None = None


@dataclass(frozen=True)
class UnarchiveConversationCommand:
    """Arguments for unarchiving conversations."""

    id: str | None = None
    all: bool = False


@dataclass(frozen=True)
class DeleteConversationCommand:
    """Arguments for deleting a conversation."""

    id: str | None = None


@dataclass(frozen=True)
class OpenConversationCommand:
    """Arguments for opening a conversation archive."""

    id: str | None = None


@dataclass(frozen=True)
class BagitUpdateCommand:
    """Arguments for refreshing BagIt metadata."""


@dataclass(frozen=True)
class BagitCheckCommand:
    """Arguments for checking BagIt status."""

    format: str = "text"


@dataclass(frozen=True)
class ListFilesCommand:
    """Arguments for listing include-able files."""

    format: str = "text"


@dataclass(frozen=True)
class ListSkillsCommand:
    """Arguments for listing discovered skills."""

    format: str = "text"


@dataclass(frozen=True)
class ListTemplatesCommand:
    """Arguments for listing discovered templates."""

    format: str = "text"


@dataclass(frozen=True)
class ListCustomInstructionsCommand:
    """Arguments for listing discovered custom instructions."""

    format: str = "text"


@dataclass(frozen=True)
class FilesApproveCommand:
    """Arguments for approving .check files by stripping the suffix when safe."""


@dataclass(frozen=True)
class FilesDeleteCommand:
    """Arguments for deleting .check files."""

    yes: bool = False


@dataclass(frozen=True)
class HeadlessAskCommand:
    """Arguments for a non-interactive chat request."""

    prompt: str | None = None
    prompt_file: Path | None = None
    use_stdin: bool = False
    includes: tuple[Path, ...] = ()
    web_urls: tuple[str, ...] = ()
    skill: str | None = None
    template: str | None = None
    variables: tuple[str, ...] = ()
    output_file: Path | None = None
    json_output: bool = False
    no_stream: bool = False
    system_prompt: str | None = None
    resource_id: str | None = None
    timeout: int | None = None
    model: str = "duo"


@dataclass(frozen=True)
class ObservabilityCommand:
    """Arguments for the observability command."""

    format: str = "text"


@dataclass(frozen=True)
class HeadlessContinueCommand:
    """Arguments for continuing a saved conversation non-interactively."""

    id: str
    prompt: str | None = None
    prompt_file: Path | None = None
    use_stdin: bool = False
    includes: tuple[Path, ...] = ()
    web_urls: tuple[str, ...] = ()
    skill: str | None = None
    template: str | None = None
    variables: tuple[str, ...] = ()
    output_file: Path | None = None
    json_output: bool = False
    no_stream: bool = False
    timeout: int | None = None
    model: str = "duo"


@dataclass(frozen=True)
class SelfcheckCommand:
    """Pass-through arguments for the self_pkg_mgmt CLI."""

    argv: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Automation-namespace commands  (chat new / chat send / chat show / chat latest)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatNewCommand:
    """Arguments for `chat new` — create a new conversation and optionally send a first message."""

    prompt: str | None = None
    prompt_file: Path | None = None
    use_stdin: bool = False
    includes: tuple[Path, ...] = ()
    web_urls: tuple[str, ...] = ()
    skill: str | None = None
    template: str | None = None
    variables: tuple[str, ...] = ()
    output_file: Path | None = None
    format: str = "markdown"
    no_stream: bool = False
    system_prompt: str | None = None
    resource_id: str | None = None
    timeout: int | None = None
    model: str = "duo"
    cwd: Path | None = None


@dataclass(frozen=True)
class ChatSendCommand:
    """Arguments for `chat send` — send one message to an existing conversation."""

    conversation: str  # ID prefix, "latest", or "--conversation-search QUERY" resolved before this
    prompt: str | None = None
    prompt_file: Path | None = None
    use_stdin: bool = False
    includes: tuple[Path, ...] = ()
    web_urls: tuple[str, ...] = ()
    skill: str | None = None
    template: str | None = None
    variables: tuple[str, ...] = ()
    output_file: Path | None = None
    format: str = "markdown"
    no_stream: bool = False
    timeout: int | None = None
    model: str = "duo"
    cwd: Path | None = None
    restore_cwd: bool = True
    fail_if_missing: bool = False


@dataclass(frozen=True)
class ChatShowCommand:
    """Arguments for `chat show` — inspect conversation metadata and state."""

    conversation: str  # ID prefix or "latest"
    format: str = "markdown"
    fail_if_missing: bool = False


@dataclass(frozen=True)
class ChatLatestCommand:
    """Arguments for `chat latest` — return the most recent active conversation."""

    format: str = "markdown"
