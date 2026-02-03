"""Tests for the executor module."""

import unittest

from gitlab_search.executor import matches_exclusion


class TestMatchesExclusion(unittest.TestCase):
    """Tests for matches_exclusion function."""

    def test_exclude_by_extension(self):
        """Test excluding by extension."""
        self.assertTrue(
            matches_exclusion("readme.md", None, [], ["md"], [])
        )
        self.assertFalse(
            matches_exclusion("script.py", None, [], ["md"], [])
        )

    def test_exclude_by_extension_with_dot(self):
        """Test extension with leading dot."""
        self.assertTrue(
            matches_exclusion("readme.md", None, [], [".md"], [])
        )

    def test_exclude_by_filename_pattern(self):
        """Test excluding by filename pattern."""
        self.assertTrue(
            matches_exclusion("app.test.js", None, ["*.test.js"], [], [])
        )
        self.assertFalse(
            matches_exclusion("app.js", None, ["*.test.js"], [], [])
        )

    def test_exclude_by_path_pattern(self):
        """Test excluding by path pattern."""
        self.assertTrue(
            matches_exclusion("file.py", "vendor/lib/file.py", [], [], ["*vendor*"])
        )
        self.assertFalse(
            matches_exclusion("file.py", "src/lib/file.py", [], [], ["*vendor*"])
        )

    def test_multiple_extension_exclusions(self):
        """Test multiple extension exclusion patterns."""
        self.assertTrue(
            matches_exclusion("readme.md", None, [], ["md", "txt"], [])
        )
        self.assertTrue(
            matches_exclusion("notes.txt", None, [], ["md", "txt"], [])
        )
        self.assertFalse(
            matches_exclusion("script.py", None, [], ["md", "txt"], [])
        )

    def test_multiple_filename_exclusions(self):
        """Test multiple filename exclusion patterns."""
        self.assertTrue(
            matches_exclusion("test_foo.py", None, ["test_*", "*_test.py"], [], [])
        )
        self.assertTrue(
            matches_exclusion("foo_test.py", None, ["test_*", "*_test.py"], [], [])
        )
        self.assertFalse(
            matches_exclusion("foo.py", None, ["test_*", "*_test.py"], [], [])
        )

    def test_no_exclusions(self):
        """Test with no exclusion patterns."""
        self.assertFalse(
            matches_exclusion("anything.py", "path/to/anything.py", [], [], [])
        )

    def test_path_fallback_to_filename(self):
        """Test path matching uses filename when path is None."""
        self.assertTrue(
            matches_exclusion("vendor_utils.py", None, [], [], ["*vendor*"])
        )

    def test_combined_exclusions(self):
        """Test combining different exclusion types."""
        # File matches extension exclusion
        self.assertTrue(
            matches_exclusion("readme.md", "docs/readme.md", ["*.test.*"], ["md"], ["*vendor*"])
        )
        # File matches filename exclusion
        self.assertTrue(
            matches_exclusion("app.test.js", "src/app.test.js", ["*.test.*"], ["md"], ["*vendor*"])
        )
        # File matches path exclusion
        self.assertTrue(
            matches_exclusion("utils.py", "vendor/utils.py", ["*.test.*"], ["md"], ["*vendor*"])
        )
        # File matches none
        self.assertFalse(
            matches_exclusion("app.py", "src/app.py", ["*.test.*"], ["md"], ["*vendor*"])
        )


if __name__ == "__main__":
    unittest.main()
