"""Stable constants for tuochat — changes only when pricing or specs change."""

from __future__ import annotations

from dataclasses import dataclass

INPUT_COST_PER_MILLION_TOKENS = 3.0
OUTPUT_COST_PER_MILLION_TOKENS = 15.0
MASK_HOLDBACK_CHARS = 256

LANG_TO_EXT: dict[str, str] = {
    "bash": ".sh",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "css": ".css",
    "go": ".go",
    "html": ".html",
    "java": ".java",
    "javascript": ".js",
    "js": ".js",
    "json": ".json",
    "markdown": ".md",
    "md": ".md",
    "python": ".py",
    "py": ".py",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "ruby": ".rb",
    "rust": ".rs",
    "sh": ".sh",
    "sql": ".sql",
    "text": ".txt",
    "toml": ".toml",
    "ts": ".ts",
    "tsx": ".tsx",
    "typescript": ".ts",
    "xml": ".xml",
    "yaml": ".yaml",
    "yml": ".yml",
}
SAFE_EXTRACTED_SUFFIXES = {".md", ".txt"}
KNOWN_EXTRACTED_SUFFIXES = {suffix.lower() for suffix in LANG_TO_EXT.values()}

NO_CODE_MODE_REPLACEMENT = "```\n(code removed due to no-code-mode)\n```"
SHELL_FENCE_LANGS = {
    "bash",
    "sh",
    "shell",
    "zsh",
    "fish",
    "powershell",
    "ps1",
    "cmd",
    "bat",
    "batch",
    "console",
    "shell-session",
}

DEFAULT_MAP_GLOBS = [
    "*.md",
    "*.txt",
    "*.py",
    "*.toml",
    "*.json",
    "*.yaml",
    "*.yml",
    "*.ini",
    "*.cfg",
    "*.sh",
    "*.ps1",
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.css",
    "*.html",
    "*.sql",
    "AGENTS.md",
    "README*",
]

WORKSPACE_SKILL_ROOTS = (".agents/skills", ".claude/skills", ".augment/skills", ".gitlab/duo/skills")
WORKSPACE_TEMPLATE_ROOTS = (".agents/templates", ".claude/templates", ".augment/templates")
WORKSPACE_CUSTOM_INSTRUCTION_ROOTS = (
    ".tuochat/custom_instructions",
    ".agents/custom_instructions",
    ".claude/custom_instructions",
    ".augment/custom_instructions",
)
DEFAULT_CUSTOM_INSTRUCTION_FILENAME = "INSTRUCTIONS.md"

SKILL_SOURCE_LABELS: dict[str, str] = {
    "central": "Central",
    "bundled": "Bundled",
    "workspace": "Cwd-relative",
}
CUSTOM_INSTRUCTION_SOURCE_LABELS: dict[str, str] = {
    "central": "Central",
    "bundled": "Bundled",
    "workspace": "Cwd-relative",
}

MODEL_LABELS: dict[str, str] = {
    "duo": "Duo",
    "eliza": "Eliza",
    "openrouter": "OpenRouter",
}

CONTEXT_BOX_WIDTH = 116
CLASSIFICATION_ANY = "Any"
CLASSIFICATION_UNKNOWN = "Classification pending review"
CLASSIFICATION_UNCLASSIFIED = "Unclassified"


@dataclass(frozen=True)
class ClassificationDefinition:
    """Human-readable metadata for a document classification."""

    abbreviation: str
    full_name: str
    meaning: str
    aliases: tuple[str, ...] = ()


