"""Configuration loading for tuochat.

Loads settings from TOML config files with env var overrides.
Supports XDG paths on Linux, standard paths on macOS/Windows.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from tuochat import winlog
from tuochat.__about__ import __title__, __version__
from tuochat.serialization import toml_load

logger = logging.getLogger("tuochat.config")
CURRENT_SETUP_VERSION = 4


def default_gitlab_user_agent() -> str:
    """Return the default GitLab-facing user agent for this client."""
    return f"{__title__}/{__version__}"


def config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    env = os.environ.get("TUOCHAT_CONFIG_DIR")
    if env:
        return Path(env)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "tuochat"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "tuochat"
    # Linux / other Unix — XDG
    xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(xdg) / "tuochat"


def data_dir() -> Path:
    """Return the platform-appropriate data directory."""
    env = os.environ.get("TUOCHAT_DATA_DIR")
    if env:
        return Path(env)

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(base) / "tuochat"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "tuochat"
    # Linux / other Unix — XDG
    xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(xdg) / "tuochat"


def log_dir() -> Path:
    """Return the platform-appropriate log directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "tuochat"
    return data_dir() / "logs"


def normalize_jira_host(host: str) -> str:
    """Normalize a Jira host to a stable HTTPS origin without a trailing slash."""
    value = host.strip()
    if not value:
        return ""

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    scheme = "https"
    netloc = parsed.netloc or parsed.path
    path = "" if parsed.netloc else ""
    normalized = parsed._replace(scheme=scheme, netloc=netloc, path=path, params="", query="", fragment="")
    return normalized.geturl().rstrip("/")


def normalize_gitlab_host(host: str) -> str:
    """Normalize a GitLab host to a stable HTTPS origin without a trailing slash."""
    value = host.strip()
    if not value:
        return ""

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    scheme = "https"
    netloc = parsed.netloc or parsed.path
    path = "" if parsed.netloc else ""
    normalized = parsed._replace(scheme=scheme, netloc=netloc, path=path, params="", query="", fragment="")
    return normalized.geturl().rstrip("/")


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse a single .env line supporting optional export prefixes."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()

    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return key, value


