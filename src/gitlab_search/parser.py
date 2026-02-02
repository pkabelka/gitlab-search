"""Find-like expression parser for CLI arguments."""

from dataclasses import dataclass, field
from enum import Enum, auto

from .expression import (
    AndNode,
    ExprNode,
    NotNode,
    OrNode,
    ParsedCommand,
    QueryNode,
)


class TokenType(Enum):
    """Token types for the expression parser."""

    QUERY = auto()  # -q "term"
    AND = auto()  # -a
    OR = auto()  # -o
    NOT = auto()  # -not or !
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    EOF = auto()  # End of tokens


@dataclass
class Token:
    """Parsed token from command line."""

    type: TokenType
    value: str | None = None


class ParseError(Exception):
    """Error during parsing of CLI arguments."""

    pass


@dataclass
class TokenizeResult:
    """Result of tokenizing CLI arguments."""

    tokens: list[Token] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    exclude_projects: list[str] = field(default_factory=list)
    exclude_groups: list[str] = field(default_factory=list)
    user: str | None = None
    my_projects: bool = False
    scope: list[str] = field(default_factory=lambda: ["blobs"])
    filename: str | None = None
    extension: str | None = None
    path: str | None = None
    archived: str = "include"
    api_url: str | None = None
    ignore_cert: bool = False
    max_requests: int | None = None
    token: str | None = None
    color: str = "auto"
    debug: bool = False
    setup: bool = False
    config_dir: str = "."