CLASSIFICATION_DEFINITIONS: dict[str, ClassificationDefinition] = {
    CLASSIFICATION_UNKNOWN: ClassificationDefinition(
        abbreviation="PENDING",
        full_name=CLASSIFICATION_UNKNOWN,
        meaning="The correct sensitivity has not been confirmed yet and needs review before wider handling.",
        aliases=("pending review", "pending", "unknown", "i don't know", "dont know yet"),
    ),
    CLASSIFICATION_UNCLASSIFIED: ClassificationDefinition(
        abbreviation="U",
        full_name=CLASSIFICATION_UNCLASSIFIED,
        meaning="Approved for routine handling without special access restrictions.",
        aliases=("unclass",),
    ),
    "CUI": ClassificationDefinition(
        abbreviation="CUI",
        full_name="Controlled Unclassified Information",
        meaning="Unclassified information that still requires safeguarding or distribution controls.",
    ),
    "CONFIDENTIAL": ClassificationDefinition(
        abbreviation="CONFIDENTIAL",
        full_name="Confidential",
        meaning="Unauthorized disclosure could reasonably be expected to cause damage.",
    ),
    "FOUO": ClassificationDefinition(
        abbreviation="FOUO",
        full_name="For Official Use Only",
        meaning="Legacy U.S. government marking for information intended only for official business use.",
    ),
    "INTERNAL": ClassificationDefinition(
        abbreviation="INTERNAL",
        full_name="Internal",
        meaning="For internal organizational use and not intended for public release.",
    ),
    "LES": ClassificationDefinition(
        abbreviation="LES",
        full_name="Law Enforcement Sensitive",
        meaning="Sensitive law-enforcement information that should stay within authorized channels.",
    ),
    "NOFORN": ClassificationDefinition(
        abbreviation="NOFORN",
        full_name="Not Releasable to Foreign Nationals",
        meaning="Must not be shared with foreign nationals or foreign governments.",
    ),
    "ORCON": ClassificationDefinition(
        abbreviation="ORCON",
        full_name="Originator Controlled",
        meaning="Further sharing requires approval from the original information owner.",
    ),
    "OUO": ClassificationDefinition(
        abbreviation="OUO",
        full_name="Official Use Only",
        meaning="For official business use and not for unrestricted public distribution.",
    ),
    "PHI": ClassificationDefinition(
        abbreviation="PHI",
        full_name="Protected Health Information",
        meaning="Health-related personal information protected by privacy rules.",
    ),
    "PII": ClassificationDefinition(
        abbreviation="PII",
        full_name="Personally Identifiable Information",
        meaning="Information that can identify a specific person and requires privacy protections.",
    ),
    "PUBLIC": ClassificationDefinition(
        abbreviation="PUBLIC",
        full_name="Public",
        meaning="Approved for unrestricted public release.",
    ),
    "SBU": ClassificationDefinition(
        abbreviation="SBU",
        full_name="Sensitive But Unclassified",
        meaning="Not classified, but still sensitive enough to require controlled handling.",
    ),
    "SECRET": ClassificationDefinition(
        abbreviation="SECRET",
        full_name="Secret",
        meaning="Unauthorized disclosure could reasonably be expected to cause serious damage.",
    ),
    "SSI": ClassificationDefinition(
        abbreviation="SSI",
        full_name="Sensitive Security Information",
        meaning="Transportation or security details restricted to protect operations and infrastructure.",
    ),
    "TOP SECRET": ClassificationDefinition(
        abbreviation="TOP SECRET",
        full_name="Top Secret",
        meaning="Unauthorized disclosure could reasonably be expected to cause exceptionally grave damage.",
    ),
    "TOP SECRET//SCI": ClassificationDefinition(
        abbreviation="TOP SECRET//SCI",
        full_name="Top Secret / Sensitive Compartmented Information",
        meaning="Top Secret information with additional compartmented access controls.",
        aliases=("TS/SCI",),
    ),
    "UCNI": ClassificationDefinition(
        abbreviation="UCNI",
        full_name="Unclassified Controlled Nuclear Information",
        meaning="Unclassified nuclear information that still requires strict access control.",
    ),
}


