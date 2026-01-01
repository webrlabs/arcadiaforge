"""
Tests for Puppeteer Browser Automation Helpers
==============================================

Tests for arcadiaforge/puppeteer_helpers.py
"""

import pytest
import json

from arcadiaforge.puppeteer_helpers import (
    browser_click_text,
    browser_find_elements,
    browser_wait_and_click,
    browser_fill_by_label,
    browser_get_text,
    browser_table_data,
    _escape_js_string,
)


class TestEscapeJsString:
    """Tests for JavaScript string escaping."""

    def test_escape_quotes(self):
        """Test escaping single and double quotes."""
        assert "\\'" in _escape_js_string("it's")
        assert '\\"' in _escape_js_string('say "hello"')

    def test_escape_backslash(self):
        """Test escaping backslashes."""
        result = _escape_js_string("path\\to\\file")
        assert "\\\\" in result

    def test_escape_newlines(self):
        """Test escaping newlines and tabs."""
        result = _escape_js_string("line1\nline2\ttab")
        assert "\\n" in result
        assert "\\t" in result

    def test_plain_text_unchanged(self):
        """Test that plain text passes through."""
        text = "hello world"
        assert _escape_js_string(text) == text


class TestBrowserClickText:
    """Tests for browser_click_text()"""

    def test_returns_valid_script(self):
        """Test that a valid JavaScript is returned."""
        result = browser_click_text("Delete")

        assert "script" in result
        assert "description" in result
        assert isinstance(result["script"], str)

    def test_script_contains_text(self):
        """Test that the script searches for the specified text."""
        result = browser_click_text("Submit Form")

        assert "Submit Form" in result["script"]

    def test_script_is_valid_javascript(self):
        """Test that the script is syntactically valid JavaScript (basic check)."""
        result = browser_click_text("Click Me")
        script = result["script"]

        # Should be an IIFE
        assert script.strip().startswith("(")
        assert script.strip().endswith(";")

        # Should contain key operations
        assert "querySelectorAll" in script
        assert "textContent" in script
        assert "click()" in script

    def test_custom_element_type(self):
        """Test with custom element type selector."""
        result = browser_click_text("Link", element_type="a.nav-link")

        assert "a.nav-link" in result["script"]

    def test_escapes_special_characters(self):
        """Test that special characters in text are escaped."""
        result = browser_click_text("It's a \"test\"")

        # Should not break the JavaScript
        assert "script" in result
        assert "\\'" in result["script"]


class TestBrowserFindElements:
    """Tests for browser_find_elements()"""

    def test_basic_selector(self):
        """Test finding elements by selector."""
        result = browser_find_elements("button")

        assert "script" in result
        assert "querySelectorAll" in result["script"]
        assert "button" in result["script"]

    def test_with_text_filter(self):
        """Test filtering by text content."""
        result = browser_find_elements("button", text_filter="Submit")

        assert "Submit" in result["script"]
        assert "filter" in result["script"]

    def test_limit_parameter(self):
        """Test that limit is included in script."""
        result = browser_find_elements("div", limit=5)

        assert "5" in result["script"]
        assert "slice" in result["script"]

    def test_returns_element_info(self):
        """Test that script returns useful element info."""
        result = browser_find_elements("a")
        script = result["script"]

        # Should extract useful properties
        assert "tagName" in script
        assert "textContent" in script
        assert "className" in script or "classes" in script


class TestBrowserWaitAndClick:
    """Tests for browser_wait_and_click()"""

    def test_returns_async_script(self):
        """Test that an async script is returned."""
        result = browser_wait_and_click("Loading Complete")

        assert "script" in result
        assert "async" in result["script"]

    def test_includes_timeout(self):
        """Test that timeout is included."""
        result = browser_wait_and_click("Button", timeout_ms=10000)

        assert "10000" in result["script"]

    def test_includes_retry_loop(self):
        """Test that script includes retry logic."""
        result = browser_wait_and_click("Dynamic Button")
        script = result["script"]

        assert "while" in script
        assert "setTimeout" in script or "Date.now()" in script


