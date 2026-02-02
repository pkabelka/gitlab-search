"""Expression-aware search executor."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .expression import ExprNode, ParsedCommand, set_universe
from .gitlab import (
    FileResult,
    GitLabClient,
    Project,
    SearchCriteria,
    SearchResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultIdentifier:
    """Unique identifier for a search result."""

    project_id: int
    filename: str
    ref: str
    startline: int

    @classmethod
    def from_result(cls, project: Project, result: SearchResult) -> "ResultIdentifier":
        """Create identifier from project and search result."""
        return cls(
            project_id=project.id,
            filename=result.filename,
            ref=result.ref,
            startline=result.startline,
        )


@dataclass(frozen=True)
class FileResultIdentifier:
    """Unique identifier for a file search result."""

    project_id: int
    path: str

    @classmethod
    def from_result(cls, project: Project, result: FileResult) -> "FileResultIdentifier":
        """Create identifier from project and file result."""
        return cls(
            project_id=project.id,
            path=result.path,
        )


@dataclass(frozen=True)
class ScopeResultIdentifier:
    """Unique identifier for a scope search result (issues, MRs, etc.)."""

    project_id: int
    item_id: int
    item_type: str

    @classmethod
    def from_result(
        cls, project: Project, result: dict, scope: str
    ) -> "ScopeResultIdentifier":
        """Create identifier from project and scope result."""
        # Different scopes use different ID fields
        if scope in ("issues", "merge_requests", "milestones"):
            item_id = result.get("iid", result.get("id", 0))
        elif scope == "commits":
            item_id = hash(result.get("id", result.get("short_id", "")))
        elif scope == "notes":
            item_id = result.get("id", 0)
        else:
            item_id = result.get("id", 0)
        return cls(
            project_id=project.id,
            item_id=item_id,
            item_type=scope,
        )


async def resolve_projects(
    client: GitLabClient,
    parsed: ParsedCommand,
) -> list[Project]:
    """Resolve projects from parsed command, including exclusions.

    Args:
        client: GitLab API client
        parsed: Parsed command with groups, projects, exclusions

    Returns:
        List of Project objects to search in
    """
    projects: list[Project] = []
    seen_ids: set[int] = set()

    # Fetch projects from groups
    if parsed.groups:
        groups = await client.fetch_groups(",".join(parsed.groups))
        group_projects = await client.fetch_projects_in_groups(groups, parsed.archived)
        for p in group_projects:
            if p.id not in seen_ids:
                projects.append(p)
                seen_ids.add(p.id)

    # Fetch explicit projects
    if parsed.projects:
        explicit_projects = await client.fetch_projects_by_ids(parsed.projects)
        for p in explicit_projects:
            if p.id not in seen_ids:
                projects.append(p)
                seen_ids.add(p.id)

    # Fetch user projects
    if parsed.user:
        user_projects = await client.fetch_user_projects(parsed.user, parsed.archived)
        for p in user_projects:
            if p.id not in seen_ids:
                projects.append(p)
                seen_ids.add(p.id)

    # Fetch my projects
    if parsed.my_projects:
        my_projects = await client.fetch_my_projects(parsed.archived)
        for p in my_projects:
            if p.id not in seen_ids:
                projects.append(p)
                seen_ids.add(p.id)

    # If nothing specified, fetch all groups
    if not parsed.groups and not parsed.projects and not parsed.user and not parsed.my_projects:
        groups = await client.fetch_groups(None)
        all_projects = await client.fetch_projects_in_groups(groups, parsed.archived)
        for p in all_projects:
            if p.id not in seen_ids:
                projects.append(p)
                seen_ids.add(p.id)

    # Apply exclusions
    if parsed.exclude_projects:
        # Resolve excluded project IDs
        excluded = await client.fetch_projects_by_ids(parsed.exclude_projects)
        excluded_ids = {p.id for p in excluded}
        projects = [p for p in projects if p.id not in excluded_ids]
        logger.debug("Excluded projects: %s", ", ".join(str(i) for i in excluded_ids))

    logger.debug(
        "Resolved %d projects: %s",
        len(projects),
        ", ".join(p.name for p in projects),
    )
    return projects


async def execute_blob_search(
    client: GitLabClient,
    projects: list[Project],
    expression: ExprNode,
    all_queries: list[str],
    filename: str | None = None,
    extension: str | None = None,
    path: str | None = None,
) -> list[tuple[Project, list[SearchResult]]]:
    """Execute blob search with expression logic.

    Args:
        client: GitLab API client
        projects: Projects to search in
        expression: Expression tree for query logic
        all_queries: All unique query strings in expression
        filename: Optional filename filter
        extension: Optional extension filter
        path: Optional path filter

    Returns:
        List of (project, results) tuples matching the expression
    """
    if not all_queries:
        return []

    # Execute all queries in parallel
    query_results: dict[str, dict[ResultIdentifier, tuple[Project, SearchResult]]] = {}

    async def search_query(query: str) -> tuple[str, list[tuple[Project, list[SearchResult]]]]:
        criteria = SearchCriteria(
            search_query=query,
            filename=filename,
            extension=extension,
            path=path,
        )
        results = await client.search_blobs_in_projects(projects, criteria)
        return query, results

    # Run all queries concurrently
    query_tasks = [search_query(q) for q in all_queries]
    query_results_list = await asyncio.gather(*query_tasks)

    # Build result mappings
    for query, results in query_results_list:
        query_results[query] = {}
        for project, search_results in results:
            for result in search_results:
                rid = ResultIdentifier.from_result(project, result)
                query_results[query][rid] = (project, result)

    # Build ID sets for expression evaluation
    id_sets: dict[str, set[Any]] = {
        q: set(results.keys()) for q, results in query_results.items()
    }

    # Compute universe for NOT operations (all unique result IDs)
    universe: set[Any] = set()
    for ids in id_sets.values():
        universe |= ids

    # Set universe on all NOT nodes
    set_universe(expression, universe)

    # Evaluate expression
    matching_ids = expression.evaluate(id_sets)

    # Collect matching results, grouped by project
    project_results: dict[int, tuple[Project, list[SearchResult]]] = {}

    for query, results in query_results.items():
        for rid, (project, result) in results.items():
            if rid in matching_ids:
                if project.id not in project_results:
                    project_results[project.id] = (project, [])
                # Avoid duplicates
                if result not in project_results[project.id][1]:
                    project_results[project.id][1].append(result)

    return list(project_results.values())


async def execute_file_search(
    client: GitLabClient,
    projects: list[Project],
    expression: ExprNode,
    all_queries: list[str],
    filename: str | None = None,
    extension: str | None = None,
    path: str | None = None,
) -> list[tuple[Project, list[FileResult]]]:
    """Execute filename search with expression logic.

    For file searches, the query is matched against the filename,
    so expression logic is evaluated differently.

    Args:
        client: GitLab API client
        projects: Projects to search in
        expression: Expression tree for query logic
        all_queries: All unique query strings in expression
        filename: Optional filename filter
        extension: Optional extension filter
        path: Optional path filter

    Returns:
        List of (project, results) tuples matching the expression
    """
    if not all_queries:
        # No query - just use filename/extension/path filters
        criteria = SearchCriteria(
            search_query="",
            filename=filename,
            extension=extension,
            path=path,
        )
        return await client.search_filenames_in_projects(projects, criteria)

    # Execute all queries in parallel
    query_results: dict[str, dict[FileResultIdentifier, tuple[Project, FileResult]]] = {}

    async def search_query(query: str) -> tuple[str, list[tuple[Project, list[FileResult]]]]:
        criteria = SearchCriteria(
            search_query=query,
            filename=filename,
            extension=extension,
            path=path,
        )
        results = await client.search_filenames_in_projects(projects, criteria)
        return query, results

    query_tasks = [search_query(q) for q in all_queries]
    query_results_list = await asyncio.gather(*query_tasks)

    for query, results in query_results_list:
        query_results[query] = {}
        for project, file_results in results:
            for result in file_results:
                rid = FileResultIdentifier.from_result(project, result)
                query_results[query][rid] = (project, result)

    id_sets: dict[str, set[Any]] = {
        q: set(results.keys()) for q, results in query_results.items()
    }

    universe: set[Any] = set()
    for ids in id_sets.values():
        universe |= ids

    set_universe(expression, universe)
    matching_ids = expression.evaluate(id_sets)

    project_results: dict[int, tuple[Project, list[FileResult]]] = {}

    for query, results in query_results.items():
        for rid, (project, result) in results.items():
            if rid in matching_ids:
                if project.id not in project_results:
                    project_results[project.id] = (project, [])
                if result not in project_results[project.id][1]:
                    project_results[project.id][1].append(result)

    return list(project_results.values())


async def execute_scope_search(
    client: GitLabClient,
    projects: list[Project],
    scope: str,
    expression: ExprNode,
    all_queries: list[str],
) -> list[tuple[Project, list[dict]]]:
    """Execute scope search (issues, MRs, etc.) with expression logic.

    Args:
        client: GitLab API client
        projects: Projects to search in
        scope: Search scope (issues, merge_requests, etc.)
        expression: Expression tree for query logic
        all_queries: All unique query strings in expression

    Returns:
        List of (project, results) tuples matching the expression
    """
    if not all_queries:
        return []

    query_results: dict[str, dict[ScopeResultIdentifier, tuple[Project, dict]]] = {}

    async def search_query(query: str) -> tuple[str, list[tuple[Project, list[dict]]]]:
        results = await client.search_scope_in_projects(projects, scope, query)
        return query, results

    query_tasks = [search_query(q) for q in all_queries]
    query_results_list = await asyncio.gather(*query_tasks)

    for query, results in query_results_list:
        query_results[query] = {}
        for project, scope_results in results:
            for result in scope_results:
                rid = ScopeResultIdentifier.from_result(project, result, scope)
                query_results[query][rid] = (project, result)

    id_sets: dict[str, set[Any]] = {
        q: set(results.keys()) for q, results in query_results.items()
    }

    universe: set[Any] = set()
    for ids in id_sets.values():
        universe |= ids

    set_universe(expression, universe)
    matching_ids = expression.evaluate(id_sets)

    project_results: dict[int, tuple[Project, list[dict]]] = {}

    for query, results in query_results.items():
        for rid, (project, result) in results.items():
            if rid in matching_ids:
                if project.id not in project_results:
                    project_results[project.id] = (project, [])
                if result not in project_results[project.id][1]:
                    project_results[project.id][1].append(result)

    return list(project_results.values())


async def execute_search(
    client: GitLabClient,
    parsed: ParsedCommand,
) -> None:
    """Execute search based on parsed command and print results.

    This is the main entry point for expression-aware search.

    Args:
        client: GitLab API client
        parsed: Parsed command with expression and options
    """
    from .output import ColorFormatter, ResultPrinter

    printer = ResultPrinter(ColorFormatter(parsed.color))

    # Resolve projects with exclusions
    projects = await resolve_projects(client, parsed)

    if not projects:
        logger.warning("No projects to search")
        return

    # Get all queries from expression
    all_queries = parsed.get_all_queries()
    expression = parsed.query_expression

    # For single query without operators, simplify to use first query for highlighting
    highlight_query = all_queries[0] if all_queries else ""

    # Perform search for each scope
    for scope in parsed.scope:
        if scope == "blobs":
            if expression:
                results = await execute_blob_search(
                    client,
                    projects,
                    expression,
                    all_queries,
                    parsed.filename,
                    parsed.extension,
                    parsed.path,
                )
            else:
                # No query expression - shouldn't happen with required -q
                results = []
            printer.print_blob_results(highlight_query, results)

        elif scope == "files":
            if expression:
                results = await execute_file_search(
                    client,
                    projects,
                    expression,
                    all_queries,
                    parsed.filename,
                    parsed.extension,
                    parsed.path,
                )
            else:
                # File search without query uses filters only
                criteria = SearchCriteria(
                    search_query="",
                    filename=parsed.filename,
                    extension=parsed.extension,
                    path=parsed.path,
                )
                results = await client.search_filenames_in_projects(projects, criteria)
            printer.print_file_results(results)

        else:
            if expression:
                results = await execute_scope_search(
                    client,
                    projects,
                    scope,
                    expression,
                    all_queries,
                )
            else:
                results = []
            printer.print_scope_results(scope, highlight_query, results)
