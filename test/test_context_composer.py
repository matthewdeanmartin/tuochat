from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tuochat.context.composer import (
    ATTACHED_CODE_PROMPT,
    build_auto_template_values,
    build_personalization_block,
    compose_system_prompt,
    default_custom_instruction_paths,
    extract_template_variables,
    fill_template_variables,
    load_agents_instructions,
    render_attached_code_value,
    resolve_template_prompt,
    strip_agents_instructions_prefix,
    system_prompt_includes_agents_instructions,
)


class MockConfig:
    def __init__(self, custom_instructions_dir=None):
        self.custom_instructions_dir = custom_instructions_dir or Path("/tmp/custom")
        self.personalization = MockPersonalization()


class MockPersonalization:
    def __init__(self):
        self.enabled = False
        self.name = ""
        self.profession = ""


def test_load_agents_instructions(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # No AGENTS.md
    assert load_agents_instructions() == (None, None)

    # Empty AGENTS.md
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("")
    assert load_agents_instructions() == (None, None)

    # Valid AGENTS.md
    agents_file.write_text("Test instructions")
    content, source = load_agents_instructions()
    assert "Test instructions" in content
    assert "AGENTS.md" in source


def test_default_custom_instruction_paths(tmp_path):
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    cfg = MockConfig(custom_instructions_dir=custom_dir)

    # Create a custom instruction file in the config dir
    from tuochat.constants import DEFAULT_CUSTOM_INSTRUCTION_FILENAME

    custom_file = custom_dir / DEFAULT_CUSTOM_INSTRUCTION_FILENAME
    custom_file.write_text("User instructions")

    paths = default_custom_instruction_paths(cfg)
    assert custom_file in paths


def test_compose_system_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    # 1. Base prompt only
    prompt, sources = compose_system_prompt("Base prompt")
    assert prompt == "Base prompt"
    assert sources == ["cli/system prompt"]

    # 2. Base prompt + AGENTS.md
    (tmp_path / "AGENTS.md").write_text("Agent info")
    prompt, sources = compose_system_prompt("Base prompt")
    assert "Agent info" in prompt
    assert "Base prompt" in prompt
    assert "cwd:AGENTS.md" in sources[0]
    assert sources[1] == "cli/system prompt"

    # 3. Base prompt + custom sections
    prompt, sources = compose_system_prompt("Base", [("source1", "Custom1")])
    assert "Base" in prompt
    assert "Custom1" in prompt
    assert "source1" in sources

    prompt, sources = compose_system_prompt("Base prompt", include_agents=False)
    assert prompt == "Base prompt"
    assert sources == ["cli/system prompt"]


def test_agents_prefix_helpers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Agent info")

    prompt, _ = compose_system_prompt("Base prompt")

    assert system_prompt_includes_agents_instructions(prompt) is True
    assert strip_agents_instructions_prefix(prompt) == "Base prompt"
    assert system_prompt_includes_agents_instructions("Base prompt") is False


def test_build_personalization_block():
    cfg = MockConfig()
    # Disabled
    assert build_personalization_block(cfg) == ""

    # Enabled, but empty
    cfg.personalization.enabled = True
    assert build_personalization_block(cfg) == ""

    # Name only
    cfg.personalization.name = "Alice"
    assert "My name is Alice." in build_personalization_block(cfg)

    # Profession with article
    cfg.personalization.profession = "Engineer"
    block = build_personalization_block(cfg)
    assert "I work as an Engineer." in block

    # Profession without article (fallback)
    cfg.personalization.profession = "Space Explorer"
    block = build_personalization_block(cfg)
    assert "My profession is Space Explorer." in block


def test_template_variables():
    text = "Hello {NAME}, welcome to {PLACE}. {NAME} again."
    vars = extract_template_variables(text)
    assert vars == ["NAME", "PLACE"]

    values = {"NAME": "Bob", "PLACE": "Earth"}
    rendered = fill_template_variables(text, values)
    assert rendered == "Hello Bob, welcome to Earth. Bob again."


def test_template_variables_ignore_doubled_braces_and_keep_first_seen_order():
    """Escaped-style doubled braces should be ignored during variable extraction."""
    text = "{{IGNORED}} and {NAME} before {PLACE} and {NAME} again"

    assert extract_template_variables(text) == ["NAME", "PLACE"]


def test_fill_template_variables_leaves_unknown_placeholders_untouched():
    """Missing template values should leave the original placeholder in place."""
    text = "Hello {NAME}, welcome to {PLACE}."

    assert fill_template_variables(text, {"NAME": "Alice"}) == "Hello Alice, welcome to {PLACE}."


def test_build_auto_template_values_includes_safe_runtime_context(monkeypatch, tmp_path):
    """Built-in template tokens should expose bounded, local runtime context."""
    project_file = tmp_path / "src.py"
    project_file.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr("tuochat.context.composer.inspect_git_repository", lambda cwd: (tmp_path, "demo-repo"))

    values = build_auto_template_values(
        now=datetime(2026, 4, 4, 23, 59, 29).astimezone(),
        cwd=tmp_path,
        user_name="Alice",
        user_os="Windows Test OS",
    )

    assert values["DATE"] == "2026-04-04"
    assert values["TIME"] == "23:59:29"
    assert values["USER_NAME"] == "Alice"
    assert values["USER_OS"] == "Windows Test OS"
    assert values["WORKING_DIRECTORY"] == str(tmp_path)
    assert values["GIT_REPO_NAME"] == "demo-repo"
    assert values["GIT_REPO_ROOT"] == str(tmp_path)
    assert "In git repository demo-repo" in values["GIT_REPO_STATUS"]
    assert "- src.py" in values["DIRECTORY_LISTING"]


def test_build_auto_template_values_falls_back_when_username_unavailable(monkeypatch, tmp_path):
    """Template auto-fill should fall back when the platform cannot resolve a username."""
    monkeypatch.setattr(
        "tuochat.context.composer.getpass.getuser", lambda: (_ for _ in ()).throw(OSError("missing user"))
    )

    values = build_auto_template_values(cwd=tmp_path, user_os="Windows Test OS")

    assert values["USER_NAME"] == "unknown"


def test_render_attached_code_value_formats_selected_file(monkeypatch, tmp_path):
    """ATTACHED_CODE should render as a fenced code block with the chosen path."""
    code_path = tmp_path / "src" / "main.py"
    code_path.parent.mkdir()
    code_path.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    rendered, selected_path = render_attached_code_value("src/main.py", cwd=tmp_path)

    assert selected_path == str(code_path)
    assert f"Attached code from {code_path.relative_to(tmp_path)}:" in rendered
    assert "```python" in rendered
    assert "print('hello')" in rendered


def test_resolve_template_prompt_uses_auto_tokens_and_file_tokens(monkeypatch, tmp_path):
    """Template rendering should auto-fill safe tokens and prompt for ATTACHED_CODE paths."""
    code_path = tmp_path / "service.py"
    code_path.write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    monkeypatch.setattr("tuochat.context.composer.inspect_git_repository", lambda cwd: (tmp_path, "demo-repo"))

    prompts_seen: list[str] = []

    def prompt_for_value(prompt_or_variable: str) -> str:
        prompts_seen.append(prompt_or_variable)
        if prompt_or_variable == "TASK":
            return "explain the control flow"
        if prompt_or_variable == ATTACHED_CODE_PROMPT:
            return "service.py"
        raise AssertionError(f"Unexpected prompt: {prompt_or_variable}")

    rendered, metadata = resolve_template_prompt(
        "Task: {TASK}\nRepo: {GIT_REPO_NAME}\nCode:\n{ATTACHED_CODE}",
        prompt_for_value=prompt_for_value,
        cwd=tmp_path,
    )

    assert prompts_seen == ["TASK", ATTACHED_CODE_PROMPT]
    assert "Task: explain the control flow" in rendered
    assert "Repo: demo-repo" in rendered
    assert "Attached code from service.py:" in rendered
    assert metadata["variables"] == {
        "TASK": "explain the control flow",
        "ATTACHED_CODE": str(code_path),
    }
    assert metadata["auto_variables"] == ["GIT_REPO_NAME"]
