from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import pytest

from tuochat.config import GitLabConfig, TuochatConfig
from tuochat.git_info import GitStatus
from tuochat.gui import git_tab, gitlab_tab, observability_tab
from tuochat.observability import DailyMetricSummary, DailyRollup


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


def make_cfg() -> TuochatConfig:
    return TuochatConfig(gitlab=GitLabConfig(host="https://gitlab.example.com", token="tok"))


def test_git_tab_helper_functions(monkeypatch, tmp_path):
    monkeypatch.setattr(git_tab, "run_git", lambda *args, cwd=None: (0, 'M  tracked.py\n?? "new file.py"\n'))

    lines = git_tab.get_porcelain_lines(tmp_path)

    assert lines == [("M ", "tracked.py"), ("??", "new file.py")]
    assert git_tab.describe_xy("M ") == "modified"
    assert git_tab.describe_xy(" M") == "modified (unstaged)"
    assert git_tab.describe_xy("??") == "untracked"
    assert git_tab.tag_for_xy("M ") == "staged"
    assert git_tab.tag_for_xy("??") == "untracked"


def test_git_tab_recent_commits_returns_split_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(git_tab, "run_git", lambda *args, cwd=None: (0, "abc first\ndef second"))

    commits = git_tab.get_recent_commits(tmp_path, n=2)

    assert commits == ["abc first", "def second"]


def test_git_status_tab_updates_dirty_repo_and_attaches_diff(monkeypatch, tk_root, tmp_path):
    attached: list[tuple[str, str]] = []
    status = GitStatus(root=tmp_path, branch="main", staged=1, unstaged=2, untracked=1, ahead=3, behind=1)
    diff_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(git_tab, "get_git_status", lambda cwd: status)
    monkeypatch.setattr(git_tab, "get_porcelain_lines", lambda root: [("M ", "tracked.py"), ("??", "new.py")])
    monkeypatch.setattr(git_tab, "get_recent_commits", lambda root, n=10: ["abc first commit"])

    def fake_run_git(*args: str, cwd=None):
        diff_calls.append(args)
        if args == ("diff", "HEAD"):
            return 0, "diff --git a/tracked.py b/tracked.py"
        return 0, ""

    monkeypatch.setattr(git_tab, "run_git", fake_run_git)

    tab = git_tab.GitStatusTab(tk_root, on_attach_context=lambda label, payload: attached.append((label, payload)))

    assert "DIRTY" in tab.dirty_banner.cget("text")
    assert "+3 ahead of upstream" in tab.sync_label.cget("text")
    assert len(tab.file_tree.get_children()) == 2
    assert tab.attach_diff_btn.cget("state") == "normal"
    assert "abc first commit" in tab.commits_text.get("1.0", "end")

    tab.attach_diff_to_context()

    assert diff_calls[0] == ("diff", "HEAD")
    assert attached == [("Git diff (main)", "```\ndiff --git a/tracked.py b/tracked.py\n```")]


def test_git_status_tab_handles_non_repo(monkeypatch, tk_root):
    monkeypatch.setattr(git_tab, "get_git_status", lambda cwd: None)

    tab = git_tab.GitStatusTab(tk_root)

    assert tab.status_label.cget("text") == "Not a git repository"
    assert tab.attach_diff_btn.cget("state") == "disabled"
    assert "(no git repo)" in tab.commits_text.get("1.0", "end")


def test_gitlab_tab_load_project_enables_actions(monkeypatch, tk_root):
    refreshed: list[bool] = []
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gitlab_tab.messagebox, "showwarning", lambda title, message, parent=None: warnings.append((title, message))
    )

    tab = gitlab_tab.GitLabTab(tk_root, make_cfg())
    monkeypatch.setattr(tab, "refresh_data", lambda: refreshed.append(True))

    tab.load_project()
    assert warnings == [("GitLab", "Enter a project path first.")]

    tab.project_var.set("group/repo")
    tab.load_project()

    assert tab.project_id == "group/repo"
    assert tab.project_path == "group/repo"
    assert tab.refresh_btn.cget("state") == "normal"
    assert tab.set_resource_btn.cget("state") == "normal"
    assert refreshed == [True]


def test_gitlab_tab_populates_lists_and_attaches_selected_context(tk_root):
    attached: list[tuple[str, str]] = []
    tab = gitlab_tab.GitLabTab(
        tk_root, make_cfg(), on_attach_context=lambda label, payload: attached.append((label, payload))
    )
    tab.mrs = [
        {
            "iid": 7,
            "title": "Fix login",
            "source_branch": "feature/login",
            "target_branch": "main",
            "state": "opened",
            "url": "https://example/mr/7",
            "description": "Adds a fix",
        },
    ]
    tab.issues = [
        {
            "iid": 42,
            "title": "Login bug",
            "state": "opened",
            "url": "https://example/issue/42",
            "description": "Repro steps",
        },
    ]
    tab.pipelines = [{"id": 1001, "ref": "main", "status": "success"}]

    tab.populate_ui()
    tab.mr_tree.selection_set("7")
    tab.on_mr_select()
    tab.attach_mr_to_context()
    tab.issue_tree.selection_set("42")
    tab.on_issue_select()
    tab.attach_issue_to_context()

    assert tab.attach_mr_btn.cget("state") == "normal"
    assert tab.attach_issue_btn.cget("state") == "normal"
    assert len(tab.pipeline_tree.get_children()) == 1
    assert attached[0][0] == "MR !7: Fix login"
    assert "**Branch:** feature/login → main" in attached[0][1]
    assert attached[1][0] == "Issue #42: Login bug"
    assert "### Description" in attached[1][1]


