"""Conversation archiving — filesystem I/O, no terminal output."""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from tuochat.constants import (
    ARCHIVE_ID_MARKER,
    CLASSIFICATION_UNKNOWN,
    COMMENT_STYLES,
    LANG_TO_EXT,
    SAFE_EXTRACTED_SUFFIXES,
    classification_display_label,
)
from tuochat.models import Conversation
from tuochat.patterns import FENCED_BLOCK_RE, FILENAME_HINT_RE, PRECEDING_FILENAME_HINT_RE

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig


BARE_FILENAME_EXTENSIONS = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".lua",
    ".md",
    ".php",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
EXTENSIONLESS_FILENAME_HINTS = {"dockerfile", "justfile", "makefile"}
MARKDOWN_FILENAME_WRAPPERS = ("**", "__", "`", "*", "_")
MARKDOWN_SUFFIXES = {".md", ".markdown"}
INDENTED_TILDE_FENCE_RE = re.compile(r"(?m)^([ ]{0,3})~~~([^\n]*)$")


def conversation_archive_root(cfg: TuochatConfig) -> Path:
    """Return the root directory used for conversation archives."""
    if write_here_mode_enabled(cfg) and not path_is_filesystem_root(Path.cwd()):
        root = workspace_tuochat_root()
        ensure_workspace_gitignore(root)
        return root / "conversations"
    return cfg.data_dir / "conversations"


def workspace_tuochat_root() -> Path:
    """Return the cwd-local runtime directory used by write-here mode."""
    return Path.cwd() / ".tuochat"


def ensure_workspace_gitignore(root: Path) -> None:
    """Ensure workspace-local archive files stay ignored without touching the repo root."""
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    content = "*\n!.gitignore\n"
    if not gitignore.exists():
        gitignore.write_text(content, encoding="utf-8")
    else:
        try:
            existing = gitignore.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        if existing != content:
            gitignore.write_text(content, encoding="utf-8")
    ensure_repo_exclude_ignores_workspace_tuochat(root)


