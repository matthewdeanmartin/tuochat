"""Interactive setup and classification helpers for the CLI."""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from tuochat.cli.prompts import (
    dedupe_preserve_order,
    prompt_bool,
    prompt_csv_list,
    prompt_input,
    prompt_int,
    prompt_pick_many,
    prompt_text,
)
from tuochat.config import CURRENT_SETUP_VERSION, TuochatConfig
from tuochat.constants import (
    CLASSIFICATION_ANY,
    CLASSIFICATION_UNCLASSIFIED,
    CLASSIFICATION_UNKNOWN,
    ORG_MARKINGS,
    ORG_OPTIONS,
    canonical_classification_name,
    classification_display_label,
    classification_help_label,
)

logger = logging.getLogger("tuochat.cli")


def markings_for_orgs(orgs: list[str]) -> list[str]:
    """Return canned markings for the selected organizations."""
    if not orgs or "All" in orgs:
        values = [marking for items in ORG_MARKINGS.values() for marking in items]
    else:
        values = [marking for org in orgs for marking in ORG_MARKINGS.get(org, [])]
    return dedupe_preserve_order([CLASSIFICATION_UNCLASSIFIED, *values])


def configured_classifications(cfg: TuochatConfig) -> list[str]:
    """Return canonical configured classifications without the always-on built-ins duplicated."""
    raw_markings = list(getattr(getattr(cfg, "classification", None), "markings", None) or [])
    resolved: list[str] = []
    for raw in raw_markings:
        canonical = canonical_classification_name(str(raw))
        if not canonical:
            continue
        resolved.append(canonical)
    return [
        item
        for item in dedupe_preserve_order(resolved)
        if item not in {CLASSIFICATION_UNKNOWN, CLASSIFICATION_UNCLASSIFIED}
    ]


def get_valid_classifications(cfg: TuochatConfig) -> list[str]:
    """Return the list of valid classification choices, including always-on built-ins."""
    return dedupe_preserve_order(
        [CLASSIFICATION_UNKNOWN, CLASSIFICATION_UNCLASSIFIED, *configured_classifications(cfg)]
    )


def classification_rank_map(cfg: TuochatConfig) -> dict[str, int]:
    """Return the configured classification ordering."""
    markings = [CLASSIFICATION_UNCLASSIFIED, *configured_classifications(cfg)]
    return {marking.upper(): index for index, marking in enumerate(markings)}


def normalized_max_classifications(cfg: TuochatConfig) -> list[str]:
    """Return normalized configured max classifications."""
    raw_values = list(getattr(getattr(cfg, "classification", None), "max_markings", None) or [])
    if not raw_values:
        return []
    valid = get_valid_classifications(cfg)
    valid_by_upper = {item.upper(): item for item in valid}
    resolved: list[str] = []
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            continue
        if text.upper() == CLASSIFICATION_ANY.upper():
            return [CLASSIFICATION_ANY]
        resolved.append(valid_by_upper.get(text.upper(), canonical_classification_name(text) or text))
    return dedupe_preserve_order(resolved)


def classification_within_max(cfg: TuochatConfig, classification: str) -> bool:
    """Return whether a classification is at or below the configured maximum."""
    maximums = normalized_max_classifications(cfg)
    if not maximums or CLASSIFICATION_ANY in maximums:
        return True
    if classification == CLASSIFICATION_UNKNOWN:
        return True
    rank_map = classification_rank_map(cfg)
    chosen_rank = rank_map.get(classification.upper())
    if chosen_rank is None:
        return False
    allowed_ranks = [rank_map[item.upper()] for item in maximums if item.upper() in rank_map]
    if not allowed_ranks:
        return True
    return chosen_rank <= max(allowed_ranks)


def classification_limit_message(cfg: TuochatConfig) -> str:
    """Return the max-classification error text."""
    maximums = normalized_max_classifications(cfg)
    if not maximums or CLASSIFICATION_ANY in maximums:
        return ""
    return f"No classifications higher than {', '.join(classification_display_label(item) for item in maximums)}."


def resolve_classification_choice(cfg: TuochatConfig, raw: str) -> str | None:
    """Resolve a raw classification input to a configured value.

    Exact configured labels win before numbered-picker indexes so numeric
    markings such as ``2`` remain selectable.
    """
    text = raw.strip()
    if not text:
        return None
    options = get_valid_classifications(cfg)
    upper = text.upper()
    for opt in options:
        if opt.upper() == upper:
            return opt
    canonical_input = canonical_classification_name(text)
    for opt in options:
        canonical = canonical_classification_name(opt)
        if canonical is not None and canonical_input == canonical:
            return opt
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(options):
            return options[index]
        return None
    return None


