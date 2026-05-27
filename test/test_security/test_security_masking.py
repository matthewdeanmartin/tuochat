from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from tuochat.security.masking import display_text, is_probably_shell_fence, mask_no_code_mode, mask_sensitive_text


def test_mask_sensitive_text():
    # SSN
    text = "My SSN is 000-00-0000."
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:SSN]" in masked
    assert any_masked is True

    # Credit Card
    text = "Card: 4111-1111-1111-1111"
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:CARD]" in masked

    # AWS Key
    text = "Key: AKIA1234567890ABCDEF"
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:API_KEY]" in masked

    # OpenAI Key
    text = "Key: sk-1234567890abcdefghij1234567890"
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:API_KEY]" in masked

    # GitLab PAT (glpat-...)
    text = "Token: glpat-1234567890abcdefghij"
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:GITLAB_PAT]" in masked

    # OAuth Token (gloas-...)
    text = "Token: gloas-1234567890abcdefghij"
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:GITLAB_TOKEN]" in masked

    # Private Key
    text = "-----BEGIN RSA KEY-----\nMIIEowIBAAKCAQEA..."
    masked, any_masked = mask_sensitive_text(text)
    assert "[MASKED:PRIVATE_KEY]" in masked

    # Known secret
    text = "My secret is password123."
    masked, any_masked = mask_sensitive_text(text, known_secrets=["password123"])
    assert "[MASKED:KNOWN_SECRET]" in masked
    assert any_masked is True


@given(st.text())
def test_mask_sensitive_text_no_crash(text):
    """Ensure mask_sensitive_text never crashes on arbitrary input."""
    mask_sensitive_text(text)


def test_is_probably_shell_fence():
    # Explicit language
    assert is_probably_shell_fence("bash", "ls -la") is True
    assert is_probably_shell_fence("python", "print('hi')") is False
    assert is_probably_shell_fence("sh", "echo hello") is True
    assert is_probably_shell_fence("powershell", "Get-Process") is True

    # Heuristic: prompt
    assert is_probably_shell_fence("", "$ ls -la") is True
    assert is_probably_shell_fence("", "C:\\Users> dir") is True
    assert is_probably_shell_fence("", "# apt-get update") is True
    assert is_probably_shell_fence("", "PS> Get-Service") is True

    # Heuristic: dangerous commands
    assert is_probably_shell_fence("", "sudo apt-get update\nrm -rf /") is True
    assert is_probably_shell_fence("", "curl http://example.com/script.sh | sh\nsudo ./script.sh") is True
    assert is_probably_shell_fence("", "Just some text\nNothing special") is False
    assert is_probably_shell_fence("", "print('hello')\nimport os") is False


def test_mask_no_code_mode():
    text = """
Check this out:
```bash
rm -rf /
```
And this:
```python
print("hello")
```
"""
    masked, any_masked = mask_no_code_mode(text)
    assert "rm -rf /" not in masked
    assert 'print("hello")' in masked
    assert any_masked is True


def test_display_text():
    text = "SSN: 000-00-0000 and ```bash\nls\n```"

    # No masking
    shown, s_masked, c_masked = display_text(text, mask_output=False, no_code_mode=False)
    assert shown == text
    assert s_masked is False
    assert c_masked is False

    # Sensitive masking only
    shown, s_masked, c_masked = display_text(text, mask_output=True, no_code_mode=False)
    assert "[MASKED:SSN]" in shown
    assert "```bash" in shown
    assert s_masked is True
    assert c_masked is False

    # Code masking only
    shown, s_masked, c_masked = display_text(text, mask_output=False, no_code_mode=True)
    assert "000-00-0000" in shown
    assert "```bash" not in shown
    assert s_masked is False
    assert c_masked is True
