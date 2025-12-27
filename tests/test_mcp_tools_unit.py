#!/usr/bin/env python3
"""
Unit Tests for MCP Tools
========================

Tests the MCP tools directly without needing an agent session.
These tests verify the tools work correctly in isolation.

Usage:
    python -m pytest tests/test_mcp_tools_unit.py -v
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def project_dir():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory(prefix="arcadia_test_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def feature_list_file(project_dir):
    """Create a test feature_list.json file."""
    features = [
        {
            "description": "Test feature 1: User authentication",
            "test_command": "npm test auth",
            "passes": False
        },
        {
            "description": "Test feature 2: Dashboard display",
            "test_command": "npm test dashboard",
            "passes": True,
            "verified_at": "2024-01-15T10:00:00Z"
        },
        {
            "description": "Test feature 3: API endpoints",
            "test_command": "npm test api",
            "passes": False
        }
    ]
    feature_file = project_dir / "feature_list.json"
    with open(feature_file, "w") as f:
        json.dump(features, f, indent=2)
    return feature_file


def call_tool(tool_obj, args):
    """Helper to call an MCP tool's handler."""
    return asyncio.run(tool_obj.handler(args))


class TestFeatureTools:
    """Tests for feature management MCP tools."""

    def test_feature_stats(self, project_dir, feature_list_file):
        """Test feature_stats tool."""
        from arcadiaforge.feature_tools import feature_stats

        # Set up the project directory
        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        result = call_tool(feature_stats, {})

        assert "content" in result
        assert len(result["content"]) > 0
        text = result["content"][0]["text"]
        assert "3" in text  # Total features
        assert "1" in text  # Passing features

    def test_feature_next(self, project_dir, feature_list_file):
        """Test feature_next tool."""
        from arcadiaforge.feature_tools import feature_next

        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        result = call_tool(feature_next, {})

        assert "content" in result
        text = result["content"][0]["text"]
        # Should return feature 0 (first non-passing)
        assert "#0" in text or "authentication" in text.lower()

    def test_feature_show(self, project_dir, feature_list_file):
        """Test feature_show tool."""
        from arcadiaforge.feature_tools import feature_show

        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        result = call_tool(feature_show, {"index": 1})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "Dashboard" in text

    def test_feature_list(self, project_dir, feature_list_file):
        """Test feature_list tool."""
        from arcadiaforge.feature_tools import feature_list

        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        result = call_tool(feature_list, {})

        assert "content" in result
        text = result["content"][0]["text"]
        # feature_list shows INCOMPLETE features by default
        assert "authentication" in text.lower()
        assert "API" in text  # Feature 3 is also incomplete

    def test_feature_search(self, project_dir, feature_list_file):
        """Test feature_search tool."""
        from arcadiaforge.feature_tools import feature_search

        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        # The tool uses "query" parameter, not "keyword"
        result = call_tool(feature_search, {"query": "API"})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "API" in text

    def test_feature_show_invalid_index(self, project_dir, feature_list_file):
        """Test feature_show with invalid index."""
        from arcadiaforge.feature_tools import feature_show

        import arcadiaforge.feature_tools as ft
        ft._project_dir = project_dir

        result = call_tool(feature_show, {"index": 999})

        assert "is_error" in result
        assert result["is_error"] == True


class TestProgressTools:
    """Tests for progress tracking MCP tools."""

    def test_progress_summary(self, project_dir, feature_list_file):
        """Test progress_summary tool."""
        from arcadiaforge.progress_tools import progress_summary

        import arcadiaforge.progress_tools as pt
        pt._project_dir = project_dir

        result = call_tool(progress_summary, {})

        assert "content" in result
        # Should work even without full setup

    def test_progress_get_last(self, project_dir, feature_list_file):
        """Test progress_get_last tool."""
        from arcadiaforge.progress_tools import progress_get_last

        import arcadiaforge.progress_tools as pt
        pt._project_dir = project_dir

        result = call_tool(progress_get_last, {"count": 5})

        assert "content" in result

    def test_progress_search(self, project_dir, feature_list_file):
        """Test progress_search tool."""
        from arcadiaforge.progress_tools import progress_search

        import arcadiaforge.progress_tools as pt
        pt._project_dir = project_dir

        result = call_tool(progress_search, {"query": "test"})

        assert "content" in result


class TestProcessTools:
    """Tests for process management MCP tools."""

    def test_process_list_empty(self, project_dir):
        """Test process_list with no tracked processes."""
        from arcadiaforge.process_tools import process_list, set_project_dir

        set_project_dir(project_dir)

        result = call_tool(process_list, {})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "No tracked processes" in text or "0" in text

    def test_process_find_port(self, project_dir):
        """Test process_find_port tool."""
        from arcadiaforge.process_tools import process_find_port, set_project_dir

        set_project_dir(project_dir)

        # Test with a port that's likely not in use
        result = call_tool(process_find_port, {"port": 59999})

        assert "content" in result
        # Should return "no process" or similar

    def test_process_stop_invalid_pid(self, project_dir):
        """Test process_stop with untracked PID."""
        from arcadiaforge.process_tools import process_stop, set_project_dir

        set_project_dir(project_dir)

        result = call_tool(process_stop, {"pid": 99999})

        assert "is_error" in result
        assert result["is_error"] == True

    def test_process_track_invalid_pid(self, project_dir):
        """Test process_track with non-existent PID."""
        from arcadiaforge.process_tools import process_track, set_project_dir

        set_project_dir(project_dir)

        result = call_tool(process_track, {"pid": 99999, "name": "test"})

        assert "is_error" in result
        assert result["is_error"] == True