def prompt_classification(
    cfg: TuochatConfig,
    *,
    current: str | None = None,
    upcoming: bool = False,
    default: str | None = None,
) -> str | None:
    """Interactively ask the user to pick a classification marking.

    Returns the chosen marking string, or None if cancelled.
    When *default* is set, pressing Enter without input returns that value.
    """
    options = get_valid_classifications(cfg)
    label = "the upcoming conversation" if upcoming else "this conversation"
    print(f"Document classification for {label}:")
    for idx, opt in enumerate(options, start=1):
        marker = " *" if opt == current else ""
        print(f"  [{idx}] {classification_help_label(opt)}{marker}")
    if default:
        print(f"  (press Enter to keep last: {classification_display_label(default)})")
    while True:
        raw = prompt_input("classify> ").strip()
        if not raw:
            return default
        chosen = resolve_classification_choice(cfg, raw)
        if chosen is None:
            if raw.isdigit():
                print("Selection out of range.", file=sys.stderr)
            else:
                print(f"Unknown classification '{raw}'. Pick from the list.", file=sys.stderr)
            continue
        if not classification_within_max(cfg, chosen):
            print(classification_limit_message(cfg), file=sys.stderr)
            continue
        return chosen


def format_default_prompt(prompt: str, default: str | None) -> str:
    """Render a prompt string with a visible default when useful."""
    if default is None or default == "":
        return f"{prompt}: "
    return f"{prompt} [{default}]: "


def print_resource_id_guidance() -> None:
    """Explain what the Duo resource id is and when users need it."""
    print("Default resource ID guidance:")
    print("  This is the GitLab project or group context sent to Duo Chat.")
    print("  If you do not know it, leave it blank. Tuochat works without a default resource ID.")
    print("  Only fill it in if your Duo setup expects a specific GitLab project/group context.")
    print("  If someone gave you one, it is usually a GitLab global ID or an internal app-specific resource string.")
    print()


def config_requires_upgrade(path: Path) -> bool:
    """Return True when an existing config predates the current guided setup."""
    from tuochat.serialization import toml_load

    if not path.is_file():
        return False
    try:
        with open(path, "rb") as handle:
            data = toml_load(handle)
    except Exception:
        return False
    version = int(data.get("setup_version", 1))
    chat = data.get("chat", {})
    personalization = data.get("personalization", {})
    classification = data.get("classification", {})
    return (
        version < CURRENT_SETUP_VERSION
        or "generated_file_header_enabled" not in chat
        or "generated_file_header_text" not in chat
        or "tutorial_completed" not in chat
        or "safety_check_extension_for_executable_files" not in chat
        or ("organizations" not in classification and "organizations" not in personalization)
        or ("markings" not in classification and "markings" not in personalization)
        or "max_markings" not in classification
    )