def find_enclosing_git_dir(start: Path) -> Path | None:
    """Return the git directory for the current workspace when one is discoverable."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        dot_git = candidate / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            try:
                text = dot_git.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            prefix = "gitdir:"
            if text.lower().startswith(prefix):
                git_dir = text[len(prefix) :].strip()
                resolved = Path(git_dir)
                if not resolved.is_absolute():
                    resolved = (candidate / resolved).resolve()
                return resolved
    return None


def ensure_repo_exclude_ignores_workspace_tuochat(root: Path) -> None:
    """Ignore the workspace runtime folder without editing the tracked root .gitignore."""
    git_dir = find_enclosing_git_dir(root)
    if git_dir is None:
        return
    info_dir = git_dir / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    exclude_path = info_dir / "exclude"
    rule = ".tuochat/"
    try:
        existing = exclude_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    if rule not in existing.splitlines():
        updated = existing.rstrip("\n")
        if updated:
            updated += "\n"
        exclude_path.write_text(updated + rule + "\n", encoding="utf-8")


def write_here_mode_enabled(cfg: TuochatConfig) -> bool:
    """Return whether cwd write-here behavior is enabled for this session."""
    return bool(getattr(getattr(cfg, "chat", None), "write_here_mode", False))


def safety_check_extension_enabled(cfg: TuochatConfig | None) -> bool:
    """Return whether extracted files should keep the safety .check suffix."""
    return bool(getattr(getattr(cfg, "chat", None), "safety_check_extension_for_executable_files", True))


def path_is_filesystem_root(path: Path) -> bool:
    """Return whether a path points at a filesystem root."""
    resolved = path.resolve()
    return resolved.parent == resolved


def conversation_archive_dir(cfg: TuochatConfig, conv: Conversation, *, create: bool = True) -> Path:
    """Return the filesystem directory used for a conversation archive."""
    root = conversation_archive_root(cfg)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    elif not root.exists():
        return allocate_archive_dir(root, conv)
    existing = find_archive_dir_for_conversation(root, conv.id)
    if existing is not None:
        return existing

    legacy = root / conv.id
    target = allocate_archive_dir(root, conv)
    if create and legacy.is_dir() and legacy != target and not target.exists():
        legacy.rename(target)
    return target


def conversation_payload_dir(cfg: TuochatConfig, conv: Conversation, *, create: bool = True) -> Path:
    """Return the payload directory used inside a conversation archive."""
    archive_dir = conversation_archive_dir(cfg, conv, create=create)
    payload_dir = archive_dir / "data"
    if create:
        payload_dir.mkdir(parents=True, exist_ok=True)
    return payload_dir


def conversation_markdown_path(cfg: TuochatConfig, conv: Conversation, *, create: bool = True) -> Path:
    """Return the markdown transcript path for a conversation archive."""
    archive_dir = conversation_archive_dir(cfg, conv, create=create)
    payload_dir = conversation_payload_dir(cfg, conv, create=create)
    return payload_dir / f"{archive_dir.name}.md"


def parse_iso_datetime(value: str | None) -> datetime:
    """Parse an ISO timestamp, tolerating missing values."""
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def archive_date_prefix(conv: Conversation) -> str:
    """Return the date prefix for a conversation archive directory."""
    return parse_iso_datetime(conv.created_at).astimezone().strftime("%Y-%m-%d")


def find_archive_dir_for_conversation(root: Path, conversation_id: str) -> Path | None:
    """Find an existing archive directory for the given conversation id."""
    for child in root.iterdir():
        if not child.is_dir():
            continue
        marker = child / ARCHIVE_ID_MARKER
        try:
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == conversation_id:
                return child
        except OSError:
            continue
    return None


def allocate_archive_dir(root: Path, conv: Conversation) -> Path:
    """Allocate a stable date-sequence archive directory for a conversation."""
    prefix = archive_date_prefix(conv)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}})$")
    highest = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = pattern.match(child.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return root / f"{prefix}-{highest + 1:03d}"


def sanitize_relative_output_path(name: str) -> Path:
    """Return a filesystem-safe relative path for extracted output."""
    raw = Path(name.replace("\\", "/"))
    parts: list[str] = []
    for part in raw.parts:
        cleaned = part.strip()
        if not cleaned or cleaned in {".", ".."} or cleaned.endswith(":"):
            continue
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
        cleaned = cleaned.strip("._")
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return Path("file")
    return Path(*parts)


def write_here_target_path(name: str) -> Path | None:
    """Return a safe cwd-relative target path, or None when the hint is unsafe."""
    raw = name.strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        return None
    candidate = Path(raw)
    if candidate.anchor or candidate.is_absolute():
        return None
    parts: list[str] = []
    for part in candidate.parts:
        cleaned = part.strip()
        if not cleaned or cleaned in {".", ".."} or cleaned.endswith(":"):
            return None
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
        cleaned = cleaned.strip("._")
        if not cleaned:
            return None
        parts.append(cleaned)
    if not parts:
        return None
    return Path(*parts)


def unique_path(path: Path, *, content: str | None = None) -> Path:
    """Pick a non-clobbering path, reusing an existing file when the content matches."""
    if not path.exists():
        return path
    if content is not None:
        try:
            if path.read_text(encoding="utf-8") == content:
                return path
        except OSError:
            pass
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
        if content is not None:
            try:
                if candidate.read_text(encoding="utf-8") == content:
                    return candidate
            except OSError:
                pass
        index += 1


def numbered_path(path: Path) -> Path:
    """Pick a non-clobbering path by numbering when the target already exists."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def format_generated_header_text(cfg: TuochatConfig, header_date: datetime) -> str:
    """Render the configured generated-file header text."""
    date_text = f"{header_date.astimezone().month}/{header_date.astimezone().day}/{header_date.astimezone().year}"
    template = cfg.chat.generated_file_header_text.strip()
    return (template.format(date=date_text) if template else "").strip()


