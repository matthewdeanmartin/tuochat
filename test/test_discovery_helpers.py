"""Tests for discovery helper modules."""

from __future__ import annotations

from types import SimpleNamespace

from tuochat.discovery.shared import bundled_templates_dir, list_text_files, parse_frontmatter_metadata
from tuochat.discovery.templates import (
    describe_template_path,
    list_available_templates,
    parse_template_metadata,
    template_body,
)


def test_parse_frontmatter_metadata_returns_metadata_and_body(tmp_path):
    """Frontmatter parsing should return normalized keys and stripped quotes."""
    path = tmp_path / "template.md"
    path.write_text(
        '---\nName: recipe\nDescription: "Recipe helper"\nignored line\n---\nBody text\n',
        encoding="utf-8",
    )

    metadata, body = parse_frontmatter_metadata(path)

    assert metadata == {"name": "recipe", "description": "Recipe helper"}
    assert body == "Body text\n"


def test_parse_frontmatter_metadata_returns_raw_text_without_frontmatter(tmp_path):
    """Plain files should produce no metadata and keep their content intact."""
    path = tmp_path / "plain.md"
    path.write_text("Just content\n", encoding="utf-8")

    metadata, body = parse_frontmatter_metadata(path)

    assert metadata == {}
    assert body == "Just content\n"


def test_list_text_files_filters_to_supported_suffixes(tmp_path):
    """Only configured text-like files should be discovered."""
    (tmp_path / "nested").mkdir()
    wanted = tmp_path / "nested" / "guide.md"
    skipped = tmp_path / "image.png"
    wanted.write_text("# hi\n", encoding="utf-8")
    skipped.write_bytes(b"png")

    paths = list_text_files(tmp_path)

    assert paths == [wanted]


def test_parse_template_metadata_uses_frontmatter_and_directory_defaults(tmp_path):
    """Template metadata should prefer frontmatter and fall back to the directory name."""
    named = tmp_path / "named-template" / "TEMPLATE.md"
    fallback = tmp_path / "fallback-template" / "TEMPLATE.md"
    named.parent.mkdir(parents=True)
    fallback.parent.mkdir(parents=True)
    named.write_text("---\nname: Recipe\ndescription: Dinner ideas\n---\nPrompt\n", encoding="utf-8")
    fallback.write_text("Prompt only\n", encoding="utf-8")

    assert parse_template_metadata(named) == ("Recipe", "Dinner ideas")
    assert parse_template_metadata(fallback) == ("fallback-template", "")


def test_template_body_strips_frontmatter_and_outer_whitespace(tmp_path):
    """Template bodies should omit frontmatter and trim surrounding blank lines."""
    path = tmp_path / "recipe" / "TEMPLATE.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: Recipe\n---\n\n  Hello {NAME}\n\n", encoding="utf-8")

    assert template_body(path) == "Hello {NAME}"


def test_list_available_templates_deduplicates_matching_real_files(tmp_path, monkeypatch):
    """Duplicate paths across central, bundled, and workspace roots should collapse to one entry."""
    shared = tmp_path / "shared-template" / "TEMPLATE.md"
    shared.parent.mkdir(parents=True)
    shared.write_text("---\nname: Shared\n---\nBody\n", encoding="utf-8")

    cfg = SimpleNamespace(templates_dir=tmp_path / "central-templates")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tuochat.discovery.templates.bundled_templates_dir", lambda: tmp_path / "bundled-templates")
    monkeypatch.setattr(
        "tuochat.discovery.templates.list_template_files_in_root",
        lambda root: [shared] if root in {cfg.templates_dir, tmp_path / "bundled-templates"} else [],
    )
    monkeypatch.setattr("tuochat.discovery.templates.list_workspace_template_files", lambda root: [shared])

    assert list_available_templates(cfg) == [shared]


def test_describe_template_path_labels_workspace_relative_templates(tmp_path, monkeypatch):
    """Workspace templates should be described relative to the current directory."""
    template = tmp_path / ".agents" / "templates" / "recipe" / "TEMPLATE.md"
    template.parent.mkdir(parents=True)
    template.write_text("---\nname: Dinner Plan\n---\nPrompt\n", encoding="utf-8")
    cfg = SimpleNamespace(templates_dir=tmp_path / "central-templates")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tuochat.discovery.templates.bundled_templates_dir", lambda: tmp_path / "bundled-templates")

    assert describe_template_path(template, cfg) == "cwd:.agents/templates/recipe (Dinner Plan)"


def test_bundled_templates_include_explain_and_refactor():
    """The package should ship the built-in explain and refactor templates."""
    bundled_root = bundled_templates_dir()

    explain_path = bundled_root / "explain" / "TEMPLATE.md"
    refactor_path = bundled_root / "refactor" / "TEMPLATE.md"

    assert explain_path.is_file()
    assert refactor_path.is_file()
    assert parse_template_metadata(explain_path)[0] == "explain"
    assert parse_template_metadata(refactor_path)[0] == "refactor"
