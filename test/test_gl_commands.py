"""Tests for Phase 3 — /gl artifact picker and server-context injection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tuochat.resources import ResourceDescriptor

GL_CATEGORY = "GitLabArtifact"


def make_state(**kwargs):
    from tuochat.resources import ResourceDescriptor

    project_resource = ResourceDescriptor(
        resource_id="gid://gitlab/Project/42",
        kind="project",
        display_label="MyProject",
        path="group/myproject",
    )
    defaults = dict(
        active_resource=project_resource,
        resource_candidates=[],
        server_context=[],
        cfg=SimpleNamespace(gitlab=SimpleNamespace(host="https://gitlab.example.com", token="tok", token_type="pat")),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _require_project
# ---------------------------------------------------------------------------


def test_require_project_no_resource(capsys):
    from tuochat.cli.commands.gl_cmd import require_project

    state = make_state(active_resource=None)
    result = require_project(state)
    assert result is None
    assert "resource" in capsys.readouterr().err.lower()


def test_require_project_group_resource(capsys):
    from tuochat.cli.commands.gl_cmd import require_project

    group_res = ResourceDescriptor(
        resource_id="gid://gitlab/Group/7",
        kind="group",
        display_label="MyGroup",
    )
    state = make_state(active_resource=group_res)
    result = require_project(state)
    assert result is None
    assert "not a project" in capsys.readouterr().err.lower()


def test_require_project_extracts_id():
    from tuochat.cli.commands.gl_cmd import require_project

    state = make_state()
    result = require_project(state)
    assert result == "42"


# ---------------------------------------------------------------------------
# /gl current
# ---------------------------------------------------------------------------


def test_gl_current_empty(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state()
    handle_gl_command("/gl", "current", state)
    out = capsys.readouterr().out
    assert "no gitlab" in out.lower() or "no gitl" in out.lower() or "no" in out.lower()


def test_gl_current_shows_items(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(
        server_context=[
            {"category": GL_CATEGORY, "name": "MyProject#issue-1", "content": "x" * 50},
            {"category": "OTHER", "name": "other", "content": "y"},
        ]
    )
    handle_gl_command("/gl", "current", state)
    out = capsys.readouterr().out
    assert "MyProject#issue-1" in out
    # OTHER category should not appear
    assert "other" not in out


# ---------------------------------------------------------------------------
# /gl remove
# ---------------------------------------------------------------------------


def test_gl_remove_existing(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(server_context=[{"category": GL_CATEGORY, "name": "MyProject#issue-5", "content": "c"}])
    handle_gl_command("/gl", "remove MyProject#issue-5", state)
    assert state.server_context == []
    assert "removed" in capsys.readouterr().out.lower()


def test_gl_remove_missing(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state()
    handle_gl_command("/gl", "remove does-not-exist", state)
    err = capsys.readouterr().err
    assert "no attached" in err.lower()


def test_gl_remove_no_arg(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state()
    handle_gl_command("/gl", "remove", state)
    err = capsys.readouterr().err
    assert "usage" in err.lower()


# ---------------------------------------------------------------------------
# /gl issue list
# ---------------------------------------------------------------------------


def test_gl_issue_list(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.list_issues.return_value = [
        {"iid": 1, "title": "First bug", "state": "opened", "url": "http://x/1", "description": "desc"},
        {"iid": 2, "title": "Second bug", "state": "opened", "url": "http://x/2", "description": ""},
    ]
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue", state)

    mock_client.list_issues.assert_called_once_with("42", state="opened")
    out = capsys.readouterr().out
    assert "First bug" in out
    assert "Second bug" in out
    assert state.server_context == []  # list doesn't attach


def test_gl_issue_list_empty(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.list_issues.return_value = []
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue", state)

    assert "no" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# /gl issue <iid>
# ---------------------------------------------------------------------------


def test_gl_issue_attach(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    issue_data = {
        "iid": 3,
        "title": "Login fails",
        "state": "opened",
        "url": "http://x/3",
        "description": "It breaks",
    }
    mock_client = MagicMock()
    mock_client.get_issue.return_value = issue_data
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue 3", state)

    mock_client.get_issue.assert_called_once_with("42", 3)
    assert len(state.server_context) == 1
    item = state.server_context[0]
    assert item["category"] == GL_CATEGORY
    assert "issue-3" in item["name"]
    assert "Login fails" in item["content"]
    assert "It breaks" in item["content"]


def test_gl_issue_attach_updates_existing(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    existing = {"category": GL_CATEGORY, "name": "MyProject#issue-3", "content": "old"}
    state = make_state(server_context=[existing])

    issue_data = {
        "iid": 3,
        "title": "Login fails",
        "state": "opened",
        "url": "http://x/3",
        "description": "New desc",
    }
    mock_client = MagicMock()
    mock_client.get_issue.return_value = issue_data
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue 3", state)

    assert len(state.server_context) == 1
    assert "New desc" in state.server_context[0]["content"]
    assert "updated" in capsys.readouterr().out.lower()


def test_gl_issue_not_found(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_issue.return_value = None
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue 99", state)

    assert state.server_context == []
    assert "not found" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# /gl mr list and attach
# ---------------------------------------------------------------------------


def test_gl_mr_list(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.list_mrs.return_value = [
        {
            "iid": 10,
            "title": "Add feature",
            "state": "opened",
            "url": "http://x/10",
            "description": "",
            "source_branch": "feat",
            "target_branch": "main",
        }
    ]
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr", state)

    out = capsys.readouterr().out
    assert "Add feature" in out
    assert "feat" in out
    assert state.server_context == []


def test_gl_mr_attach(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mr_data = {
        "iid": 10,
        "title": "Add feature",
        "state": "opened",
        "url": "http://x/10",
        "description": "Does stuff",
        "source_branch": "feat",
        "target_branch": "main",
    }
    mock_client = MagicMock()
    mock_client.get_mr.return_value = mr_data
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr 10", state)

    mock_client.get_mr.assert_called_once_with("42", 10)
    assert len(state.server_context) == 1
    item = state.server_context[0]
    assert item["category"] == GL_CATEGORY
    assert "mr-10" in item["name"]
    assert "Add feature" in item["content"]
    assert "feat" in item["content"]


def test_gl_mr_not_found(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_mr.return_value = None
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr 99", state)

    assert state.server_context == []
    assert "not found" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# /gl file
# ---------------------------------------------------------------------------


def test_gl_file_attach(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = "# README\nHello world"
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "file README.md", state)

    mock_client.get_file_content.assert_called_once_with("42", "README.md", "HEAD")
    assert len(state.server_context) == 1
    item = state.server_context[0]
    assert item["category"] == GL_CATEGORY
    assert "README.md" in item["name"]
    assert "Hello world" in item["content"]


def test_gl_file_with_ref(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = "content"
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "file src/main.py v1.0", state)

    mock_client.get_file_content.assert_called_once_with("42", "src/main.py", "v1.0")


def test_gl_file_not_found(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = None
    state = make_state()
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "file missing.py", state)

    assert state.server_context == []
    assert "not found" in capsys.readouterr().err.lower()


def test_gl_file_no_arg(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state()
    handle_gl_command("/gl", "file", state)
    assert "usage" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# No credentials / no project guards
# ---------------------------------------------------------------------------


def test_gl_no_credentials(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(cfg=SimpleNamespace(gitlab=SimpleNamespace(host="", token="", token_type="pat")))
    handle_gl_command("/gl", "issue", state)
    err = capsys.readouterr().err
    assert "configured" in err.lower() or "token" in err.lower() or "host" in err.lower()


def test_gl_no_project(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(active_resource=None)
    handle_gl_command("/gl", "issue", state)
    err = capsys.readouterr().err
    assert "resource" in err.lower() or "project" in err.lower()


# ---------------------------------------------------------------------------
# Unknown sub-command prints help
# ---------------------------------------------------------------------------


def test_gl_unknown_sub_prints_help(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state()
    handle_gl_command("/gl", "bogus", state)
    out = capsys.readouterr().out
    assert "issue" in out.lower()
    assert "mr" in out.lower()
    assert "file" in out.lower()
