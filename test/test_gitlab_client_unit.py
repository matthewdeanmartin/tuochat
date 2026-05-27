from __future__ import annotations

import base64
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from tuochat.config import default_gitlab_user_agent
from tuochat.gitlab_client import GitLabMetaClient, get_gitlab_module


@pytest.fixture
def mock_gitlab():
    with patch("tuochat.gitlab_client.get_gitlab_module") as mock_get:
        mock_module = MagicMock()
        mock_get.return_value = mock_module
        yield mock_module


@pytest.fixture
def client(mock_gitlab):
    return GitLabMetaClient("https://gitlab.com", "token", "pat")


def test_init_pat(mock_gitlab):
    GitLabMetaClient("https://gitlab.com", "my-token", "pat")
    mock_gitlab.Gitlab.assert_called_once_with(
        url="https://gitlab.com",
        private_token="my-token",
        oauth_token=None,
        user_agent=default_gitlab_user_agent(),
    )


def test_init_oauth(mock_gitlab):
    GitLabMetaClient("https://gitlab.com", "my-token", "oauth")
    mock_gitlab.Gitlab.assert_called_once_with(
        url="https://gitlab.com",
        private_token=None,
        oauth_token="my-token",
        user_agent=default_gitlab_user_agent(),
    )


def test_get_gitlab_module_returns_imported_module():
    fake_module = ModuleType("gitlab")
    with patch("tuochat.gitlab_client.importlib.import_module", return_value=fake_module) as mock_import:
        result = get_gitlab_module()

    assert result is fake_module
    mock_import.assert_called_once_with("gitlab")


def test_get_gitlab_module_missing_dependency_raises_helpful_error():
    with patch("tuochat.gitlab_client.importlib.import_module", side_effect=ImportError("missing")):
        with pytest.raises(ImportError, match="tuochat\\[gitlab\\]"):
            get_gitlab_module()


def test_list_projects(client):
    mock_p = MagicMock()
    mock_p.id = 123
    mock_p.name = "Project"
    mock_p.path_with_namespace = "group/project"
    mock_p.web_url = "https://gitlab.com/group/project"

    client.gl.projects.list.return_value = [mock_p]

    results = client.list_projects(limit=10)
    assert len(results) == 1
    assert results[0].resource_id == "gid://gitlab/Project/123"
    client.gl.projects.list.assert_called_once_with(membership=True, per_page=10, get_all=False)


def test_list_projects_error(client):
    client.gl.projects.list.side_effect = Exception("error")
    results = client.list_projects()
    assert results == []


def test_list_projects_allows_membership_override(client):
    client.gl.projects.list.return_value = []

    client.list_projects(limit=7, membership=False)

    client.gl.projects.list.assert_called_once_with(membership=False, per_page=7, get_all=False)


def test_list_groups(client):
    mock_g = MagicMock()
    mock_g.id = 456
    mock_g.name = "Group"
    mock_g.full_path = "group"
    mock_g.web_url = "https://gitlab.com/group"

    client.gl.groups.list.return_value = [mock_g]

    results = client.list_groups(limit=5)
    assert len(results) == 1
    assert results[0].resource_id == "gid://gitlab/Group/456"
    client.gl.groups.list.assert_called_once_with(per_page=5, get_all=False)


def test_list_groups_error(client):
    client.gl.groups.list.side_effect = Exception("error")

    assert client.list_groups() == []


def test_search_projects(client):
    mock_p = MagicMock()
    mock_p.id = 789
    mock_p.name = "Search Result"
    mock_p.path_with_namespace = "group/search"
    mock_p.web_url = "https://gitlab.com/group/search"

    client.gl.projects.list.return_value = [mock_p]

    results = client.search_projects("query", limit=3)
    assert len(results) == 1
    client.gl.projects.list.assert_called_once_with(search="query", per_page=3, get_all=False)


def test_search_projects_error(client):
    client.gl.projects.list.side_effect = Exception("error")

    assert client.search_projects("query") == []


def test_get_project_by_path(client):
    mock_p = MagicMock()
    mock_p.id = 1
    mock_p.name = "P"
    mock_p.path_with_namespace = "group/p"
    mock_p.web_url = "https://gitlab.com/group/p"

    client.gl.projects.get.return_value = mock_p

    result = client.get_project_by_path("group/p")
    assert result is not None
    assert result.display_label == "P"
    client.gl.projects.get.assert_called_once_with("group/p")


def test_get_project_by_path_error(client):
    client.gl.projects.get.side_effect = Exception("not found")
    assert client.get_project_by_path("missing") is None


def test_get_project_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.get_project(123) is None


