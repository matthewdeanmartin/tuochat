"""Sensitive data masking — pure functions, no terminal I/O."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from tuochat.constants import NO_CODE_MODE_REPLACEMENT, SHELL_FENCE_LANGS
from tuochat.patterns import (
    AWS_KEY_RE,
    CREDIT_CARD_RE,
    FENCED_BLOCK_RE,
    GITLAB_PAT_RE,
    OAUTH_TOKEN_RE,
    OPENAI_KEY_RE,
    PRIVATE_KEY_RE,
    SSN_RE,
)

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig


def known_secret_values(cfg: TuochatConfig) -> list[str]:
    """Return configured secrets that should be masked on screen."""
    secrets: list[str] = []
    gitlab = getattr(cfg, "gitlab", None)
    for value in [
        getattr(gitlab, "token", ""),
        os.environ.get("TUOCHAT_GITLAB_TOKEN", ""),
    ]:
        if value and value not in secrets:
            secrets.append(value)
    return secrets


def mask_sensitive_text(text: str, *, known_secrets: list[str] | None = None) -> tuple[str, bool]:
    """Mask sensitive patterns for terminal display only."""
    masked = text
    any_masked = False
    for pattern, replacement in [
        (SSN_RE, "[MASKED:SSN]"),
        (CREDIT_CARD_RE, "[MASKED:CARD]"),
        (AWS_KEY_RE, "[MASKED:API_KEY]"),
        (OPENAI_KEY_RE, "[MASKED:API_KEY]"),
        (GITLAB_PAT_RE, "[MASKED:GITLAB_PAT]"),
        (OAUTH_TOKEN_RE, "[MASKED:GITLAB_TOKEN]"),
        (PRIVATE_KEY_RE, "[MASKED:PRIVATE_KEY]"),
    ]:
        masked, count = pattern.subn(replacement, masked)
        any_masked = any_masked or count > 0
    for secret in known_secrets or []:
        if secret and secret in masked:
            masked = masked.replace(secret, "[MASKED:KNOWN_SECRET]")
            any_masked = True
    return masked, any_masked


def is_probably_shell_fence(info: str, content: str) -> bool:
    """Heuristically decide whether a fenced block is clearly shell-like."""
    language = info.strip().split()[0].lower() if info.strip() else ""
    if language in SHELL_FENCE_LANGS:
        return True

    stripped_lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not stripped_lines:
        return False

    prompt_like = sum(
        1 for line in stripped_lines[:5] if line.startswith(("$ ", "# ", "PS> ", "C:\\", "cmd> ", "sh> ", "bash> "))
    )
    if prompt_like >= 1:
        return True

    dangerous_starts = (
        "rm ",
        "sudo ",
        "chmod ",
        "chown ",
        "curl ",
        "wget ",
        "powershell ",
        "pwsh ",
        "cmd /c",
        "bash ",
        "sh ",
        "./",
    )
    shellish = sum(1 for line in stripped_lines[:5] if line.startswith(dangerous_starts))
    return shellish >= 2


def mask_no_code_mode(text: str) -> tuple[str, bool]:
    """Replace clearly shell-like fenced code blocks for terminal display."""
    masked_any = False

    def replace(match: re.Match[str]) -> str:
        nonlocal masked_any
        info = match.group(1)
        content = match.group(2)
        if is_probably_shell_fence(info, content):
            masked_any = True
            return NO_CODE_MODE_REPLACEMENT
        return match.group(0)

    return FENCED_BLOCK_RE.sub(replace, text), masked_any


def display_text(
    text: str,
    *,
    mask_output: bool,
    no_code_mode: bool,
    known_secrets: list[str] | None = None,
) -> tuple[str, bool, bool]:
    """Return the text as it should appear on screen plus masking flags."""
    shown = text
    sensitive_masked = False
    code_masked = False
    if no_code_mode:
        shown, code_masked = mask_no_code_mode(shown)
    if mask_output:
        shown, sensitive_masked = mask_sensitive_text(shown, known_secrets=known_secrets)
    return shown, sensitive_masked, code_masked