def load_dotenv(dotenv_path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """Load environment variables from a .env file using only stdlib."""
    if dotenv_path is None:
        path = Path.cwd() / ".env"
    else:
        path = Path(dotenv_path).expanduser()

    if not path.is_file():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value

    return path


@dataclass
class GitLabConfig:
    """GitLab connection settings."""

    host: str = ""
    token: str = ""
    token_type: str = "pat"  # "pat" or "oauth"
    user_agent: str = field(default_factory=default_gitlab_user_agent)


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class OpenRouterConfig:
    """OpenRouter connection settings (optional alternative to Duo)."""

    api_key: str = ""
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    model: str = ""
    models: list[str] = field(default_factory=list)
    rotate_models: bool = False
    http_referer: str = ""
    x_title: str = ""

    def effective_models(self) -> list[str]:
        """Return the model rotation list, falling back to `model` when empty."""
        if self.models:
            return list(self.models)
        if self.model:
            return [self.model]
        return []


@dataclass
class JiraConfig:
    """Jira connection settings (optional extra)."""

    host: str = ""
    deployment: str = ""  # "cloud" or "server"; inferred from host if empty
    email: str = ""  # required for cloud auth
    token: str = ""
    project: str = ""  # last-used project key, optional
    ssl_ca_cert: str = ""  # path to CA bundle or "" to use default (set to "false" to disable verification)

    def effective_deployment(self) -> str:
        """Return explicit deployment or infer from host."""
        if self.deployment:
            return self.deployment
        host_lower = self.host.lower()
        if "atlassian.net" in host_lower:
            return "cloud"
        return "server"


@dataclass
class ChatConfig:
    """Chat behavior settings."""

    platform_origin: str = "tuochat"
    default_resource_id: str | None = None
    timeout: int = 120
    websocket_welcome_timeout: int = 20
    websocket_subscription_timeout: int = 20
    streaming: bool = True
    enable_no_stream: bool = False
    mask_output: bool = True
    dot_timer: bool = False
    quiet: bool = False
    no_banner: bool = False
    blind: bool = False
    response_footer_warning_enabled: bool = False
    response_footer_warning_text: str = "Responses may be inaccurate. Verify before use."
    generated_file_header_enabled: bool = True
    generated_file_header_text: str = "Generated by Duo {date}. Apply appropriate review to LLM code before use."
    max_request_chars: int = 32000
    context_window_tokens: int = 200000
    conversation_expiration_days: int = 0
    no_write: bool = False
    tutorial_completed: bool = False
    write_here_mode: bool = False
    approve_writes: bool = False
    safety_check_extension_for_executable_files: bool = True
    refuse_writes_on_dirty_tree: bool = False


@dataclass
class NotificationsConfig:
    """Notification behavior settings."""

    long_request_bell_enabled: bool = True
    long_request_bell_seconds: int = 20


@dataclass
class PersonalizationConfig:
    """Optional first-request personalization settings."""

    enabled: bool = False
    name: str = ""
    profession: str = ""


@dataclass
class ClassificationConfig:
    """Document classification settings used by classification workflows."""

    enabled: bool = False
    ask_per_conversation: bool = True
    organizations: list[str] = field(default_factory=list)
    markings: list[str] = field(default_factory=list)
    max_markings: list[str] = field(default_factory=list)


@dataclass
class RecordsConfig:
    """Records-keeping and retention settings for saved conversation files."""

    retention_years: int = 0
    retention_label: str = ""


@dataclass
class WarnWordsConfig:
    """Optional case-insensitive phrase warnings."""

    enabled: bool = False
    phrases: list[str] = field(default_factory=list)


@dataclass
class PickerConfig:
    """Controls how interactive item pickers behave in the CLI.

    mode:
        "auto"     — adapt based on list size and blind_mode (default)
        "paged"    — always page through items in chunks
        "ask_one"  — present one item at a time (accessible, screen-reader friendly)

    list_threshold:
        In "auto" mode, lists with this many items or fewer are shown all at once.

    prefilter_threshold:
        In "auto" mode, lists larger than this prompt for a substring filter before
        displaying.  Has no effect in "paged" or "ask_one" modes.

    page_size:
        Number of items shown per page in "paged" and "auto" (large-list) modes.
    """

    mode: str = "auto"
    list_threshold: int = 8
    prefilter_threshold: int = 20
    page_size: int = 10


@dataclass
class SecurityConfig:
    """Security-related startup settings."""

    audit_enabled: bool = True


@dataclass
class FeaturesConfig:
    """Lightweight feature flags for incubating behavior."""

    startup_audit: bool = False


GUI_THEMES = {
    "system": "System Default",
    "light": "Light",
    "dark": "Dark",
    "green_terminal": "Green Terminal",
    "amber_terminal": "Amber Terminal",
    "solarized": "Solarized",
    "hot_dog_stand": "Hot Dog Stand",
}

# Built-in ttk widget themes (no custom text-area colors, just ttk chrome).
GUI_TTK_THEMES = ("aqua", "clam", "alt", "default", "classic", "step", "vista", "xpnative", "winnative")


@dataclass
class GuiConfig:
    """GUI font and visual theme settings."""

    font_family: str = ""
    font_size: int = 0
    theme: str = "system"


@dataclass
class WebAttachConfig:
    """Settings for the /web and /web-preview attachment commands."""

    enabled: bool = True
    https_only: bool = True
    public_ip_only: bool = True
    tls13_only: bool = False  # experimental — breaks many sites
    allowed_ports: list[int] = field(default_factory=lambda: [80, 443])
    timeout_seconds: int = 20
    max_response_bytes: int = 2_000_000
    max_attachment_chars: int = 40_000
    preview_chars: int = 4_000
    engine_order: list[str] = field(default_factory=lambda: ["readability", "html2text"])
    follow_redirects: bool = True
    max_redirects: int = 5


@dataclass
class TuochatConfig:
    """Top-level configuration."""

    setup_version: int = CURRENT_SETUP_VERSION
    gitlab: GitLabConfig = field(default_factory=GitLabConfig)
    openrouter: OpenRouterConfig = field(default_factory=OpenRouterConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    personalization: PersonalizationConfig = field(default_factory=PersonalizationConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    records: RecordsConfig = field(default_factory=RecordsConfig)
    warn_words: WarnWordsConfig = field(default_factory=WarnWordsConfig)
    picker: PickerConfig = field(default_factory=PickerConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    web_attach: WebAttachConfig = field(default_factory=WebAttachConfig)
    gui: GuiConfig = field(default_factory=GuiConfig)
    config_dir: Path = field(default_factory=config_dir)
    data_dir: Path = field(default_factory=data_dir)
    log_dir: Path = field(default_factory=log_dir)

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database."""
        return self.data_dir / "tuochat.db"

    @property
    def config_file(self) -> Path:
        """Path to the config file."""
        return self.config_dir / "config.toml"

    @property
    def custom_instructions_dir(self) -> Path:
        """Directory containing custom instruction files."""
        return self.config_dir / "custom_instructions"

    @property
    def skills_dir(self) -> Path:
        """Directory containing skill files."""
        return self.config_dir / "skills"

    @property
    def templates_dir(self) -> Path:
        """Directory containing prompt template files."""
        return self.config_dir / "templates"

    def validate(self) -> list[str]:
        """Return a list of validation warnings (empty = valid)."""
        warnings = []
        if not self.gitlab.host:
            warnings.append("GitLab host is not configured")
        if not self.gitlab.token:
            warnings.append("GitLab token is not configured")
        elif self.gitlab.token_type == "pat" and not self.gitlab.token.startswith(("glpat-", "gloas-")):  # nosec B105
            warnings.append("Token does not look like a GitLab PAT (expected glpat-... prefix)")
        return warnings

    def redacted(self) -> dict:
        """Return config as a dict with the token redacted."""
        return {
            "setup_version": self.setup_version,
            "gitlab": {
                "host": self.gitlab.host,
                "token": redact_token(self.gitlab.token),
                "token_type": self.gitlab.token_type,
                "user_agent": self.gitlab.user_agent,
            },
            "chat": {
                "platform_origin": self.chat.platform_origin,
                "default_resource_id": self.chat.default_resource_id,
                "timeout": self.chat.timeout,
                "websocket_welcome_timeout": self.chat.websocket_welcome_timeout,
                "websocket_subscription_timeout": self.chat.websocket_subscription_timeout,
                "streaming": self.chat.streaming,
                "mask_output": self.chat.mask_output,
                "dot_timer": self.chat.dot_timer,
                "quiet": self.chat.quiet,
                "no_banner": self.chat.no_banner,
                "blind": self.chat.blind,
                "response_footer_warning_enabled": self.chat.response_footer_warning_enabled,
                "response_footer_warning_text": self.chat.response_footer_warning_text,
                "generated_file_header_enabled": self.chat.generated_file_header_enabled,
                "generated_file_header_text": self.chat.generated_file_header_text,
                "max_request_chars": self.chat.max_request_chars,
                "context_window_tokens": self.chat.context_window_tokens,
                "conversation_expiration_days": self.chat.conversation_expiration_days,
                "no_write": self.chat.no_write,
                "tutorial_completed": self.chat.tutorial_completed,
                "safety_check_extension_for_executable_files": self.chat.safety_check_extension_for_executable_files,
            },
            "notifications": {
                "long_request_bell_enabled": self.notifications.long_request_bell_enabled,
                "long_request_bell_seconds": self.notifications.long_request_bell_seconds,
            },
            "personalization": {
                "enabled": self.personalization.enabled,
                "name": self.personalization.name,
                "profession": self.personalization.profession,
            },
            "classification": {
                "enabled": self.classification.enabled,
                "ask_per_conversation": self.classification.ask_per_conversation,
                "organizations": self.classification.organizations,
                "markings": self.classification.markings,
                "max_markings": self.classification.max_markings,
            },
            "records": {
                "retention_years": self.records.retention_years,
                "retention_label": self.records.retention_label,
            },
            "warn_words": {
                "enabled": self.warn_words.enabled,
                "phrases": self.warn_words.phrases,
            },
            "picker": {
                "mode": self.picker.mode,
                "list_threshold": self.picker.list_threshold,
                "prefilter_threshold": self.picker.prefilter_threshold,
                "page_size": self.picker.page_size,
            },
            "paths": {
                "config_dir": str(self.config_dir),
                "data_dir": str(self.data_dir),
                "log_dir": str(self.log_dir),
                "db_path": str(self.db_path),
            },
        }


def redact_token(token: str) -> str:
    """Redact a token for display, showing only first 8 chars."""
    if not token:
        return "(not set)"
    if len(token) <= 8:
        return "***"
    return token[:8] + "***"


def load_config(config_path: str | None = None) -> TuochatConfig:
    """Load configuration from TOML file with env var overrides.

    Priority (highest to lowest):
    1. Environment variables (TUOCHAT_GITLAB_HOST, TUOCHAT_GITLAB_TOKEN)
    2. Config file specified by TUOCHAT_CONFIG env var
    3. Config file at the platform-default location
    4. Built-in defaults
    """
    load_dotenv()
    cfg = TuochatConfig()

    # Determine config file path
    path_str = config_path or os.environ.get("TUOCHAT_CONFIG")
    if path_str:
        path = Path(path_str)
    else:
        path = cfg.config_file

    # Load TOML if it exists
    if path.is_file():
        logger.debug("Loading config from %s", path)
        with open(path, "rb") as f:
            data = toml_load(f)
        apply_toml(cfg, data)
    else:
        logger.debug("No config file at %s", path)

    # Environment variable overrides (highest priority)
    env_host = os.environ.get("TUOCHAT_GITLAB_HOST")
    if env_host:
        cfg.gitlab.host = normalize_gitlab_host(env_host)

    env_token = os.environ.get("TUOCHAT_GITLAB_TOKEN")
    if env_token:
        cfg.gitlab.token = env_token

    env_token_type = os.environ.get("TUOCHAT_GITLAB_TOKEN_TYPE")
    if env_token_type:
        cfg.gitlab.token_type = env_token_type

    env_user_agent = os.environ.get("TUOCHAT_GITLAB_USER_AGENT")
    if env_user_agent is not None:
        cfg.gitlab.user_agent = env_user_agent

    # OpenRouter environment variable overrides
    env_openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if env_openrouter_key:
        cfg.openrouter.api_key = env_openrouter_key

    env_openrouter_base = os.environ.get("OPENROUTER_BASE_URL")
    if env_openrouter_base:
        cfg.openrouter.base_url = env_openrouter_base

    env_openrouter_model = os.environ.get("OPENROUTER_MODEL")
    if env_openrouter_model:
        cfg.openrouter.model = env_openrouter_model

    env_openrouter_models = os.environ.get("OPENROUTER_MODELS")
    if env_openrouter_models:
        cfg.openrouter.models = [item.strip() for item in env_openrouter_models.split(",") if item.strip()]

    env_openrouter_rotate = os.environ.get("OPENROUTER_ROTATE_MODELS")
    if env_openrouter_rotate is not None:
        cfg.openrouter.rotate_models = env_openrouter_rotate.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    env_openrouter_referer = os.environ.get("OPENROUTER_HTTP_REFERER")
    if env_openrouter_referer:
        cfg.openrouter.http_referer = env_openrouter_referer

    env_openrouter_title = os.environ.get("OPENROUTER_X_TITLE")
    if env_openrouter_title:
        cfg.openrouter.x_title = env_openrouter_title

    # Jira environment variable overrides
    env_jira_host = os.environ.get("TUOCHAT_JIRA_HOST")
    if env_jira_host:
        cfg.jira.host = normalize_jira_host(env_jira_host)

    env_jira_deployment = os.environ.get("TUOCHAT_JIRA_DEPLOYMENT")
    if env_jira_deployment:
        cfg.jira.deployment = env_jira_deployment

    env_jira_email = os.environ.get("TUOCHAT_JIRA_EMAIL")
    if env_jira_email:
        cfg.jira.email = env_jira_email

    env_jira_token = os.environ.get("TUOCHAT_JIRA_TOKEN")
    if env_jira_token:
        cfg.jira.token = env_jira_token

    env_jira_project = os.environ.get("TUOCHAT_JIRA_PROJECT")
    if env_jira_project:
        cfg.jira.project = env_jira_project

    env_jira_ssl_ca_cert = os.environ.get("TUOCHAT_JIRA_SSL_CA_CERT")
    if env_jira_ssl_ca_cert:
        cfg.jira.ssl_ca_cert = env_jira_ssl_ca_cert

    # Resolve effective deployment (infer from host if not explicit)
    if cfg.jira.host and not cfg.jira.deployment:
        host_lower = cfg.jira.host.lower()
        if "atlassian.net" in host_lower:
            cfg.jira.deployment = "cloud"
        else:
            cfg.jira.deployment = "server"

    # If no plaintext token landed on the config (no env var, no value in
    # the TOML file), try the OS secret store. This is the common path for
    # users who completed the first-run wizard and chose keyring storage.
    if not cfg.gitlab.token and cfg.gitlab.host:
        try:
            from tuochat.security.credentials import load_from_keyring  # noqa: PLC0415

            stored = load_from_keyring(cfg.gitlab.host)
        except Exception as exc:  # pragma: no cover - keyring backend specific
            logger.warning(
                "keyring lookup failed during config load: %s",
                exc,
                extra={"winlog_event_id": winlog.EV_AUTH_FAILURE},
            )
            stored = None
        if stored is not None and stored.access_token:
            cfg.gitlab.token = stored.access_token
            cfg.gitlab.token_type = stored.token_type or cfg.gitlab.token_type

    # OpenRouter API key keyring fallback
    if not cfg.openrouter.api_key:
        try:
            from tuochat.security.openrouter_secret import load_api_key  # noqa: PLC0415

            stored_key = load_api_key()
        except Exception as exc:  # pragma: no cover - keyring backend specific
            logger.warning("keyring lookup for OpenRouter failed: %s", exc)
            stored_key = None
        if stored_key:
            cfg.openrouter.api_key = stored_key

    return cfg


def write_default_config(config_path: str | Path | None = None, *, force: bool = False) -> Path:
    """Create a starter config file and return its path."""
    cfg = TuochatConfig()
    if config_path is None:
        path = cfg.config_file
    else:
        path = Path(config_path).expanduser()

    if path.exists() and not force:
        raise FileExistsError(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "custom_instructions").mkdir(parents=True, exist_ok=True)
    (path.parent / "skills").mkdir(parents=True, exist_ok=True)
    (path.parent / "templates").mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(cfg), encoding="utf-8")
    return path


def render_config(cfg: TuochatConfig) -> str:
    """Render a config object to TOML."""

    def quote(value: str | None) -> str:
        raw = "" if value is None else str(value)
        escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def to_bool(value: bool) -> str:
        return "true" if value else "false"

    def to_list(values: list[str]) -> str:
        return "[" + ", ".join(quote(item) for item in values) + "]"

    return "\n".join(
        [
            f"setup_version = {int(cfg.setup_version)}",
            "",
            "[gitlab]",
            f"host = {quote(cfg.gitlab.host or 'https://gitlab.com')}",
            f"token = {quote(cfg.gitlab.token)}",
            f"token_type = {quote(cfg.gitlab.token_type)}",
            f"user_agent = {quote(cfg.gitlab.user_agent)}",
            "",
            "[openrouter]",
            f"api_key = {quote(cfg.openrouter.api_key)}",
            f"base_url = {quote(cfg.openrouter.base_url)}",
            f"model = {quote(cfg.openrouter.model)}",
            f"models = {to_list(cfg.openrouter.models)}",
            f"rotate_models = {to_bool(cfg.openrouter.rotate_models)}",
            f"http_referer = {quote(cfg.openrouter.http_referer)}",
            f"x_title = {quote(cfg.openrouter.x_title)}",
            "",
            "[chat]",
            f"platform_origin = {quote(cfg.chat.platform_origin)}",
            f"default_resource_id = {quote(cfg.chat.default_resource_id)}",
            f"timeout = {int(cfg.chat.timeout)}",
            f"websocket_welcome_timeout = {int(cfg.chat.websocket_welcome_timeout)}",
            f"websocket_subscription_timeout = {int(cfg.chat.websocket_subscription_timeout)}",
            f"streaming = {to_bool(cfg.chat.streaming)}",
            f"enable_no_stream = {to_bool(cfg.chat.enable_no_stream)}",
            f"mask_output = {to_bool(cfg.chat.mask_output)}",
            f"dot_timer = {to_bool(cfg.chat.dot_timer)}",
            f"quiet = {to_bool(cfg.chat.quiet)}",
            f"no_banner = {to_bool(cfg.chat.no_banner)}",
            f"blind = {to_bool(cfg.chat.blind)}",
            f"response_footer_warning_enabled = {to_bool(cfg.chat.response_footer_warning_enabled)}",
            f"response_footer_warning_text = {quote(cfg.chat.response_footer_warning_text)}",
            f"generated_file_header_enabled = {to_bool(cfg.chat.generated_file_header_enabled)}",
            f"generated_file_header_text = {quote(cfg.chat.generated_file_header_text)}",
            f"max_request_chars = {int(cfg.chat.max_request_chars)}",
            f"context_window_tokens = {int(cfg.chat.context_window_tokens)}",
            f"conversation_expiration_days = {int(cfg.chat.conversation_expiration_days)}",
            f"no_write = {to_bool(cfg.chat.no_write)}",
            f"tutorial_completed = {to_bool(cfg.chat.tutorial_completed)}",
            f"safety_check_extension_for_executable_files = {to_bool(cfg.chat.safety_check_extension_for_executable_files)}",
            "",
            "[notifications]",
            f"long_request_bell_enabled = {to_bool(cfg.notifications.long_request_bell_enabled)}",
            f"long_request_bell_seconds = {int(cfg.notifications.long_request_bell_seconds)}",
            "",
            "[personalization]",
            f"enabled = {to_bool(cfg.personalization.enabled)}",
            f"name = {quote(cfg.personalization.name)}",
            f"profession = {quote(cfg.personalization.profession)}",
            "",
            "[classification]",
            f"enabled = {to_bool(cfg.classification.enabled)}",
            f"ask_per_conversation = {to_bool(cfg.classification.ask_per_conversation)}",
            f"organizations = {to_list(cfg.classification.organizations)}",
            f"markings = {to_list(cfg.classification.markings)}",
            f"max_markings = {to_list(cfg.classification.max_markings)}",
            "",
            "[records]",
            f"retention_years = {int(cfg.records.retention_years)}",
            f"retention_label = {quote(cfg.records.retention_label)}",
            "",
            "[warn_words]",
            f"enabled = {to_bool(cfg.warn_words.enabled)}",
            f"phrases = {to_list(cfg.warn_words.phrases)}",
            "",
            "[picker]",
            f"mode = {quote(cfg.picker.mode)}",
            f"list_threshold = {int(cfg.picker.list_threshold)}",
            f"prefilter_threshold = {int(cfg.picker.prefilter_threshold)}",
            f"page_size = {int(cfg.picker.page_size)}",
            "",
            "[features]",
            f"startup_audit = {to_bool(cfg.features.startup_audit)}",
            "",
            "[security]",
            f"audit_enabled = {to_bool(cfg.security.audit_enabled)}",
            "",
            "[web_attach]",
            f"enabled = {to_bool(cfg.web_attach.enabled)}",
            f"https_only = {to_bool(cfg.web_attach.https_only)}",
            f"public_ip_only = {to_bool(cfg.web_attach.public_ip_only)}",
            f"tls13_only = {to_bool(cfg.web_attach.tls13_only)}",
            f"allowed_ports = [{', '.join(str(p) for p in cfg.web_attach.allowed_ports)}]",
            f"timeout_seconds = {int(cfg.web_attach.timeout_seconds)}",
            f"max_response_bytes = {int(cfg.web_attach.max_response_bytes)}",
            f"max_attachment_chars = {int(cfg.web_attach.max_attachment_chars)}",
            f"preview_chars = {int(cfg.web_attach.preview_chars)}",
            f"engine_order = {to_list(cfg.web_attach.engine_order)}",
            f"follow_redirects = {to_bool(cfg.web_attach.follow_redirects)}",
            f"max_redirects = {int(cfg.web_attach.max_redirects)}",
            "",
            "[gui]",
            f"font_family = {quote(cfg.gui.font_family)}",
            f"font_size = {int(cfg.gui.font_size)}",
            f"theme = {quote(cfg.gui.theme)}",
            "",
            "# [jira]",
            '# host = "https://yourcompany.atlassian.net"',
            '# deployment = "cloud"   # cloud or server (inferred from host if omitted)',
            '# email = "you@example.com"  # required for cloud auth',
            '# token = ""',
            '# project = ""  # optional last-used project key',
            '# ssl_ca_cert = ""  # path to CA bundle for self-signed/private PKI certs',
            '#                    set to "false" to disable SSL verification (insecure)',
            "",
        ]
    )


def save_config(cfg: TuochatConfig, config_path: str | Path | None = None) -> Path:
    """Write a config object to disk and return its path."""
    path = Path(config_path).expanduser() if config_path is not None else cfg.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "custom_instructions").mkdir(parents=True, exist_ok=True)
    (path.parent / "skills").mkdir(parents=True, exist_ok=True)
    (path.parent / "templates").mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(cfg), encoding="utf-8")
    return path


def apply_toml(cfg: TuochatConfig, data: dict) -> None:
    """Apply parsed TOML data to a config object."""
    if "setup_version" in data:
        cfg.setup_version = max(1, int(data["setup_version"]))

    gl = data.get("gitlab", {})
    if "host" in gl:
        cfg.gitlab.host = normalize_gitlab_host(str(gl["host"]))
    if "token" in gl:
        cfg.gitlab.token = str(gl["token"])
    if "token_type" in gl:
        cfg.gitlab.token_type = str(gl["token_type"])
    if "user_agent" in gl:
        cfg.gitlab.user_agent = str(gl["user_agent"])

    openrouter = data.get("openrouter", {})
    if "api_key" in openrouter:
        cfg.openrouter.api_key = str(openrouter["api_key"])
    if "base_url" in openrouter:
        cfg.openrouter.base_url = str(openrouter["base_url"]) or DEFAULT_OPENROUTER_BASE_URL
    if "model" in openrouter:
        cfg.openrouter.model = str(openrouter["model"])
    if "models" in openrouter:
        cfg.openrouter.models = [str(item) for item in openrouter["models"]]
    if "rotate_models" in openrouter:
        cfg.openrouter.rotate_models = bool(openrouter["rotate_models"])
    if "http_referer" in openrouter:
        cfg.openrouter.http_referer = str(openrouter["http_referer"])
    if "x_title" in openrouter:
        cfg.openrouter.x_title = str(openrouter["x_title"])

    chat = data.get("chat", {})
    if "platform_origin" in chat:
        cfg.chat.platform_origin = str(chat["platform_origin"])
    if "default_resource_id" in chat:
        val = chat["default_resource_id"]
        cfg.chat.default_resource_id = str(val) if val else None
    if "timeout" in chat:
        cfg.chat.timeout = int(chat["timeout"])
    if "websocket_welcome_timeout" in chat:
        cfg.chat.websocket_welcome_timeout = max(1, int(chat["websocket_welcome_timeout"]))
    if "websocket_subscription_timeout" in chat:
        cfg.chat.websocket_subscription_timeout = max(1, int(chat["websocket_subscription_timeout"]))
    if "streaming" in chat:
        cfg.chat.streaming = bool(chat["streaming"])
    if "enable_no_stream" in chat:
        cfg.chat.enable_no_stream = bool(chat["enable_no_stream"])
    if "mask_output" in chat:
        cfg.chat.mask_output = bool(chat["mask_output"])
    if "dot_timer" in chat:
        cfg.chat.dot_timer = bool(chat["dot_timer"])
    if "quiet" in chat:
        cfg.chat.quiet = bool(chat["quiet"])
    if "no_banner" in chat:
        cfg.chat.no_banner = bool(chat["no_banner"])
    if "blind" in chat:
        cfg.chat.blind = bool(chat["blind"])
    if "response_footer_warning_enabled" in chat:
        cfg.chat.response_footer_warning_enabled = bool(chat["response_footer_warning_enabled"])
    if "response_footer_warning_text" in chat:
        cfg.chat.response_footer_warning_text = str(chat["response_footer_warning_text"])
    if "generated_file_header_enabled" in chat:
        cfg.chat.generated_file_header_enabled = bool(chat["generated_file_header_enabled"])
    if "generated_file_header_text" in chat:
        cfg.chat.generated_file_header_text = str(chat["generated_file_header_text"])
    if "max_request_chars" in chat:
        cfg.chat.max_request_chars = max(1, int(chat["max_request_chars"]))
    if "context_window_tokens" in chat:
        cfg.chat.context_window_tokens = max(1, int(chat["context_window_tokens"]))
    if "conversation_expiration_days" in chat:
        cfg.chat.conversation_expiration_days = max(0, int(chat["conversation_expiration_days"]))
    if "no_write" in chat:
        cfg.chat.no_write = bool(chat["no_write"])
    if "tutorial_completed" in chat:
        cfg.chat.tutorial_completed = bool(chat["tutorial_completed"])
    if "safety_check_extension_for_executable_files" in chat:
        cfg.chat.safety_check_extension_for_executable_files = bool(chat["safety_check_extension_for_executable_files"])

    notifications = data.get("notifications", {})
    if "long_request_bell_enabled" in notifications:
        cfg.notifications.long_request_bell_enabled = bool(notifications["long_request_bell_enabled"])
    if "long_request_bell_seconds" in notifications:
        cfg.notifications.long_request_bell_seconds = max(1, int(notifications["long_request_bell_seconds"]))

    personalization = data.get("personalization", {})
    if "enabled" in personalization:
        cfg.personalization.enabled = bool(personalization["enabled"])
    if "name" in personalization:
        cfg.personalization.name = str(personalization["name"])
    if "profession" in personalization:
        cfg.personalization.profession = str(personalization["profession"])

    classification = data.get("classification", {})
    if "enabled" in classification:
        cfg.classification.enabled = bool(classification["enabled"])
    if "ask_per_conversation" in classification:
        cfg.classification.ask_per_conversation = bool(classification["ask_per_conversation"])
    if "organizations" in classification:
        cfg.classification.organizations = [str(item) for item in classification["organizations"]]
    elif "organizations" in personalization:
        cfg.classification.organizations = [str(item) for item in personalization["organizations"]]
    if "markings" in classification:
        cfg.classification.markings = [str(item) for item in classification["markings"]]
    elif "markings" in personalization:
        cfg.classification.markings = [str(item) for item in personalization["markings"]]
    if "max_markings" in classification:
        cfg.classification.max_markings = [str(item) for item in classification["max_markings"]]

    records = data.get("records", {})
    if "retention_years" in records:
        cfg.records.retention_years = max(0, int(records["retention_years"]))
    if "retention_label" in records:
        cfg.records.retention_label = str(records["retention_label"])

    warn_words = data.get("warn_words", {})
    if "enabled" in warn_words:
        cfg.warn_words.enabled = bool(warn_words["enabled"])
    if "phrases" in warn_words:
        cfg.warn_words.phrases = [str(item) for item in warn_words["phrases"]]

    picker = data.get("picker", {})
    if "mode" in picker:
        cfg.picker.mode = str(picker["mode"])
    if "list_threshold" in picker:
        cfg.picker.list_threshold = max(0, int(picker["list_threshold"]))
    if "prefilter_threshold" in picker:
        cfg.picker.prefilter_threshold = max(0, int(picker["prefilter_threshold"]))
    if "page_size" in picker:
        cfg.picker.page_size = max(1, int(picker["page_size"]))

    features = data.get("features", {})
    if "startup_audit" in features:
        cfg.features.startup_audit = bool(features["startup_audit"])

    security = data.get("security", {})
    if "audit_enabled" in security:
        cfg.security.audit_enabled = bool(security["audit_enabled"])

    web_attach = data.get("web_attach", {})
    if "enabled" in web_attach:
        cfg.web_attach.enabled = bool(web_attach["enabled"])
    if "https_only" in web_attach:
        cfg.web_attach.https_only = bool(web_attach["https_only"])
    if "public_ip_only" in web_attach:
        cfg.web_attach.public_ip_only = bool(web_attach["public_ip_only"])
    if "tls13_only" in web_attach:
        cfg.web_attach.tls13_only = bool(web_attach["tls13_only"])
    if "allowed_ports" in web_attach:
        cfg.web_attach.allowed_ports = [int(p) for p in web_attach["allowed_ports"]]
    if "timeout_seconds" in web_attach:
        cfg.web_attach.timeout_seconds = max(1, int(web_attach["timeout_seconds"]))
    if "max_response_bytes" in web_attach:
        cfg.web_attach.max_response_bytes = max(1024, int(web_attach["max_response_bytes"]))
    if "max_attachment_chars" in web_attach:
        cfg.web_attach.max_attachment_chars = max(100, int(web_attach["max_attachment_chars"]))
    if "preview_chars" in web_attach:
        cfg.web_attach.preview_chars = max(100, int(web_attach["preview_chars"]))
    if "engine_order" in web_attach:
        cfg.web_attach.engine_order = [str(e) for e in web_attach["engine_order"]]
    if "follow_redirects" in web_attach:
        cfg.web_attach.follow_redirects = bool(web_attach["follow_redirects"])
    if "max_redirects" in web_attach:
        cfg.web_attach.max_redirects = max(0, int(web_attach["max_redirects"]))

    gui = data.get("gui", {})
    if "font_family" in gui:
        cfg.gui.font_family = str(gui["font_family"])
    if "font_size" in gui:
        cfg.gui.font_size = max(0, int(gui["font_size"]))
    if "theme" in gui:
        cfg.gui.theme = str(gui["theme"])

    jira = data.get("jira", {})
    if "host" in jira:
        cfg.jira.host = normalize_jira_host(str(jira["host"]))
    if "deployment" in jira:
        cfg.jira.deployment = str(jira["deployment"])
    if "email" in jira:
        cfg.jira.email = str(jira["email"])
    if "token" in jira:
        cfg.jira.token = str(jira["token"])
    if "project" in jira:
        cfg.jira.project = str(jira["project"])
    if "ssl_ca_cert" in jira:
        cfg.jira.ssl_ca_cert = str(jira["ssl_ca_cert"])