def test_list_issues(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_issue = MagicMock()
    mock_issue.iid = 1
    mock_issue.title = "Issue 1"
    mock_issue.state = "opened"
    mock_issue.web_url = "https://url/1"
    mock_issue.description = "desc"

    mock_project.issues.list.return_value = [mock_issue]

    issues = client.list_issues(123)
    assert len(issues) == 1
    assert issues[0]["title"] == "Issue 1"
    mock_project.issues.list.assert_called_once_with(state="opened", per_page=20, get_all=False)


def test_list_issues_uses_custom_limit_and_state(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project
    mock_project.issues.list.return_value = []

    client.list_issues(123, limit=5, state="closed")

    mock_project.issues.list.assert_called_once_with(state="closed", per_page=5, get_all=False)


def test_list_issues_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.list_issues(123) == []


def test_get_issue(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_issue = MagicMock()
    mock_issue.iid = 1
    mock_issue.title = "Issue 1"
    mock_issue.state = "opened"
    mock_issue.web_url = "https://url/1"
    mock_issue.description = "desc"

    mock_project.issues.get.return_value = mock_issue

    issue = client.get_issue(123, 1)
    assert issue is not None
    assert issue["iid"] == 1
    mock_project.issues.get.assert_called_once_with(1)


def test_get_issue_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.get_issue(123, 1) is None


def test_list_mrs(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_mr = MagicMock()
    mock_mr.iid = 1
    mock_mr.title = "MR 1"
    mock_mr.state = "opened"
    mock_mr.web_url = "https://url/mr1"
    mock_mr.description = "desc"
    mock_mr.source_branch = "src"
    mock_mr.target_branch = "tgt"

    mock_project.mergerequests.list.return_value = [mock_mr]

    mrs = client.list_mrs(123)
    assert len(mrs) == 1
    assert mrs[0]["source_branch"] == "src"


def test_list_mrs_uses_custom_limit_and_state(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project
    mock_project.mergerequests.list.return_value = []

    client.list_mrs(123, limit=4, state="merged")

    mock_project.mergerequests.list.assert_called_once_with(state="merged", per_page=4, get_all=False)


def test_list_mrs_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.list_mrs(123) == []


def test_get_mr(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_mr = MagicMock()
    mock_mr.iid = 1
    mock_mr.title = "MR 1"
    mock_mr.state = "opened"
    mock_mr.web_url = "https://url/mr1"
    mock_mr.description = "desc"
    mock_mr.source_branch = "src"
    mock_mr.target_branch = "tgt"

    mock_project.mergerequests.get.return_value = mock_mr

    mr = client.get_mr(123, 1)
    assert mr is not None
    assert mr["iid"] == 1


def test_get_mr_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.get_mr(123, 1) is None


def test_get_file_content(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_file = MagicMock()
    mock_file.content = base64.b64encode(b"hello world").decode("utf-8")
    mock_project.files.get.return_value = mock_file

    content = client.get_file_content(123, "README.md")
    assert content == "hello world"
    mock_project.files.get.assert_called_once_with(file_path="README.md", ref="HEAD")


def test_get_file_content_decodes_invalid_bytes_with_replacement(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_file = MagicMock()
    mock_file.content = base64.b64encode(b"hello\xffworld").decode("utf-8")
    mock_project.files.get.return_value = mock_file

    content = client.get_file_content(123, "README.md")

    assert content == "hello\ufffdworld"


def test_get_file_content_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.get_file_content(123, "README.md") is None


def test_list_pipelines(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_pipeline = MagicMock()
    mock_pipeline.id = 99
    mock_pipeline.status = "success"
    mock_pipeline.ref = "main"
    mock_pipeline.web_url = "https://gitlab.com/group/project/-/pipelines/99"
    mock_pipeline.created_at = "2026-04-10T12:00:00Z"
    mock_project.pipelines.list.return_value = [mock_pipeline]

    pipelines = client.list_pipelines(123, limit=3)

    assert pipelines == [
        {
            "id": 99,
            "status": "success",
            "ref": "main",
            "url": "https://gitlab.com/group/project/-/pipelines/99",
            "created_at": "2026-04-10T12:00:00Z",
        }
    ]
    mock_project.pipelines.list.assert_called_once_with(per_page=3, get_all=False)


def test_list_pipelines_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.list_pipelines(123) == []


def test_list_tree(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    mock_item = {"name": "file.txt", "path": "file.txt", "type": "blob"}
    mock_project.repository_tree.return_value = [mock_item]

    items = client.list_tree(123)
    assert len(items) == 1
    assert items[0]["name"] == "file.txt"
    mock_project.repository_tree.assert_called_once_with(path="", ref="HEAD", per_page=50, get_all=False)


def test_list_tree_uses_custom_path_ref_and_limit(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project
    mock_project.repository_tree.return_value = []

    client.list_tree(123, path="docs", ref="main", limit=7)

    mock_project.repository_tree.assert_called_once_with(path="docs", ref="main", per_page=7, get_all=False)


def test_list_tree_error(client):
    client.gl.projects.get.side_effect = Exception("boom")

    assert client.list_tree(123) == []


def test_get_project(client):
    mock_project = MagicMock()
    client.gl.projects.get.return_value = mock_project

    result = client.get_project(123)
    assert result == mock_project


def test_build_meta_client():
    from tuochat.config import TuochatConfig

    cfg = TuochatConfig()
    cfg.gitlab.host = "https://custom.gitlab.com"
    cfg.gitlab.token = "secret"
    cfg.gitlab.token_type = "oauth"

    with patch("tuochat.gitlab_client.GitLabMetaClient") as mock_cls:
        from tuochat.gitlab_client import build_meta_client

        build_meta_client(cfg)
        mock_cls.assert_called_once_with(
            host="https://custom.gitlab.com",
            token="secret",
            token_type="oauth",
            user_agent=cfg.gitlab.user_agent,
        )
