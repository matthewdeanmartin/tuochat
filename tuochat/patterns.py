"""Compiled regex patterns for tuochat — stable, no imports from project."""

from __future__ import annotations

import re

FENCED_BLOCK_RE = re.compile(r"```([^\n`]*)\n(.*?)\n```", re.DOTALL)
FILENAME_HINT_RE = re.compile(
    r"^\s*(?:#|//|--|;|/\*+|<!--)?\s*filename\s*:\s*([^\s*<>:\"|?]+(?:/[^\s*<>:\"|?]+)*)",
    re.IGNORECASE,
)
PRECEDING_FILENAME_HINT_RE = re.compile(
    r"^\s*(?:file\s+path|filepath|file\s+name|filename|path)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
OPENAI_KEY_RE = re.compile(r"sk-[a-zA-Z0-9]{20,}")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA|PRIVATE) KEY-----")
GITLAB_PAT_RE = re.compile(r"\bglpat-[A-Za-z0-9_-]{12,}\b")
OAUTH_TOKEN_RE = re.compile(r"\bgloas-[A-Za-z0-9_-]{12,}\b")
SKILL_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
TEMPLATE_VARIABLE_RE = re.compile(r"(?<!\{)\{([A-Za-z][A-Za-z0-9_]*)\}(?!\})")