def run_init_wizard(*, config_path: str | Path | None, force: bool) -> Path:
    """Interactively create or update the config file."""
    from tuochat.config import load_config, normalize_gitlab_host, save_config

    default_cfg = TuochatConfig()
    target = Path(config_path).expanduser() if config_path is not None else default_cfg.config_file
    cfg = load_config(str(target)) if target.exists() else default_cfg
    if target.exists() and not force:
        raise FileExistsError(f"Config file already exists: {target}")

    print("Tuochat guided setup")
    print(f"Config file: {target}")
    print()

    host = prompt_text(
        format_default_prompt("GitLab server URL", cfg.gitlab.host or "https://gitlab.com"),
        default=cfg.gitlab.host or "https://gitlab.com",
    )
    cfg.gitlab.host = normalize_gitlab_host(host)
    cfg.setup_version = CURRENT_SETUP_VERSION

    # Credentials: PAT vs OAuth, and where to store them. The auth_cmd
    # helper handles keyring vs config-file persistence so the same
    # logic powers both first-run and `tuochat auth login`.
    if not cfg.gitlab.token:
        from tuochat.cli.commands.auth_cmd import interactive_login  # noqa: PLC0415

        try:
            interactive_login(cfg)
        except Exception as exc:  # pragma: no cover - network/browser dependent
            print(f"Credential setup failed: {exc}")
            print("You can finish setup later with `tuochat auth login`.")
    else:
        print("(keeping existing token from config / environment)")

    # Set sensible defaults for settings not explicitly asked
    cfg.chat.no_banner = True

    print()
    print("Accessibility")
    cfg.chat.blind = prompt_bool("Enable blind-friendly / screen-reader mode?", default=cfg.chat.blind)
    if cfg.chat.blind:
        cfg.chat.no_banner = True

    print()
    print("AI response warnings")
    cfg.chat.response_footer_warning_enabled = prompt_bool(
        "Show a disclaimer footer after each AI response?",
        default=cfg.chat.response_footer_warning_enabled,
    )
    if cfg.chat.response_footer_warning_enabled:
        cfg.chat.response_footer_warning_text = prompt_text(
            format_default_prompt("Footer warning text", cfg.chat.response_footer_warning_text),
            default=cfg.chat.response_footer_warning_text,
        )

    print()
    print("Generated file headers")
    cfg.chat.generated_file_header_enabled = prompt_bool(
        "Add a generated-by header to AI-extracted code files?",
        default=cfg.chat.generated_file_header_enabled,
    )
    if cfg.chat.generated_file_header_enabled:
        cfg.chat.generated_file_header_text = prompt_text(
            format_default_prompt("Header text (`{date}` is supported)", cfg.chat.generated_file_header_text),
            default=cfg.chat.generated_file_header_text,
        )

    print()
    print("Request limits")
    cfg.chat.max_request_chars = prompt_int(
        "Max characters per request (limits context sent to AI)",
        default=cfg.chat.max_request_chars,
        minimum=1000,
    )
    cfg.chat.context_window_tokens = prompt_int(
        "Context window tokens (model limit, used for estimation)",
        default=cfg.chat.context_window_tokens,
        minimum=1000,
    )
    cfg.chat.conversation_expiration_days = prompt_int(
        "Auto-delete conversations older than N days (0 = keep forever)",
        default=cfg.chat.conversation_expiration_days,
        minimum=0,
    )
    cfg.chat.no_write = prompt_bool(
        "No-write mode — disable local conversation history?",
        default=cfg.chat.no_write,
    )

    print()
    print("Personalization")
    cfg.personalization.enabled = prompt_bool(
        "Inject your name and role into the first message of each conversation?",
        default=cfg.personalization.enabled,
    )
    if cfg.personalization.enabled:
        cfg.personalization.name = prompt_text(
            format_default_prompt("Name", cfg.personalization.name),
            default=cfg.personalization.name,
        )
        cfg.personalization.profession = prompt_text(
            format_default_prompt("Profession / role", cfg.personalization.profession),
            default=cfg.personalization.profession,
        )

    print()
    print("Document classifications")
    cfg.classification.enabled = prompt_bool(
        "Enable document classification prompts for each conversation?",
        default=cfg.classification.enabled,
    )
    if cfg.classification.enabled:
        cfg.classification.ask_per_conversation = prompt_bool(
            "Ask for a classification at the start of each new conversation?",
            default=cfg.classification.ask_per_conversation,
        )
        cfg.classification.organizations = prompt_pick_many(
            "Pick organizations whose classification markings you use:",
            ORG_OPTIONS,
            default=cfg.classification.organizations,
        )
        available_markings = markings_for_orgs(cfg.classification.organizations)
        cfg.classification.markings = prompt_pick_many(
            "Pick the classification markings allowed for your conversations:",
            ["All", *available_markings],
            default=cfg.classification.markings
            or (["All"] if available_markings and len(available_markings) == 1 else []),
        )
        if "All" in cfg.classification.markings:
            cfg.classification.markings = available_markings
        cfg.classification.max_markings = prompt_pick_many(
            "Pick the highest classification(s) you are allowed to use (Any = no limit):",
            [CLASSIFICATION_ANY, *cfg.classification.markings],
            default=cfg.classification.max_markings or [CLASSIFICATION_ANY],
        )
        if CLASSIFICATION_ANY in cfg.classification.max_markings:
            cfg.classification.max_markings = [CLASSIFICATION_ANY]
    else:
        cfg.classification.ask_per_conversation = False
        cfg.classification.max_markings = []

    print()
    print("Warn words")
    cfg.warn_words.enabled = prompt_bool(
        "Warn before sending if the message contains certain words or phrases?",
        default=cfg.warn_words.enabled,
    )
    if cfg.warn_words.enabled:
        cfg.warn_words.phrases = prompt_csv_list(
            "Warn words / phrases (comma-separated, blank keeps current)",
            default=cfg.warn_words.phrases,
        )

    print()
    print("Notifications")
    cfg.notifications.long_request_bell_enabled = prompt_bool(
        "Play a bell when a request takes a long time?",
        default=cfg.notifications.long_request_bell_enabled,
    )
    if cfg.notifications.long_request_bell_enabled:
        cfg.notifications.long_request_bell_seconds = prompt_int(
            "Bell after how many seconds?",
            default=cfg.notifications.long_request_bell_seconds,
            minimum=1,
        )

    print()
    advanced = prompt_bool("Configure advanced settings? (timeouts, streaming, masking, etc.)", default=False)
    if advanced:
        print()
        print("Advanced settings")
        print_resource_id_guidance()
        cfg.chat.default_resource_id = (
            prompt_text(
                format_default_prompt("Default resource ID (leave blank if unknown)", cfg.chat.default_resource_id),
                default=cfg.chat.default_resource_id,
            )
            or None
        )
        cfg.chat.timeout = prompt_int("Request timeout seconds", default=cfg.chat.timeout, minimum=1)
        cfg.chat.websocket_welcome_timeout = prompt_int(
            "WebSocket welcome timeout seconds",
            default=cfg.chat.websocket_welcome_timeout,
            minimum=1,
        )
        cfg.chat.websocket_subscription_timeout = prompt_int(
            "WebSocket subscription timeout seconds",
            default=cfg.chat.websocket_subscription_timeout,
            minimum=1,
        )
        cfg.chat.streaming = prompt_bool("Enable streaming replies?", default=cfg.chat.streaming)
        cfg.chat.mask_output = prompt_bool("Mask sensitive output on screen?", default=cfg.chat.mask_output)
        cfg.chat.dot_timer = prompt_bool("Show the dot timer during long requests?", default=cfg.chat.dot_timer)
        cfg.chat.quiet = prompt_bool("Use quiet mode?", default=cfg.chat.quiet)
        cfg.chat.no_banner = prompt_bool("Hide the startup banner?", default=cfg.chat.no_banner)
        cfg.chat.safety_check_extension_for_executable_files = prompt_bool(
            "Add .check to non-.txt/.md extracted files for safety?",
            default=cfg.chat.safety_check_extension_for_executable_files,
        )
        cfg.chat.tutorial_completed = prompt_bool("Mark the built-in tutorial as already completed?", default=False)

    path = save_config(cfg, target)
    print()
    print(f"Saved config: {path}")
    print("You can review the active config later with `tuochat config`.")
    return path


