"""Tests for expression AST nodes."""

import unittest

from gitlab_search.expression import (
    AndNode,
    NotNode,
    OrNode,
    QueryNode,
    set_universe,
)


class TestQueryNode(unittest.TestCase):
    """Tests for QueryNode."""

    def test_evaluate_with_matching_results(self):
        """Test evaluating query with matching results."""
        node = QueryNode("foo")
        results = {"foo": {1, 2, 3}, "bar": {4, 5}}

        self.assertEqual(node.evaluate(results), {1, 2, 3})

    def test_evaluate_with_no_matching_results(self):
        """Test evaluating query with no matching results."""
        node = QueryNode("baz")
        results = {"foo": {1, 2, 3}, "bar": {4, 5}}

        self.assertEqual(node.evaluate(results), set())

    def test_get_queries(self):
        """Test getting queries from node."""
        node = QueryNode("foo")

        self.assertEqual(node.get_queries(), ["foo"])


class TestAndNode(unittest.TestCase):
    """Tests for AndNode."""

    def test_evaluate_intersection(self):
        """Test AND evaluates to intersection."""
        left = QueryNode("a")
        right = QueryNode("b")
        node = AndNode(left, right)
        results = {"a": {1, 2, 3}, "b": {2, 3, 4}}

        self.assertEqual(node.evaluate(results), {2, 3})

    def test_evaluate_empty_intersection(self):
        """Test AND with no overlap."""
        left = QueryNode("a")
        right = QueryNode("b")
        node = AndNode(left, right)
        results = {"a": {1, 2}, "b": {3, 4}}

        self.assertEqual(node.evaluate(results), set())

    def test_get_queries(self):
        """Test getting queries from AND node."""
        node = AndNode(QueryNode("a"), QueryNode("b"))

        self.assertEqual(set(node.get_queries()), {"a", "b"})


class TestOrNode(unittest.TestCase):
    """Tests for OrNode."""

    def test_evaluate_union(self):
        """Test OR evaluates to union."""
        left = QueryNode("a")
        right = QueryNode("b")
        node = OrNode(left, right)
        results = {"a": {1, 2, 3}, "b": {2, 3, 4}}

        self.assertEqual(node.evaluate(results), {1, 2, 3, 4})

    def test_evaluate_one_empty(self):
        """Test OR with one empty set."""
        left = QueryNode("a")
        right = QueryNode("b")
        node = OrNode(left, right)
        results = {"a": {1, 2, 3}, "b": set()}

        self.assertEqual(node.evaluate(results), {1, 2, 3})

    def test_get_queries(self):
        """Test getting queries from OR node."""
        node = OrNode(QueryNode("a"), QueryNode("b"))

        self.assertEqual(set(node.get_queries()), {"a", "b"})


class TestNotNode(unittest.TestCase):
    """Tests for NotNode."""

    def test_evaluate_complement(self):
        """Test NOT evaluates to complement."""
        child = QueryNode("a")
        node = NotNode(child, universe={1, 2, 3, 4, 5})
        results = {"a": {1, 2, 3}}

        self.assertEqual(node.evaluate(results), {4, 5})

    def test_evaluate_empty_complement(self):
        """Test NOT when child matches everything."""
        child = QueryNode("a")
        node = NotNode(child, universe={1, 2, 3})
        results = {"a": {1, 2, 3}}

        self.assertEqual(node.evaluate(results), set())

    def test_evaluate_full_complement(self):
        """Test NOT when child matches nothing."""
        child = QueryNode("a")
        node = NotNode(child, universe={1, 2, 3})
        results = {"a": set()}

        self.assertEqual(node.evaluate(results), {1, 2, 3})

    def test_evaluate_without_universe_raises(self):
        """Test NOT without universe raises error."""
        child = QueryNode("a")
        node = NotNode(child)  # No universe set
        results = {"a": {1, 2, 3}}

        with self.assertRaises(ValueError) as ctx:
            node.evaluate(results)
        self.assertIn("universe", str(ctx.exception))

    def test_get_queries(self):
        """Test getting queries from NOT node."""
        node = NotNode(QueryNode("a"))

        self.assertEqual(node.get_queries(), ["a"])


