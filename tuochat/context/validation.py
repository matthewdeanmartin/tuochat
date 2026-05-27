"""Request validation — entropy checks, warn-word detection, size guards."""

from __future__ import annotations

import base64
import math
import re
import sys
from typing import TYPE_CHECKING, Callable

from tuochat.estimation import substantive_char_count

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig


HIGH_ENTROPY_CANDIDATE_RE = re.compile(r"(?<![\w/+.-])[A-Za-z0-9_+=/-]{16,}(?![\w/+.-])")


def shannon_entropy(text: str) -> float:
    """Compute the Shannon entropy per character for a string."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def looks_like_base64(text: str) -> bool:
    """Best-effort check for base64-like content."""
    normalized = text.strip("=")
    if len(normalized) < 16 or len(normalized) % 4 == 1:
        return False
    try:
        base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    except Exception:
        return False
    return True


def is_high_entropy_string(candidate: str) -> bool:
    """Heuristically flag token/password-like strings."""
    if len(candidate) < 20:
        return False
    charset_groups = sum(
        [
            any(ch.islower() for ch in candidate),
            any(ch.isupper() for ch in candidate),
            any(ch.isdigit() for ch in candidate),
            any(not ch.isalnum() for ch in candidate),
        ]
    )
    entropy = shannon_entropy(candidate)
    if candidate.startswith(("http://", "https://")):
        return False
    if charset_groups >= 3 and entropy >= 3.5:
        return True
    if looks_like_base64(candidate) and entropy >= 3.25:
        return True
    if all(ch in "0123456789abcdefABCDEF" for ch in candidate) and entropy >= 3.0:
        return True
    return False


def find_high_entropy_strings(text: str) -> list[str]:
    """Return distinct high-entropy strings found in a message."""
    matches: list[str] = []
    seen: set[str] = set()
    for candidate in HIGH_ENTROPY_CANDIDATE_RE.findall(text):
        if candidate in seen:
            continue
        if is_high_entropy_string(candidate):
            seen.add(candidate)
            matches.append(candidate)
    return matches


def truncate_for_display(text: str, *, limit: int = 80) -> str:
    """Truncate a string for terminal display."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def find_warn_phrases(text: str, cfg: TuochatConfig) -> list[str]:
    """Return configured warning phrases found in text, case-insensitively."""
    if not cfg.warn_words.enabled:
        return []
    lowered = text.casefold()
    matches: list[str] = []
    seen: set[str] = set()
    for phrase in cfg.warn_words.phrases:
        normalized = phrase.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        if key in lowered:
            seen.add(key)
            matches.append(normalized)
    return matches


def confirm_high_entropy_strings(text: str, prompt_fn: Callable[[str], str]) -> bool:
    """Prompt the user before sending suspicious high-entropy strings."""
    matches = find_high_entropy_strings(text)
    if not matches:
        return True

    print("Potential secret-like strings detected:")
    for idx, match in enumerate(matches, start=1):
        print(f"  [{idx}] {truncate_for_display(match)}")
    choice = prompt_fn("Send anyway? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def confirm_warn_words(text: str, cfg: TuochatConfig, prompt_fn: Callable[[str], str]) -> bool:
    """Prompt before sending text that contains configured warning phrases."""
    matches = find_warn_phrases(text, cfg)
    if not matches:
        return True
    print("Configured warn words detected:")
    for idx, phrase in enumerate(matches, start=1):
        print(f"  [{idx}] {phrase}")
    choice = prompt_fn("Send anyway? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def confirm_large_request(actual_chars: int, max_chars: int, prompt_fn: Callable[[str], str]) -> bool:
    """Prompt before sending an oversized request."""
    print(
        "Request is larger than the configured soft limit: "
        f"{actual_chars} chars exceeds max_request_chars={max_chars}.",
        file=sys.stderr,
    )
    print(
        "It may be slow, expensive, or rejected upstream depending on GitLab Duo limits.",
        file=sys.stderr,
    )
    choice = prompt_fn("Send anyway? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def confirm_too_short_request(text: str, prompt_fn: Callable[[str], str]) -> bool:
    """Prompt before sending a very short request."""
    count = substantive_char_count(text)
    if count >= 10:
        return True
    print(
        f"Request looks very short ({count} non-whitespace, non-punctuation characters).",
        file=sys.stderr,
    )
    choice = prompt_fn("Send it anyway? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def find_gitlab_token_in_text(text: str, cfg: TuochatConfig) -> list[str]:
    """Return any GitLab API token values found literally in text."""
    import os

    candidates: list[str] = []
    seen: set[str] = set()
    for token in [
        getattr(getattr(cfg, "gitlab", None), "token", "") or "",
        os.environ.get("TUOCHAT_GITLAB_TOKEN", ""),
    ]:
        if token and len(token) >= 8 and token not in seen and token in text:
            seen.add(token)
            candidates.append(token)
    return candidates


def warn_large_request(actual_chars: int, max_chars: int) -> None:
    """Emit a non-fatal warning when an oversized request is sent non-interactively."""
    print(
        f"Warning: request is {actual_chars} chars, exceeds max_request_chars={max_chars}. "
        "Sending anyway (non-interactive mode).",
        file=sys.stderr,
    )


def validate_user_request(
    user_input: str,
    outbound_input: str,
    max_request_chars: int,
    cfg: TuochatConfig,
    prompt_fn: Callable[[str], str],
    *,
    non_interactive: bool = False,
) -> bool:
    """Validate a request before it is sent upstream.

    When non_interactive=True, size-limit violations emit a warning and proceed
    rather than prompting the user (which would fail in headless mode).
    """
    if not user_input.strip():
        print("Request cannot be blank or whitespace only.", file=sys.stderr)
        return False
    gitlab_tokens = find_gitlab_token_in_text(outbound_input, cfg)
    if gitlab_tokens:
        print(
            "Your request appears to contain your GitLab API token. "
            "The LLM does not need and should not receive your API key.",
            file=sys.stderr,
        )
        print("Request cancelled to prevent token exposure.", file=sys.stderr)
        return False
    if not confirm_too_short_request(user_input, prompt_fn):
        print("Request cancelled.")
        return False
    if len(outbound_input) > max_request_chars:
        if non_interactive:
            warn_large_request(len(outbound_input), max_request_chars)
        elif not confirm_large_request(len(outbound_input), max_request_chars, prompt_fn):
            print("Request cancelled.")
            return False
    if not confirm_warn_words(outbound_input, cfg, prompt_fn):
        print("Request cancelled.")
        return False
    if not confirm_high_entropy_strings(user_input, prompt_fn):
        print("Request cancelled.")
        return False
    return True
