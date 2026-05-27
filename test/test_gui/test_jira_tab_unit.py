"""Focused Tkinter tests for the Jira tab."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter", exc_type=ImportError)

from tuochat.config import TuochatConfig  # noqa F841
from tuochat.gui import jira_tab  # noqa F841
from tuochat.jira_models import JiraIssueDescriptor, JiraIssueDetail, JiraProjectDescriptor


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


def test_jira_tab_connect_warns_when_jira_is_not_configured(monkeypatch, tk_root):
    warnings: list[tuple[str, str]] = []
    cfg = TuochatConfig()
    monkeypatch.setattr(
        jira_tab.messagebox,
        "showwarning",
        lambda title, message, parent=None: warnings.append((title, message)),
    )

    tab = jira_tab.JiraTab(tk_root, cfg)
    tab.connect()

    assert warnings == [
        (
            "Jira",
            "Jira is not configured.\n\nAdd [jira] host / token to your config.toml\nor set TUOCHAT_JIRA_HOST and TUOCHAT_JIRA_TOKEN.",
        )
    ]


def test_jira_tab_filters_projects_and_issues_and_attaches_context(monkeypatch, tk_root):
    attached: list[tuple[str, str]] = []
    cfg = TuochatConfig()
    cfg.jira.host = "https://company.atlassian.net"
    cfg.jira.deployment = "cloud"
    detail = JiraIssueDetail(
        key="APP-2",
        summary="Write onboarding docs",
        url="https://company.atlassian.net/browse/APP-2",
        project_key="APP",
        status="Done",
        issue_type="Task",
        assignee="Ada Lovelace",
        description="Capture the release steps in one place.",
    )

    class FakeClient:
        def list_projects(self):
            return [
                JiraProjectDescriptor(key="APP", name="Application"),
                JiraProjectDescriptor(key="OPS", name="Operations"),
            ]

        def list_issues(self, project_key: str):
            assert project_key == "APP"
            return [
                JiraIssueDescriptor(key="APP-1", summary="Fix login", status="Open", issue_type="Bug"),
                JiraIssueDescriptor(key="APP-2", summary="Write onboarding docs", status="Done", issue_type="Task"),
            ]

        def get_issue(self, issue_key: str):
            assert issue_key == "APP-2"
            return detail

    tab = jira_tab.JiraTab(tk_root, cfg, on_attach_context=lambda label, payload: attached.append((label, payload)))
    tab.client = FakeClient()
    monkeypatch.setattr(tab.parent, "after", lambda delay, callback: callback())

    tab.do_fetch_projects()
    assert "Host: https://company.atlassian.net  Deployment: cloud" == tab.config_label.cget("text")
    assert list(tab.project_tree.get_children()) == ["APP", "OPS"]

    tab.project_filter_var.set("app")
    assert list(tab.project_tree.get_children()) == ["APP"]

    tab.selected_project_key = "APP"
    tab.do_fetch_issues("APP")
    assert tab.status_var.get() == "Loaded 2 issues for APP."
    assert list(tab.issue_tree.get_children()) == ["APP-1", "APP-2"]

    tab.issue_filter_var.set("done")
    assert list(tab.issue_tree.get_children()) == ["APP-2"]

    tab.do_load_preview("APP-2")
    preview_text = tab.preview_text.get("1.0", "end")
    assert "Jira issue: APP-2" in preview_text
    assert "Assignee: Ada Lovelace" in preview_text
    assert "Description:" in preview_text

    tab.do_attach("APP-2")
    assert attached == [
        (
            "[jira] APP-2 Write onboarding docs",
            "\n".join(
                [
                    "Jira issue: APP-2",
                    "URL: https://company.atlassian.net/browse/APP-2",
                    "Project: APP",
                    "Summary: Write onboarding docs",
                    "Type: Task",
                    "Status: Done",
                    "Assignee: Ada Lovelace",
                    "",
                    "Description:",
                    "Capture the release steps in one place.",
                ]
            ),
        )
    ]
    assert tab.status_var.get() == "Queued: [jira] APP-2 Write onboarding docs"