class TestSetUniverse(unittest.TestCase):
    """Tests for set_universe function."""

    def test_set_on_not_node(self):
        """Test setting universe on NOT node."""
        node = NotNode(QueryNode("a"))
        set_universe(node, {1, 2, 3})

        self.assertEqual(node.universe, {1, 2, 3})

    def test_set_on_nested_not(self):
        """Test setting universe on nested NOT nodes."""
        inner = NotNode(QueryNode("a"))
        outer = NotNode(inner)
        set_universe(outer, {1, 2, 3, 4, 5})

        self.assertEqual(outer.universe, {1, 2, 3, 4, 5})
        self.assertEqual(inner.universe, {1, 2, 3, 4, 5})

    def test_set_on_and_with_not(self):
        """Test setting universe on AND containing NOT."""
        not_node = NotNode(QueryNode("a"))
        and_node = AndNode(not_node, QueryNode("b"))
        set_universe(and_node, {1, 2, 3})

        self.assertEqual(not_node.universe, {1, 2, 3})

    def test_set_on_or_with_not(self):
        """Test setting universe on OR containing NOT."""
        not_node = NotNode(QueryNode("a"))
        or_node = OrNode(QueryNode("b"), not_node)
        set_universe(or_node, {1, 2, 3})

        self.assertEqual(not_node.universe, {1, 2, 3})

    def test_no_effect_on_query_node(self):
        """Test set_universe does nothing on QueryNode."""
        node = QueryNode("a")
        set_universe(node, {1, 2, 3})
        # No error, just does nothing


class TestComplexExpressions(unittest.TestCase):
    """Tests for complex expression evaluation."""

    def test_and_or_combination(self):
        """Test (a AND b) OR c."""
        and_node = AndNode(QueryNode("a"), QueryNode("b"))
        or_node = OrNode(and_node, QueryNode("c"))
        results = {
            "a": {1, 2, 3},
            "b": {2, 3, 4},
            "c": {5, 6}
        }

        # a AND b = {2, 3}
        # (a AND b) OR c = {2, 3, 5, 6}
        self.assertEqual(or_node.evaluate(results), {2, 3, 5, 6})

    def test_or_and_combination(self):
        """Test a OR (b AND c)."""
        and_node = AndNode(QueryNode("b"), QueryNode("c"))
        or_node = OrNode(QueryNode("a"), and_node)
        results = {
            "a": {1, 2},
            "b": {3, 4, 5},
            "c": {4, 5, 6}
        }

        # b AND c = {4, 5}
        # a OR (b AND c) = {1, 2, 4, 5}
        self.assertEqual(or_node.evaluate(results), {1, 2, 4, 5})

    def test_not_with_and(self):
        """Test NOT a AND b."""
        not_node = NotNode(QueryNode("a"), universe={1, 2, 3, 4, 5})
        and_node = AndNode(not_node, QueryNode("b"))
        results = {
            "a": {1, 2},
            "b": {2, 3, 4}
        }

        # NOT a = {3, 4, 5}
        # (NOT a) AND b = {3, 4}
        self.assertEqual(and_node.evaluate(results), {3, 4})

    def test_not_with_or(self):
        """Test NOT a OR b."""
        not_node = NotNode(QueryNode("a"), universe={1, 2, 3, 4, 5})
        or_node = OrNode(not_node, QueryNode("b"))
        results = {
            "a": {1, 2},
            "b": {2, 3}
        }

        # NOT a = {3, 4, 5}
        # (NOT a) OR b = {2, 3, 4, 5}
        self.assertEqual(or_node.evaluate(results), {2, 3, 4, 5})

    def test_deeply_nested(self):
        """Test deeply nested expression."""
        # ((a AND b) OR (c AND d)) AND e
        ab = AndNode(QueryNode("a"), QueryNode("b"))
        cd = AndNode(QueryNode("c"), QueryNode("d"))
        ab_or_cd = OrNode(ab, cd)
        final = AndNode(ab_or_cd, QueryNode("e"))

        results = {
            "a": {1, 2, 3},
            "b": {2, 3, 4},
            "c": {5, 6, 7},
            "d": {6, 7, 8},
            "e": {2, 6, 9}
        }

        # a AND b = {2, 3}
        # c AND d = {6, 7}
        # (a AND b) OR (c AND d) = {2, 3, 6, 7}
        # ((a AND b) OR (c AND d)) AND e = {2, 6}
        self.assertEqual(final.evaluate(results), {2, 6})


if __name__ == "__main__":
    unittest.main()
