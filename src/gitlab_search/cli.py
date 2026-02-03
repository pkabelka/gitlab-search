"""Command-line interface for gitlab-search."""

import asyncio
import logging
import sys
from importlib.metadata import version

from .config import (
    CONFIG_FILENAME,
    DEFAULT_API_URL,
    DEFAULT_MAX_REQUESTS,
    load_config,
    resolve_token,
    write_config,
)
from .executor import execute_search
from .gitlab import GitLabClient
from .output import ColorFormatter, ResultPrinter
from .parser import ParseError, parse_command
from .expression import ParsedCommand

PROGRAM_NAME = "gitlab-search"
VALID_SCOPES = [
    "blobs", "files", "issues", "merge_requests",
    "milestones", "wiki_blobs", "commits", "notes"
]


def print_help() -> None:
    """Print help message."""
    print(f"""Usage: {PROGRAM_NAME} [OPTIONS] -q QUERY [-q QUERY ...]

Search for file contents in GitLab repositories using find-like expression syntax.

Query Options:
  -q QUERY              Search query (required, can be repeated)
  -a                    AND operator (implicit between -q flags)
  -o                    OR operator
  -not, !               NOT operator (negation)
  ( )                   Grouping (use \\( \\) in shell)

Project Source Options (can be combined):
  -g, --groups GROUPS   Comma-separated list of groups (name or numeric ID)
  -p, --projects PROJS  Comma-separated list of projects (path or numeric ID)
  -u, --user USER       Search in projects owned by this user
  --my-projects         Search in projects you are a member of
  -r, --recursive       Recursively search all subgroups under specified groups

  Use -not before -p or -g to exclude projects/groups:
    -g mygroup -not -p excluded_project

Search Scope:
  -s, --scope SCOPES    Comma-separated search scopes (default: blobs)
                        Choices: {', '.join(sorted(VALID_SCOPES))}

Search Filters:
  -f, --filename FILE   Search only in files matching this pattern
  -e, --extension EXT   Search only in files with this extension
  -P, --path PATH       Search only in files with this path

  Use -not before -f, -e, or -P to exclude files:
    -q "term" ! -e md              Exclude .md files
    -q "term" ! -f "*.test.js"     Exclude test files
    -q "term" ! -P "*vendor*"      Exclude vendor directory

Archive Filter:
  --archived MODE       Filter archived projects: include, only, exclude
                        (default: include)

Connection Options:
  --api-url URL         GitLab API base URL (default: {DEFAULT_API_URL})
  --ignore-cert         Ignore API certificate errors
  --max-requests N      Max concurrent requests (default: {DEFAULT_MAX_REQUESTS})
  --token TOKEN         GitLab personal access token
  --token-file FILE     Read GitLab token from file (mutually exclusive with --token)

Environment Variables:
  GITLAB_SEARCH_TOKEN   GitLab token (used if --token/--token-file not provided)

Setup:
  --setup               Store options in configuration file
  -C, --config FILE     Configuration file path (default: ./{CONFIG_FILENAME})

Other:
  --color MODE          Colorize output: auto, always, never (default: auto)
  --debug               Enable debug logging
  -V, --version         Show version and exit
  -h, --help            Show this help and exit

Examples:
  # Simple search
  {PROGRAM_NAME} -p myproject -q "search term"

  # Search with AND (files must contain both terms)
  {PROGRAM_NAME} -p myproject -q "term1" -q "term2"
  {PROGRAM_NAME} -p myproject -q "term1" -a -q "term2"

  # Search with OR (files containing either term)
  {PROGRAM_NAME} -p myproject -q "term1" -o -q "term2"

  # Exclude a project from group search
  {PROGRAM_NAME} -g mygroup ! -p excluded_project -q "term"

  # Recursively search all subgroups
  {PROGRAM_NAME} -g parent_group -r -q "term"

  # Exclude a subgroup from group search
  {PROGRAM_NAME} -g parent_group -r ! -g parent_group/subgroup -q "term"

  # Combined AND and OR with grouping
  {PROGRAM_NAME} -p myproject \\( -q "a" -o -q "b" \\) -q "c"

  # Exclude markdown files from search
  {PROGRAM_NAME} -p myproject -q "term" ! -e md

  # Exclude test files and vendor directory
  {PROGRAM_NAME} -p myproject -q "term" ! -f "*.test.*" ! -P "*vendor*"
""")