def tokenize_args(args: list[str]) -> TokenizeResult:
    """Tokenize command-line arguments into expression tokens and options.

    Separates expression tokens (-q, -a, -o, -not, !, (, ))
    from option arguments (-g, -p, -s, etc.)

    Args:
        args: Raw command-line arguments (sys.argv[1:])

    Returns:
        TokenizeResult with tokens and options

    Raises:
        ParseError: If arguments are malformed
    """
    result = TokenizeResult()
    i = 0
    pending_not = False  # Track if -not/! was just seen

    while i < len(args):
        arg = args[i]

        if arg == "-q":
            # Query predicate
            i += 1
            if i >= len(args):
                raise ParseError("-q requires a query argument")
            result.tokens.append(Token(TokenType.QUERY, args[i]))
            pending_not = False

        elif arg == "-a":
            result.tokens.append(Token(TokenType.AND))
            pending_not = False

        elif arg == "-o":
            result.tokens.append(Token(TokenType.OR))
            pending_not = False

        elif arg in ("-not", "!"):
            result.tokens.append(Token(TokenType.NOT))
            pending_not = True

        elif arg == "(":
            result.tokens.append(Token(TokenType.LPAREN))
            pending_not = False

        elif arg == ")":
            result.tokens.append(Token(TokenType.RPAREN))
            pending_not = False

        elif arg in ("-g", "--groups"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a group argument")
            # Check if this is an exclusion (preceded by -not)
            if pending_not and result.tokens and result.tokens[-1].type == TokenType.NOT:
                result.tokens.pop()  # Remove the NOT token
                result.exclude_groups.extend(args[i].split(","))
            else:
                result.groups.extend(args[i].split(","))
            pending_not = False

        elif arg in ("-p", "--projects"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a project argument")
            # Check if this is an exclusion (preceded by -not)
            if pending_not and result.tokens and result.tokens[-1].type == TokenType.NOT:
                result.tokens.pop()  # Remove the NOT token
                result.exclude_projects.extend(args[i].split(","))
            else:
                result.projects.extend(args[i].split(","))
            pending_not = False

        elif arg in ("-u", "--user"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a user argument")
            result.user = args[i]
            pending_not = False

        elif arg == "--my-projects":
            result.my_projects = True
            pending_not = False

        elif arg in ("-s", "--scope"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a scope argument")
            result.scope = [s.strip() for s in args[i].split(",")]
            pending_not = False

        elif arg in ("-f", "--filename"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a filename argument")
            result.filename = args[i]
            pending_not = False

        elif arg in ("-e", "--extension"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires an extension argument")
            result.extension = args[i]
            pending_not = False

        elif arg in ("-P", "--path"):
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a path argument")
            result.path = args[i]
            pending_not = False

        elif arg == "--archived":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires an argument")
            if args[i] not in ("include", "only", "exclude"):
                raise ParseError(
                    f"--archived must be one of: include, only, exclude"
                )
            result.archived = args[i]
            pending_not = False

        elif arg == "--api-url":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a URL argument")
            result.api_url = args[i]
            pending_not = False

        elif arg == "--ignore-cert":
            result.ignore_cert = True
            pending_not = False

        elif arg == "--max-requests":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a number argument")
            try:
                result.max_requests = int(args[i])
            except ValueError:
                raise ParseError(f"--max-requests requires an integer")
            pending_not = False

        elif arg == "--token":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a token argument")
            result.token = args[i]
            pending_not = False

        elif arg == "--color":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires an argument")
            if args[i] not in ("auto", "always", "never"):
                raise ParseError(f"--color must be one of: auto, always, never")
            result.color = args[i]
            pending_not = False

        elif arg == "--debug":
            result.debug = True
            pending_not = False

        elif arg == "--setup":
            result.setup = True
            pending_not = False

        elif arg == "--dir":
            i += 1
            if i >= len(args):
                raise ParseError(f"{arg} requires a directory argument")
            result.config_dir = args[i]
            pending_not = False

        elif arg in ("-V", "--version"):
            # Version is handled by argparse, but we need to recognize it
            raise ParseError("VERSION")

        elif arg in ("-h", "--help"):
            # Help is handled by argparse, but we need to recognize it
            raise ParseError("HELP")

        elif arg.startswith("-"):
            raise ParseError(f"Unknown option: {arg}")

        else:
            # Unknown positional argument
            raise ParseError(f"Unknown argument: {arg}")

        i += 1

    result.tokens.append(Token(TokenType.EOF))
    return result


class ExpressionParser:
    """Parser for find-like expression syntax.

    Grammar:
        expr        := term (OR term)*
        term        := factor (AND? factor)*   # AND is implicit
        factor      := NOT? primary
        primary     := QUERY | LPAREN expr RPAREN
    """

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> ExprNode | None:
        """Parse tokens into expression tree.

        Returns:
            Expression tree root, or None if no query tokens
        """
        if not self._has_query_tokens():
            return None
        expr = self._parse_expr()
        if not self._check(TokenType.EOF):
            raise ParseError(f"Unexpected token at position {self.pos}")
        return expr

    def _has_query_tokens(self) -> bool:
        """Check if there are any QUERY tokens."""
        return any(t.type == TokenType.QUERY for t in self.tokens)

    def _current(self) -> Token:
        """Get current token."""
        if self.pos >= len(self.tokens):
            return Token(TokenType.EOF)
        return self.tokens[self.pos]

    def _previous(self) -> Token:
        """Get previous token."""
        return self.tokens[self.pos - 1]

    def _check(self, token_type: TokenType) -> bool:
        """Check if current token is of given type."""
        return self._current().type == token_type

    def _match(self, token_type: TokenType) -> bool:
        """Check and consume token if it matches."""
        if self._check(token_type):
            self.pos += 1
            return True
        return False

    def _advance(self) -> Token:
        """Consume and return current token."""
        token = self._current()
        self.pos += 1
        return token

    def _expect(self, token_type: TokenType) -> Token:
        """Expect and consume a specific token type."""
        if not self._check(token_type):
            raise ParseError(
                f"Expected {token_type.name} at position {self.pos}, "
                f"got {self._current().type.name}"
            )
        return self._advance()

    def _parse_expr(self) -> ExprNode:
        """Parse OR expression (lowest precedence)."""
        left = self._parse_term()
        while self._match(TokenType.OR):
            right = self._parse_term()
            left = OrNode(left, right)
        return left

    def _parse_term(self) -> ExprNode:
        """Parse AND expression (implicit or explicit)."""
        left = self._parse_factor()
        # Continue while we see AND, QUERY, NOT, or LPAREN (implicit AND)
        while (
            self._check(TokenType.AND)
            or self._check(TokenType.QUERY)
            or self._check(TokenType.NOT)
            or self._check(TokenType.LPAREN)
        ):
            if self._check(TokenType.AND):
                self._advance()  # consume explicit AND
            right = self._parse_factor()
            left = AndNode(left, right)
        return left

    def _parse_factor(self) -> ExprNode:
        """Parse NOT expression."""
        if self._match(TokenType.NOT):
            return NotNode(self._parse_primary())
        return self._parse_primary()

    def _parse_primary(self) -> ExprNode:
        """Parse primary expression (query or grouped)."""
        if self._match(TokenType.LPAREN):
            expr = self._parse_expr()
            self._expect(TokenType.RPAREN)
            return expr

        if self._match(TokenType.QUERY):
            value = self._previous().value
            if value is None:
                raise ParseError("QUERY token missing value")
            return QueryNode(value)

        raise ParseError(
            f"Expected query or '(' at position {self.pos}, "
            f"got {self._current().type.name}"
        )


def parse_command(args: list[str]) -> ParsedCommand:
    """Parse command line arguments into ParsedCommand.

    Args:
        args: Raw command-line arguments (sys.argv[1:])

    Returns:
        ParsedCommand with all parsed options and expression tree

    Raises:
        ParseError: If arguments are malformed
    """
    result = tokenize_args(args)

    # Parse expression tree from tokens
    parser = ExpressionParser(result.tokens)
    expression = parser.parse()

    return ParsedCommand(
        groups=result.groups,
        projects=result.projects,
        exclude_projects=result.exclude_projects,
        exclude_groups=result.exclude_groups,
        user=result.user,
        my_projects=result.my_projects,
        query_expression=expression,
        scope=result.scope,
        filename=result.filename,
        extension=result.extension,
        path=result.path,
        archived=result.archived,
        api_url=result.api_url,
        ignore_cert=result.ignore_cert,
        max_requests=result.max_requests,
        token=result.token,
        color=result.color,
        debug=result.debug,
        setup=result.setup,
        config_dir=result.config_dir,
    )