def commentize_header(path: Path, text: str) -> str:
    """Convert header text into the appropriate comment syntax for a path."""
    if not text:
        return ""
    suffixes = [suffix.lower() for suffix in path.suffixes]
    suffix = ""
    if suffixes:
        suffix = suffixes[-2] if suffixes[-1] == ".check" and len(suffixes) >= 2 else suffixes[-1]
    if not suffix:
        return text
    style = COMMENT_STYLES.get(suffix)
    if style is None:
        return ""
    prefix, suffix_text = style
    lines = text.splitlines() or [text]
    return "\n".join(f"{prefix}{line}{suffix_text}".rstrip() for line in lines)


def apply_generated_file_header(path: Path, content: str, cfg: TuochatConfig | None, *, header_date: datetime) -> str:
    """Prepend the configured generated-file header when enabled."""
    if cfg is None or not cfg.chat.generated_file_header_enabled:
        return content
    header_text = format_generated_header_text(cfg, header_date)
    header = commentize_header(path, header_text)
    if not header:
        return content
    if content.startswith(header):
        return content
    return f"{header}\n\n{content}" if content else f"{header}\n"


INFO_ATTR_RE = re.compile(
    r"""(?:title|filename|file(?:[-_]?name)?|name|path|source)\s*=\s*["']?([^\s"'>{,]+)["']?""",
    re.IGNORECASE,
)


def filename_hint_from_block(info: str, content: str) -> tuple[str | None, str]:
    """Infer a filename from a fenced block info string, trying many common LLM styles.

    Recognised forms (in priority order):
      ```python:password_manager.py           colon-joined lang:path
      ```python password_manager.py           space-separated second token
      ```python title="password_manager.py"   attribute (title/filename/file/name/path/source)
      ```python {filename="..."}              JSX / Pandoc brace attributes
      ```{.python filename="..."}             Pandoc class+attr
      ``` path/to/file.py                     bare path as the whole info string
    Inside-block first-line comment hints are handled separately via FILENAME_HINT_RE.
    """
    info_tokens = [token for token in info.strip().split() if token]

    # 1. ```lang:filename.ext  (single colon-joined token)
    if info_tokens and ":" in info_tokens[0]:
        _lang, _, rest = info_tokens[0].partition(":")
        if rest and ("." in rest or "/" in rest or "\\" in rest):
            return rest, content

    # 2. ```lang filename.ext  (space-separated extra tokens)
    for token in info_tokens[1:]:
        stripped = token.strip("\"'")
        if "." in stripped or "/" in stripped or "\\" in stripped:
            # skip attribute-style tokens like title="foo" — those are handled below
            if "=" not in token:
                return stripped, content

    # 3. attribute style: title="x", filename="x", file="x", name="x", path="x", source="x"
    attr_match = INFO_ATTR_RE.search(info)
    if attr_match:
        candidate = attr_match.group(1).strip("\"',")
        if candidate:
            return candidate, content

    # 4. bare path as whole info string (no language prefix at all)
    if len(info_tokens) == 1:
        candidate = info_tokens[0].strip("\"'")
        if ("." in candidate or "/" in candidate or "\\" in candidate) and ":" not in candidate:
            return candidate, content

    lines = content.splitlines()
    if lines:
        match = FILENAME_HINT_RE.match(lines[0])
        if match:
            stripped = "\n".join(lines[1:]).lstrip("\n")
            return match.group(1), stripped
    return None, content


def filename_hint_before_block(text: str, block_start: int) -> str | None:
    """Infer a filename from the nearby lines immediately before a fenced block."""
    lines = text[:block_start].splitlines()
    nonempty_lines_seen = 0
    for raw_line in reversed(lines):
        line = raw_line.strip()
        if not line:
            continue
        nonempty_lines_seen += 1
        hint = extract_filename_hint_from_line(line)
        if hint is not None:
            return hint
        if nonempty_lines_seen >= 3:
            break
    return None


