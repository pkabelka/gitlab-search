"""Tests for the find-like expression parser."""

import unittest

from gitlab_search.expression import AndNode, NotNode, OrNode, QueryNode
from gitlab_search.parser import (
    ExpressionParser,
    ParseError,
    Token,
    TokenType,
    parse_command,
    tokenize_args,
)


class TestTokenizeArgs(unittest.TestCase):
    """Tests for tokenize_args function."""

    def test_single_query(self):
        """Test tokenizing a single query."""
        result = tokenize_args(["-p", "proj", "-q", "foo"])

        self.assertEqual(result.projects, ["proj"])
        self.assertEqual(len(result.tokens), 2)  # QUERY + EOF
        self.assertEqual(result.tokens[0].type, TokenType.QUERY)
        self.assertEqual(result.tokens[0].value, "foo")

    def test_multiple_queries_implicit_and(self):
        """Test multiple queries create implicit AND."""
        result = tokenize_args(["-p", "proj", "-q", "a", "-q", "b"])

        self.assertEqual(len(result.tokens), 3)  # QUERY, QUERY, EOF
        self.assertEqual(result.tokens[0].value, "a")
        self.assertEqual(result.tokens[1].value, "b")

    def test_explicit_and(self):
        """Test explicit AND operator."""
        result = tokenize_args(["-p", "proj", "-q", "a", "-a", "-q", "b"])

        self.assertEqual(len(result.tokens), 4)  # QUERY, AND, QUERY, EOF
        self.assertEqual(result.tokens[0].type, TokenType.QUERY)
        self.assertEqual(result.tokens[1].type, TokenType.AND)
        self.assertEqual(result.tokens[2].type, TokenType.QUERY)

    def test_or_operator(self):
        """Test OR operator."""
        result = tokenize_args(["-p", "proj", "-q", "a", "-o", "-q", "b"])

        self.assertEqual(len(result.tokens), 4)  # QUERY, OR, QUERY, EOF
        self.assertEqual(result.tokens[1].type, TokenType.OR)

    def test_not_operator(self):
        """Test NOT operator."""
        result = tokenize_args(["-p", "proj", "-not", "-q", "a"])

        self.assertEqual(len(result.tokens), 3)  # NOT, QUERY, EOF
        self.assertEqual(result.tokens[0].type, TokenType.NOT)
        self.assertEqual(result.tokens[1].type, TokenType.QUERY)

    def test_bang_not_operator(self):
        """Test ! as NOT operator."""
        result = tokenize_args(["-p", "proj", "!", "-q", "a"])

        self.assertEqual(result.tokens[0].type, TokenType.NOT)

    def test_parentheses(self):
        """Test parentheses grouping."""
        result = tokenize_args(["-p", "proj", "(", "-q", "a", "-o", "-q", "b", ")"])

        self.assertEqual(result.tokens[0].type, TokenType.LPAREN)
        self.assertEqual(result.tokens[4].type, TokenType.RPAREN)

    def test_project_exclusion(self):
        """Test project exclusion with -not -p."""
        result = tokenize_args(["-g", "grp", "-not", "-p", "proj", "-q", "x"])

        self.assertEqual(result.groups, ["grp"])
        self.assertEqual(result.exclude_projects, ["proj"])
        # NOT token should be consumed, not in expression
        self.assertTrue(
            all(t.type != TokenType.NOT or t.type == TokenType.EOF for t in result.tokens[:-1])
        )

    def test_group_exclusion(self):
        """Test group exclusion with ! -g."""
        result = tokenize_args(["-g", "grp1", "!", "-g", "grp2", "-q", "x"])

        self.assertEqual(result.groups, ["grp1"])
        self.assertEqual(result.exclude_groups, ["grp2"])

    def test_combined_groups_and_projects(self):
        """Test combining -g and -p."""
        result = tokenize_args(["-g", "grp", "-p", "proj", "-q", "x"])

        self.assertEqual(result.groups, ["grp"])
        self.assertEqual(result.projects, ["proj"])

    def test_comma_separated_projects(self):
        """Test comma-separated project list."""
        result = tokenize_args(["-p", "proj1,proj2,proj3", "-q", "x"])

        self.assertEqual(result.projects, ["proj1", "proj2", "proj3"])

    def test_connection_options(self):
        """Test connection options parsing."""
        result = tokenize_args([
            "-p", "proj",
            "--api-url", "https://example.com/api/v4",
            "--token", "secret",
            "--max-requests", "10",
            "--ignore-cert",
            "--debug",
            "-q", "x"
        ])

        self.assertEqual(result.api_url, "https://example.com/api/v4")
        self.assertEqual(result.token, "secret")
        self.assertEqual(result.max_requests, 10)
        self.assertTrue(result.ignore_cert)
        self.assertTrue(result.debug)

    def test_search_filters(self):
        """Test search filter options."""
        result = tokenize_args([
            "-p", "proj",
            "-f", "*.py",
            "-e", "py",
            "-P", "src/",
            "-q", "x"
        ])

        self.assertEqual(result.filename, "*.py")
        self.assertEqual(result.extension, "py")
        self.assertEqual(result.path, "src/")

    def test_archived_option(self):
        """Test --archived option."""
        result = tokenize_args(["-p", "proj", "--archived", "exclude", "-q", "x"])

        self.assertEqual(result.archived, "exclude")

    def test_recursive_short_flag(self):
        """Test -r recursive flag in tokenizer."""
        result = tokenize_args(["-g", "grp", "-r", "-q", "x"])

        self.assertTrue(result.recursive)

    def test_recursive_long_flag(self):
        """Test --recursive flag in tokenizer."""
        result = tokenize_args(["-g", "grp", "--recursive", "-q", "x"])

        self.assertTrue(result.recursive)

    def test_recursive_default_false(self):
        """Test recursive is False by default in tokenizer."""
        result = tokenize_args(["-g", "grp", "-q", "x"])

        self.assertFalse(result.recursive)

    def test_missing_query_argument(self):
        """Test error on missing -q argument."""
        with self.assertRaises(ParseError) as ctx:
            tokenize_args(["-p", "proj", "-q"])
        self.assertIn("-q requires a query argument", str(ctx.exception))

    def test_unknown_option(self):
        """Test error on unknown option."""
        with self.assertRaises(ParseError) as ctx:
            tokenize_args(["-p", "proj", "--unknown", "-q", "x"])
        self.assertIn("Unknown option", str(ctx.exception))


