"""Tests for Phase 1 (resource discovery) and Phase 2 (git awareness)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuochat.git_info import GitStatus, get_git_status
from tuochat.resources import ResourceDescriptor, resource_descriptor_from_group, resource_descriptor_from_project

# ---------------------------------------------------------------------------
# ResourceDescriptor
# ---------------------------------------------------------------------------


def test_resource_descriptor_str_with_path():
    r = ResourceDescriptor(
        resource_id="gid://gitlab/Project/42",
        kind="project",
        display_label="My Repo",
        path="mygroup/myrepo",
    )
    assert "project" in str(r)
    assert "My Repo" in str(r)
    assert "mygroup/myrepo" in str(r)


def test_resource_descriptor_str_no_path():
    r = ResourceDescriptor(resource_id="gid://gitlab/Group/7", kind="group", display_label="My Group")
    assert "group" in str(r)
    assert "My Group" in str(r)


def test_resource_descriptor_from_project():
    fake = SimpleNamespace(
        id=42, name="My Repo", path_with_namespace="mygroup/myrepo", web_url="https://gitlab.example.com/mygroup/myrepo"
    )
    r = resource_descriptor_from_project(fake)
    assert r.resource_id == "gid://gitlab/Project/42"
    assert r.kind == "project"
    assert r.display_label == "My Repo"
    assert r.path == "mygroup/myrepo"


def test_resource_descriptor_from_group():
    fake = SimpleNamespace(id=7, name="My Group", full_path="mygroup", web_url="https://gitlab.example.com/mygroup")
    r = resource_descriptor_from_group(fake)
    assert r.resource_id == "gid://gitlab/Group/7"
    assert r.kind == "group"
    assert r.display_label == "My Group"
    assert r.path == "mygroup"


# ---------------------------------------------------------------------------
# GitStatus
# ---------------------------------------------------------------------------


def test_git_status_dirty():
    gs = GitStatus(root=Path("/repo"), branch="main", staged=1, unstaged=2, untracked=0)
    assert gs.dirty is True
    assert "dirty" in gs.summary()
    assert "main" in gs.summary()


def test_git_status_clean():
    gs = GitStatus(root=Path("/repo"), branch="main")
    assert gs.dirty is False
    assert "clean" in gs.summary()


def test_git_status_detached_head():
    gs = GitStatus(root=Path("/repo"), branch=None)
    assert "detached" in gs.summary()


def test_git_status_ahead_behind():
    gs = GitStatus(root=Path("/repo"), branch="feat", ahead=3, behind=1)
    summary = gs.summary()
    assert "+3" in summary
    assert "-1" in summary


def test_get_git_status_non_repo(tmp_path):
    """A failed top-level probe is treated as a non-repo directory."""
    with patch("tuochat.git_info.run_git", return_value=(1, "")) as mock_run:
        result = get_git_status(tmp_path)

    mock_run.assert_called_once_with("rev-parse", "--show-toplevel", cwd=tmp_path)
    assert result is None


def test_get_git_status_real_repo():
    """Running inside the tuochat repo should return a non-None GitStatus."""
    result = get_git_status(Path(__file__).parent.parent)
    if result is None:
        pytest.skip("no .git directory available (e.g. Docker build context strips .git)")
    assert result.root is not None
    assert isinstance(result.dirty, bool)


def test_get_git_status_parses_branch_sync_and_status_counts():
    responses = [
        (0, "C:/repo"),
        (0, "main"),
        (0, "2 3"),
        (0, "M  staged.txt\n M unstaged.txt\nMM both.txt\n?? new.txt"),
    ]

    with patch("tuochat.git_info.run_git", side_effect=responses):
        result = get_git_status(Path("C:/repo/subdir"))

    assert result == GitStatus(
        root=Path("C:/repo"),
        branch="main",
        staged=2,
        unstaged=2,
        untracked=1,
        ahead=3,
        behind=2,
    )


def test_get_git_status_treats_head_as_detached_and_skips_missing_upstream():
    responses = [
        (0, "C:/repo"),
        (0, "HEAD"),
        (1, ""),
        (0, ""),
    ]

    with patch("tuochat.git_info.run_git", side_effect=responses):
        result = get_git_status(Path("C:/repo"))

    assert result is not None
    assert result.branch is None
    assert result.ahead is None
    assert result.behind is None
    assert result.dirty is False


def test_get_git_status_ignores_invalid_ahead_behind_counts():
    responses = [
        (0, "C:/repo"),
        (0, "main"),
        (0, "oops nope"),
        (0, ""),
    ]

    with patch("tuochat.git_info.run_git", side_effect=responses):
        result = get_git_status(Path("C:/repo"))

    assert result is not None
    assert result.ahead is None
    assert result.behind is None


@pytest.mark.parametrize(
    ("status_out", "expected"),
    [
        ("A  added.txt", (1, 0, 0)),
        (" M modified.txt", (0, 1, 0)),
        ("?? new.txt", (0, 0, 1)),
        ("AM staged-and-modified.txt", (1, 1, 0)),
        ("R  old.txt -> new.txt\n D removed.txt", (1, 1, 0)),
    ],
)
def test_get_git_status_counts_porcelain_variants(status_out, expected):
    responses = [
        (0, "C:/repo"),
        (0, "main"),
        (1, ""),
        (0, status_out),
    ]

    with patch("tuochat.git_info.run_git", side_effect=responses):
        result = get_git_status(Path("C:/repo"))

    assert result is not None
    assert (result.staged, result.unstaged, result.untracked) == expected


# ---------------------------------------------------------------------------
# resource_cmd — unit tests for the handler logic
# ---------------------------------------------------------------------------


def make_state(**kwargs):
    """Minimal ReplState-like namespace for testing resource_cmd without full REPL."""
    defaults = dict(
        active_resource=None,
        resource_candidates=[],
        server_context=[],
        cfg=SimpleNamespace(gitlab=SimpleNamespace(host="https://gitlab.example.com", token="tok", token_type="pat")),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def project_resource(resource_id: int = 1, label: str = "Alpha", path: str = "g/alpha") -> ResourceDescriptor:
    return ResourceDescriptor(
        resource_id=f"gid://gitlab/Project/{resource_id}",
        kind="project",
        display_label=label,
        path=path,
    )


def test_resource_cmd_show_current_none(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state()
    handle_resource_command("/resource", "", state)
    out = capsys.readouterr().out
    assert "No resource" in out


def test_resource_cmd_show_current_set(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    r = ResourceDescriptor(resource_id="gid://gitlab/Project/1", kind="project", display_label="Alpha", path="g/alpha")
    state = make_state(active_resource=r)
    handle_resource_command("/resource", "", state)
    out = capsys.readouterr().out
    assert "Alpha" in out
    assert "project" in out


def test_resource_cmd_clear(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    r = ResourceDescriptor(resource_id="gid://gitlab/Project/1", kind="project", display_label="Alpha")
    state = make_state(active_resource=r)
    handle_resource_command("/resource", "clear", state)
    assert state.active_resource is None
    out = capsys.readouterr().out
    assert "cleared" in out.lower()


def test_resource_cmd_clear_none(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state()
    handle_resource_command("/resource", "clear", state)
    out = capsys.readouterr().out
    assert "No resource" in out


def test_resource_cmd_pick_no_candidates(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state()
    handle_resource_command("/resource", "pick 0", state)
    err = capsys.readouterr().err
    assert "list" in err.lower() or "no resource" in err.lower()


def test_resource_cmd_pick_valid(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    candidates = [
        ResourceDescriptor(resource_id="gid://gitlab/Project/1", kind="project", display_label="Alpha"),
        ResourceDescriptor(resource_id="gid://gitlab/Project/2", kind="project", display_label="Beta"),
    ]
    state = make_state(resource_candidates=candidates)
    handle_resource_command("/resource", "pick 1", state)
    assert state.active_resource is not None
    assert state.active_resource.display_label == "Beta"
    out = capsys.readouterr().out
    assert "Beta" in out


def test_resource_cmd_pick_out_of_range(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    candidates = [
        ResourceDescriptor(resource_id="gid://gitlab/Project/1", kind="project", display_label="Alpha"),
    ]
    state = make_state(resource_candidates=candidates)
    handle_resource_command("/resource", "pick 5", state)
    assert state.active_resource is None
    err = capsys.readouterr().err
    assert "range" in err.lower() or "out of" in err.lower()


def test_resource_cmd_list_calls_client(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    mock_client = MagicMock()
    mock_client.list_projects.return_value = [
        ResourceDescriptor(resource_id="gid://gitlab/Project/1", kind="project", display_label="Alpha", path="g/alpha"),
    ]
    state = make_state()
    # build_client imports GitLabMetaClient lazily — patch at the source module
    with patch("tuochat.gitlab_client.GitLabMetaClient", return_value=mock_client):
        with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
            handle_resource_command("/resource", "list", state)

    assert len(state.resource_candidates) == 1
    out = capsys.readouterr().out
    assert "Alpha" in out


def test_resource_cmd_list_search(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    mock_client = MagicMock()
    mock_client.search_projects.return_value = [
        ResourceDescriptor(resource_id="gid://gitlab/Project/9", kind="project", display_label="Foo"),
    ]
    state = make_state()
    with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
        handle_resource_command("/resource", "list foo", state)

    mock_client.search_projects.assert_called_once_with("foo")
    out = capsys.readouterr().out
    assert "Foo" in out


def test_resource_cmd_set_by_path(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    found = ResourceDescriptor(
        resource_id="gid://gitlab/Project/3", kind="project", display_label="Gamma", path="g/gamma"
    )
    mock_client = MagicMock()
    mock_client.get_project_by_path.return_value = found
    state = make_state()
    with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
        handle_resource_command("/resource", "set g/gamma", state)

    assert state.active_resource is not None
    assert state.active_resource.display_label == "Gamma"


def test_resource_cmd_set_not_found(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    mock_client = MagicMock()
    mock_client.get_project_by_path.return_value = None
    state = make_state()
    with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
        handle_resource_command("/resource", "set x/y", state)

    assert state.active_resource is None
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_resource_cmd_no_credentials(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state(cfg=SimpleNamespace(gitlab=SimpleNamespace(host="", token="", token_type="pat")))
    handle_resource_command("/resource", "list", state)
    err = capsys.readouterr().err
    assert "host" in err.lower() or "configured" in err.lower()


def test_resource_cmd_missing_gitlab_extra(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state()
    with patch("tuochat.gitlab_client.GitLabMetaClient", side_effect=ImportError("Install tuochat[gitlab]")):
        handle_resource_command("/resource", "list", state)

    err = capsys.readouterr().err
    assert "tuochat[gitlab]" in err


def test_gl_cmd_missing_gitlab_extra(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(
        active_resource=ResourceDescriptor(
            resource_id="gid://gitlab/Project/1",
            kind="project",
            display_label="Alpha",
            path="g/alpha",
        ),
        server_context=[],
    )
    with patch("tuochat.gitlab_client.GitLabMetaClient", side_effect=ImportError("Install tuochat[gitlab]")):
        handle_gl_command("/gl", "issue", state)

    err = capsys.readouterr().err
    assert "tuochat[gitlab]" in err


def test_resource_cmd_pick_missing_index(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state(resource_candidates=[project_resource()])
    handle_resource_command("/resource", "pick", state)

    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_resource_cmd_pick_non_numeric(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state(resource_candidates=[project_resource()])
    handle_resource_command("/resource", "pick nope", state)

    err = capsys.readouterr().err
    assert "expected a number" in err.lower()


def test_resource_cmd_list_no_results(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    mock_client = MagicMock()
    mock_client.list_projects.return_value = []
    state = make_state()
    with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
        handle_resource_command("/resource", "list", state)

    out = capsys.readouterr().out
    assert "No projects found." in out


def test_resource_cmd_list_marks_active_resource(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    active = project_resource()
    mock_client = MagicMock()
    mock_client.list_projects.return_value = [active, project_resource(resource_id=2, label="Beta", path="g/beta")]
    state = make_state(active_resource=active)
    with patch("tuochat.cli.commands.resource_cmd.build_client", return_value=mock_client):
        handle_resource_command("/resource", "list", state)

    out = capsys.readouterr().out
    assert "[0]* Alpha" in out


def test_resource_cmd_set_missing_path(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    state = make_state()
    handle_resource_command("/resource", "set", state)

    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_resource_cmd_unknown_subcommand_prints_help(capsys):
    from tuochat.cli.commands.resource_cmd import handle_resource_command

    handle_resource_command("/resource", "wat", make_state())

    out = capsys.readouterr().out
    assert "Resource commands:" in out


def test_gl_cmd_requires_active_project(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    handle_gl_command("/gl", "issue", make_state())

    err = capsys.readouterr().err
    assert "no project selected" in err.lower()


def test_gl_cmd_rejects_group_resource(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    state = make_state(
        active_resource=ResourceDescriptor(
            resource_id="gid://gitlab/Group/7",
            kind="group",
            display_label="My Group",
            path="my-group",
        )
    )
    handle_gl_command("/gl", "issue", state)

    err = capsys.readouterr().err
    assert "not a project" in err.lower()


def test_gl_cmd_unknown_subcommand_prints_help(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    handle_gl_command("/gl", "wat", make_state())

    out = capsys.readouterr().out
    assert "GitLab artifact commands:" in out


def test_gl_issue_list_defaults_invalid_state_to_opened(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.list_issues.return_value = [
        {"iid": 1, "title": "Fix login", "state": "opened", "url": "https://x", "description": ""}
    ]
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue bogus", state)

    mock_client.list_issues.assert_called_once_with("1", state="opened")
    out = capsys.readouterr().out
    assert "opened issues" in out


def test_gl_issue_attach_not_found(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_issue.return_value = None
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue 42", state)

    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_gl_issue_attach_adds_context(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    mock_client = MagicMock()
    mock_client.get_issue.return_value = {
        "iid": 42,
        "title": "Fix login",
        "state": "opened",
        "url": "https://gitlab.example.com/g/alpha/-/issues/42",
        "description": "Detailed issue body",
    }
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "issue 42", state)

    assert state.server_context == [
        {
            "category": GL_CATEGORY,
            "name": "Alpha#issue-42",
            "content": (
                "GitLab Issue: Alpha#42\n"
                "Title: Fix login\n"
                "State: opened\n"
                "URL: https://gitlab.example.com/g/alpha/-/issues/42\n\n"
                "Description:\n"
                "Detailed issue body"
            ),
        }
    ]
    out = capsys.readouterr().out
    assert "Attached: Alpha#issue-42" in out


def test_gl_mr_list_defaults_invalid_state_to_opened(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.list_mrs.return_value = [
        {
            "iid": 5,
            "title": "Add endpoint",
            "state": "opened",
            "url": "https://x",
            "description": "",
            "source_branch": "feature",
            "target_branch": "main",
        }
    ]
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr bogus", state)

    mock_client.list_mrs.assert_called_once_with("1", state="opened")
    out = capsys.readouterr().out
    assert "opened merge requests" in out


def test_gl_mr_attach_not_found(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_mr.return_value = None
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr 5", state)

    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_gl_mr_attach_adds_context(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    mock_client = MagicMock()
    mock_client.get_mr.return_value = {
        "iid": 5,
        "title": "Add endpoint",
        "state": "opened",
        "url": "https://gitlab.example.com/g/alpha/-/merge_requests/5",
        "description": "Detailed MR body",
        "source_branch": "feature",
        "target_branch": "main",
    }
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "mr 5", state)

    assert state.server_context == [
        {
            "category": GL_CATEGORY,
            "name": "Alpha!mr-5",
            "content": (
                "GitLab Merge Request: Alpha!5\n"
                "Title: Add endpoint\n"
                "State: opened\n"
                "Branches: feature -> main\n"
                "URL: https://gitlab.example.com/g/alpha/-/merge_requests/5\n\n"
                "Description:\n"
                "Detailed MR body"
            ),
        }
    ]
    out = capsys.readouterr().out
    assert "Attached: Alpha!mr-5" in out


def test_gl_file_requires_argument(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    handle_gl_command("/gl", "file", make_state(active_resource=project_resource()))

    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_gl_file_missing_content(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = None
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "file README.md main", state)

    err = capsys.readouterr().err
    assert "file not found" in err.lower()


def test_gl_file_attaches_context_with_ref(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    mock_client = MagicMock()
    mock_client.get_file_content.return_value = "# Hello\nworld"
    state = make_state(active_resource=project_resource())
    with patch("tuochat.cli.commands.gl_cmd.build_client", return_value=mock_client):
        handle_gl_command("/gl", "file README.md main", state)

    mock_client.get_file_content.assert_called_once_with("1", "README.md", "main")
    assert state.server_context == [
        {
            "category": GL_CATEGORY,
            "name": "Alpha:README.md",
            "content": "Repository file: Alpha/README.md (ref: main)\n\n# Hello\nworld",
        }
    ]
    out = capsys.readouterr().out
    assert "File: README.md" in out


def test_gl_current_lists_attached_artifacts(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    state = make_state(
        server_context=[
            {"category": GL_CATEGORY, "name": "Alpha#issue-42", "content": "hello"},
            {"category": "FILE", "name": "notes", "content": "skip"},
        ]
    )
    handle_gl_command("/gl", "current", state)

    out = capsys.readouterr().out
    assert "Attached GitLab artifacts (1):" in out
    assert "Alpha#issue-42" in out
    assert "notes" not in out


def test_gl_remove_requires_name(capsys):
    from tuochat.cli.commands.gl_cmd import handle_gl_command

    handle_gl_command("/gl", "remove", make_state())

    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_gl_remove_missing_entry(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    state = make_state(server_context=[{"category": GL_CATEGORY, "name": "Alpha#issue-1", "content": "body"}])
    handle_gl_command("/gl", "remove missing", state)

    err = capsys.readouterr().err
    assert "no attached artifact" in err.lower()


def test_gl_remove_deletes_only_matching_gitlab_entry(capsys):
    from tuochat.cli.commands.gl_cmd import GL_CATEGORY, handle_gl_command

    state = make_state(
        server_context=[
            {"category": GL_CATEGORY, "name": "Alpha#issue-1", "content": "issue"},
            {"category": "FILE", "name": "Alpha#issue-1", "content": "keep"},
        ]
    )
    handle_gl_command("/gl", "remove Alpha#issue-1", state)

    assert state.server_context == [{"category": "FILE", "name": "Alpha#issue-1", "content": "keep"}]
    out = capsys.readouterr().out
    assert "Removed: Alpha#issue-1" in out


def test_gl_upsert_context_updates_existing_entry(capsys):
    from tuochat.cli.commands import gl_cmd

    state = make_state(server_context=[{"category": gl_cmd.GL_CATEGORY, "name": "Alpha#issue-1", "content": "old"}])
    gl_cmd.upsert_context(state, "Alpha#issue-1", "new")

    assert state.server_context == [{"category": gl_cmd.GL_CATEGORY, "name": "Alpha#issue-1", "content": "new"}]
    out = capsys.readouterr().out
    assert "Updated context: Alpha#issue-1" in out


# ---------------------------------------------------------------------------
# toggle_write_here_mode dirty-tree integration
# ---------------------------------------------------------------------------


def make_repl_state():
    """Build a minimal ReplState for session tests."""
    from tuochat.cli.models import ReplState
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation
    from tuochat.persistence import NullConversationStore

    cfg = TuochatConfig()
    return ReplState(
        conv=Conversation(title="test"),
        store=NullConversationStore(cfg.db_path),
        provider=object(),  # type: ignore[arg-type]
        cfg=cfg,
        streaming=True,
    )


def test_toggle_write_here_warns_on_dirty_tree(capsys, tmp_path):
    from tuochat.cli.session import toggle_write_here_mode
    from tuochat.git_info import GitStatus

    state = make_repl_state()
    dirty = GitStatus(root=tmp_path, branch="main", staged=0, unstaged=2, untracked=1)

    # get_git_status is imported lazily inside toggle_write_here_mode — patch at source
    with patch("tuochat.git_info.get_git_status", return_value=dirty):
        with patch("tuochat.cli.session.cwd_is_filesystem_root", return_value=False):
            with patch("tuochat.cli.session.set_session_write_here_mode"):
                toggle_write_here_mode(state, True)

    out = capsys.readouterr().out
    assert "dirty" in out.lower() or "warning" in out.lower()


def test_toggle_write_here_blocks_when_refuse_enabled(capsys, tmp_path):
    from tuochat.cli.session import toggle_write_here_mode
    from tuochat.git_info import GitStatus

    state = make_repl_state()
    state.cfg.chat.refuse_writes_on_dirty_tree = True
    dirty = GitStatus(root=tmp_path, branch="main", staged=1, unstaged=0, untracked=0)

    with patch("tuochat.git_info.get_git_status", return_value=dirty):
        with patch("tuochat.cli.session.cwd_is_filesystem_root", return_value=False):
            with patch("tuochat.cli.session.set_session_write_here_mode") as mock_set:
                toggle_write_here_mode(state, True)
                mock_set.assert_not_called()

    err = capsys.readouterr().err
    assert "blocked" in err.lower() or "dirty" in err.lower()


def test_toggle_write_here_clean_tree_proceeds(tmp_path):
    from tuochat.cli.session import toggle_write_here_mode
    from tuochat.git_info import GitStatus

    state = make_repl_state()
    clean = GitStatus(root=tmp_path, branch="main")

    with patch("tuochat.git_info.get_git_status", return_value=clean):
        with patch("tuochat.cli.session.cwd_is_filesystem_root", return_value=False):
            with patch("tuochat.cli.session.set_session_write_here_mode") as mock_set:
                toggle_write_here_mode(state, True)
                mock_set.assert_called_once_with(state.cfg, True)
