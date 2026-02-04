"""GitLab API client with async support."""

import asyncio
import fnmatch
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .config import Config

logger = logging.getLogger(__name__)

@dataclass
class Response:
    """HTTP response wrapper."""
    status: int
    headers: dict[str, str]
    body: bytes

    def raise_for_status(self) -> None:
        """Raise an exception if the response status indicates an error."""
        if self.status >= 400:
            raise urllib.error.HTTPError(
                url="", code=self.status, msg=f"HTTP {self.status}", hdrs={}, fp=None
            )

    def json(self) -> Any:
        """Parse response body as JSON."""
        return json.loads(self.body.decode("utf-8"))

@dataclass
class Group:
    """GitLab group."""
    id: str
    name: str

@dataclass
class Project:
    """GitLab project."""
    id: int
    name: str
    web_url: str
    archived: bool

@dataclass
class SearchResult:
    """Search result from GitLab."""
    data: str
    filename: str
    ref: str
    startline: int


@dataclass
class SearchCriteria:
    """Search criteria for GitLab search."""
    search_query: str
    filename: str | None = None
    extension: str | None = None
    path: str | None = None


@dataclass
class FileCriteriaPatterns:
    """Compiled regex patterns from SearchCriteria for matching and highlighting."""
    filename: re.Pattern[str] | None = None
    extension: re.Pattern[str] | None = None
    path: re.Pattern[str] | None = None

    @classmethod
    def from_criteria(cls, criteria: SearchCriteria) -> "FileCriteriaPatterns":
        """Create compiled patterns from SearchCriteria."""
        ext = criteria.extension
        return cls(
            filename=re.compile(fnmatch.translate(criteria.filename), re.IGNORECASE) if criteria.filename else None,
            extension=re.compile(
                re.escape(ext if ext.startswith('.') else f'.{ext}') + r'\Z',
                re.IGNORECASE
            ) if ext else None,
            path=re.compile(fnmatch.translate(criteria.path), re.IGNORECASE) if criteria.path else None,
        )

    def has_any(self) -> bool:
        """Check if any pattern is set."""
        return self.filename is not None or self.extension is not None or self.path is not None

    def matches(self, name: str, path: str) -> bool:
        """Check if filename and path match all set patterns.

        Args:
            name: Filename to check against filename/extension patterns
            path: Full path to check against path pattern

        Returns:
            True if all set patterns match
        """
        if self.filename and not self.filename.match(name):
            return False
        if self.extension and not self.extension.search(name):
            return False
        if self.path and not self.path.match(path):
            return False
        return True


@dataclass
class FileResult:
    """File search result (filename search via repository tree)."""
    path: str
    name: str
    type: str

@dataclass
class IssueResult:
    """Issue search result."""
    iid: int
    title: str
    state: str
    web_url: str

@dataclass
class MergeRequestResult:
    """Merge request search result."""
    iid: int
    title: str
    state: str
    web_url: str

@dataclass
class MilestoneResult:
    """Milestone search result."""
    iid: int
    title: str
    state: str
    web_url: str

@dataclass
class WikiResult:
    """Wiki blob search result."""
    path: str
    data: str
    slug: str

@dataclass
class CommitResult:
    """Commit search result."""
    short_id: str
    title: str
    message: str
    web_url: str

@dataclass
class NoteResult:
    """Note/comment search result."""
    body: str
    noteable_type: str
    noteable_iid: int | None

def get_next_pagination_url(response: Response) -> str | None:
    """Extract next page URL from Link header.

    GitLab uses Link header for pagination:
    <url>; rel="prev", <url>; rel="next", <url>; rel="first", <url>; rel="last"

    Args:
        response: HTTP response object

    Returns:
        Next page URL if available, None otherwise
    """
    link_header = response.headers.get("Link")
    if not link_header:
        return None

    # Parse link entries
    for entry in link_header.split(","):
        parts = [p.strip() for p in entry.split(";")]
        if len(parts) >= 2:
            url = parts[0].strip("<>")
            rel = parts[1].strip()
            if rel == 'rel="next"':
                return url

    return None