class TestExpressionParser(unittest.TestCase):
    """Tests for ExpressionParser class."""

    def test_single_query(self):
        """Test parsing single query."""
        tokens = [Token(TokenType.QUERY, "foo"), Token(TokenType.EOF)]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, QueryNode)
        self.assertEqual(result.query, "foo")

    def test_implicit_and(self):
        """Test implicit AND between queries."""
        tokens = [
            Token(TokenType.QUERY, "a"),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, AndNode)
        self.assertIsInstance(result.left, QueryNode)
        self.assertIsInstance(result.right, QueryNode)
        self.assertEqual(result.left.query, "a")
        self.assertEqual(result.right.query, "b")

    def test_explicit_and(self):
        """Test explicit AND operator."""
        tokens = [
            Token(TokenType.QUERY, "a"),
            Token(TokenType.AND),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, AndNode)

    def test_or_operator(self):
        """Test OR operator."""
        tokens = [
            Token(TokenType.QUERY, "a"),
            Token(TokenType.OR),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, OrNode)
        self.assertEqual(result.left.query, "a")
        self.assertEqual(result.right.query, "b")

    def test_not_operator(self):
        """Test NOT operator."""
        tokens = [
            Token(TokenType.NOT),
            Token(TokenType.QUERY, "a"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, NotNode)
        self.assertIsInstance(result.child, QueryNode)
        self.assertEqual(result.child.query, "a")

    def test_parentheses_grouping(self):
        """Test parentheses change precedence."""
        # (a OR b) AND c
        tokens = [
            Token(TokenType.LPAREN),
            Token(TokenType.QUERY, "a"),
            Token(TokenType.OR),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.RPAREN),
            Token(TokenType.QUERY, "c"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        # Should be AND(OR(a, b), c)
        self.assertIsInstance(result, AndNode)
        self.assertIsInstance(result.left, OrNode)
        self.assertIsInstance(result.right, QueryNode)
        self.assertEqual(result.right.query, "c")

    def test_or_lower_precedence_than_and(self):
        """Test OR has lower precedence than AND."""
        # a AND b OR c should be (a AND b) OR c
        tokens = [
            Token(TokenType.QUERY, "a"),
            Token(TokenType.AND),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.OR),
            Token(TokenType.QUERY, "c"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, OrNode)
        self.assertIsInstance(result.left, AndNode)
        self.assertIsInstance(result.right, QueryNode)

    def test_multiple_or(self):
        """Test multiple OR operators."""
        tokens = [
            Token(TokenType.QUERY, "a"),
            Token(TokenType.OR),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.OR),
            Token(TokenType.QUERY, "c"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        # Should be OR(OR(a, b), c) - left associative
        self.assertIsInstance(result, OrNode)
        self.assertIsInstance(result.left, OrNode)

    def test_not_with_and(self):
        """Test NOT binds tighter than AND."""
        # NOT a AND b should be (NOT a) AND b
        tokens = [
            Token(TokenType.NOT),
            Token(TokenType.QUERY, "a"),
            Token(TokenType.AND),
            Token(TokenType.QUERY, "b"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsInstance(result, AndNode)
        self.assertIsInstance(result.left, NotNode)
        self.assertIsInstance(result.right, QueryNode)

    def test_empty_tokens(self):
        """Test parsing with no query tokens."""
        tokens = [Token(TokenType.EOF)]
        parser = ExpressionParser(tokens)

        result = parser.parse()

        self.assertIsNone(result)

    def test_unbalanced_parentheses(self):
        """Test error on unbalanced parentheses."""
        tokens = [
            Token(TokenType.LPAREN),
            Token(TokenType.QUERY, "a"),
            Token(TokenType.EOF)
        ]
        parser = ExpressionParser(tokens)

        with self.assertRaises(ParseError) as ctx:
            parser.parse()
        self.assertIn("Expected RPAREN", str(ctx.exception))


class TestParseCommand(unittest.TestCase):
    """Tests for parse_command function."""

    def test_simple_search(self):
        """Test simple search command."""
        parsed = parse_command(["-p", "myproject", "-q", "searchterm"])

        self.assertEqual(parsed.projects, ["myproject"])
        self.assertIsNotNone(parsed.query_expression)
        self.assertIsInstance(parsed.query_expression, QueryNode)
        self.assertEqual(parsed.query_expression.query, "searchterm")

    def test_and_search(self):
        """Test AND search command."""
        parsed = parse_command(["-p", "proj", "-q", "a", "-q", "b"])

        self.assertIsInstance(parsed.query_expression, AndNode)
        queries = parsed.get_all_queries()
        self.assertIn("a", queries)
        self.assertIn("b", queries)

    def test_or_search(self):
        """Test OR search command."""
        parsed = parse_command(["-p", "proj", "-q", "a", "-o", "-q", "b"])

        self.assertIsInstance(parsed.query_expression, OrNode)

    def test_exclude_project(self):
        """Test project exclusion."""
        parsed = parse_command(["-g", "mygroup", "!", "-p", "excluded", "-q", "x"])

        self.assertEqual(parsed.groups, ["mygroup"])
        self.assertEqual(parsed.exclude_projects, ["excluded"])

    def test_get_all_queries(self):
        """Test getting all unique queries."""
        parsed = parse_command(["-p", "proj", "-q", "a", "-q", "b", "-o", "-q", "a"])

        queries = parsed.get_all_queries()
        # Should have unique queries, order preserved
        self.assertEqual(queries, ["a", "b"])

    def test_scope_option(self):
        """Test scope option."""
        parsed = parse_command(["-p", "proj", "-s", "issues,merge_requests", "-q", "x"])

        self.assertEqual(parsed.scope, ["issues", "merge_requests"])

    def test_setup_mode(self):
        """Test setup mode."""
        parsed = parse_command(["--setup", "--token", "mytoken"])

        self.assertTrue(parsed.setup)
        self.assertEqual(parsed.token, "mytoken")

    def test_recursive_short_flag(self):
        """Test -r recursive flag."""
        parsed = parse_command(["-g", "mygroup", "-r", "-q", "term"])

        self.assertEqual(parsed.groups, ["mygroup"])
        self.assertTrue(parsed.recursive)

    def test_recursive_long_flag(self):
        """Test --recursive flag."""
        parsed = parse_command(["-g", "mygroup", "--recursive", "-q", "term"])

        self.assertEqual(parsed.groups, ["mygroup"])
        self.assertTrue(parsed.recursive)

    def test_recursive_default_false(self):
        """Test recursive is False by default."""
        parsed = parse_command(["-g", "mygroup", "-q", "term"])

        self.assertFalse(parsed.recursive)

    def test_recursive_with_multiple_groups(self):
        """Test recursive with multiple groups."""
        parsed = parse_command(["-g", "grp1,grp2", "-r", "-q", "term"])

        self.assertEqual(parsed.groups, ["grp1", "grp2"])
        self.assertTrue(parsed.recursive)

    def test_extension_exclusion(self):
        """Test extension exclusion with ! -e."""
        result = tokenize_args(["-p", "proj", "-q", "x", "!", "-e", "md"])

        self.assertEqual(result.exclude_extensions, ["md"])
        # NOT token should be consumed
        self.assertTrue(
            all(t.type != TokenType.NOT for t in result.tokens[:-1])
        )

    def test_filename_exclusion(self):
        """Test filename exclusion with -not -f."""
        result = tokenize_args(["-p", "proj", "-q", "x", "-not", "-f", "*.test.js"])

        self.assertEqual(result.exclude_filenames, ["*.test.js"])
        self.assertTrue(
            all(t.type != TokenType.NOT for t in result.tokens[:-1])
        )

    def test_path_exclusion(self):
        """Test path exclusion with ! -P."""
        result = tokenize_args(["-p", "proj", "-q", "x", "!", "-P", "*vendor*"])

        self.assertEqual(result.exclude_paths, ["*vendor*"])
        self.assertTrue(
            all(t.type != TokenType.NOT for t in result.tokens[:-1])
        )

    def test_multiple_file_exclusions(self):
        """Test multiple file exclusions."""
        result = tokenize_args([
            "-p", "proj", "-q", "x",
            "!", "-e", "md",
            "!", "-e", "txt",
            "!", "-f", "*.test.js"
        ])

        self.assertEqual(result.exclude_extensions, ["md", "txt"])
        self.assertEqual(result.exclude_filenames, ["*.test.js"])

    def test_inclusion_and_exclusion_combined(self):
        """Test combining inclusion and exclusion filters."""
        result = tokenize_args([
            "-p", "proj", "-q", "x",
            "-e", "py",           # Include only .py files
            "!", "-f", "test_*"   # But exclude test files
        ])

        self.assertEqual(result.extension, "py")
        self.assertEqual(result.exclude_filenames, ["test_*"])

    def test_exclusion_parsed_command(self):
        """Test file exclusions in ParsedCommand."""
        parsed = parse_command([
            "-p", "proj", "-q", "x",
            "!", "-e", "md",
            "!", "-f", "*.test.*",
            "!", "-P", "*vendor*"
        ])

        self.assertEqual(parsed.exclude_extensions, ["md"])
        self.assertEqual(parsed.exclude_filenames, ["*.test.*"])
        self.assertEqual(parsed.exclude_paths, ["*vendor*"])


if __name__ == "__main__":
    unittest.main()
