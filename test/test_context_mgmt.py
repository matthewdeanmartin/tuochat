"""Tests for context management features: artifacts, agent prompts, and recipes."""

from __future__ import annotations

import tuochat.context.artifacts as artifacts_module
from tuochat.config import TuochatConfig
from tuochat.context.artifacts import (
    AppliesTo,
    ArtifactKind,
    ContextArtifact,
    discover_agent_prompt_artifacts,
    discover_all_artifacts,
    discover_custom_instruction_artifacts,
    discover_skill_artifacts,
    discover_template_artifacts,
)
from tuochat.context.recipes import (
    RECIPE_FILE_COUNT_THRESHOLD,
    Recipe,
    RecipeMatch,
    expand_recipe,
    get_recipe,
    list_recipes,
)
from tuochat.discovery.agent_prompts import (
    auto_select_agent_prompt,
    describe_agent_prompt_path,
    list_available_agent_prompts,
    list_cwd_agent_prompt_files,
    list_workspace_agent_prompt_files,
    load_agent_prompt_content,
)
from tuochat.estimation import estimate_tokens

# ---------------------------------------------------------------------------
# ContextArtifact model
# ---------------------------------------------------------------------------


def test_context_artifact_size_and_tokens():
    artifact = ContextArtifact(
        kind=ArtifactKind.SKILL,
        display_name="my-skill",
        source_label="bundled:my-skill",
        raw_content="Hello world",
        resolved_content="Hello world, resolved",
    )
    assert artifact.size_chars == len("Hello world, resolved")
    assert artifact.estimated_tokens == estimate_tokens("Hello world, resolved")


def test_context_artifact_falls_back_to_raw_for_empty_resolved():
    artifact = ContextArtifact(
        kind=ArtifactKind.SKILL,
        display_name="x",
        source_label="y",
        raw_content="raw content here",
        resolved_content="",
    )
    assert artifact.size_chars == len("raw content here")
    assert artifact.estimated_tokens == estimate_tokens("raw content here")


def test_context_artifact_kind_enum_values():
    assert ArtifactKind.AGENT_PROMPT.value == "agent_prompt"
    assert ArtifactKind.SKILL.value == "skill"
    assert ArtifactKind.TEMPLATE.value == "template"
    assert ArtifactKind.CUSTOM_INSTRUCTION.value == "custom_instruction"
    assert ArtifactKind.RECIPE.value == "recipe"
    assert ArtifactKind.FILE_ATTACHMENT.value == "file_attachment"


def test_context_artifact_applies_to_defaults():
    skill = ContextArtifact(kind=ArtifactKind.SKILL, display_name="s", source_label="l")
    assert skill.applies_to == AppliesTo.NEXT_TURN


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def test_discover_all_artifacts_combines_sections_in_fixed_order(monkeypatch):
    cfg = TuochatConfig()
    agent_artifact = ContextArtifact(ArtifactKind.AGENT_PROMPT, "agent", "agent-source")
    skill_artifact = ContextArtifact(ArtifactKind.SKILL, "skill", "skill-source")
    template_artifact = ContextArtifact(ArtifactKind.TEMPLATE, "template", "template-source")
    custom_artifact = ContextArtifact(ArtifactKind.CUSTOM_INSTRUCTION, "custom", "custom-source")

    monkeypatch.setattr(artifacts_module, "discover_agent_prompt_artifacts", lambda cfg: [agent_artifact])
    monkeypatch.setattr(artifacts_module, "discover_skill_artifacts", lambda cfg: [skill_artifact])
    monkeypatch.setattr(artifacts_module, "discover_template_artifacts", lambda cfg: [template_artifact])
    monkeypatch.setattr(
        artifacts_module,
        "discover_custom_instruction_artifacts",
        lambda cfg: [custom_artifact],
    )

    assert discover_all_artifacts(cfg) == [
        agent_artifact,
        skill_artifact,
        template_artifact,
        custom_artifact,
    ]