class TestBrowserFillByLabel:
    """Tests for browser_fill_by_label()"""

    def test_basic_fill(self):
        """Test filling an input by label."""
        result = browser_fill_by_label("Username", "testuser")

        assert "script" in result
        assert "Username" in result["script"]
        assert "testuser" in result["script"]

    def test_triggers_events(self):
        """Test that script triggers input/change events."""
        result = browser_fill_by_label("Email", "test@example.com")
        script = result["script"]

        assert "dispatchEvent" in script
        assert "input" in script.lower() or "change" in script.lower()

    def test_handles_for_attribute(self):
        """Test that script checks label 'for' attribute."""
        result = browser_fill_by_label("Password", "secret123")
        script = result["script"]

        assert "htmlFor" in script or "for" in script

    def test_fallback_to_placeholder(self):
        """Test fallback to placeholder matching."""
        result = browser_fill_by_label("Search", "query")
        script = result["script"]

        assert "placeholder" in script


class TestBrowserGetText:
    """Tests for browser_get_text()"""

    def test_basic_get_text(self):
        """Test getting text from elements."""
        result = browser_get_text("h1")

        assert "script" in result
        assert "h1" in result["script"]
        assert "textContent" in result["script"]

    def test_returns_array(self):
        """Test that script returns an array of texts."""
        result = browser_get_text(".item")
        script = result["script"]

        assert "map" in script
        assert "texts" in script.lower() or "return" in script


class TestBrowserTableData:
    """Tests for browser_table_data()"""

    def test_default_table_selector(self):
        """Test with default table selector."""
        result = browser_table_data()

        assert "script" in result
        assert "table" in result["script"]

    def test_custom_selector(self):
        """Test with custom table selector."""
        result = browser_table_data("#data-table")

        assert "#data-table" in result["script"]

    def test_extracts_headers(self):
        """Test that script extracts table headers."""
        result = browser_table_data()
        script = result["script"]

        assert "th" in script
        assert "headers" in script

    def test_extracts_rows(self):
        """Test that script extracts table rows."""
        result = browser_table_data()
        script = result["script"]

        assert "tbody" in script or "tr" in script
        assert "td" in script
        assert "rows" in script


class TestScriptExecution:
    """Tests for script format and executability."""

    def test_all_scripts_are_iifes(self):
        """Test that all generated scripts are IIFEs."""
        scripts = [
            browser_click_text("Test")["script"],
            browser_find_elements("div")["script"],
            browser_fill_by_label("Name", "value")["script"],
            browser_get_text("p")["script"],
            browser_table_data()["script"],
        ]

        for script in scripts:
            # Should be wrapped in IIFE
            stripped = script.strip()
            assert stripped.startswith("("), f"Script should start with '(': {stripped[:50]}"

    def test_scripts_return_objects(self):
        """Test that scripts return objects with success/error fields."""
        scripts = [
            browser_click_text("Test")["script"],
            browser_find_elements("div")["script"],
            browser_fill_by_label("Name", "value")["script"],
        ]

        for script in scripts:
            # Should have return statements with success field
            assert "return" in script
            assert "success" in script

    def test_no_syntax_errors_in_scripts(self):
        """Test that generated scripts don't have obvious syntax errors."""
        test_cases = [
            browser_click_text("Test's \"Quote\""),
            browser_find_elements("div.class[data-attr='value']"),
            browser_fill_by_label("Field\nWith\tSpecial", "Value"),
        ]

        for result in test_cases:
            script = result["script"]
            # Count braces - should be balanced
            assert script.count("{") == script.count("}"), f"Unbalanced braces in: {script[:100]}"
            assert script.count("(") == script.count(")"), f"Unbalanced parens in: {script[:100]}"