class GitLabClient:
    """Async GitLab API client."""

    @staticmethod
    def _get_archived_query_param(archived_filter: str) -> str:
        """Get query parameter for archived filter.

        Args:
            archived_filter: Archive filter - "all"/"include", "only", or "exclude"

        Returns:
            Query parameter string (empty, "&archived=true", or "&archived=false")
        """
        if archived_filter == "only":
            return "&archived=true"
        elif archived_filter == "exclude":
            return "&archived=false"
        return ""

    def __init__(self, config: Config) -> None:
        """Initialize GitLab client.

        Args:
            config: GitLab configuration
        """
        self.config = config
        self.base_url = config.api_url.rstrip("/")
        self.headers = {"PRIVATE-TOKEN": config.token}
        self.verify_cert = not config.ignore_cert
        self.ssl_context: ssl.SSLContext | None = None
        if not self.verify_cert:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
            logger.debug('Certificate will not be verified')
        logger.debug('Certificate verification enabled: %s', str(self.verify_cert))
        self.semaphore = asyncio.Semaphore(config.max_requests)

    def _request_sync(self, url: str) -> Response:
        """Make synchronous HTTP GET request.

        Args:
            url: Full URL to request

        Returns:
            Response object
        """
        logger.debug("Requesting: GET %s", url)
        request = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(request, context=self.ssl_context) as resp:
            return Response(
                status=resp.status,
                headers=dict(resp.headers),
                body=resp.read(),
            )

    async def _request(self, url: str) -> Response:
        """Make async HTTP GET request with concurrent request limit.

        Args:
            url: Full URL to request

        Returns:
            Response object
        """
        async with self.semaphore:
            return await asyncio.to_thread(self._request_sync, url)

    async def _paginated_request(
        self, url: str, is_absolute: bool = False
    ) -> list[dict]:
        """Make paginated HTTP GET request.

        Args:
            url: URL to request (relative or absolute)
            is_absolute: Whether URL is absolute

        Returns:
            List of all results from all pages
        """
        full_url = url if is_absolute else f"{self.base_url}{url}"
        response = await self._request(full_url)
        response.raise_for_status()

        results = response.json()
        next_url = get_next_pagination_url(response)

        if next_url:
            next_results = await self._paginated_request(next_url, is_absolute=True)
            results.extend(next_results)

        return results

    async def fetch_groups(self, group_names: str | None = None) -> list[Group]:
        """Fetch GitLab groups.

        Args:
            group_names: Comma-separated group names to filter by,
                or None to fetch all groups

        Returns:
            List of Group objects
        """
        if group_names:
            # Use provided group names directly
            groups = [
                Group(id=name, name=name) for name in group_names.split(",")
            ]
        else:
            # Fetch all groups from API
            data = await self._paginated_request("/groups?per_page=100")
            groups = [Group(id=str(g["id"]), name=g["name"]) for g in data]

        logger.debug("Using groups: %s", ", ".join(g.name for g in groups))

        return groups

    async def fetch_descendant_groups(self, group: Group) -> list[Group]:
        """Fetch all descendant groups (subgroups at all levels) of a group.

        Uses GitLab's /groups/:id/descendant_groups endpoint which returns
        all descendants (subgroups, sub-subgroups, etc.) in one response.

        Args:
            group: Parent group to fetch descendants for

        Returns:
            List of all descendant Group objects
        """
        url = f"/groups/{group.id}/descendant_groups?per_page=100&all_available=true"
        try:
            data = await self._paginated_request(url)
            descendants = [Group(id=str(g["id"]), name=g["full_path"]) for g in data]
            logger.debug(
                "Found %d descendant groups for %s: %s",
                len(descendants),
                group.name,
                ", ".join(g.name for g in descendants),
            )
            return descendants
        except Exception as e:
            logger.warning("Failed to fetch descendant groups for %s: %s", group.name, e)
            return []

    async def fetch_projects_in_groups(
        self,
        groups: list[Group],
        archived_filter: str = "all",
        recursive: bool = False,
        exclude_groups: list[str] | None = None,
    ) -> list[Project]:
        """Fetch projects in the specified groups.

        Args:
            groups: List of groups to fetch projects from
            archived_filter: Archive filter - "all", "only", or "exclude"
            recursive: If True, also fetch projects from all descendant subgroups
            exclude_groups: List of group names/IDs to exclude from search

        Returns:
            List of Project objects
        """
        all_groups = list(groups)

        # If recursive, fetch all descendant groups first
        if recursive:
            descendant_results = await asyncio.gather(
                *[self.fetch_descendant_groups(g) for g in groups]
            )
            for descendants in descendant_results:
                all_groups.extend(descendants)
            logger.debug(
                "Total groups after recursive expansion: %d",
                len(all_groups),
            )

        # Filter out excluded groups
        if exclude_groups:
            exclude_set = set(exclude_groups)
            original_count = len(all_groups)
            all_groups = [
                g for g in all_groups
                if g.id not in exclude_set and g.name not in exclude_set
            ]
            logger.debug(
                "Excluded %d groups, %d remaining",
                original_count - len(all_groups),
                len(all_groups),
            )

        async def fetch_group_projects(group: Group) -> list[dict]:
            url = f"/groups/{group.id}/projects?per_page=100{self._get_archived_query_param(archived_filter)}"
            return await self._paginated_request(url)

        # Fetch all group projects concurrently
        results = await asyncio.gather(
            *[fetch_group_projects(g) for g in all_groups]
        )

        # Flatten results and deduplicate by project ID
        seen_ids: set[int] = set()
        all_projects: list[Project] = []
        for project_list in results:
            for p in project_list:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_projects.append(
                        Project(
                            id=p["id"],
                            name=p["name"],
                            web_url=p["web_url"],
                            archived=p["archived"],
                        )
                    )

        logger.debug("Using projects: %s", ", ".join(p.name for p in all_projects))

        return all_projects

    def _build_search_query(self, criteria: SearchCriteria) -> str:
        """Build search query string with filters.

        Args:
            criteria: Search criteria

        Returns:
            URL-encoded search query
        """
        parts = [criteria.search_query]

        if criteria.filename:
            parts.append(f"filename:{criteria.filename}")
        if criteria.extension:
            parts.append(f"extension:{criteria.extension}")
        if criteria.path:
            parts.append(f"path:{criteria.path}")

        return quote(" ".join(parts))

    async def search_blobs_in_project(
        self, project: Project, criteria: SearchCriteria
    ) -> tuple[Project, list[SearchResult]]:
        """Search for blob content in a single project.

        Args:
            project: Project to search in
            criteria: Search criteria with optional filename/extension/path filters

        Returns:
            Tuple of (project, search results)
        """
        query = self._build_search_query(criteria)
        url = f"{self.base_url}/projects/{project.id}/search?scope=blobs&search={query}"

        response = await self._request(url)
        response.raise_for_status()

        results = [
            SearchResult(
                data=r["data"],
                filename=r["filename"],
                ref=r["ref"],
                startline=r["startline"],
            )
            for r in response.json()
        ]

        return project, results

    async def search_blobs_in_projects(
        self, projects: list[Project], criteria: SearchCriteria
    ) -> list[tuple[Project, list[SearchResult]]]:
        """Search for blob content in multiple projects.

        Args:
            projects: List of projects to search in
            criteria: Search criteria with optional filename/extension/path filters

        Returns:
            List of (project, search results) tuples, filtered to only
            include projects with results
        """
        results = await asyncio.gather(
            *[self.search_blobs_in_project(p, criteria) for p in projects]
        )

        # Filter to only include projects with results
        return [(p, r) for p, r in results if r]

    async def fetch_user_projects(
        self, user: str, archived_filter: str = "include"
    ) -> list[Project]:
        """Fetch projects owned by a user.

        Args:
            user: Username or user ID
            archived_filter: Archive filter - "include", "only", or "exclude"

        Returns:
            List of Project objects
        """
        url = f"/users/{user}/projects?per_page=100{self._get_archived_query_param(archived_filter)}"
        data = await self._paginated_request(url)

        projects = [
            Project(
                id=p["id"],
                name=p["name"],
                web_url=p["web_url"],
                archived=p["archived"],
            )
            for p in data
        ]

        logger.debug("Using user projects: %s", ", ".join(p.name for p in projects))
        return projects

    async def fetch_my_projects(self, archived_filter: str = "include") -> list[Project]:
        """Fetch projects the current user is a member of.

        Args:
            archived_filter: Archive filter - "include", "only", or "exclude"

        Returns:
            List of Project objects
        """
        url = f"/projects?membership=true&per_page=100{self._get_archived_query_param(archived_filter)}"
        data = await self._paginated_request(url)

        projects = [
            Project(
                id=p["id"],
                name=p["name"],
                web_url=p["web_url"],
                archived=p["archived"],
            )
            for p in data
        ]

        logger.debug("Using my projects: %s", ", ".join(p.name for p in projects))
        return projects

    async def fetch_projects_by_ids(self, project_ids: list[str]) -> list[Project]:
        """Fetch specific projects by ID or path.

        Args:
            project_ids: List of project IDs or paths

        Returns:
            List of Project objects
        """
        async def fetch_project(project_id: str) -> Project:
            url = f"/projects/{quote(project_id, safe='')}"
            response = await self._request(f"{self.base_url}{url}")
            response.raise_for_status()
            p = response.json()
            return Project(
                id=p["id"],
                name=p["name"],
                web_url=p["web_url"],
                archived=p["archived"],
            )

        projects = await asyncio.gather(*[fetch_project(pid) for pid in project_ids])
        logger.debug("Using projects: %s", ", ".join(p.name for p in projects))
        return list(projects)

    async def search_filenames_in_project(
        self, project: Project, criteria: SearchCriteria, ref: str = "HEAD"
    ) -> tuple[Project, list[FileResult]]:
        """Search for files by name using repository tree API.

        Args:
            project: Project to search in
            criteria: Search criteria with filename/extension/path patterns
            ref: Git ref (branch/tag) to search in

        Returns:
            Tuple of (project, matching files)
        """
        patterns = FileCriteriaPatterns.from_criteria(criteria)

        url = f"/projects/{project.id}/repository/tree?recursive=true&per_page=100&ref={ref}"
        try:
            all_files = await self._paginated_request(url)
        except urllib.error.HTTPError:
            return project, []

        matching = [
            FileResult(path=f["path"], name=f["name"], type=f["type"])
            for f in all_files
            if f["type"] == "blob" and patterns.matches(f["name"], f["path"])
        ]

        return project, matching

    async def search_filenames_in_projects(
        self, projects: list[Project], criteria: SearchCriteria
    ) -> list[tuple[Project, list[FileResult]]]:
        """Search for files by name in multiple projects.

        Args:
            projects: List of projects to search in
            criteria: Search criteria

        Returns:
            List of (project, file results) tuples
        """
        results = await asyncio.gather(
            *[self.search_filenames_in_project(p, criteria) for p in projects]
        )
        return [(p, r) for p, r in results if r]

    async def search_scope_in_project(
        self, project: Project, scope: str, search_query: str
    ) -> tuple[Project, list[dict]]:
        """Search with a specific scope in a project.

        Args:
            project: Project to search in
            scope: Search scope (issues, merge_requests, etc.)
            search_query: Search query

        Returns:
            Tuple of (project, raw results)
        """
        url = f"{self.base_url}/projects/{project.id}/search?scope={scope}&search={quote(search_query)}"
        response = await self._request(url)
        response.raise_for_status()
        return project, response.json()

    async def search_scope_in_projects(
        self, projects: list[Project], scope: str, search_query: str
    ) -> list[tuple[Project, list[dict]]]:
        """Search with a specific scope in multiple projects.

        Args:
            projects: List of projects to search in
            scope: Search scope
            search_query: Search query

        Returns:
            List of (project, results) tuples
        """
        results = await asyncio.gather(
            *[self.search_scope_in_project(p, scope, search_query) for p in projects]
        )
        return [(p, r) for p, r in results if r]
