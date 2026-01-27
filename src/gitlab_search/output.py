"""Terminal output formatting with ANSI colors."""

import re
import sys

from .gitlab import Project, SearchResult

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

class ResultPrinter:
    """Prints search results with optional color formatting."""

    def __init__(self, formatter: ColorFormatter) -> None:
        """Initialize printer with a color formatter.

        Args:
            formatter: ColorFormatter instance for styling output
        """
        self.fmt = formatter

    def highlight_term(self, term: str, data: str) -> str:
        """Highlight matched term in red.

        Uses case-insensitive matching but preserves original case
        in the output.

        Args:
            term: The search term to highlight
            data: The text containing matches

        Returns:
            Text with matched terms highlighted in red
        """
        escaped_term = re.escape(term)
        pattern = re.compile(f"({escaped_term})", re.IGNORECASE)
        return pattern.sub(lambda m: self.fmt.red(m.group(1)), data)

    def print_search_results(
        self, term: str, results: list[tuple[Project, list[SearchResult]]]
    ) -> None:
        """Print search results with formatting.

        Args:
            term: The search term used
            results: List of (project, search results) tuples
        """
        for project, search_results in results:
            # Format each result
            formatted_results = ""
            for result in search_results:
                url = url_to_line(project, result)
                highlighted_data = self.highlight_term(
                    term, indent_preview(result.data)
                )
                formatted_results += (
                    f"\n\t{self.fmt.underline(url)}\n\n\t\t{highlighted_data}"
                )

            # Add archived indicator if needed
            archived_info = ""
            if project.archived:
                archived_info = self.fmt.bold(self.fmt.red(" (archived)"))

            print(f"{self.fmt.bold(self.fmt.green(project.name))}{archived_info}:")
            print(formatted_results)

    def print_success(self, message: str) -> None:
        print(self.fmt.green(message))
