"""Unit tests for Jira slash-command helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuochat.cli.commands import jira_cmd
from tuochat.config import TuochatConfig
from tuochat.jira_models import JiraIssueDescriptor, JiraIssueDetail, JiraProjectDescriptor


@pytest.fixture(autouse=True)
def clear_jira_session_cache():
    jira_cmd.clear_session_cache()
    yield
    jira_cmd.clear_session_cache()


def make_state() -> SimpleNamespace:
    cfg = TuochatConfig()
    cfg.jira.host = "https://company.atlassian.net"
    cfg.jira.deployment = "cloud"
    cfg.jira.email = "dev@example.com"
    cfg.jira.token = "abcdefgh12345678"
    cfg.jira.project = "OPS"
    return SimpleNamespace(cfg=cfg, pending_attachment_messages=[], pending_attachment_names=[])


def test_get_or_build_client_reuses_cached_client_until_config_changes(monkeypatch):
    state = make_state()
    created_clients: list[object] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created_clients.append(self)

    monkeypatch.setattr("tuochat.jira_client.JiraMetaClient", FakeClient, raising=False)

    first_client = jira_cmd.get_or_build_client(state)
    second_client = jira_cmd.get_or_build_client(state)
    state.cfg.jira.token = "different-token"
    third_client = jira_cmd.get_or_build_client(state)

    assert first_client is second_client
    assert third_client is not first_client
    assert len(created_clients) == 2
    assert created_clients[0].kwargs["host"] == "https://company.atlassian.net"
    assert created_clients[1].kwargs["token"] == "different-token"


def test_handle_status_reports_config_and_masks_token(monkeypatch, capsys):
    state = make_state()
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object() if name == "jira" else None)

    jira_cmd.handle_status(state)

    captured = capsys.readouterr()
    assert "Jira extra installed:  yes" in captured.out
    assert "Jira host:             https://company.atlassian.net" in captured.out
    assert "Jira deployment:       cloud" in captured.out
    assert "Jira email:            dev@example.com" in captured.out
    assert "Jira token:            abcdefgh***" in captured.out
    assert "Last project:          OPS" in captured.out


def test_pick_project_accepts_default_and_numeric_selection(monkeypatch):
    state = make_state()
    client = SimpleNamespace(
        list_projects=lambda: [
            JiraProjectDescriptor(key="OPS", name="Operations"),
            JiraProjectDescriptor(key="APP", name="Application"),
        ]
    )

    monkeypatch.setattr("tuochat.cli.prompts.prompt_input", lambda prompt: "", raising=False)
    assert jira_cmd.pick_project(client, state) == "OPS"

    monkeypatch.setattr("tuochat.cli.prompts.prompt_input", lambda prompt: "2", raising=False)
    assert jira_cmd.pick_project(client, state) == "APP"


def test_pick_issues_accepts_numbers_and_keys_and_skips_unknown_entries(monkeypatch, capsys):
    client = SimpleNamespace(
        list_issues=lambda project_key: [
            JiraIssueDescriptor(key="APP-1", summary="Fix login", status="Open"),
            JiraIssueDescriptor(key="APP-2", summary="Write docs", status="Done"),
        ]
    )

    monkeypatch.setattr("tuochat.cli.prompts.prompt_input", lambda prompt: "2 app-1 99 nope 2", raising=False)

    selected = jira_cmd.pick_issues(client, "APP", SimpleNamespace())

    captured = capsys.readouterr()
    assert selected == ["APP-2", "APP-1"]
    assert "Skipping unknown selection: 99" in captured.out
    assert "Skipping unknown issue key: nope" in captured.out


def test_attach_issue_formats_and_queues_attachment(capsys):
    state = make_state()
    detail = JiraIssueDetail(
        key="APP-7",
        summary="Investigate websocket timeout",
        url="https://company.atlassian.net/browse/APP-7",
        project_key="APP",
        status="In Progress",
        issue_type="Bug",
        description="The timeout happens after 20 seconds.",
    )
    client = SimpleNamespace(get_issue=lambda issue_key: detail)

    jira_cmd.attach_issue(client, "APP-7", state)

    captured = capsys.readouterr()
    assert state.pending_attachment_names == ["[jira] APP-7 Investigate websocket timeout"]
    assert state.pending_attachment_messages == [
        "\n".join(
            [
                "Jira issue: APP-7",
                "URL: https://company.atlassian.net/browse/APP-7",
                "Project: APP",
                "Summary: Investigate websocket timeout",
                "Type: Bug",
                "Status: In Progress",
                "",
                "Description:",
                "The timeout happens after 20 seconds.",
            ]
        )
    ]
    assert "Queued: [jira] APP-7 Investigate websocket timeout" in captured.out