def is_first_run(cfg: TuochatConfig, *, config_path: str | Path | None = None) -> bool:
    """Return True when no usable config or env-backed credentials exist yet."""
    has_env_credentials = bool(os.environ.get("TUOCHAT_GITLAB_HOST") and os.environ.get("TUOCHAT_GITLAB_TOKEN"))
    has_openrouter_configuration = bool(cfg.openrouter.api_key and cfg.openrouter.effective_models())
    target = Path(config_path).expanduser() if config_path else cfg.config_file
    return (
        not target.is_file()
        and not has_env_credentials
        and not cfg.gitlab.host
        and not cfg.gitlab.token
        and not has_openrouter_configuration
    )


def maybe_run_first_run_setup(cfg: TuochatConfig, *, config_path: str | Path | None = None) -> TuochatConfig:
    """Offer and run interactive setup on first use."""
    target = Path(config_path).expanduser() if config_path else cfg.config_file
    if is_first_run(cfg, config_path=config_path):
        print("No Tuochat config was found, so first-run setup is starting now.")
        path = run_init_wizard(config_path=target, force=True)
    elif config_requires_upgrade(target):
        print(
            "Your config is missing newer setup fields for personalization, document classifications, or generated-file headers."
        )
        choice = prompt_input("Run guided setup now to update it in place? [Y/n] ").strip().lower()
        if choice in {"", "y", "yes"}:
            path = run_init_wizard(config_path=target, force=True)
        else:
            return cfg
    else:
        return cfg

    from tuochat.config import load_config

    return load_config(str(path))


def should_offer_first_run_tutorial(cfg: TuochatConfig) -> bool:
    """Return whether the tutorial should auto-run."""
    return not bool(getattr(getattr(cfg, "chat", None), "tutorial_completed", False))


__all__ = [
    "markings_for_orgs",
    "get_valid_classifications",
    "classification_rank_map",
    "normalized_max_classifications",
    "classification_within_max",
    "classification_limit_message",
    "resolve_classification_choice",
    "prompt_classification",
    "format_default_prompt",
    "print_resource_id_guidance",
    "config_requires_upgrade",
    "run_init_wizard",
    "is_first_run",
    "maybe_run_first_run_setup",
    "should_offer_first_run_tutorial",
]