def test_discover_agent_prompt_artifacts_uses_session_prompt_scope(tmp_path, monkeypatch):
    cfg = TuochatConfig()
    prompt_path = tmp_path / "AGENTS.md"
    prompt_path.write_text("Use careful reasoning.", encoding="utf-8")

    monkeypatch.setattr(
        artifacts_module,
        "list_available_agent_prompts",
        lambda: [prompt_path],
        raising=False,
    )
    monkeypatch.setattr(
        "tuochat.discovery.agent_prompts.list_available_agent_prompts",
        lambda root=None: [prompt_path],
    )
    monkeypatch.setattr(
        "tuochat.discovery.agent_prompts.describe_agent_prompt_path",
        lambda path: f"cwd:{path.name}",
    )

    artifacts = discover_agent_prompt_artifacts(cfg)

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.kind == ArtifactKind.AGENT_PROMPT
    assert artifact.applies_to == AppliesTo.SESSION_PROMPT
    assert artifact.raw_content == "Use careful reasoning."
    assert artifact.resolved_content == "Use careful reasoning."


def test_discover_agent_prompt_artifacts_tolerates_invalid_utf8(tmp_path, monkeypatch):
    cfg = TuochatConfig()
    prompt_path = tmp_path / "AGENTS.md"
    prompt_path.write_bytes(b"\xff\xfe\x00")

    monkeypatch.setattr(
        "tuochat.discovery.agent_prompts.list_available_agent_prompts",
        lambda root=None: [prompt_path],
    )
    monkeypatch.setattr(
        "tuochat.discovery.agent_prompts.describe_agent_prompt_path",
        lambda path: f"cwd:{path.name}",
    )

    artifacts = discover_agent_prompt_artifacts(cfg)

    assert len(artifacts) == 1
    assert artifacts[0].raw_content == ""
    assert artifacts[0].resolved_content == ""


def test_discover_skill_artifacts_has_resolved_content(tmp_path):
    cfg = TuochatConfig()
    artifacts = discover_skill_artifacts(cfg)
    for artifact in artifacts:
        assert artifact.kind == ArtifactKind.SKILL
        assert artifact.display_name
        assert artifact.source_label


def test_discover_template_artifacts_has_raw_content(tmp_path):
    cfg = TuochatConfig()
    artifacts = discover_template_artifacts(cfg)
    for artifact in artifacts:
        assert artifact.kind == ArtifactKind.TEMPLATE
        assert artifact.source_label


def test_discover_custom_instruction_artifacts(tmp_path):
    cfg = TuochatConfig()
    artifacts = discover_custom_instruction_artifacts(cfg)
    for artifact in artifacts:
        assert artifact.kind == ArtifactKind.CUSTOM_INSTRUCTION
        assert artifact.applies_to == AppliesTo.NEXT_CONVERSATION


# ---------------------------------------------------------------------------
# Agent prompt discovery
# ---------------------------------------------------------------------------