class TestTroubleshootingTools:
    """Tests for troubleshooting MCP tools."""

    def test_troubleshoot_list_categories(self, project_dir):
        """Test troubleshoot_list_categories tool."""
        from arcadiaforge.troubleshooting_tools import troubleshoot_list_categories

        import arcadiaforge.troubleshooting_tools as tt
        tt._project_dir = project_dir

        result = call_tool(troubleshoot_list_categories, {})

        assert "content" in result

    def test_troubleshoot_get_recent(self, project_dir):
        """Test troubleshoot_get_recent tool."""
        from arcadiaforge.troubleshooting_tools import troubleshoot_get_recent

        import arcadiaforge.troubleshooting_tools as tt
        tt._project_dir = project_dir

        result = call_tool(troubleshoot_get_recent, {"count": 5})

        assert "content" in result

    def test_troubleshoot_search(self, project_dir):
        """Test troubleshoot_search tool."""
        from arcadiaforge.troubleshooting_tools import troubleshoot_search

        import arcadiaforge.troubleshooting_tools as tt
        tt._project_dir = project_dir

        result = call_tool(troubleshoot_search, {"query": "error"})

        assert "content" in result


class TestProcessTracker:
    """Tests for the ProcessTracker class."""

    def test_tracker_initialization(self, project_dir):
        """Test ProcessTracker initialization."""
        from arcadiaforge.process_tracker import ProcessTracker

        tracker = ProcessTracker(project_dir)

        assert tracker.project_dir == project_dir
        assert tracker.tracker_file == project_dir / ".processes.json"

    def test_tracker_track_and_untrack(self, project_dir):
        """Test tracking and untracking processes."""
        from arcadiaforge.process_tracker import ProcessTracker

        tracker = ProcessTracker(project_dir)

        # Track a fake process (won't actually exist)
        tracker.track(
            pid=12345,
            command="python test.py",
            session_id=1,
            name="test-process",
            port=8000
        )

        assert 12345 in tracker.processes
        assert tracker.processes[12345].name == "test-process"
        assert tracker.processes[12345].port == 8000

        # Untrack
        tracker.untrack(12345)
        assert 12345 not in tracker.processes

    def test_tracker_persistence(self, project_dir):
        """Test that tracker persists to disk."""
        from arcadiaforge.process_tracker import ProcessTracker

        # Create tracker and add process
        tracker1 = ProcessTracker(project_dir)
        tracker1.track(pid=11111, command="test", session_id=1)

        # Create new tracker instance - should load from disk
        tracker2 = ProcessTracker(project_dir)
        assert 11111 in tracker2.processes

    def test_extract_name(self, project_dir):
        """Test name extraction from commands."""
        from arcadiaforge.process_tracker import ProcessTracker

        tracker = ProcessTracker(project_dir)

        assert tracker._extract_name("python app.py") == "python app.py"
        assert tracker._extract_name("node server.js") == "node server.js"
        assert tracker._extract_name("npm run dev") == "npm:dev"
        assert tracker._extract_name("npx vite") == "vite"


class TestSecurityValidation:
    """Tests for security validation of process kill commands."""

    def test_pkill_blocked_python(self):
        """Test that pkill python is blocked."""
        from arcadiaforge.security import validate_pkill_command

        allowed, reason = validate_pkill_command("pkill python")

        assert allowed == False
        assert "BLOCKED" in reason

    def test_pkill_blocked_node(self):
        """Test that pkill node is blocked."""
        from arcadiaforge.security import validate_pkill_command

        allowed, reason = validate_pkill_command("pkill node")

        assert allowed == False
        assert "BLOCKED" in reason

    def test_pkill_allowed_with_script(self):
        """Test that pkill -f with script is allowed."""
        from arcadiaforge.security import validate_pkill_command

        allowed, reason = validate_pkill_command('pkill -f "python app.py"')

        assert allowed == True

    def test_pkill_allowed_vite(self):
        """Test that pkill vite is allowed."""
        from arcadiaforge.security import validate_pkill_command

        allowed, reason = validate_pkill_command("pkill vite")

        assert allowed == True

    def test_taskkill_blocked_python(self):
        """Test that taskkill /IM python.exe is blocked."""
        from arcadiaforge.security import validate_taskkill_command

        allowed, reason = validate_taskkill_command("taskkill /IM python.exe")

        assert allowed == False
        assert "BLOCKED" in reason

    def test_taskkill_allowed_with_filter(self):
        """Test that taskkill with /FI is allowed."""
        from arcadiaforge.security import validate_taskkill_command

        allowed, reason = validate_taskkill_command('taskkill /IM python.exe /FI "WINDOWTITLE eq App"')

        assert allowed == True

    def test_taskkill_allowed_vite(self):
        """Test that taskkill /IM vite.exe is allowed."""
        from arcadiaforge.security import validate_taskkill_command

        allowed, reason = validate_taskkill_command("taskkill /IM vite.exe")

        assert allowed == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