def extract_filename_hint_from_line(line: str) -> str | None:
    """Extract a likely filename hint from a single nearby markdown line."""
    raw_candidate = line.strip()
    stripped_candidate = strip_markdown_filename_formatting(line)

    for candidate in (raw_candidate, stripped_candidate):
        match = PRECEDING_FILENAME_HINT_RE.match(candidate)
        if match:
            return match.group(1).strip()

    for candidate in (stripped_candidate, raw_candidate):
        if candidate and is_likely_filename_hint(candidate):
            return candidate
    return None


def strip_markdown_filename_formatting(line: str) -> str:
    """Remove common markdown wrappers around a bare filename hint."""
    candidate = line.strip()
    candidate = re.sub(r"^(?:[-*+]\s+|>\s+|\d+\.\s+|#{1,6}\s+)", "", candidate)
    # Strip trailing " (continued)" annotation that LLMs add to continuation blocks
    candidate = re.sub(r"\s*\(continued\)\s*$", "", candidate, flags=re.IGNORECASE)

    previous = None
    while candidate and candidate != previous:
        previous = candidate
        candidate = candidate.strip().strip(":")
        for wrapper in MARKDOWN_FILENAME_WRAPPERS:
            if candidate.startswith(wrapper) and candidate.endswith(wrapper) and len(candidate) > len(wrapper) * 2:
                candidate = candidate[len(wrapper) : -len(wrapper)].strip()
        link_match = re.fullmatch(r"\[([^\]]+)\]\([^)]+\)", candidate)
        if link_match:
            candidate = link_match.group(1).strip()
    return candidate


def is_likely_filename_hint(candidate: str) -> bool:
    """Return whether a nearby line looks like a standalone filename or path."""
    cleaned = candidate.strip().strip("\"'").replace("\\", "/")
    if not cleaned or any(part in {"", ".", ".."} for part in cleaned.split("/")):
        return False
    if cleaned.lower() in EXTENSIONLESS_FILENAME_HINTS:
        return True
    path = Path(cleaned)
    if path.suffix.lower() in BARE_FILENAME_EXTENSIONS:
        return True
    return "/" in cleaned and bool(path.suffix)


def extension_for_language(language: str) -> str:
    """Map a fenced code language to a likely file extension."""
    return LANG_TO_EXT.get(language.lower(), ".txt")


def normalize_extracted_output_path(path: Path, *, language: str, cfg: TuochatConfig | None) -> Path:
    """Normalize extracted code output names and apply the safety .check suffix when configured."""
    if (
        not path.name.lower().endswith(".check")
        and not path.suffix
        and path.name.lower() not in EXTENSIONLESS_FILENAME_HINTS
    ):
        path = path.with_name(path.name + extension_for_language(language))
    if path.name.lower().endswith(".check"):
        return path
    if not safety_check_extension_enabled(cfg):
        return path
    if path.suffix.lower() in SAFE_EXTRACTED_SUFFIXES:
        return path
    return path.with_name(path.name + ".check")


def restore_markdown_inner_fences(content: str) -> str:
    """Convert the markdown-in-markdown tilde workaround back to triple-backtick fences."""
    return INDENTED_TILDE_FENCE_RE.sub(r"\1```\2", content)


def should_restore_markdown_inner_fences(path: Path, *, language: str) -> bool:
    """Return whether extracted content should restore markdown inner fences."""
    suffixes = [suffix.lower() for suffix in path.suffixes]
    effective_suffix = (
        suffixes[-2] if suffixes and suffixes[-1] == ".check" and len(suffixes) >= 2 else path.suffix.lower()
    )
    return effective_suffix in MARKDOWN_SUFFIXES or language.lower() == "markdown"


def is_bagit_tag_file(path: Path) -> bool:
    """Return whether the path is BagIt metadata rather than conversation payload."""
    name = path.name.lower()
    return (
        name == "bagit.txt"
        or name == "bag-info.txt"
        or name == "fetch.txt"
        or name.startswith("manifest-")
        or name.startswith("tagmanifest-")
    )


