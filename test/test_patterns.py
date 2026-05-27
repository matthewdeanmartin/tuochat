"""Tests for compiled regex patterns."""

from __future__ import annotations

from tuochat.patterns import (
    AWS_KEY_RE,
    CREDIT_CARD_RE,
    FENCED_BLOCK_RE,
    FILENAME_HINT_RE,
    GITLAB_PAT_RE,
    OAUTH_TOKEN_RE,
    OPENAI_KEY_RE,
    PRECEDING_FILENAME_HINT_RE,
    PRIVATE_KEY_RE,
    SKILL_FRONTMATTER_RE,
    SSN_RE,
    TEMPLATE_VARIABLE_RE,
)


def test_fenced_block_re():
    text = "```python\nprint('hello')\n```"
    match = FENCED_BLOCK_RE.search(text)
    assert match is not None
    assert match.group(1) == "python"
    assert match.group(2) == "print('hello')"

    text_multiple = "```python\n1\n```\n```bash\n2\n```"
    matches = FENCED_BLOCK_RE.findall(text_multiple)
    assert len(matches) == 2
    assert matches[0] == ("python", "1")
    assert matches[1] == ("bash", "2")


def test_filename_hint_re():
    assert FILENAME_HINT_RE.search("# filename: src/main.py").group(1) == "src/main.py"
    assert FILENAME_HINT_RE.search("// filename: lib.js").group(1) == "lib.js"
    assert FILENAME_HINT_RE.search("-- filename: config.lua").group(1) == "config.lua"
    assert FILENAME_HINT_RE.search("/* filename: styles.css */").group(1) == "styles.css"
    assert FILENAME_HINT_RE.search("<!-- filename: index.html -->").group(1) == "index.html"
    assert FILENAME_HINT_RE.search("filename: just_file.txt").group(1) == "just_file.txt"
    assert FILENAME_HINT_RE.search("  FILENAME:  path/to/file.py  ").group(1) == "path/to/file.py"


def test_preceding_filename_hint_re():
    assert PRECEDING_FILENAME_HINT_RE.search("file path: src/main.py").group(1) == "src/main.py"
    assert PRECEDING_FILENAME_HINT_RE.search("filepath: lib.js").group(1) == "lib.js"
    assert PRECEDING_FILENAME_HINT_RE.search("file name: config.lua").group(1) == "config.lua"
    assert PRECEDING_FILENAME_HINT_RE.search("filename: styles.css").group(1) == "styles.css"
    assert PRECEDING_FILENAME_HINT_RE.search("path: index.html").group(1) == "index.html"


def test_ssn_re():
    assert SSN_RE.search("My SSN is 123-45-6789.")
    assert not SSN_RE.search("123-45-678")
    assert not SSN_RE.search("123456789")


def test_credit_card_re():
    assert CREDIT_CARD_RE.search("1234-5678-9012-3456")
    assert CREDIT_CARD_RE.search("1234567890123456")
    assert CREDIT_CARD_RE.search("1234 5678 9012 3456")


def test_aws_key_re():
    assert AWS_KEY_RE.search("AKIAABCDEF1234567890")
    assert not AWS_KEY_RE.search("BKIAABCDEF1234567890")


def test_openai_key_re():
    assert OPENAI_KEY_RE.search("sk-1234567890abcdefghij1234567890")
    assert not OPENAI_KEY_RE.search("sk-123")


def test_private_key_re():
    assert PRIVATE_KEY_RE.search("-----BEGIN RSA KEY-----")
    assert PRIVATE_KEY_RE.search("-----BEGIN PRIVATE KEY-----")


def test_gitlab_pat_re():
    assert GITLAB_PAT_RE.search("glpat-1234567890abcdefghij")
    assert not GITLAB_PAT_RE.search("glpat-123")


def test_oauth_token_re():
    assert OAUTH_TOKEN_RE.search("gloas-1234567890abcdefghij")


def test_skill_frontmatter_re():
    text = "---\nname: my-skill\n---\nBody"
    match = SKILL_FRONTMATTER_RE.search(text)
    assert match is not None
    assert "name: my-skill" in match.group(1)


def test_template_variable_re():
    text = "Hello {NAME}, welcome to {PLACE}!"
    matches = TEMPLATE_VARIABLE_RE.findall(text)
    assert matches == ["NAME", "PLACE"]

    # Escaped braces should not match
    text_escaped = "Braces: {{STAY}} but {MATCH}."
    matches = TEMPLATE_VARIABLE_RE.findall(text_escaped)
    assert matches == ["MATCH"]
