"""GitLab API client with async support."""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .config import Config

logger = logging.getLogger(__name__)

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
    term: str
    filename: str | None = None
    extension: str | None = None
    path: str | None = None

def get_next_pagination_url(response: requests.Response) -> str | None:
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

    def __init__(self, config: Config) -> None:
        """Initialize GitLab client.

        Args:
            config: GitLab configuration
        """
        self.config = config
        self.base_url = config.api_url.rstrip("/")
        self.headers = {"PRIVATE-TOKEN": config.token}
        self.verify_cert = not config.ignore_cert
        self.semaphore = asyncio.Semaphore(config.max_requests)

    def _request_sync(self, url: str) -> requests.Response:
        """Make synchronous HTTP GET request.

        Args:
            url: Full URL to request

        Returns:
            Response object
        """
        logger.debug("Requesting: GET %s", url)
        return requests.get(url, headers=self.headers, verify=self.verify_cert)

    async def _request(self, url: str) -> requests.Response:
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

    async def fetch_projects_in_groups(
        self, groups: list[Group], archived_filter: str = "all"
    ) -> list[Project]:
        """Fetch projects in the specified groups.

        Args:
            groups: List of groups to fetch projects from
            archive: Archive filter - "all", "only", or "exclude"

        Returns:
            List of Project objects
        """
        archived_query_param = ""
        if archived_filter == "only":
            archived_query_param = "&archived=true"
        elif archived_filter == "exclude":
            archived_query_param = "&archived=false"

        async def fetch_group_projects(group: Group) -> list[dict]:
            url = f"/groups/{group.id}/projects?per_page=100{archived_query_param}"
            return await self._paginated_request(url)

        # Fetch all group projects concurrently
        results = await asyncio.gather(
            *[fetch_group_projects(g) for g in groups]
        )

        # Flatten results
        all_projects: list[Project] = []
        for project_list in results:
            for p in project_list:
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
        parts = [criteria.term]

        if criteria.filename:
            parts.append(f"filename:{criteria.filename}")
        if criteria.extension:
            parts.append(f"extension:{criteria.extension}")
        if criteria.path:
            parts.append(f"path:{criteria.path}")

        return quote(" ".join(parts))

    async def search_in_project(
        self, project: Project, criteria: SearchCriteria
    ) -> tuple[Project, list[SearchResult]]:
        """Search for content in a single project.

        Args:
            project: Project to search in
            criteria: Search criteria

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

    async def search_in_projects(
        self, projects: list[Project], criteria: SearchCriteria
    ) -> list[tuple[Project, list[SearchResult]]]:
        """Search for content in multiple projects.

        Args:
            projects: List of projects to search in
            criteria: Search criteria

        Returns:
            List of (project, search results) tuples, filtered to only
            include projects with results
        """
        results = await asyncio.gather(
            *[self.search_in_project(p, criteria) for p in projects]
        )

        # Filter to only include projects with results
        return [(p, r) for p, r in results if r]