def canonical_classification_name(value: str | None) -> str | None:
    """Resolve a user-facing classification label or alias to its canonical stored form."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text in CLASSIFICATION_DEFINITIONS:
        return text
    upper = text.upper()
    for canonical, definition in CLASSIFICATION_DEFINITIONS.items():
        choices = {
            canonical.upper(),
            definition.abbreviation.upper(),
            definition.full_name.upper(),
            *(alias.upper() for alias in definition.aliases),
        }
        if upper in choices:
            return canonical
    return text


def classification_definition(value: str | None) -> ClassificationDefinition | None:
    """Return metadata for a canonical or aliased classification value when known."""
    canonical = canonical_classification_name(value)
    if canonical is None:
        return None
    return CLASSIFICATION_DEFINITIONS.get(canonical)


def classification_display_label(value: str | None) -> str:
    """Render a compact label that expands abbreviations when metadata is available."""
    canonical = canonical_classification_name(value)
    if canonical is None:
        return "(none)"
    definition = CLASSIFICATION_DEFINITIONS.get(canonical)
    if definition is None:
        return canonical
    if canonical == definition.full_name:
        return canonical
    return f"{canonical} ({definition.full_name})"


def classification_help_label(value: str | None) -> str:
    """Render a descriptive classification label including its meaning when known."""
    canonical = canonical_classification_name(value)
    if canonical is None:
        return "(none)"
    definition = CLASSIFICATION_DEFINITIONS.get(canonical)
    if definition is None:
        return canonical
    label = classification_display_label(canonical)
    return f"{label} — {definition.meaning}"


ARCHIVE_ID_MARKER = ".conversation-id"

COMMENT_STYLES: dict[str, tuple[str, str]] = {
    ".c": ("// ", ""),
    ".cpp": ("// ", ""),
    ".cs": ("// ", ""),
    ".css": ("/* ", " */"),
    ".go": ("// ", ""),
    ".h": ("// ", ""),
    ".hpp": ("// ", ""),
    ".html": ("<!-- ", " -->"),
    ".ini": ("; ", ""),
    ".java": ("// ", ""),
    ".js": ("// ", ""),
    ".md": ("<!-- ", " -->"),
    ".php": ("// ", ""),
    ".ps1": ("# ", ""),
    ".py": ("# ", ""),
    ".rb": ("# ", ""),
    ".rs": ("// ", ""),
    ".scss": ("/* ", " */"),
    ".sh": ("# ", ""),
    ".sql": ("-- ", ""),
    ".svg": ("<!-- ", " -->"),
    ".toml": ("# ", ""),
    ".ts": ("// ", ""),
    ".tsx": ("// ", ""),
    ".xml": ("<!-- ", " -->"),
    ".yaml": ("# ", ""),
    ".yml": ("# ", ""),
}

ORG_MARKINGS: dict[str, list[str]] = {
    "U.S. Army": ["CUI", "FOUO", "SECRET", "TOP SECRET", "NOFORN"],
    "U.S. Navy": ["CUI", "FOUO", "SECRET", "TOP SECRET", "NOFORN"],
    "U.S. Air Force": ["CUI", "FOUO", "SECRET", "TOP SECRET", "NOFORN"],
    "U.S. Marine Corps": ["CUI", "FOUO", "SECRET", "TOP SECRET", "NOFORN"],
    "U.S. Space Force": ["CUI", "FOUO", "SECRET", "TOP SECRET", "NOFORN"],
    "U.S. Coast Guard": ["CUI", "FOUO", "LES", "SECRET", "TOP SECRET"],
    "DoD / Joint Staff": ["CUI", "FOUO", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN"],
    "Department of Homeland Security": ["CUI", "FOUO", "LES", "SSI", "SECRET", "TOP SECRET"],
    "Department of Justice / FBI": ["CUI", "FOUO", "LES", "SECRET", "TOP SECRET", "NOFORN"],
    "CIA": ["CUI", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN", "ORCON"],
    "NSA": ["CUI", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN", "ORCON"],
    "DIA": ["CUI", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN", "ORCON"],
    "NGA": ["CUI", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN"],
    "NRO": ["CUI", "SECRET", "TOP SECRET", "TOP SECRET//SCI", "NOFORN"],
    "Department of State": ["CUI", "SBU", "CONFIDENTIAL", "SECRET", "TOP SECRET", "NOFORN"],
    "Department of Energy": ["CUI", "OUO", "SECRET", "TOP SECRET", "UCNI"],
    "Department of the Treasury": ["CUI", "FOUO", "SBU", "SECRET"],
    "HHS / CDC": ["CUI", "FOUO", "SBU"],
    "FEMA": ["CUI", "FOUO", "LES", "SSI"],
    "VA": ["CUI", "FOUO", "PII", "PHI"],
}
ORG_OPTIONS = ["All", *ORG_MARKINGS.keys()]

STARTUP_BANNER = r"""
 _______               _           _