def test_list_cwd_agent_prompt_files_finds_agents_md(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("You are helpful.")
    found = list_cwd_agent_prompt_files(tmp_path)
    assert agents in found


def test_list_cwd_agent_prompt_files_finds_claude_md(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("Be concise.")
    found = list_cwd_agent_prompt_files(tmp_path)
    assert claude in found


def test_list_cwd_agent_prompt_files_agents_before_claude(tmp_path):
    agents = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    agents.write_text("agents")
    claude.write_text("claude")
    found = list_cwd_agent_prompt_files(tmp_path)
    assert found.index(agents) < found.index(claude)


def test_list_cwd_agent_prompt_files_skips_missing(tmp_path):
    found = list_cwd_agent_prompt_files(tmp_path)
    assert found == []


def test_list_workspace_agent_prompt_files(tmp_path):
    prompt_dir = tmp_path / ".agents" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "custom.md").write_text("My custom prompt")
    found = list_workspace_agent_prompt_files(tmp_path)
    names = [p.name for p in found]
    assert "custom.md" in names


def test_list_available_agent_prompts_preserves_root_priority_over_workspace(tmp_path):
    agents = tmp_path / "AGENTS.md"
    workspace_prompt = tmp_path / ".agents" / "prompts" / "custom.md"
    workspace_prompt.parent.mkdir(parents=True)
    agents.write_text("root prompt", encoding="utf-8")
    workspace_prompt.write_text("workspace prompt", encoding="utf-8")

    found = list_available_agent_prompts(tmp_path)

    assert found[:2] == [agents, workspace_prompt]


def test_list_available_agent_prompts_deduplicates(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("dedupe test")
    found = list_available_agent_prompts(tmp_path)
    resolved = [p.resolve() for p in found]
    assert len(resolved) == len(set(resolved))


def test_auto_select_agent_prompt_returns_highest_priority(tmp_path):
    agents = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    agents.write_text("agents")
    claude.write_text("claude")
    path, label = auto_select_agent_prompt(tmp_path)
    assert path is not None
    assert path.name == "AGENTS.md"
    assert label is not None


def test_auto_select_agent_prompt_returns_none_when_empty(tmp_path):
    path, label = auto_select_agent_prompt(tmp_path)
    assert path is None
    assert label is None


def test_describe_agent_prompt_path_cwd_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("x")
    label = describe_agent_prompt_path(agents)
    assert label == "cwd:AGENTS.md"


def test_load_agent_prompt_content_returns_text(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("  my instructions  ")
    content = load_agent_prompt_content(p)
    assert content == "my instructions"


def test_load_agent_prompt_content_returns_none_for_missing(tmp_path):
    p = tmp_path / "nonexistent.md"
    assert load_agent_prompt_content(p) is None


def test_load_agent_prompt_content_returns_none_for_empty(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("   ")
    assert load_agent_prompt_content(p) is None


def test_load_agent_prompt_content_returns_none_for_invalid_utf8(tmp_path, capsys):
    p = tmp_path / "bad.md"
    p.write_bytes(b"\xff\xfe\x00")

    assert load_agent_prompt_content(p) is None

    captured = capsys.readouterr()
    assert "not valid UTF-8" in captured.err


# ---------------------------------------------------------------------------
# composer.py: expanded agent prompt path support
# ---------------------------------------------------------------------------


def test_load_agents_instructions_uses_custom_path(tmp_path):
    from tuochat.context.composer import load_agents_instructions

    custom = tmp_path / "CLAUDE.md"
    custom.write_text("Be concise.")
    content, label = load_agents_instructions(custom)
    assert content is not None
    assert "Be concise." in content
    assert "CLAUDE.md" in label


def test_load_agents_instructions_default_falls_back_to_agents_md(tmp_path, monkeypatch):
    from tuochat.context.composer import load_agents_instructions

    monkeypatch.chdir(tmp_path)
    # No AGENTS.md in tmp_path
    content, label = load_agents_instructions()
    assert content is None
    assert label is None


def test_compose_system_prompt_with_agent_prompt_path(tmp_path):
    from tuochat.context.composer import compose_system_prompt

    custom = tmp_path / "CLAUDE.md"
    custom.write_text("Be concise.")
    prompt, sources = compose_system_prompt(None, agent_prompt_path=custom)
    assert prompt is not None
    assert "Be concise." in prompt
    assert any("CLAUDE.md" in s for s in sources)


def test_compose_system_prompt_agent_prompt_none_mode(tmp_path, monkeypatch):
    from tuochat.context.composer import compose_system_prompt

    monkeypatch.chdir(tmp_path)
    # No AGENTS.md exists
    prompt, sources = compose_system_prompt(None, include_agents=False)
    assert prompt is None
    assert sources == []


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


def test_list_recipes_returns_non_empty():
    recipes = list_recipes()
    assert len(recipes) > 0


def test_list_recipes_has_python_overview():
    recipes = {r.name for r in list_recipes()}
    assert "python-overview" in recipes


def test_list_recipes_has_java():
    recipes = {r.name for r in list_recipes()}
    assert any("java" in name for name in recipes)


def test_list_recipes_has_angular():
    recipes = {r.name for r in list_recipes()}
    assert any("angular" in name for name in recipes)


def test_list_recipes_has_yaml_bash():
    recipes = {r.name for r in list_recipes()}
    assert any("yaml" in name for name in recipes)


def test_get_recipe_returns_known():
    recipe = get_recipe("python-debug")
    assert recipe is not None
    assert recipe.name == "python-debug"
    assert recipe.flavor == "debug"


def test_get_recipe_returns_none_for_unknown():
    assert get_recipe("nonexistent-recipe-xyz") is None


def test_expand_recipe_empty_dir(tmp_path):
    recipe = get_recipe("python-overview")
    assert recipe is not None
    match = expand_recipe(recipe, cwd=tmp_path)
    assert isinstance(match, RecipeMatch)
    assert match.matched_paths == []
    assert match.rendered == ""
    assert match.estimated_tokens == 0


def test_expand_recipe_matches_files(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
    (tmp_path / "README.md").write_text("# My Project")
    recipe = get_recipe("python-overview")
    assert recipe is not None
    match = expand_recipe(recipe, cwd=tmp_path)
    matched_names = [p.name for p in match.matched_paths]
    assert "pyproject.toml" in matched_names
    assert "README.md" in matched_names


def test_expand_recipe_renders_fenced_blocks(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
    recipe = get_recipe("python-overview")
    assert recipe is not None
    match = expand_recipe(recipe, cwd=tmp_path)
    assert "pyproject.toml" in match.rendered
    assert "```" in match.rendered


def test_expand_recipe_excludes_glob_patterns(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def main(): pass")
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_main.py").write_text("def test_main(): pass")
    recipe = get_recipe("python-core")
    assert recipe is not None
    match = expand_recipe(recipe, cwd=tmp_path)
    matched_names = [p.name for p in match.matched_paths]
    assert "main.py" in matched_names
    assert "test_main.py" not in matched_names


def test_expand_recipe_skips_binary_files(tmp_path):
    binary_file = tmp_path / "data.bin"
    binary_file.write_bytes(b"\x00\x01\x02" * 100)
    recipe = Recipe(
        name="test",
        display_name="test",
        description="test",
        globs=["*.bin"],
    )
    match = expand_recipe(recipe, cwd=tmp_path)
    assert binary_file not in match.matched_paths
    assert binary_file in match.skipped_paths


def test_expand_recipe_respects_supported_ignore_files(tmp_path):
    (tmp_path / ".agentignore").write_text("secret.py\n", encoding="utf-8")
    visible = tmp_path / "visible.py"
    visible.write_text("print('visible')\n", encoding="utf-8")
    secret = tmp_path / "secret.py"
    secret.write_text("print('secret')\n", encoding="utf-8")
    recipe = Recipe(
        name="ignore-aware",
        display_name="Ignore aware",
        description="test",
        globs=["*.py"],
    )

    match = expand_recipe(recipe, cwd=tmp_path)

    assert visible in match.matched_paths
    assert secret not in match.matched_paths
    assert secret in match.skipped_paths


def test_expand_recipe_deduplicates_overlapping_globs(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("print('hello')\n", encoding="utf-8")
    recipe = Recipe(
        name="dedupe",
        display_name="Dedupe",
        description="test",
        globs=["*.py", "main.*"],
    )

    match = expand_recipe(recipe, cwd=tmp_path)

    assert match.matched_paths == [source]


def test_expand_recipe_applies_per_file_char_cap(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("abcdefghij", encoding="utf-8")
    recipe = Recipe(
        name="capped",
        display_name="Capped",
        description="test",
        globs=["*.txt"],
        per_file_cap_chars=5,
    )

    match = expand_recipe(recipe, cwd=tmp_path)

    assert "abcde" in match.rendered
    assert "... (truncated at 5 chars)" in match.rendered


def test_recipe_requires_preview_when_over_threshold(tmp_path):
    # Create enough files to trigger preview requirement
    for i in range(RECIPE_FILE_COUNT_THRESHOLD + 1):
        (tmp_path / f"file_{i}.txt").write_text(f"content {i}")
    recipe = Recipe(
        name="big-test",
        display_name="Big test",
        description="test",
        globs=["*.txt"],
    )
    match = expand_recipe(recipe, cwd=tmp_path)
    assert match.requires_preview


def test_recipe_no_preview_for_small_set(tmp_path):
    (tmp_path / "small.txt").write_text("small content")
    recipe = Recipe(
        name="small-test",
        display_name="Small test",
        description="test",
        globs=["*.txt"],
    )
    match = expand_recipe(recipe, cwd=tmp_path)
    assert not match.requires_preview


def test_recipe_all_flavors_present():
    flavors = {r.flavor for r in list_recipes()}
    assert "overview" in flavors
    assert "core" in flavors
    assert "debug" in flavors


def test_recipe_each_language_has_three_flavors():
    recipes = list_recipes()
    lang_flavors: dict[str, set[str]] = {}
    for recipe in recipes:
        lang = recipe.name.split("-")[0]
        lang_flavors.setdefault(lang, set()).add(recipe.flavor)
    for lang, flavors in lang_flavors.items():
        assert "overview" in flavors, f"{lang} missing overview"
        assert "core" in flavors, f"{lang} missing core"
        assert "debug" in flavors, f"{lang} missing debug"
