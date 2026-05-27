"""Unit tests for Jira client helpers and normalized metadata reads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuochat import jira_client


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.raise_for_status_calls = 0

    def raise_for_status(self) -> None:
        self.raise_for_status_calls += 1

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict) -> FakeResponse:
        self.calls.append((url, params))
        return self.responses.pop(0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("jira.example.com", "https://jira.example.com"),
        (" https://jira.example.com/ ", "https://jira.example.com"),
        ("http://jira.example.com/projects/team", "http://jira.example.com"),
        ("", ""),
    ],
)
def test_normalize_jira_host_strips_paths_and_trailing_slash(raw, expected):
    assert jira_client.normalize_jira_host(raw) == expected


def test_build_jira_client_uses_basic_auth_for_cloud(monkeypatch):
    class FakeJiraModule:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def JIRA(self, **kwargs):
            self.calls.append(kwargs)
            return "cloud-client"

    fake_jira_module = FakeJiraModule()
    monkeypatch.setattr(jira_client, "get_jira_module", lambda: fake_jira_module)

    client = jira_client.build_jira_client("https://company.atlassian.net", "cloud", "dev@example.com", "secret-token")

    assert client == "cloud-client"
    assert fake_jira_module.calls == [
        {
            "options": {"server": "https://company.atlassian.net", "verify": True},
            "basic_auth": ("dev@example.com", "secret-token"),
        }
    ]


def test_build_jira_client_uses_token_auth_for_server(monkeypatch):
    class FakeJiraModule:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def JIRA(self, **kwargs):
            self.calls.append(kwargs)
            return "server-client"

    fake_jira_module = FakeJiraModule()
    monkeypatch.setattr(jira_client, "get_jira_module", lambda: fake_jira_module)

    client = jira_client.build_jira_client("https://jira.example.com", "server", "", "secret-token")

    assert client == "server-client"
    assert fake_jira_module.calls == [
        {
            "options": {"server": "https://jira.example.com", "verify": True},
            "token_auth": "secret-token",
        }
    ]


def test_list_projects_cloud_uses_paginated_api_and_caches_results(monkeypatch):
    fake_session = FakeSession(
        [
            FakeResponse(
                {
                    "values": [
                        {"key": "ZZZ", "name": "Zulu", "projectTypeKey": "software", "id": 3},
                        {"key": "AAA", "name": "Alpha", "projectTypeKey": "service_desk", "id": 1},
                    ],
                    "isLast": False,
                }
            ),
            FakeResponse(
                {
                    "values": [
                        {"key": "BBB", "name": "Beta", "projectTypeKey": "business", "id": 2},
                    ],
                    "isLast": True,
                }
            ),
        ]
    )
    fake_client = SimpleNamespace(_session=fake_session)
    monkeypatch.setattr(jira_client, "build_jira_client", lambda *args: fake_client)

    client = jira_client.JiraMetaClient("company.atlassian.net/browse/APP", "cloud", "dev@example.com", "token")

    projects = client.list_projects(limit=5)
    cached_projects = client.list_projects(limit=5)

    assert [project.key for project in projects] == ["AAA", "BBB", "ZZZ"]
    assert projects[0].name == "Alpha"
    assert projects[0].project_type == "service_desk"
    assert projects[0].project_id == "1"
    assert cached_projects is projects
    assert fake_session.calls == [
        (
            "https://company.atlassian.net/rest/api/3/project/search",
            {"startAt": 0, "maxResults": 5, "orderBy": "key"},
        ),
        (
            "https://company.atlassian.net/rest/api/3/project/search",
            {"startAt": 2, "maxResults": 5, "orderBy": "key"},
        ),
    ]


def test_list_issues_builds_descriptors_and_uses_cache(monkeypatch):
    fields_one = SimpleNamespace(
        summary="Fix login redirect",
        status=SimpleNamespace(name="In Progress"),
        issuetype=SimpleNamespace(name="Bug"),
        updated="2026-04-11T16:00:00Z",
        assignee=SimpleNamespace(displayName="Ada Lovelace"),
    )
    fields_two = SimpleNamespace(
        summary="Document rollout",
        status=SimpleNamespace(name="Done"),
        issuetype=SimpleNamespace(name="Task"),
        updated="2026-04-10T14:30:00Z",
        assignee=None,
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def search_issues(self, jql: str, *, fields: str, maxResults: int):
            self.calls.append((jql, fields, maxResults))
            return [
                SimpleNamespace(key="APP-2", fields=fields_one),
                SimpleNamespace(key="APP-1", fields=fields_two),
            ]

    fake_client = FakeClient()
    monkeypatch.setattr(jira_client, "build_jira_client", lambda *args: fake_client)

    client = jira_client.JiraMetaClient("https://jira.example.com", "server", "", "token")

    issues = client.list_issues("APP", limit=2)
    cached_issues = client.list_issues("APP", limit=2)

    assert [issue.key for issue in issues] == ["APP-2", "APP-1"]
    assert issues[0].summary == "Fix login redirect"
    assert issues[0].status == "In Progress"
    assert issues[0].issue_type == "Bug"
    assert issues[0].updated == "2026-04-11T16:00:00Z"
    assert issues[0].assignee == "Ada Lovelace"
    assert issues[1].assignee == ""
    assert cached_issues is issues
    assert fake_client.calls == [
        (
            "project = APP ORDER BY updated DESC",
            "summary,status,issuetype,updated,assignee",
            2,
        )
    ]


def test_get_issue_flattens_adf_description_and_extracts_names(monkeypatch):
    adf_description = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "First line"},
                    {"type": "text", "text": " and more"},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Second line"}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    issue_fields = SimpleNamespace(
        summary="Investigate auth timeout",
        status=SimpleNamespace(name="To Do"),
        issuetype=SimpleNamespace(name="Story"),
        priority=SimpleNamespace(name="High"),
        assignee=SimpleNamespace(displayName="Grace Hopper"),
        reporter=SimpleNamespace(name="reporter-account"),
        created="2026-04-09T09:00:00Z",
        updated="2026-04-11T11:45:00Z",
        labels=["customer", "auth"],
        fixVersions=[SimpleNamespace(name="2026.04")],
        components=[SimpleNamespace(name="backend"), SimpleNamespace(name="login")],
        description=adf_description,
    )
    fake_issue = SimpleNamespace(key="AUTH-7", fields=issue_fields)
    fake_client = SimpleNamespace(issue=lambda issue_key, *, fields: fake_issue)
    monkeypatch.setattr(jira_client, "build_jira_client", lambda *args: fake_client)

    client = jira_client.JiraMetaClient("jira.example.com", "server", "", "token")
    detail = client.get_issue("AUTH-7")

    assert detail.key == "AUTH-7"
    assert detail.url == "https://jira.example.com/browse/AUTH-7"
    assert detail.project_key == "AUTH"
    assert detail.status == "To Do"
    assert detail.issue_type == "Story"
    assert detail.priority == "High"
    assert detail.assignee == "Grace Hopper"
    assert detail.reporter == "reporter-account"
    assert detail.labels == ["customer", "auth"]
    assert detail.fix_versions == ["2026.04"]
    assert detail.components == ["backend", "login"]
    assert detail.description.startswith("First line and more\nSecond line")
    assert detail.description.endswith("\n\n")
