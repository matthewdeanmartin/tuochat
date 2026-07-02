"""Jira integration client for tuochat.

Wraps the optional `jira` package with helpers for project listing,
issue search, and single-issue fetch.  All methods return normalized
tuochat descriptors rather than raw jira library objects.

Authentication:
  Cloud:       basic_auth=(email, token)
  Self-hosted: token_auth=token
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    pass

logger = logging.getLogger("tuochat.jira_client")

JIRA_INSTALL_HINT = (
    "The Jira integration requires the 'jira' package.\n"
    "Install it with:  uv sync --extra jira\n"
    "or:               pip install 'tuochat[jira]'"
)

# Maximum issues fetched per project list view
DEFAULT_ISSUE_LIMIT = 50
# Maximum projects fetched per listing call
DEFAULT_PROJECT_LIMIT = 100


def normalize_jira_host(host: str) -> str:
    """Return a scheme-qualified base URL without a trailing slash."""
    value = host.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    normalized = urlunparse((parsed.scheme or "https", parsed.netloc, "", "", "", ""))
    return normalized.rstrip("/")


def infer_deployment(host: str) -> str:
    """Infer 'cloud' or 'server' from the host URL heuristically."""
    host_lower = host.lower()
    if host_lower.endswith(".atlassian.net") or "atlassian.net" in host_lower:
        return "cloud"
    return "server"


def get_jira_module():
    """Import and return the top-level jira module, or raise ImportError with a hint."""
    try:
        import jira as jira_module  # type: ignore[import-not-found]  # noqa: PLC0415

        return jira_module
    except ImportError as exc:
        raise ImportError(JIRA_INSTALL_HINT) from exc


def build_jira_client(host: str, deployment: str, email: str, token: str, ssl_ca_cert: str = ""):
    """Construct an authenticated jira.JIRA instance.

    Raises ImportError if jira is not installed.
    Raises jira.JIRAError on auth failure.

    ssl_ca_cert: path to a CA bundle file, "false" to disable SSL verification
    (insecure), or "" to use the default CA bundle.  Use a custom CA path when
    your Jira server uses a private/corporate certificate authority that Python's
    bundled certifi store does not include.
    """
    jira_module = get_jira_module()

    if ssl_ca_cert.lower() == "false":
        verify: bool | str = False
        logger.warning("Jira SSL verification is disabled — connections are not authenticated")
    elif ssl_ca_cert:
        verify = ssl_ca_cert
    else:
        verify = True

    options = {"server": host, "verify": verify}

    if deployment == "cloud":
        client = jira_module.JIRA(
            options=options,
            basic_auth=(email, token),
        )
    else:
        client = jira_module.JIRA(
            options=options,
            token_auth=token,
        )

    return client


class JiraMetaClient:
    """Read-only Jira metadata client.

    Provides project listing, issue search, and issue fetch in terms of
    normalized tuochat descriptors.  Session-level caches reduce round
    trips without adding persistent machinery.
    """

    def __init__(self, host: str, deployment: str, email: str, token: str, ssl_ca_cert: str = "") -> None:
        self.host = normalize_jira_host(host)
        self.deployment = deployment
        self.email = email
        self.token = token
        self.client = build_jira_client(self.host, deployment, email, token, ssl_ca_cert)
        self.cached_projects: list[Any] | None = None
        self.cached_issues: dict[str, list[Any]] = {}

    def validate_auth(self) -> str:
        """Return the authenticated user's display name, or raise on failure."""
        me = self.client.myself()
        return me.get("displayName") or me.get("name") or "(unknown)"

    def list_projects(self, limit: int = DEFAULT_PROJECT_LIMIT) -> list[Any]:
        """Return normalized JiraProjectDescriptor list for all visible projects."""
        from tuochat.jira_models import JiraProjectDescriptor  # noqa: PLC0415

        if self.cached_projects is not None:
            return self.cached_projects

        raw: list[dict] = []

        if self.deployment == "cloud":
            raw = self.list_projects_cloud(limit)
        else:
            raw = self.list_projects_server(limit)

        descriptors = [
            JiraProjectDescriptor(
                key=p.get("key", ""),
                name=p.get("name", ""),
                project_type=p.get("projectTypeKey", ""),
                project_id=str(p.get("id", "")),
            )
            for p in raw
        ]
        descriptors.sort(key=lambda p: p.key)
        self.cached_projects = descriptors
        return descriptors

    def list_projects_cloud(self, limit: int) -> list[dict]:
        """Use paginated REST v3 endpoint for Jira Cloud."""
        results: list[dict] = []
        start_at = 0
        page_size = min(50, limit)

        while len(results) < limit:
            resp = self.client._session.get(  # noqa: SLF001
                f"{self.host}/rest/api/3/project/search",
                params={
                    "startAt": start_at,
                    "maxResults": page_size,
                    "orderBy": "key",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            page = data.get("values", [])
            results.extend(page)

            if data.get("isLast", True) or not page:
                break
            start_at += len(page)

        return results[:limit]

    def list_projects_server(self, limit: int) -> list[dict]:
        """Use jira.projects() for self-hosted Jira."""
        projects = self.client.projects()
        raw = []
        for p in projects[:limit]:
            raw.append(
                {
                    "key": getattr(p, "key", ""),
                    "name": getattr(p, "name", ""),
                    "projectTypeKey": getattr(p, "projectTypeKey", ""),
                    "id": getattr(p, "id", ""),
                }
            )
        return raw

    def list_issues(self, project_key: str, limit: int = DEFAULT_ISSUE_LIMIT) -> list[Any]:
        """Return a list of JiraIssueDescriptor for the given project."""
        from tuochat.jira_models import JiraIssueDescriptor  # noqa: PLC0415

        if project_key in self.cached_issues:
            return self.cached_issues[project_key]

        jql = f"project = {project_key} ORDER BY updated DESC"
        fields = "summary,status,issuetype,updated,assignee"

        issues = self.client.search_issues(jql, fields=fields, maxResults=limit)

        descriptors = [
            JiraIssueDescriptor(
                key=issue.key,
                summary=getattr(issue.fields, "summary", "") or "",
                status=field_name(issue.fields, "status"),
                issue_type=field_name(issue.fields, "issuetype"),
                updated=field_str(issue.fields, "updated"),
                assignee=display_name(issue.fields, "assignee"),
            )
            for issue in issues
        ]
        self.cached_issues[project_key] = descriptors
        return descriptors

    def get_issue(self, issue_key: str) -> Any:
        """Fetch a single issue and return a JiraIssueDetail."""
        from tuochat.jira_models import JiraIssueDetail  # noqa: PLC0415

        fields_param = (
            "summary,status,issuetype,priority,assignee,reporter,"
            "created,updated,labels,fixVersions,components,description"
        )
        issue = self.client.issue(issue_key, fields=fields_param)
        f = issue.fields

        description_raw = getattr(f, "description", "") or ""
        description = flatten_description(description_raw)

        return JiraIssueDetail(
            key=issue.key,
            summary=getattr(f, "summary", "") or "",
            url=f"{self.host}/browse/{issue.key}",
            project_key=issue.key.rsplit("-", 1)[0] if "-" in issue.key else "",
            status=field_name(f, "status"),
            issue_type=field_name(f, "issuetype"),
            priority=field_name(f, "priority"),
            assignee=display_name(f, "assignee"),
            reporter=display_name(f, "reporter"),
            created=field_str(f, "created"),
            updated=field_str(f, "updated"),
            labels=list(getattr(f, "labels", []) or []),
            fix_versions=[getattr(v, "name", str(v)) for v in (getattr(f, "fixVersions", []) or [])],
            components=[getattr(c, "name", str(c)) for c in (getattr(f, "components", []) or [])],
            description=description,
        )


# Helpers for safely extracting fields from jira resource objects


def field_name(fields: Any, attr: str) -> str:
    obj = getattr(fields, attr, None)
    if obj is None:
        return ""
    return getattr(obj, "name", "") or str(obj)


def display_name(fields: Any, attr: str) -> str:
    obj = getattr(fields, attr, None)
    if obj is None:
        return ""
    return getattr(obj, "displayName", "") or getattr(obj, "name", "") or str(obj)


def field_str(fields: Any, attr: str) -> str:
    val = getattr(fields, attr, None)
    if val is None:
        return ""
    return str(val)


def flatten_description(description: Any) -> str:
    """Convert Jira Cloud ADF description dicts or plain strings to text."""
    if not description:
        return ""
    if isinstance(description, str):
        return description

    # Atlassian Document Format (ADF) — recursively extract text
    if isinstance(description, dict):
        return extract_adf_text(description)

    return str(description)


def extract_adf_text(node: dict) -> str:
    """Recursively extract plain text from an ADF node tree."""
    node_type = node.get("type", "")

    if node_type == "text":
        return node.get("text", "")

    children = node.get("content", []) or []
    parts = [extract_adf_text(child) for child in children]

    # Add newlines after block-level nodes
    block_types = {"paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote", "codeBlock", "rule"}
    joined = "".join(parts)
    if node_type in block_types:
        return joined + "\n"
    return joined