def ensure_archive_payload_layout(archive_dir: Path) -> Path:
    """Ensure a conversation archive stores payload files in a BagIt-style data directory."""
    payload_dir = archive_dir / "data"
    if payload_dir.exists():
        return payload_dir
    payload_dir.mkdir(parents=True, exist_ok=True)
    for child in list(archive_dir.iterdir()):
        if child == payload_dir or child.name == ARCHIVE_ID_MARKER or is_bagit_tag_file(child):
            continue
        child.rename(payload_dir / child.name)
    return payload_dir


def load_bagit_module():
    """Return the optional bagit module when installed."""
    try:
        return importlib.import_module("bagit")
    except ModuleNotFoundError:
        return None


@dataclass(frozen=True)
class BagitCheckResult:
    """Validation status for one saved conversation archive."""

    archive_dir: Path
    conversation_id: str
    status: str
    detail: str | None = None


def bag_info_for_conversation(
    conv: Conversation,
    *,
    classification: str | None = None,
    user: str | None = None,
) -> dict[str, str]:
    """Build BagIt metadata for a conversation archive."""
    bag_info = {
        "Bag-Group-Identifier": "tuochat-conversations",
        "External-Identifier": conv.id,
        "Internal-Sender-Identifier": conv.id,
        "Internal-Sender-Description": f"Tuochat conversation archive: {conv.title or 'Untitled Conversation'}",
        "Conversation-Created-At": conv.created_at,
        "Conversation-Updated-At": conv.updated_at,
    }
    if classification:
        bag_info["Conversation-Classification"] = classification_display_label(classification)
    if user:
        bag_info["Contact-Name"] = user
    return bag_info


