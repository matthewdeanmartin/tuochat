from __future__ import annotations

from tuochat.discovery.custom_instructions import (
    custom_instruction_source_for_path,
    describe_custom_instruction_path,
    list_workspace_custom_instruction_files,
)


class MockConfig:
    def __init__(self, custom_instructions_dir):
        self.custom_instructions_dir = custom_instructions_dir


def test_custom_instruction_source_for_path(monkeypatch, tmp_path):
    central_dir = tmp_path / "central"
    central_dir.mkdir()
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    cfg = MockConfig(custom_instructions_dir=central_dir)
    monkeypatch.setattr("tuochat.discovery.custom_instructions.bundled_custom_instructions_dir", lambda: bundled_dir)

    central_file = central_dir / "test.md"
    bundled_file = bundled_dir / "test.md"
    workspace_file = workspace_dir / "test.md"

    # Need to make sure they exist for .resolve() and .is_relative_to() logic if needed
    central_file.touch()
    bundled_file.touch()
    workspace_file.touch()

    assert custom_instruction_source_for_path(central_file, cfg) == "central"
    assert custom_instruction_source_for_path(bundled_file, cfg) == "bundled"
    assert custom_instruction_source_for_path(workspace_file, cfg) == "workspace"


def test_describe_custom_instruction_path(monkeypatch, tmp_path):
    central_dir = tmp_path / "central"
    central_dir.mkdir()
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()

    monkeypatch.chdir(cwd_dir)
    cfg = MockConfig(custom_instructions_dir=central_dir)
    monkeypatch.setattr("tuochat.discovery.custom_instructions.bundled_custom_instructions_dir", lambda: bundled_dir)

    central_file = central_dir / "subdir" / "test.md"
    bundled_file = bundled_dir / "test.md"
    cwd_file = cwd_dir / "local.md"

    # Ensure they exist
    (central_dir / "subdir").mkdir()
    central_file.touch()
    bundled_file.touch()
    cwd_file.touch()

    assert describe_custom_instruction_path(central_file, cfg) == "central:subdir/test.md"
    assert describe_custom_instruction_path(bundled_file, cfg) == "bundled:test.md"
    assert describe_custom_instruction_path(cwd_file, cfg) == "cwd:local.md"


def test_list_workspace_custom_instruction_files(tmp_path):
    (tmp_path / ".tuochat").mkdir()
    (tmp_path / ".tuochat" / "custom_instructions").mkdir()
    (tmp_path / ".tuochat" / "custom_instructions" / "instr.md").touch()
    (tmp_path / "other.txt").touch()

    files = list_workspace_custom_instruction_files(tmp_path)
    names = [f.name for f in files]
    assert "instr.md" in names
    assert "other.txt" not in names