|__   __|             | |         | |
   | |_   _  ___   ___| |__   __ _| |_
   | | | | |/ _ \ / __| '_ \ / _` | __|
   | | |_| | (_) | (__| | | | (_| | |_
   |_|\__,_|\___/ \___|_| |_|\__,_|\__|
"""

KNOWN_SLASH_COMMANDS = {
    "/help",
    "/help-menu",
    "/status",
    "/config",
    "/doctor",
    "/about",
    "/setup",
    "/shortcuts",
    "/shortcut",
    "/files",
    "/approve-checks",
    "/diff",
    "/dir",
    "/ls",
    "/attach",
    "/include",
    "/include-last",
    "/map",
    "/code-map",
    "/detach",
    "/skills",
    "/skill",
    "/template",
    "/custom",
    "/agent-prompt",
    "/agent-prompts",
    "/recipe",
    "/recipes",
    "/preview",
    "/context",
    "/token-check",
    "/timeout",
    "/verbose",
    "/stream",
    "/mask",
    "/dot-timer",
    "/blind",
    "/no-write",
    "/write-here-mode",
    "/approve-writes",
    "/no-code-mode",
    "/retry",
    "/copy",
    "/log",
    "/history",
    "/done",
    "/open",
    "/title",
    "/model",
    "/duo-model",
    "/openrouter-model",
    "/tutorial",
    "/new",
    "/clear",
    "/reset",
    "/server-add",
    "/server-remove",
    "/server-current-items",
    "/server-query",
    "/server-retrieve",
    "/server-clear",
    "/server-get-item-content",
    "/archive",
    "/unarchive",
    "/resume",
    "/delete",
    "/search",
    "/nuke",
    "/quit",
    "/exit",
    "/classify",
    "/usage",
    "/update-bagit",
    "/check-bagit",
    "/resource",
    "/git",
    "/gl",
    "/jira",
    "/web",
    "/web-preview",
    "/transcript",
    "/memory",
    "/compact",
    "/todo",
}
KNOWN_BARE_COMMANDS = {command[1:] for command in KNOWN_SLASH_COMMANDS}

TUTORIAL_CONTINUE_CHOICES = {"", "y", "yes", "1", "continue", "c"}
TUTORIAL_PICKER_ALIASES = {"pick", "picker", "menu", "list"}
TUTORIAL_LESSON_ORDER = [
    "multiline-input",
    "model-selection",
    "eliza-demo",
    "classification",
    "help",
    "status",
    "retry",
    "files-and-includes",
    "maps-and-code-maps",
    "no-write",
    "conversation-files",
]
TUTORIAL_LESSONS: dict[str, dict[str, object]] = {
    "multiline-input": {
        "title": "Multiline input",
        "summary": "Submit multi-line prompts with the terminal EOF key sequence.",
        "body": [
            "Tuochat supports multi-line prompts.",
            "",
            "How you submit depends on what is installed:",
            "",
            "  With prompt-toolkit installed (richer experience):",
            "    - Enter adds a new line.",
            "    - Alt+S submits the message.",
            "    - On Windows, Ctrl+Z on a non-empty buffer also submits.",
            "",
            "  Without prompt-toolkit (readline / plain input):",
            "    - Type your message one line at a time.",
            "    - Windows: Ctrl+Z, then Enter to submit.",
            "    - macOS / Linux: Ctrl+D to submit.",
            "",
            "Try it now — type a line and submit using the method that matches your setup.",
        ],
    },
    "model-selection": {
        "title": "Model selection",
        "summary": "Pick between Duo, Eliza, and OpenRouter during the session.",
        "body": [
            "Use `/model` to see the current model and pick a different one.",
            "",
            "Choices:",
            "- Duo: connects to GitLab Duo Chat (requires authentication).",
            "- Eliza: a local pattern-matching bot for practicing the interface without Duo.",
            "",
            "Short form: `/model duo` or `/model eliza`.",
            "If you run just `/model`, Tuochat shows a numbered picker.",
            "",
            "Use `/duo-model` to check whether your GitLab instance supports a separate",
            "server-side Duo model selector.",
            "",
            "Eliza is not an AI — she is a simple scripted responder used for local practice.",
        ],
    },
    "eliza-demo": {
        "title": "Eliza demo",
        "summary": "Practice a live exchange with the local Eliza bot before using Duo.",
        "body": [
            "Eliza is a simple pattern-matching bot built into Tuochat.",
            "She is NOT Duo and NOT an AI — she is a scripted local responder,",
            "here so you can try the interface without any network connection.",
            "",
            "You will send her a message right now.",
            "When you are done exploring, switch to Duo with `/model duo`.",
        ],
    },
    "classification": {
        "title": "Classification",
        "summary": "Set the document marking for the current conversation.",
        "body": [
            "Use `/classify` to set a document classification for this conversation.",
            "",
            "You can either run `/classify` to pick from the configured list or",
            "run `/classify SECRET` or another allowed marking directly.",
            "",
            "If classification prompts are enabled in config, Tuochat can ask at conversation start.",
            "The selected marking is echoed in saved markdown transcripts.",
        ],
    },
    "help": {
        "title": "Help and help menu",
        "summary": "Use `/help` for grouped help and `/help menu` or `/help-menu` for a simpler view.",
        "body": [
            "Use `/help` to see all interactive slash commands in grouped sections.",
            "",
            "Use `/help menu` or `/help-menu` for a menu-style view meant for blind users,",
            "screen readers, and anyone who prefers a simpler linear help layout.",
            "",
            "You can narrow help to one area at a time, for example `/help output`,",
            "`/help safety`, `/help files`, or `/help exit`.",
            "",
            "The help output reflects the current app build, so it is the fastest way",
            "to see what commands are available right now.",
        ],
    },
    "status": {
        "title": "Session status",
        "summary": "Use `/status` to see the current session configuration at a glance.",
        "body": [
            "Use `/status` any time to see a summary of the active session:",
            "",
            "- Active model (Duo or Eliza)",
            "- Classification marking",
            "- Data directory where conversation files are saved",
            "- No-write mode, streaming, masking, and other toggles",
            "- GitLab resource and token limits",
            "",
            "`/status` is the fastest way to confirm your settings without opening config.",
            "It is safe to run at any point and does not affect the conversation.",
        ],
    },
    "retry": {
        "title": "Retry last message",
        "summary": "Use `/retry` to re-send your last prompt if the response was unsatisfactory.",
        "body": [
            "Use `/retry` to re-send the most recent user message.",
            "",
            "This is useful when:",
            "- The model gave a confusing or incomplete answer",
            "- The network request timed out or failed",
            "- You want a second attempt at the same question",
            "",
            "`/retry` resends the exact same text, so edit your prompt first if you want",
            "to refine it before trying again.",
            "",
            "If there is no prior message in this session, `/retry` will tell you so.",
        ],
    },
    "files-and-includes": {
        "title": "Files and globs",
        "summary": "Attach files or globbed file sets from the working directory.",
        "body": [
            "Use `/files` to list likely text files you can include.",
            "Use `/include path` or `/attach path` to attach one file to the next request.",
            "Use `/include 3` or `/attach 3` to attach by the numbered `/files` picker.",
            "",
            "You can include many files with globs.",
            "Examples:",
            "- `/include README.md`",
            "- `/attach README.md`",
            "- `/include tuochat/**/*.py`",
            "- `/include tuochat/**/*.py 25`",
            "",
            "Glob basics:",
            "- `*` matches within one path segment",
            "- `**` matches recursively through directories",
            "- `?` matches one character",
        ],
    },
    "maps-and-code-maps": {
        "title": "Maps and code maps",
        "summary": "Preview and queue `/map` and `/code-map` for the next request.",
        "body": [
            "Use `/map [glob] [limit]` to build a directory-style map of matching files.",
            "Use `/code-map [glob] [limit]` to bundle matching text files and their contents.",
            "",
            "Important: running these commands does not send anything to the model yet.",
            "They only preview the attachment and ask whether to queue it for the next request.",
            "",
            "The queued map or code map is sent only after you type your next chat message.",
            "",
            "Examples:",
            "- `/map tuochat/**/*.py 25`",
            "- `/code-map README.md`",
            "- `/code-map tuochat/**/*.py 10`",
        ],
    },
    "no-write": {
        "title": "No-write mode",
        "summary": "Temporarily disable local history, transcript files, and log files.",
        "body": [
            "Use `/no-write on` when you do not want Tuochat writing sqlite history,",
            "conversation markdown, extracted files, or file logs.",
            "",
            "Use `/no-write off` to restore normal local persistence.",
            "If you run `/no-write` with no argument, Tuochat explains the choices and opens a picker.",
        ],
    },
    "conversation-files": {
        "title": "Conversation markdown files",
        "summary": "Find saved markdown transcripts and extracted files after a chat ends.",
        "body": [
            "When local writes are enabled, Tuochat saves conversation artifacts under the data directory.",
            "",
            "During chat, `/status` shows the configured data directory.",
            "At the end of a conversation, Tuochat prints the saved markdown path and extracted-file count.",
            "You can also use `/open` to open the archive folder on disk.",
            "",
            "On Windows the default data root is usually `%LOCALAPPDATA%\\tuochat`.",
            "Conversation markdown files live under its `conversations` folder unless `/no-write` is on.",
        ],
    },
}