def test_gitlab_tab_sets_and_clears_resource(tk_root):
    resources: list[str | None] = []
    cfg = make_cfg()
    cfg.chat.default_resource_id = "gid://gitlab/Project/5"
    tab = gitlab_tab.GitLabTab(tk_root, cfg, on_set_resource=resources.append)
    tab.project_id = "123"
    tab._resolve_resource_id = lambda: "gid://gitlab/Project/123"

    tab.set_project_as_resource()
    tab.clear_resource()

    assert resources == ["gid://gitlab/Project/123", None]
    assert tab.resource_label.cget("text") == "gid://gitlab/Project/5"


def test_gitlab_tab_fetch_data_populates_and_handles_errors(monkeypatch, tk_root):
    cfg = make_cfg()
    tab = gitlab_tab.GitLabTab(tk_root, cfg)
    tab.project_id = "group/repo"
    monkeypatch.setattr(tab.parent, "after", lambda delay, callback: callback())

    class FakeClient:
        def __init__(
            self, host: str, token: str, token_type: str, user_agent: str | None = None
        ) -> None:  # noqa: ARG002
            pass

        def list_mrs(self, project_id):
            return [{"iid": 1, "title": "MR", "source_branch": "feature"}]

        def list_issues(self, project_id):
            return [{"iid": 2, "title": "Issue"}]

        def list_pipelines(self, project_id):
            return [{"id": 99, "ref": "main", "status": "failed"}]

    monkeypatch.setattr("tuochat.gitlab_client.GitLabMetaClient", FakeClient)
    tab.fetch_data()

    assert "Loaded: 1 open MRs, 1 open issues, 1 recent pipelines" in tab.status_var.get()

    class BrokenClient:
        def __init__(
            self, host: str, token: str, token_type: str, user_agent: str | None = None
        ) -> None:  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr("tuochat.gitlab_client.GitLabMetaClient", BrokenClient)
    tab.fetch_data()
    assert tab.status_var.get() == "Error: boom"


def test_pipeline_tag_and_format_value_helpers():
    assert gitlab_tab.pipeline_tag("success") == "pipeline_success"
    assert gitlab_tab.pipeline_tag("weird") == "pipeline_other"
    assert observability_tab.format_value(12_500) == "12.5k"
    assert observability_tab.format_value(1_234) == "1234"
    assert observability_tab.format_value(12.34) == "12.3"
    assert observability_tab.format_value(0.5) == "0.50"


def test_observability_extract_series_and_draw_line_chart(tk_root):
    rollups = [
        DailyRollup(
            day="2026-04-08",
            total_response_ms=DailyMetricSummary(count=2, average=15.0, median=10.0, p95=20.0, max=25.0),
        )
    ]
    days, medians, p95s, maxes = observability_tab.extract_series(rollups, "total_response_ms")
    canvas = tk.Canvas(tk_root, width=400, height=120)

    observability_tab.draw_line_chart(canvas, days, medians, p95s, maxes)

    assert days == ["2026-04-08"]
    assert medians == [10.0]
    assert p95s == [20.0]
    assert maxes == [25.0]
    assert canvas.find_all()


def test_observability_view_refresh_updates_summary_and_charts(tk_root):
    class FakeStore:
        def get_observability_rollups(self, since_iso: str):
            assert "T" in since_iso
            return [
                DailyRollup(
                    day="2026-04-08",
                    request_tokens=DailyMetricSummary(count=1, average=100.0, median=100.0, p95=100.0, max=100.0),
                    response_tokens=DailyMetricSummary(count=1, average=200.0, median=200.0, p95=200.0, max=200.0),
                    time_to_first_token_ms=DailyMetricSummary(count=1, average=50.0, median=50.0, p95=50.0, max=50.0),
                    time_per_token_ms=DailyMetricSummary(count=1, average=2.0, median=2.0, p95=2.0, max=2.0),
                    total_response_ms=DailyMetricSummary(count=1, average=300.0, median=300.0, p95=300.0, max=300.0),
                    completed=3,
                    failed=1,
                    cancelled=2,
                )
            ]

    view = observability_tab.build_observability_tab(tk_root, FakeStore())

    summary = view.summary_var.get()
    assert "Completed:  3" in summary
    assert "Failed:     1" in summary
    assert "Cancelled:  2" in summary
    assert all(canvas.find_all() for canvas in view.canvases.values())