def write_bagit_tag_file(path: Path, values: Mapping[str, str | list[str]]) -> None:
    """Write a BagIt tag file in the simple key-value format bagit expects."""
    lines: list[str] = []
    for key in sorted(values):
        raw_value = values[key]
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in items:
            text = re.sub(r"\r\n|\r|\n", "", str(item))
            lines.append(f"{key}: {text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initialize_bagit_archive(bagit_module, archive_dir: Path, bag_info: dict[str, str]) -> None:
    """Create BagIt metadata for an archive that is not yet a bag."""
    ensure_archive_payload_layout(archive_dir)
    algorithms = list(getattr(bagit_module, "DEFAULT_CHECKSUMS", ["sha256", "sha512"]))
    old_dir = os.getcwd()
    try:
        os.chdir(archive_dir)
        total_bytes, total_files = bagit_module.make_manifests(
            "data",
            1,
            algorithms=algorithms,
            encoding="utf-8",
        )
    finally:
        os.chdir(old_dir)

    archive_info = dict(bag_info)
    archive_info.setdefault("Bagging-Date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    version = getattr(bagit_module, "VERSION", "unknown")
    project_url = getattr(bagit_module, "PROJECT_URL", "https://pypi.org/project/bagit/")
    archive_info.setdefault("Bag-Software-Agent", f"bagit.py v{version} <{project_url}>")
    archive_info["Payload-Oxum"] = f"{total_bytes}.{total_files}"

    bagit_txt = "BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"
    (archive_dir / "bagit.txt").write_text(bagit_txt, encoding="utf-8")
    write_bagit_tag_file(archive_dir / "bag-info.txt", archive_info)


def sync_bagit_metadata(
    archive_dir: Path,
    conv: Conversation,
    *,
    classification: str | None = None,
    user: str | None = None,
    bagit_module=None,
) -> None:
    """Refresh BagIt metadata and manifests when bagit is available."""
    bagit_module = bagit_module or load_bagit_module()
    if bagit_module is None:
        return
    ensure_archive_payload_layout(archive_dir)
    bag_info = bag_info_for_conversation(conv, classification=classification, user=user)
    if not (archive_dir / "bagit.txt").exists():
        initialize_bagit_archive(bagit_module, archive_dir, bag_info)
    bag = bagit_module.Bag(str(archive_dir))
    bag.info.update(bag_info)
    bag.save(manifests=True)


def refresh_archive_bagit_metadata(
    cfg: TuochatConfig,
    conversations_by_id: Mapping[str, Conversation] | None = None,
    *,
    user: str | None = None,
    bagit_module=None,
) -> tuple[int, int]:
    """Refresh BagIt metadata for every saved conversation archive under the active root."""
    bagit_module = bagit_module or load_bagit_module()
    if bagit_module is None:
        return 0, 0
    root = conversation_archive_root(cfg)
    if not root.exists():
        return 0, 0
    conversation_lookup = dict(conversations_by_id or {})
    updated = 0
    skipped = 0
    for archive_dir in sorted(root.iterdir()):
        if not archive_dir.is_dir():
            continue
        marker_path = archive_dir / ARCHIVE_ID_MARKER
        try:
            conversation_id = marker_path.read_text(encoding="utf-8").strip()
        except OSError:
            skipped += 1
            continue
        if not conversation_id:
            skipped += 1
            continue
        conv = conversation_lookup.get(conversation_id) or Conversation(id=conversation_id, title=archive_dir.name)
        ensure_archive_payload_layout(archive_dir)
        sync_bagit_metadata(archive_dir, conv, user=user, bagit_module=bagit_module)
        updated += 1
    return updated, skipped


def check_archive_bagit_status(
    cfg: TuochatConfig,
    *,
    bagit_module=None,
) -> tuple[list[BagitCheckResult], int]:
    """Report whether saved conversation archives still validate against BagIt metadata."""
    bagit_module = bagit_module or load_bagit_module()
    if bagit_module is None:
        return [], 0
    root = conversation_archive_root(cfg)
    if not root.exists():
        return [], 0
    bag_error_types = tuple(
        error_type
        for error_type in (
            getattr(bagit_module, "BagError", None),
            getattr(bagit_module, "BagValidationError", None),
            OSError,
        )
        if isinstance(error_type, type) and issubclass(error_type, Exception)
    )
    results: list[BagitCheckResult] = []
    skipped = 0
    for archive_dir in sorted(root.iterdir()):
        if not archive_dir.is_dir():
            continue
        marker_path = archive_dir / ARCHIVE_ID_MARKER
        try:
            conversation_id = marker_path.read_text(encoding="utf-8").strip()
        except OSError:
            skipped += 1
            continue
        if not conversation_id:
            skipped += 1
            continue
        if not (archive_dir / "bagit.txt").exists():
            results.append(BagitCheckResult(archive_dir, conversation_id, "missing"))
            continue
        try:
            bag = bagit_module.Bag(str(archive_dir))
            bag.validate(processes=1)
        except Exception as error:  # pylint: disable=broad-exception-caught
            if isinstance(error, bag_error_types):
                results.append(BagitCheckResult(archive_dir, conversation_id, "changed", str(error)))
                continue
            raise error
        results.append(BagitCheckResult(archive_dir, conversation_id, "valid"))
    return results, skipped


# Matches escaped backtick fences that some LLMs emit to avoid triggering markdown
# renderers when the prompt itself contains triple-backtick fences.
# e.g. "` ` `python foo.py" or "\`\`\`python foo.py" → "```python foo.py"
ESCAPED_FENCE_RE = re.compile(
    r"^(?:` ` `|\\`\\`\\`)([^\n]*)$",
    re.MULTILINE,
)

PARTIAL_FENCE_OPEN_RE = re.compile(r"^```([^\n`]*)$", re.MULTILINE)


def detect_partial_code_fence(content: str) -> tuple[str | None, str | None, str | None]:
    """Return (language_hint, partial_content, name_hint) when the response ends mid-fence.

    A partial fence is one that opens (```lang) but the response text ends before
    the closing (``` on its own line) appears.  Returns (None, None, None) when no
    unclosed fence is detected.
    """
    if not content:
        return None, None, None
    remaining = content
    last_open: re.Match | None = None
    last_open_pos: int = 0
    while True:
        open_match = PARTIAL_FENCE_OPEN_RE.search(remaining)
        if open_match is None:
            break
        after_open = remaining[open_match.end() + 1 :]
        close_pos = re.search(r"^```\s*$", after_open, re.MULTILINE)
        if close_pos is not None:
            remaining = after_open[close_pos.end() :]
            last_open = None
        else:
            last_open = open_match
            last_open_pos = len(content) - len(remaining) + open_match.start()
            break
    if last_open is None:
        return None, None, None
    info = last_open.group(1).strip()
    language = info.split()[0] if info else None
    partial = remaining[last_open.end() :].lstrip("\n") if last_open else None
    name_hint = filename_hint_before_block(content, last_open_pos) if last_open_pos > 0 else None
    return language, partial, name_hint


def normalize_escaped_fences(content: str) -> str:
    """Normalize LLM-escaped backtick fences to standard triple-backtick fences.

    Some LLMs escape their own code fences (e.g. "` ` `python foo.py") when the
    user prompt itself contains triple-backtick fences, to avoid breaking markdown
    rendering.  This converts them back to proper triple-backtick fences so that
    FENCED_BLOCK_RE can match them.
    """
    return ESCAPED_FENCE_RE.sub(r"```\1", content)


def extract_code_files(
    conv_dir: Path,
    conv: Conversation,
    cfg: TuochatConfig,
    *,
    approve_write: Callable[[Path], bool] | None = None,
) -> list[Path]:
    """Extract assistant fenced code blocks to sibling files."""
    extracted: list[Path] = []
    fallback_index = 1
    header_date = parse_iso_datetime(conv.updated_at)
    write_here = write_here_mode_enabled(cfg) and not path_is_filesystem_root(Path.cwd())
    for msg in conv.messages:
        if msg.role != "assistant" or not msg.content:
            continue
        content = normalize_escaped_fences(msg.content)
        partial_lang, partial_content, partial_name_hint = detect_partial_code_fence(content)
        if partial_lang is not None or partial_content is not None:
            ext = extension_for_language(partial_lang or "text")
            if partial_name_hint:
                base = Path(partial_name_hint).name
                partial_name = f"{base}.partial.check"
            else:
                partial_name = f"partial{ext}.partial.check"
            partial_path = unique_path(conv_dir / partial_name, content=partial_content or "")
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_text(partial_content or "", encoding="utf-8")
            extracted.append(partial_path)
        for match in FENCED_BLOCK_RE.finditer(content):
            info = match.group(1).strip()
            raw_content = match.group(2)
            language = info.split()[0] if info else "text"
            hinted_name = filename_hint_before_block(content, match.start())
            inline_hint, file_content = filename_hint_from_block(info, raw_content)
            hinted_name = hinted_name or inline_hint
            write_here_target: Path | None = None
            if hinted_name:
                safe_cwd_rel = write_here_target_path(hinted_name) if write_here else None
                if safe_cwd_rel is not None:
                    safe_cwd_rel = normalize_extracted_output_path(safe_cwd_rel, language=language, cfg=cfg)
                    write_here_target = Path.cwd() / safe_cwd_rel
                    candidate_rel = safe_cwd_rel
                else:
                    candidate_rel = sanitize_relative_output_path(hinted_name)
            else:
                candidate_rel = Path(f"file{fallback_index}{extension_for_language(language)}")
                fallback_index += 1
            if write_here_target is None:
                candidate_rel = normalize_extracted_output_path(candidate_rel, language=language, cfg=cfg)
            archive_target = unique_path(conv_dir / candidate_rel, content=None)
            target_template = write_here_target or archive_target
            normalized_content = (
                restore_markdown_inner_fences(file_content)
                if should_restore_markdown_inner_fences(target_template, language=language)
                else file_content
            )
            rendered_content = apply_generated_file_header(
                target_template, normalized_content, cfg, header_date=header_date
            )
            archive_target = unique_path(conv_dir / candidate_rel, content=rendered_content)
            target = archive_target
            if write_here_target is not None:
                approved = approve_write(write_here_target) if approve_write is not None else True
                if approved:
                    target = unique_path(write_here_target, content=rendered_content)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered_content, encoding="utf-8")
            extracted.append(target)
    return extracted


def render_conversation_markdown(
    conv: Conversation,
    *,
    conv_dir: Path | None = None,
    extracted_files: list[Path] | None = None,
    classification: str | None = None,
    user: str | None = None,
    os_user: str | None = None,
    gitlab_user: str | None = None,
    retention_years: int = 0,
    retention_label: str = "",
) -> str:
    """Render a conversation as markdown with optional file references."""
    lines = []
    if classification and classification != CLASSIFICATION_UNKNOWN:
        lines.append(f"<!-- Classification: {classification} -->")
        lines.append(f"**CLASSIFICATION: {classification}**")
        lines.append("")
    lines.append(f"# {conv.title or 'Untitled Conversation'}")
    lines.append("")
    lines.append(f"- Conversation ID: `{conv.id}`")
    lines.append(f"- Started: `{conv.created_at}`")
    lines.append(f"- Updated: `{conv.updated_at}`")
    lines.append(f"- Resource ID: `{conv.resource_id or '(none)'}`")
    if classification:
        lines.append(f"- Classification: {classification_display_label(classification)}")
    if user:
        lines.append(f"- Author: `{user}`")
    if gitlab_user:
        lines.append(f"- GitLab User: `{gitlab_user}`")
    if os_user:
        lines.append(f"- OS User: `{os_user}`")
    if retention_years > 0:
        lines.append(f"- Retention: {retention_years} year{'s' if retention_years != 1 else ''}")
    elif retention_label:
        lines.append(f"- Retention: {retention_label}")
    lines.append(f"- Date: `{datetime.now(timezone.utc).strftime('%Y-%m-%d')}`")
    lines.append("")
    if conv.system_prompt:
        lines.extend(["## System Prompt", "", conv.system_prompt, ""])
    if extracted_files:
        lines.append("## Extracted Files")
        lines.append("")
        for path in extracted_files:
            if conv_dir is not None:
                try:
                    label = path.relative_to(conv_dir).as_posix()
                except ValueError:
                    try:
                        label = "./" + path.relative_to(Path.cwd()).as_posix()
                    except ValueError:
                        label = str(path)
            else:
                label = path.name
            lines.append(f"- `{label}`")
        lines.append("")
    for msg in conv.messages:
        role_label = msg.role.capitalize()
        lines.append(f"## {role_label}")
        lines.append("")
        lines.append(msg.content or "(empty)")
        lines.append("")
    return "\n".join(lines)


def sync_conversation_artifacts(
    cfg: TuochatConfig,
    conv: Conversation,
    *,
    classification: str | None = None,
    approve_write: Callable[[Path], bool] | None = None,
) -> tuple[Path | None, Path | None, list[Path]]:
    """Persist a conversation as markdown plus extracted fenced files."""
    archive_dir = conversation_archive_dir(cfg, conv)
    archive_dir.mkdir(parents=True, exist_ok=True)
    payload_dir = ensure_archive_payload_layout(archive_dir)
    (archive_dir / ARCHIVE_ID_MARKER).write_text(conv.id, encoding="utf-8")
    extracted = extract_code_files(payload_dir, conv, cfg, approve_write=approve_write)
    md_path = conversation_markdown_path(cfg, conv)
    personalization = getattr(cfg, "personalization", None)
    user = personalization.name.strip() or None if personalization is not None else None
    gitlab_user: str | None = None
    os_user: str | None
    try:
        os_user = os.getlogin()
    except OSError:
        os_user = os.environ.get("USERNAME") or os.environ.get("USER") or None
    records = getattr(cfg, "records", None)
    retention_years = records.retention_years if records else 0
    retention_label = records.retention_label if records else ""
    md_path.write_text(
        render_conversation_markdown(
            conv,
            conv_dir=payload_dir,
            extracted_files=extracted,
            classification=classification,
            user=user,
            os_user=os_user,
            gitlab_user=gitlab_user,
            retention_years=retention_years,
            retention_label=retention_label,
        ),
        encoding="utf-8",
    )
    sync_bagit_metadata(archive_dir, conv, classification=classification, user=user)
    return archive_dir, md_path, extracted