def print_version() -> None:
    """Print version."""
    print(f"{PROGRAM_NAME} {version(PROGRAM_NAME)}")


def validate_scopes(scopes: list[str]) -> None:
    """Validate search scopes.

    Args:
        scopes: List of scope names

    Raises:
        ParseError: If any scope is invalid
    """
    invalid = set(scopes) - set(VALID_SCOPES)
    if invalid:
        raise ParseError(
            f"invalid scope(s): {', '.join(sorted(invalid))} "
            f"(choose from {', '.join(sorted(VALID_SCOPES))})"
        )


def run_setup(parsed: ParsedCommand) -> None:
    """Run the setup command.

    Args:
        parsed: Parsed command
    """
    config_path = write_config(
        file_path=parsed.config_file,
        api_url=parsed.api_url if parsed.api_url else DEFAULT_API_URL,
        ignore_cert=parsed.ignore_cert,
        max_requests=parsed.max_requests if parsed.max_requests else DEFAULT_MAX_REQUESTS,
    )
    printer = ResultPrinter(ColorFormatter(parsed.color))
    printer.print_success(
        f"Successfully wrote config to {config_path}, "
        f"{PROGRAM_NAME} is now ready to be used"
    )


async def run_search(parsed: ParsedCommand) -> None:
    """Run the search command.

    Args:
        parsed: Parsed command with expression and options
    """
    logger = logging.getLogger(__name__)
    config = load_config(parsed.config_file)

    # Apply CLI overrides
    if parsed.api_url is not None:
        config.api_url = parsed.api_url
    if parsed.ignore_cert:
        config.ignore_cert = True
    if parsed.max_requests is not None:
        config.max_requests = parsed.max_requests
    config.token = resolve_token(parsed.token, parsed.token_file)
    if not config.token:
        logger.critical("Token not provided")
        sys.exit(1)

    client = GitLabClient(config)

    try:
        await execute_search(client, parsed)
    except Exception as e:
        logger.critical("Search failed")
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
    """Main entry point."""
    # Handle --help and --version before custom parsing
    if len(sys.argv) == 1:
        print_help()
        sys.exit(1)

    if "-h" in sys.argv or "--help" in sys.argv:
        print_help()
        sys.exit(0)

    if "-V" in sys.argv or "--version" in sys.argv:
        print_version()
        sys.exit(0)

    try:
        parsed = parse_command(sys.argv[1:])
    except ParseError as e:
        if str(e) == "VERSION":
            print_version()
            sys.exit(0)
        elif str(e) == "HELP":
            print_help()
            sys.exit(0)
        else:
            print(f"Error: {e}", file=sys.stderr)
            print(f"Try '{PROGRAM_NAME} --help' for more information.", file=sys.stderr)
            sys.exit(1)

    configure_logging(parsed.debug)

    # Validate scopes
    try:
        validate_scopes(parsed.scope)
    except ParseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Check mutual exclusivity of --token and --token-file
    if parsed.token is not None and parsed.token_file is not None:
        print("Error: --token and --token-file are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if parsed.setup:
        run_setup(parsed)
    elif parsed.query_expression is None and parsed.scope != ["files"]:
        print("Error: -q QUERY is required (unless using -s files)", file=sys.stderr)
        print(f"Try '{PROGRAM_NAME} --help' for more information.", file=sys.stderr)
        sys.exit(1)
    else:
        try:
            asyncio.run(run_search(parsed))
        except KeyboardInterrupt:
            print("Received interrupt, exiting")


if __name__ == "__main__":
    main()
