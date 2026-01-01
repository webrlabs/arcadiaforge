"""
Tests for Enhanced Error Messages with Context
===============================================

Tests for arcadiaforge/error_context.py
"""

import pytest

from arcadiaforge.error_context import (
    enhance_error_message,
    get_tool_suggestion,
    format_error_with_context,
    ERROR_SUGGESTIONS,
    PATTERN_SUGGESTIONS,
)


class TestEnhanceErrorMessage:
    """Tests for enhance_error_message()"""

    def test_empty_error(self):
        """Test with empty error string."""
        result = enhance_error_message("")
        assert result == ""

    def test_none_error(self):
        """Test with None error."""
        result = enhance_error_message(None)
        assert result is None

    def test_unknown_error_unchanged(self):
        """Test that unknown errors pass through unchanged."""
        error = "Some random error that doesn't match anything"
        result = enhance_error_message(error)
        assert result == error

    # Unix command errors
    def test_cp_command_not_found(self):
        """Test suggestion for cp command not found."""
        error = "cp: command not found"
        result = enhance_error_message(error)

        assert "file_copy" in result
        assert "Suggestion" in result

    def test_rm_command_not_found(self):
        """Test suggestion for rm command not found."""
        error = "rm: command not found"
        result = enhance_error_message(error)

        assert "file_delete" in result
        assert "Suggestion" in result

    def test_mkdir_command_not_found(self):
        """Test suggestion for mkdir command not found."""
        error = "mkdir: command not found"
        result = enhance_error_message(error)

        assert "file_ensure_dir" in result

    def test_find_command_not_found(self):
        """Test suggestion for find command not found."""
        error = "find: command not found"
        result = enhance_error_message(error)

        assert "file_glob" in result
        assert "**/*.py" in result

    def test_grep_command_not_found(self):
        """Test suggestion for grep command not found."""
        error = "grep: command not found"
        result = enhance_error_message(error)

        assert "Grep" in result

    # Windows command errors
    def test_windows_copy_not_recognized(self):
        """Test suggestion for Windows copy command error."""
        error = "'copy' is not recognized as an internal or external command"
        result = enhance_error_message(error)

        assert "file_copy" in result

    def test_windows_del_not_recognized(self):
        """Test suggestion for Windows del command error."""
        error = "'del' is not recognized as an internal or external command"
        result = enhance_error_message(error)

        assert "file_delete" in result

    def test_windows_type_not_recognized(self):
        """Test suggestion for Windows type command error."""
        error = "'type' is not recognized as an internal or external command"
        result = enhance_error_message(error)

        assert "Read" in result

    # Puppeteer selector errors
    def test_has_text_selector_error(self):
        """Test suggestion for :has-text() selector error."""
        error = "Error: 'button:has-text(\"Submit\")' is not a valid selector"
        result = enhance_error_message(error)

        assert "browser_click_text" in result

    def test_contains_selector_error(self):
        """Test suggestion for :contains() selector error."""
        error = "Error: selector ':contains(test)' is not a valid selector"
        result = enhance_error_message(error)

        assert "browser_find_elements" in result

    def test_has_selector_error(self):
        """Test suggestion for :has() selector error."""
        error = "Error: selector 'div:has(.child)' is not a valid selector"
        result = enhance_error_message(error)

        assert "puppeteer_evaluate" in result

    def test_failed_to_find_element(self):
        """Test suggestion for element not found."""
        error = "failed to find element matching selector"
        result = enhance_error_message(error)

        assert "browser_find_elements" in result

    def test_waiting_for_selector(self):
        """Test suggestion for selector timeout."""
        error = "Timeout waiting for selector '.dynamic-element'"
        result = enhance_error_message(error)

        assert "browser_wait_and_click" in result

    # Docker errors
    def test_docker_daemon_not_running(self):
        """Test suggestion for Docker daemon error."""
        error = "Error: docker daemon is not running"
        result = enhance_error_message(error)

        assert "feature_mark_blocked" in result

    def test_docker_connect_error(self):
        """Test suggestion for Docker connection error."""
        error = "docker: error during connect: cannot connect to Docker daemon"
        result = enhance_error_message(error)

        assert "feature_mark_blocked" in result

    # Port/network errors
    def test_address_in_use(self):
        """Test suggestion for port in use error."""
        error = "Error: listen EADDRINUSE: address already in use :::3000"
        result = enhance_error_message(error)

        assert "server_stop" in result or "server_list" in result

    # Git errors
    def test_not_a_git_repository(self):
        """Test suggestion for not a git repo error."""
        error = "fatal: not a git repository"
        result = enhance_error_message(error)

        assert "git init" in result

    # npm errors
    def test_npm_eresolve(self):
        """Test suggestion for npm dependency conflict."""
        error = "npm ERR! ERESOLVE unable to resolve dependency tree"
        result = enhance_error_message(error)

        assert "legacy-peer-deps" in result

    def test_with_context(self):
        """Test enhancement with command context."""
        error = "cp: command not found"
        context = {"command": "cp source.txt dest.txt"}

        result = enhance_error_message(error, context)

        assert "file_copy" in result


