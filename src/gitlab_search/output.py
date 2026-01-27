"""Terminal output formatting with ANSI colors."""

import re
import sys

from .gitlab import FileResult, Project, SearchResult

class ColorFormatter:
    """Handles colored terminal output with configurable color mode."""

    # ANSI escape codes
    RED = "\033[31m"
    GREEN = "\033[32m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"

    def __init__(self, mode: str = "auto") -> None:
        """Initialize formatter with color mode.

        Args:
            mode: "auto", "always", or "never"
        """
        if mode == "always":
            self.use_colors = True
        elif mode == "never":
            self.use_colors = False
        else:
            self.use_colors = sys.stdout.isatty()

    def red(self, text: str) -> str:
        """Apply red color to text."""
        if not self.use_colors:
            return text
        return f"{self.RED}{text}{self.RESET}"

    def green(self, text: str) -> str:
        """Apply green color to text."""
        if not self.use_colors:
            return text
        return f"{self.GREEN}{text}{self.RESET}"

    def bold(self, text: str) -> str:
        """Apply bold formatting to text."""
        if not self.use_colors:
            return text
        return f"{self.BOLD}{text}{self.RESET}"

    def underline(self, text: str) -> str:
        """Apply underline formatting to text."""
        if not self.use_colors:
            return text
        return f"{self.UNDERLINE}{text}{self.RESET}"

def url_to_line(project: Project, result: SearchResult) -> str:
    """Generate URL to the specific line in the file.

    Args:
        project: The project containing the file
        result: The search result

    Returns:
        URL string pointing to the file and line
    """
    number_of_lines = result.data.count("\n")
    end_line = result.startline + number_of_lines - 1
    return (
        f"{project.web_url}/blob/{result.ref}/{result.filename}#L{result.startline}-{end_line}"
    )

def indent_preview(preview: str) -> str:
    """Indent multiline preview text.

    Args:
        preview: The preview text to indent

    Returns:
        Indented text with each newline followed by tabs
    """
    return preview.replace("\n", "\n\t\t")

def extract_snippet(text: str, search_query: str, context_chars: int = 100) -> str | None:
    """Extract snippet around first occurrence of search_query.

    Args:
        text: Full text to search in
        search_query: Search query to find
        context_chars: Characters to show before/after match

    Returns:
        Snippet with ellipsis if truncated, or None if search_query not found
    """
    match = re.search(re.escape(search_query), text, re.IGNORECASE)
    if not match:
        return None

    start = max(0, match.start() - context_chars)
    end = min(len(text), match.end() + context_chars)

    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet

class ResultPrinter:
    """Prints search results with optional color formatting."""

    def __init__(self, formatter: ColorFormatter) -> None:
        """Initialize printer with a color formatter.

        Args:
            formatter: ColorFormatter instance for styling output
        """
        self.fmt = formatter

    def highlight_search_query(self, search_query: str, data: str) -> str:
        """Highlight matched search_query in red.

        Uses case-insensitive matching but preserves original case
        in the output.

        Args:
            search_query: The search query to highlight
            data: The text containing matches

        Returns:
            Text with matched search query highlighted
        """
        escaped_search_query = re.escape(search_query)
        pattern = re.compile(f"({escaped_search_query})", re.IGNORECASE)
        return pattern.sub(lambda m: self.fmt.red(m.group(1)), data)

    def _print_project_header(self, project: Project) -> None:
        """Print project header with archived indicator if needed."""
        archived_info = ""
        if project.archived:
            archived_info = self.fmt.bold(self.fmt.red(" (archived)"))
        print(f"{self.fmt.bold(self.fmt.green(project.name))}{archived_info}:")

    def print_blob_results(
        self, search_query: str, results: list[tuple[Project, list[SearchResult]]]
    ) -> None:
        """Print blob search results with formatting.

        Args:
            search_query: The search query used
            results: List of (project, search results) tuples
        """
        for project, search_results in results:
            formatted_results = ""
            for result in search_results:
                url = url_to_line(project, result)
                highlighted_data = self.highlight_search_query(
                    search_query, indent_preview(result.data)
                )
                formatted_results += (
                    f"\n\t{self.fmt.underline(url)}\n\n\t\t{highlighted_data}"
                )
            self._print_project_header(project)
            print(formatted_results)

    def print_file_results(
        self, results: list[tuple[Project, list[FileResult]]]
    ) -> None:
        """Print filename search results.

        Args:
            results: List of (project, file results) tuples
        """
        for project, file_results in results:
            self._print_project_header(project)
            for result in file_results:
                url = f"{project.web_url}/-/blob/HEAD/{result.path}"
                print(f"\t{self.fmt.underline(url)}")

    def print_scope_results(
        self, scope: str, search_query: str, results: list[tuple[Project, list[dict]]]
    ) -> None:
        """Print generic scope search results.

        Args:
            scope: The search scope (issues, merge_requests, etc.)
            search_query: The search query used
            results: List of (project, raw results) tuples
        """
        for project, scope_results in results:
            self._print_project_header(project)
            for result in scope_results:
                if scope in ("issues", "merge_requests", "milestones"):
                    iid = result.get("iid", "")
                    title = result.get("title", "")
                    state = result.get("state", "")
                    web_url = result.get("web_url", "")
                    description = result.get("description", "") or ""

                    print(f"\n\t{self.fmt.underline(web_url)}")
                    highlighted_title = self.highlight_search_query(search_query, title)
                    print(f"\t#{iid} [{state}] {highlighted_title}")

                    snippet = extract_snippet(description, search_query)
                    if snippet:
                        highlighted_snippet = self.highlight_search_query(search_query, indent_preview(snippet))
                        print(f"\t\t{highlighted_snippet}")
                elif scope == "wiki_blobs":
                    slug = result.get("slug", "")
                    data = result.get("data", "")
                    url = f"{project.web_url}/-/wikis/{slug}"
                    highlighted = self.highlight_search_query(search_query, indent_preview(data))
                    print(f"\t{self.fmt.underline(url)}\n\n\t\t{highlighted}")
                elif scope == "commits":
                    short_id = result.get("short_id", "")
                    title = result.get("title", "")
                    web_url = result.get("web_url", "")
                    print(f"\n\t{self.fmt.underline(web_url)}")
                    print(f"\t{short_id} {title}")
                elif scope == "notes":
                    body = result.get("body", "")
                    noteable_type = result.get("noteable_type", "")
                    noteable_iid = result.get("noteable_iid", "")
                    highlighted = self.highlight_search_query(search_query, indent_preview(body))
                    print(f"\n\t{noteable_type} #{noteable_iid}")
                    print(f"\t\t{highlighted}")

    def print_success(self, message: str) -> None:
        print(self.fmt.green(message))
