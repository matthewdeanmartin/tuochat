from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tuochat.constants import DEFAULT_MAP_GLOBS
from tuochat.context.attachments import (
    attachment_stub_name,
    code_fence_language,
    has_glob_chars,
    is_probably_binary,
    prepare_include,
    read_include_file,
    read_safe_text_file,
    split_map_globs,
)


def test_is_probably_binary():
    assert is_probably_binary(b"") is False
    assert is_probably_binary(b"Hello world") is False
    assert is_probably_binary(b"\x00\x01\x02") is True
    # 30% suspicious bytes threshold
    # 0-8, 14-31, 127 are suspicious
    assert is_probably_binary(bytes(range(10))) is True  # 0-8 are 9 bytes, 9 is 1 byte. 9/10 = 90% > 30%
    assert is_probably_binary(b"A" * 70 + b"\x01" * 30) is False  # exactly 30% is False because it uses > 0.30
    assert is_probably_binary(b"A" * 69 + b"\x01" * 31) is True  # > 30%


def test_read_safe_text_file(tmp_path):
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello UTF-8", encoding="utf-8")
    result = read_safe_text_file(txt_file)
    assert result is not None
    text, fingerprint, size = result
    assert text == "Hello UTF-8"
    assert fingerprint == hashlib.sha256(b"Hello UTF-8").hexdigest()
    assert size == len(b"Hello UTF-8")

    bin_file = tmp_path / "test.bin"
    bin_file.write_bytes(b"\x00\x01\x02")
    assert read_safe_text_file(bin_file) is None

    # Invalid UTF-8
    invalid_file = tmp_path / "invalid.txt"
    invalid_file.write_bytes(b"\xff\xfe\xfd")  # Not valid UTF-8
    assert read_safe_text_file(invalid_file) is None


def test_read_include_file(tmp_path):
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello UTF-8", encoding="utf-8")
    text, fingerprint, size = read_include_file(txt_file)
    assert text == "Hello UTF-8"

    bin_file = tmp_path / "test.bin"
    bin_file.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError, match="Binary files are not supported"):
        read_include_file(bin_file)

    invalid_file = tmp_path / "invalid.txt"
    invalid_file.write_bytes(b"\xff\xfe\xfd")
    with pytest.raises(UnicodeDecodeError):
        read_include_file(invalid_file)


def test_split_map_globs():
    assert split_map_globs(None) == list(DEFAULT_MAP_GLOBS)
    assert split_map_globs("") == list(DEFAULT_MAP_GLOBS)
    assert split_map_globs("*.py|*.md") == ["*.py", "*.md"]
    assert split_map_globs("  *.py  |  ") == ["*.py"]


def test_code_fence_language():
    assert code_fence_language(Path("test.py")) == "python"
    assert code_fence_language(Path("test.yaml")) == "yaml"
    assert code_fence_language(Path("test.yml")) == "yaml"
    assert code_fence_language(Path("test.ps1")) == "powershell"
    assert code_fence_language(Path("test.js")) == "javascript"
    assert code_fence_language(Path("test.ts")) == "typescript"
    assert code_fence_language(Path("README.md")) == "markdown"
    assert code_fence_language(Path("plain.txt")) == "txt"
    assert code_fence_language(Path("no_extension")) == "text"


def test_has_glob_chars():
    assert has_glob_chars("*.py") is True
    assert has_glob_chars("test?.txt") is True
    assert has_glob_chars("file[0-9].txt") is True
    assert has_glob_chars("plain_file.txt") is False


def test_attachment_stub_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # re.sub(r"[^A-Za-z0-9._-]+", "-", "*.py") -> "-.py"
    # "-.py".strip("-") -> ".py"
    # f"prefix-.py.stub"
    assert attachment_stub_name("prefix", "*.py", ".stub") == tmp_path / "prefix-.py.stub"
    assert attachment_stub_name("map", None, ".txt") == tmp_path / "map-default.txt"
    # "src/**/*.ts" -> "src-.ts" because "/**/*" matches [^A-Za-z0-9._-]+
    assert attachment_stub_name("code", "src/**/*.ts", ".md") == tmp_path / "code-src-.ts.md"


class MockState:
    def __init__(self):
        self.pending_attachment_messages = None
        self.pending_attachment_names = None


def test_queue_management():
    state = MockState()
    from tuochat.context.attachments import clear_pending_attachments, consume_pending_attachments, queue_attachment

    queue_attachment(state, Path("file1.txt"), "message1")
    assert state.pending_attachment_names == ["file1.txt"]
    assert state.pending_attachment_messages == ["message1"]

    queue_attachment(state, Path("file2.txt"), "message2")
    assert state.pending_attachment_names == ["file1.txt", "file2.txt"]
    assert state.pending_attachment_messages == ["message1", "message2"]

    consume_pending_attachments(state, 1)
    assert state.pending_attachment_names == ["file2.txt"]
    assert state.pending_attachment_messages == ["message2"]

    clear_pending_attachments(state)
    assert state.pending_attachment_names == []
    assert state.pending_attachment_messages == []