class TestPatternSuggestions:
    """Tests for pattern-based suggestions."""

    def test_button_has_text_pattern(self):
        """Test pattern matching for button:has-text()."""
        error = "button:has-text('Submit Form') is not valid"
        result = enhance_error_message(error)

        assert "browser_click_text" in result
        # Should extract the text from the pattern
        assert "Submit Form" in result or "browser_click_text" in result

    def test_copy_command_pattern(self):
        """Test pattern matching for copy commands."""
        error = "Error: copy 'file.txt' 'dest/file.txt' failed"
        result = enhance_error_message(error)

        assert "file_copy" in result

    def test_rm_recursive_pattern(self):
        """Test pattern matching for rm -rf."""
        error = "Error: rm -rf build/ command failed"
        result = enhance_error_message(error)

        assert "file_delete" in result
        assert "recursive" in result

    def test_mkdir_p_pattern(self):
        """Test pattern matching for mkdir -p."""
        error = "Error: mkdir -p path/to/dir failed"
        result = enhance_error_message(error)

        assert "file_ensure_dir" in result


class TestGetToolSuggestion:
    """Tests for get_tool_suggestion()"""

    def test_cp_suggestion(self):
        """Test suggestion for cp command."""
        result = get_tool_suggestion("cp source.txt dest.txt")

        assert "file_copy" in result
        assert "src=" in result
        assert "dest=" in result

    def test_mv_suggestion(self):
        """Test suggestion for mv command."""
        result = get_tool_suggestion("mv old.txt new.txt")

        assert "file_move" in result

    def test_rm_suggestion(self):
        """Test suggestion for rm command."""
        result = get_tool_suggestion("rm -rf build/")

        assert "file_delete" in result
        assert "recursive" in result

    def test_mkdir_suggestion(self):
        """Test suggestion for mkdir command."""
        result = get_tool_suggestion("mkdir -p some/dir")

        assert "file_ensure_dir" in result

    def test_ls_suggestion(self):
        """Test suggestion for ls command."""
        result = get_tool_suggestion("ls -la")

        assert "file_list" in result

    def test_cat_suggestion(self):
        """Test suggestion for cat command."""
        result = get_tool_suggestion("cat file.txt")

        assert "Read" in result

    def test_grep_suggestion(self):
        """Test suggestion for grep command."""
        result = get_tool_suggestion("grep pattern file.txt")

        assert "Grep" in result

    def test_find_suggestion(self):
        """Test suggestion for find command."""
        result = get_tool_suggestion("find . -name '*.py'")

        assert "file_glob" in result

    def test_windows_copy_suggestion(self):
        """Test suggestion for Windows copy command."""
        result = get_tool_suggestion("copy source.txt dest.txt")

        assert "file_copy" in result

    def test_windows_del_suggestion(self):
        """Test suggestion for Windows del command."""
        result = get_tool_suggestion("del file.txt")

        assert "file_delete" in result

    def test_windows_type_suggestion(self):
        """Test suggestion for Windows type command."""
        result = get_tool_suggestion("type file.txt")

        assert "Read" in result

    def test_unknown_command_no_suggestion(self):
        """Test that unknown commands return None."""
        result = get_tool_suggestion("some_random_command arg1 arg2")

        assert result is None

    def test_empty_command_no_suggestion(self):
        """Test that empty command returns None."""
        result = get_tool_suggestion("")

        assert result is None


