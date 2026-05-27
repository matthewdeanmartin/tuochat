"""GitLab metadata client — separate from the Duo chat transport.

Wraps python-gitlab for resource discovery (projects, groups).
Never touches the Duo API; that lives in provider/duo.py.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import TYPE_CHECKING

from tuochat.config import default_gitlab_user_agent
from tuochat.resources import ResourceDescriptor, resource_descriptor_from_group, resource_descriptor_from_project

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

logger = logging.getLogger("tuochat.gitlab_client")

GITLAB_INSTALL_HINT = "GitLab support is not installed. Install tuochat[gitlab] or tuochat[all]."


def get_gitlab_module() -> ModuleType:
    """Import gitlab, raising ImportError with a helpful message if missing."""
    try:
        return importlib.import_module("gitlab")
    except ImportError as e:
        raise ImportError(GITLAB_INSTALL_HINT) from e


class GitLabMetaClient:
    """Thin wrapper around python-gitlab for resource discovery."""

    def __init__(self, host: str, token: str, token_type: str = "pat", user_agent: str | None = None) -> None:
        gitlab = get_gitlab_module()
        effective_user_agent = default_gitlab_user_agent() if user_agent is None else user_agent
        # python-gitlab expects a plain URL (no path)
        kwargs = {
            "url": host,
            "private_token": token if token_type == "pat" else None,
            "oauth_token": token if token_type == "oauth" else None,
        }
        if effective_user_agent:
            kwargs["user_agent"] = effective_user_agent
        self.gl = gitlab.Gitlab(**kwargs)

    def list_projects(self, *, limit: int = 30, membership: bool = True) -> list[ResourceDescriptor]:
        """Return up to *limit* projects the current user is a member of."""
        try:
            projects = self.gl.projects.list(membership=membership, per_page=limit, get_all=False)
            return [resource_descriptor_from_project(p) for p in projects]
        except Exception as exc:
            logger.warning("Failed to list projects: %s", exc)
            return []

    def list_groups(self, *, limit: int = 30) -> list[ResourceDescriptor]:
        """Return up to *limit* groups the current user belongs to."""
        try:
            groups = self.gl.groups.list(per_page=limit, get_all=False)
            return [resource_descriptor_from_group(g) for g in groups]
        except Exception as exc:
            logger.warning("Failed to list groups: %s", exc)
            return []

    def search_projects(self, query: str, *, limit: int = 20) -> list[ResourceDescriptor]:
        """Search for projects matching *query*."""
        try:
            projects = self.gl.projects.list(search=query, per_page=limit, get_all=False)
            return [resource_descriptor_from_project(p) for p in projects]
        except Exception as exc:
            logger.warning("Project search failed: %s", exc)
            return []

    def get_project_by_path(self, path: str) -> ResourceDescriptor | None:
        """Look up a single project by its namespace path (e.g. 'group/repo')."""
        try:
            project = self.gl.projects.get(path)
            return resource_descriptor_from_project(project)
        except Exception as exc:
            logger.warning("get_project_by_path(%r) failed: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Phase 3: artifact fetch helpers
    # ------------------------------------------------------------------

    def get_project(self, project_id: str | int) -> object | None:
        """Return the raw python-gitlab Project object, or None on failure."""
        try:
            return self.gl.projects.get(project_id)
        except Exception as exc:
            logger.warning("get_project(%r) failed: %s", project_id, exc)
            return None

    def list_issues(self, project_id: str | int, *, limit: int = 20, state: str = "opened") -> list[dict]:
        """Return a list of issue dicts {iid, title, state, url, description} for *project_id*."""
        try:
            project = self.gl.projects.get(project_id)
            issues = project.issues.list(state=state, per_page=limit, get_all=False)
            return [
                {
                    "iid": issue.iid,
                    "title": issue.title,
                    "state": issue.state,
                    "url": issue.web_url,
                    "description": issue.description or "",
                }
                for issue in issues
            ]
        except Exception as exc:
            logger.warning("list_issues(%r) failed: %s", project_id, exc)
            return []

    def get_issue(self, project_id: str | int, iid: int) -> dict | None:
        """Fetch a single issue by project-local IID."""
        try:
            project = self.gl.projects.get(project_id)
            issue = project.issues.get(iid)
            return {
                "iid": issue.iid,
                "title": issue.title,
                "state": issue.state,
                "url": issue.web_url,
                "description": issue.description or "",
            }
        except Exception as exc:
            logger.warning("get_issue(%r, %r) failed: %s", project_id, iid, exc)
            return None

    def list_mrs(self, project_id: str | int, *, limit: int = 20, state: str = "opened") -> list[dict]:
        """Return a list of MR dicts {iid, title, state, url, description, source_branch, target_branch}."""
        try:
            project = self.gl.projects.get(project_id)
            mrs = project.mergerequests.list(state=state, per_page=limit, get_all=False)
            return [
                {
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "url": mr.web_url,
                    "description": mr.description or "",
                    "source_branch": mr.source_branch,
                    "target_branch": mr.target_branch,
                }
                for mr in mrs
            ]
        except Exception as exc:
            logger.warning("list_mrs(%r) failed: %s", project_id, exc)
            return []

    def get_mr(self, project_id: str | int, iid: int) -> dict | None:
        """Fetch a single MR by project-local IID."""
        try:
            project = self.gl.projects.get(project_id)
            mr = project.mergerequests.get(iid)
            return {
                "iid": mr.iid,
                "title": mr.title,
                "state": mr.state,
                "url": mr.web_url,
                "description": mr.description or "",
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
            }
        except Exception as exc:
            logger.warning("get_mr(%r, %r) failed: %s", project_id, iid, exc)
            return None

    def get_file_content(self, project_id: str | int, file_path: str, ref: str = "HEAD") -> str | None:
        """Return decoded text content of a repository file, or None on failure."""
        try:
            project = self.gl.projects.get(project_id)
            f = project.files.get(file_path=file_path, ref=ref)
            import base64

            return base64.b64decode(f.content).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("get_file_content(%r, %r) failed: %s", project_id, file_path, exc)
            return None

    def list_pipelines(self, project_id: str | int, *, limit: int = 10) -> list[dict]:
        """Return recent pipeline dicts {id, status, ref, web_url, created_at} for *project_id*."""
        try:
            project = self.gl.projects.get(project_id)
            pipelines = project.pipelines.list(per_page=limit, get_all=False)
            return [
                {
                    "id": p.id,
                    "status": p.status,
                    "ref": p.ref,
                    "url": p.web_url,
                    "created_at": getattr(p, "created_at", ""),
                }
                for p in pipelines
            ]
        except Exception as exc:
            logger.warning("list_pipelines(%r) failed: %s", project_id, exc)
            return []

    def list_tree(self, project_id: str | int, path: str = "", ref: str = "HEAD", *, limit: int = 50) -> list[dict]:
        """List repository tree entries (files and directories) at *path*."""
        try:
            project = self.gl.projects.get(project_id)
            items = project.repository_tree(path=path, ref=ref, per_page=limit, get_all=False)
            return [{"name": item["name"], "path": item["path"], "type": item["type"]} for item in items]
        except Exception as exc:
            logger.warning("list_tree(%r, %r) failed: %s", project_id, path, exc)
            return []


def build_meta_client(cfg: TuochatConfig) -> GitLabMetaClient:
    """Construct a GitLabMetaClient from the active config."""
    return GitLabMetaClient(
        host=cfg.gitlab.host,
        token=cfg.gitlab.token,
        token_type=cfg.gitlab.token_type,
        user_agent=getattr(cfg.gitlab, "user_agent", None),
    )