def test_detach_pending_attachment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state = MockState()
    from tuochat.context.attachments import detach_pending_attachment, queue_attachment

    queue_attachment(state, tmp_path / "file1.txt", "msg1")
    queue_attachment(state, tmp_path / "file2.txt", "msg2")
    queue_attachment(state, tmp_path / "file3.txt", "msg3")

    # Detach by index
    assert detach_pending_attachment(state, "2") is True
    assert state.pending_attachment_names == [str(tmp_path / "file1.txt"), str(tmp_path / "file3.txt")]

    # Detach by name (relative)
    (tmp_path / "file3.txt").touch()  # Need it to exist for some logic maybe?
    # Actually detach_pending_attachment uses Path(name).relative_to(cwd)
    assert detach_pending_attachment(state, "file3.txt") is True
    assert state.pending_attachment_names == [str(tmp_path / "file1.txt")]

    # Detach all
    queue_attachment(state, tmp_path / "file2.txt", "msg2")
    assert detach_pending_attachment(state, "all") is True
    assert state.pending_attachment_names == []

    # Detach non-existent
    assert detach_pending_attachment(state, "nonexistent") is False


def test_list_include_candidates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import list_include_candidates

    (tmp_path / "test.py").touch()
    (tmp_path / "README.md").touch()
    (tmp_path / "data.bin").touch()  # Should be ignored if suffix not in allowed
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "secret.py").touch()  # Should be ignored

    candidates = list_include_candidates()
    names = {p.name for p in candidates}
    assert "test.py" in names
    assert "README.md" in names
    assert "data.bin" not in names
    assert "secret.py" not in names


def test_list_include_candidates_respects_supported_ignore_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import list_include_candidates_under

    (tmp_path / ".agentignore").write_text("secret.py\nbuild/\n!build/keep.py\n", encoding="utf-8")
    (tmp_path / "visible.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("print('nope')\n", encoding="utf-8")
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "drop.py").write_text("print('drop')\n", encoding="utf-8")
    (build_dir / "keep.py").write_text("print('keep')\n", encoding="utf-8")

    candidates = list_include_candidates_under(tmp_path, limit=None)
    relpaths = {path.relative_to(tmp_path).as_posix() for path in candidates}

    assert "visible.py" in relpaths
    assert "secret.py" not in relpaths
    assert "build/drop.py" not in relpaths
    assert "build/keep.py" in relpaths


def test_select_include_candidates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import select_include_candidates

    (tmp_path / "file1.py").touch()
    (tmp_path / "file2.py").touch()
    (tmp_path / "other.md").touch()

    state = MockState()
    state.last_candidates = [tmp_path / "file1.py", tmp_path / "file2.py", tmp_path / "other.md"]

    # Select by index
    assert select_include_candidates("1", state) == [tmp_path / "file1.py"]
    assert select_include_candidates("3", state) == [tmp_path / "other.md"]
    assert select_include_candidates("4", state) is None

    # Select by plain path
    assert select_include_candidates("file1.py", state) == [tmp_path / "file1.py"]

    # Select by glob - resolve both sides to absolute for comparison
    matches = select_include_candidates("*.py", state)
    assert matches is not None
    assert {p.resolve() for p in matches} == {(tmp_path / "file1.py").resolve(), (tmp_path / "file2.py").resolve()}

    # Select by glob with limit
    matches = select_include_candidates("*.py 1", state)
    assert matches is not None
    assert len(matches) == 1
    assert matches[0].resolve() in {(tmp_path / "file1.py").resolve(), (tmp_path / "file2.py").resolve()}


def test_select_include_candidates_rejects_ignored_path(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import select_include_candidates

    (tmp_path / ".agentignore").write_text("secret.py\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("print('secret')\n", encoding="utf-8")

    state = MockState()

    assert select_include_candidates("secret.py", state) is None
    assert "excluded by ignore rules" in capsys.readouterr().err


def test_prepare_include_rejects_ignored_file(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claudeignore").write_text("hidden.md\n", encoding="utf-8")
    hidden = tmp_path / "hidden.md"
    hidden.write_text("sneaky\n", encoding="utf-8")

    assert prepare_include(hidden, MockState()) is None
    assert "excluded by ignore rules" in capsys.readouterr().err


def test_map_candidates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import map_candidates

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").touch()
    (tmp_path / "src" / "util.py").touch()
    (tmp_path / "README.md").touch()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").touch()

    candidates = map_candidates(tmp_path, "*.py", 10)
    names = {p.name for p in candidates}
    assert "main.py" in names
    assert "util.py" in names
    assert "README.md" not in names
    assert "config" not in names  # .git is ignored


def test_map_candidates_respects_supported_ignore_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import map_candidates

    (tmp_path / ".claudeignore").write_text("src/ignore.py\n", encoding="utf-8")
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "keep.py").write_text("print('keep')\n", encoding="utf-8")
    (source_dir / "ignore.py").write_text("print('ignore')\n", encoding="utf-8")

    candidates = map_candidates(tmp_path, "*.py", 10)
    relpaths = {path.relative_to(tmp_path).as_posix() for path in candidates}

    assert "src/keep.py" in relpaths
    assert "src/ignore.py" not in relpaths


def test_render_map_attachment(tmp_path):
    from tuochat.context.attachments import render_map_attachment

    matches = [tmp_path / "file1.txt", tmp_path / "file2.txt"]
    for m in matches:
        m.touch()

    rendered = render_map_attachment(tmp_path, matches, glob_pattern="*.txt", limit=10)
    assert "Directory map for:" in rendered
    assert "Glob: *.txt" in rendered
    assert "file1.txt" in rendered
    assert "file2.txt" in rendered


def test_code_map_candidates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from tuochat.context.attachments import code_map_candidates

    (tmp_path / "test.py").write_text("print('hello')")
    (tmp_path / "test.bin").write_bytes(b"\x00\x01\x02")

    matches = code_map_candidates(tmp_path, "*", 10)
    names = {p.name for p in matches}
    assert "test.py" in names
    assert "test.bin" not in names  # Binary files should be excluded from code map
