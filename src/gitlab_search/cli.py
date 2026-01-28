"""Command-line interface for gitlab-search."""

import argparse
import asyncio
import logging
import sys
from importlib.metadata import version

from .config import (
    DEFAULT_API_URL,
    DEFAULT_MAX_REQUESTS,
    load_config,
    write_config,
)
from .gitlab import GitLabClient, SearchCriteria
from .output import ColorFormatter, ResultPrinter

PROGRAM_NAME = "gitlab-search"
VALID_SCOPES = [
    "blobs", "files", "issues", "merge_requests",
    "milestones", "wiki_blobs", "commits", "notes"
]

def parse_scopes(scope_arg: str) -> list[str]:
    """Parse and validate comma-separated scopes.

    Args:
        scope_arg: Comma-separated scope string

    Returns:
        List of valid scope names

    Raises:
        argparse.ArgumentTypeError: If any scope is invalid
    """
    scopes = [s.strip() for s in scope_arg.split(",")]
    invalid = set(scopes) - set(VALID_SCOPES)
    if invalid:
        raise argparse.ArgumentTypeError(
            f"invalid choice(s): {', '.join(sorted(invalid))} "
            f"(choose from {', '.join(sorted(VALID_SCOPES))})"
        )
    return scopes

def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Search for file contents in GitLab repositories.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {version(PROGRAM_NAME)}",
    )

    # Search arguments
    parser.add_argument(
        "search_query",
        metavar="QUERY",
        nargs="?",
        help="GitLab search query",
    )

    # Project source options (mutually exclusive)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "-g",
        "--groups",
        metavar="GROUPS",
        help="comma separated list of groups (name or numeric ID)",
    )
    source_group.add_argument(
        "-p",
        "--projects",
        metavar="PROJECTS",
        help="comma separated list of projects (path or numeric ID)",
    )
    source_group.add_argument(
        "-u",
        "--user",
        metavar="USER",
        help="search in projects owned by this user (username or numeric ID)",
    )
    source_group.add_argument(
        "--my-projects",
        action="store_true",
        help="search in your own projects",
    )

    # Search scope
    parser.add_argument(
        "-s",
        "--scope",
        metavar="SCOPES",
        type=parse_scopes,
        default="blobs",
        help=f"comma-separated search scopes: {', '.join(sorted(VALID_SCOPES))} (default: %(default)s)",
    )

    # Search filters
    parser.add_argument(
        "-f",
        "--filename",
        metavar="FILENAME",
        help="search content only in files matching this (supports wildcard operator '*')",
    )
    parser.add_argument(
        "-e",
        "--extension",
        metavar="EXT",
        help="search content only in files with this extension",
    )
    parser.add_argument(
        "-P",
        "--path",
        metavar="FILE_PATH",
        help="search content only in files with the given path",
    )
    parser.add_argument(
        "-a",
        "--archived",
        choices=["include", "only", "exclude"],
        default="include",
        help=(
            "search in all projects, search only in archived projects, "
            "exclude archived projects (default: %(default)s)"
        ),
    )

    # Connection options (used for both search override and setup)
    parser.add_argument(
        "--api-url",
        metavar="API_URL_BASE",
        help=f"GitLab API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--ignore-cert",
        action="store_true",
        default=False,
        help="ignore API certificate errors",
    )
    parser.add_argument(
        "--max-requests",
        metavar="N_REQUESTS",
        type=int,
        help=(
            "maximum number of concurrent requests sent to GitLab "
            f"(default: {DEFAULT_MAX_REQUESTS})"
        ),
    )
    parser.add_argument(
        "--token",
        metavar="PERSONAL_ACCESS_TOKEN",
        default=None,
        help="GitLab personal access token",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="colorize output (default: %(default)s)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="enable debug logging",
    )

    # Setup options
    parser.add_argument(
        "--setup",
        action="store_true",
        help="store the provided options in a configuration file",
    )
    parser.add_argument(
        "--dir",
        metavar="CONFIG_DIR",
        default=".",
        help="configuration file directory (default: %(default)s)",
    )

    return parser

def run_setup(args: argparse.Namespace) -> None:
    """Run the setup command.

    Args:
        args: Parsed command-line arguments
    """
    config_path = write_config(
        directory=args.dir,
        token=args.token,
        api_url=args.api_url if args.api_url else DEFAULT_API_URL,
        ignore_cert=bool(args.ignore_cert),
        max_requests=args.max_requests if args.max_requests else DEFAULT_MAX_REQUESTS,
    )
    printer = ResultPrinter(ColorFormatter(args.color))
    printer.print_success(
        f"Successfully wrote config to {config_path}, "
        f"{PROGRAM_NAME} is now ready to be used"
    )

async def run_search(args: argparse.Namespace) -> None:
    """Run the search command.

    Args:
        args: Parsed command-line arguments
    """
    logger = logging.getLogger(__name__)
    config = load_config()

    # Apply CLI overrides
    if args.api_url is not None:
        config.api_url = args.api_url
    if args.ignore_cert:
        config.ignore_cert = True
    if args.max_requests is not None:
        config.max_requests = args.max_requests
    if args.token is not None:
        config.token = args.token

    client = GitLabClient(config)
    printer = ResultPrinter(ColorFormatter(args.color))

    criteria = SearchCriteria(
        search_query=args.search_query,
        filename=args.filename,
        extension=args.extension,
        path=args.path,
    )

    try:
        # Determine project source
        if args.projects:
            logger.debug("Fetching projects by IDs or names")
            projects = await client.fetch_projects_by_ids(args.projects.split(","))
        elif args.user:
            logger.debug("Fetching projects of user: %s", args.user)
            logger.debug("Archived projects: %s", args.archived)
            projects = await client.fetch_user_projects(args.user, args.archived)
        elif args.my_projects:
            logger.debug("Fetching own user projects")
            projects = await client.fetch_my_projects(args.archived)
        else:
            logger.debug("Fetching projects by available groups")
            groups = await client.fetch_groups(args.groups)
            projects = await client.fetch_projects_in_groups(groups, args.archived)

        # Perform search for each scope
        for scope in args.scope:
            if scope == "blobs":
                results = await client.search_blobs_in_projects(projects, criteria)
                printer.print_blob_results(criteria.search_query, results)
            elif scope == "files":
                results = await client.search_filenames_in_projects(projects, criteria)
                printer.print_file_results(results)
            else:
                results = await client.search_scope_in_projects(projects, scope, criteria.search_query)
                printer.print_scope_results(scope, criteria.search_query, results)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def configure_logging(debug: bool) -> None:
    """Configure logging based on debug flag.

    Args:
        debug: Whether to enable debug logging
    """
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )

def main() -> None:
    parser = create_argument_parser()
    args = parser.parse_args()

    configure_logging(args.debug)

    if args.setup:
        run_setup(args)
    elif not args.search_query and args.scope != ['files']:
        parser.print_help()
        sys.exit(1)
    else:
        try:
            asyncio.run(run_search(args))
        except KeyboardInterrupt:
            print('Received interrupt, exiting')

if __name__ == "__main__":
    main()