class TestFormatErrorWithContext:
    """Tests for format_error_with_context()"""

    def test_basic_formatting(self):
        """Test basic error formatting."""
        result = format_error_with_context("Test error message")

        assert "ERROR DETAILS" in result
        assert "Test error message" in result
        assert "=" * 60 in result

    def test_with_tool_name(self):
        """Test formatting with tool name."""
        result = format_error_with_context(
            "Test error",
            tool_name="bash",
        )

        assert "Tool: bash" in result

    def test_with_tool_input(self):
        """Test formatting with tool input."""
        result = format_error_with_context(
            "Test error",
            tool_name="bash",
            tool_input={"command": "cp file.txt dest/"},
        )

        assert "Input:" in result
        assert "cp file.txt" in result

    def test_with_session_id(self):
        """Test formatting with session ID."""
        result = format_error_with_context(
            "Test error",
            session_id=42,
        )

        assert "Session: 42" in result

    def test_truncates_large_input(self):
        """Test that large inputs are truncated."""
        large_input = {"command": "x" * 1000}

        result = format_error_with_context(
            "Test error",
            tool_input=large_input,
        )

        assert "..." in result
        assert len(result) < 2000

    def test_includes_enhanced_suggestions(self):
        """Test that suggestions are included for matching errors."""
        result = format_error_with_context(
            "cp: command not found",
            tool_name="bash",
            tool_input={"command": "cp source.txt dest.txt"},
        )

        assert "file_copy" in result

    def test_full_context(self):
        """Test with all context fields."""
        result = format_error_with_context(
            error="rm: command not found",
            tool_name="bash",
            tool_input={"command": "rm -rf build/"},
            session_id=123,
        )

        assert "ERROR DETAILS" in result
        assert "Tool: bash" in result
        assert "rm -rf build" in result
        assert "Session: 123" in result
        assert "file_delete" in result


class TestErrorSuggestionsDatabase:
    """Tests for the ERROR_SUGGESTIONS database."""

    def test_command_not_found_entries(self):
        """Test that command not found has expected entries."""
        cmd_not_found = ERROR_SUGGESTIONS.get("command not found", {})

        assert "cp" in cmd_not_found
        assert "rm" in cmd_not_found
        assert "mkdir" in cmd_not_found
        assert "ls" in cmd_not_found
        assert "cat" in cmd_not_found
        assert "find" in cmd_not_found
        assert "grep" in cmd_not_found

    def test_puppeteer_selector_entries(self):
        """Test Puppeteer selector error entries."""
        not_valid = ERROR_SUGGESTIONS.get("not a valid selector", {})

        assert ":has-text" in not_valid
        assert ":contains" in not_valid

    def test_docker_entries(self):
        """Test Docker error entries."""
        docker = ERROR_SUGGESTIONS.get("docker", {})

        assert "daemon is not running" in docker

    def test_port_entries(self):
        """Test port/address error entries."""
        assert "address already in use" in ERROR_SUGGESTIONS
        assert "eaddrinuse" in ERROR_SUGGESTIONS


class TestPatternSuggestionsDatabase:
    """Tests for PATTERN_SUGGESTIONS patterns."""

    def test_pattern_count(self):
        """Test that patterns are defined."""
        assert len(PATTERN_SUGGESTIONS) > 0

    def test_pattern_structure(self):
        """Test pattern tuple structure."""
        for pattern, suggestion, category in PATTERN_SUGGESTIONS:
            assert isinstance(pattern, str)
            assert isinstance(suggestion, str)
            assert isinstance(category, str)
            assert len(pattern) > 0
            assert len(suggestion) > 0

    def test_patterns_are_valid_regex(self):
        """Test that all patterns are valid regex."""
        import re

        for pattern, suggestion, category in PATTERN_SUGGESTIONS:
            # Should not raise
            compiled = re.compile(pattern, re.IGNORECASE)
            assert compiled is not None


class TestCommandSpecificSuggestions:
    """Tests for _get_command_specific_suggestion()"""

    def test_screenshot_command(self):
        """Test screenshot-related command suggestion."""
        error = "some error"
        context = {"command": "capture screenshot of page"}
        result = enhance_error_message(error, context)

        # The suggestion might be added if there's a match
        # Just verify no crash occurs
        assert error in result

    def test_cp_command_context(self):
        """Test cp command in context gets suggestion."""
        error = "something failed"
        context = {"command": "cp file.txt dest/"}

        result = enhance_error_message(error, context)

        assert "file_copy" in result

    def test_ls_head_command_context(self):
        """Test ls | head pattern gets suggestion."""
        error = "pipe failed"
        context = {"command": "ls -lt *.png | head -1"}

        result = enhance_error_message(error, context)

        assert "file_latest" in result

    def test_mkdir_p_command_context(self):
        """Test mkdir -p gets suggestion."""
        error = "command failed"
        context = {"command": "mkdir -p nested/dir/structure"}

        result = enhance_error_message(error, context)

        assert "file_ensure_dir" in result


class TestMaxSuggestions:
    """Tests for suggestion limits."""

    def test_max_three_suggestions(self):
        """Test that maximum 3 suggestions are shown."""
        # Create an error that matches multiple patterns
        error = "cp: command not found while trying mkdir -p"

        result = enhance_error_message(error)

        # Count suggestion markers
        suggestion_count = result.count("Suggestion")
        assert suggestion_count <= 3
