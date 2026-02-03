"""Expression AST for find-like query syntax."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ExprNode(ABC):
    """Base class for expression tree nodes."""

    @abstractmethod
    def evaluate(self, results: dict[str, set[Any]]) -> set[Any]:
        """Evaluate this node against search results.

        Args:
            results: Dict mapping query string to set of matching result IDs

        Returns:
            Set of result IDs that match this expression
        """
        pass

    @abstractmethod
    def get_queries(self) -> list[str]:
        """Get all query strings in this expression tree.

        Returns:
            List of unique query strings
        """
        pass


@dataclass
class QueryNode(ExprNode):
    """Leaf node representing a single search query (-q "term")."""

    query: str

    def evaluate(self, results: dict[str, set[Any]]) -> set[Any]:
        return results.get(self.query, set())

    def get_queries(self) -> list[str]:
        return [self.query]


@dataclass
class AndNode(ExprNode):
    """Binary AND node - intersection of children."""

    left: ExprNode
    right: ExprNode

    def evaluate(self, results: dict[str, set[Any]]) -> set[Any]:
        return self.left.evaluate(results) & self.right.evaluate(results)

    def get_queries(self) -> list[str]:
        return self.left.get_queries() + self.right.get_queries()


@dataclass
class OrNode(ExprNode):
    """Binary OR node - union of children."""

    left: ExprNode
    right: ExprNode

    def evaluate(self, results: dict[str, set[Any]]) -> set[Any]:
        return self.left.evaluate(results) | self.right.evaluate(results)

    def get_queries(self) -> list[str]:
        return self.left.get_queries() + self.right.get_queries()


@dataclass
class NotNode(ExprNode):
    """Unary NOT node - complement of child.

    Requires universe set to be set before evaluation.
    """

    child: ExprNode
    universe: set[Any] = field(default_factory=set)

    def evaluate(self, results: dict[str, set[Any]]) -> set[Any]:
        if not self.universe:
            raise ValueError("NOT node requires universe set for complement")
        return self.universe - self.child.evaluate(results)

    def get_queries(self) -> list[str]:
        return self.child.get_queries()


def set_universe(node: ExprNode, universe: set[Any]) -> None:
    """Recursively set universe on all NOT nodes in the tree.

    Args:
        node: Root of expression tree
        universe: Universe set (all possible result IDs)
    """
    if isinstance(node, NotNode):
        node.universe = universe
        set_universe(node.child, universe)
    elif isinstance(node, (AndNode, OrNode)):
        set_universe(node.left, universe)
        set_universe(node.right, universe)


# Scope modifiers for project/group exclusions


@dataclass
class ScopeModifier(ABC):
    """Base class for scope modifiers."""

    pass


@dataclass
class ExcludeProject(ScopeModifier):
    """Exclude specific project(s) from search scope."""

    projects: list[str]


@dataclass
class ExcludeGroup(ScopeModifier):
    """Exclude specific group(s) from search scope."""

    groups: list[str]


@dataclass
class ParsedCommand:
    """Complete parsed command from CLI arguments."""

    # Scope definition (can be combined)
    groups: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    user: str | None = None
    my_projects: bool = False

    # Scope modifiers (exclusions)
    exclude_projects: list[str] = field(default_factory=list)
    exclude_groups: list[str] = field(default_factory=list)

    # Query expression tree
    query_expression: ExprNode | None = None

    # Other options
    scope: list[str] = field(default_factory=lambda: ["blobs"])
    filename: str | None = None
    extension: str | None = None
    path: str | None = None
    archived: str = "include"
    recursive: bool = False

    # Connection options
    api_url: str | None = None
    ignore_cert: bool = False
    max_requests: int | None = None
    token: str | None = None
    token_file: str | None = None
    color: str = "auto"
    debug: bool = False

    # Setup mode
    setup: bool = False
    config_file: str | None = None

    def get_all_queries(self) -> list[str]:
        """Get all unique query strings from the expression tree.

        Returns:
            List of unique query strings
        """
        if self.query_expression is None:
            return []
        queries = self.query_expression.get_queries()
        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        return unique
