"""
Tests for progress_tools.py - Custom MCP tools for progress log management.
"""

import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
import pytest

from arcadiaforge import progress_tools
from arcadiaforge.progress_tools import (
    create_progress_tools_server,
    progress_get_last,
    progress_add,
    progress_summary,
    progress_search,
    progress_get_issues,
    PROGRESS_TOOLS,
    PROGRESS_FILE,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    tmp_dir = Path(tempfile.mkdtemp())
    # Set the global project directory
    progress_tools._project_dir = tmp_dir
    yield tmp_dir
    # Cleanup
    shutil.rmtree(tmp_dir)


@pytest.fixture
def sample_progress():
    """Sample progress entries for testing."""
    return {
        "entries": [
            {
                "session_id": 1,
                "timestamp": "2024-01-15T10:00:00+00:00",
                "accomplished": ["Set up project structure", "Added features to the database"],
                "tests_completed": [],
                "tests_status": "0/50 passing",
                "issues_found": ["Missing TypeScript config"],
                "issues_fixed": [],
                "next_steps": ["Install dependencies", "Implement login"],
                "notes": "Initial setup"
            },
            {
                "session_id": 2,
                "timestamp": "2024-01-15T14:00:00+00:00",
                "accomplished": ["Implemented login feature", "Added form validation"],
                "tests_completed": [0, 1, 2],
                "tests_status": "3/50 passing",
                "issues_found": ["Button alignment issue"],
                "issues_fixed": ["Missing TypeScript config"],
                "next_steps": ["Implement logout", "Fix button alignment"],
                "notes": ""
            },
            {
                "session_id": 3,
                "timestamp": "2024-01-16T09:00:00+00:00",
                "accomplished": ["Implemented logout", "Fixed button alignment"],
                "tests_completed": [3, 4],
                "tests_status": "5/50 passing",
                "issues_found": [],
                "issues_fixed": ["Button alignment issue"],
                "next_steps": ["Implement password reset"],
                "notes": "Good progress today"
            }
        ]
    }


@pytest.fixture
def project_with_progress(temp_project_dir, sample_progress):
    """Create a project with a claude-progress.json file."""
    progress_file = temp_project_dir / PROGRESS_FILE
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(sample_progress, f, indent=2)
    return temp_project_dir


class TestProgressGetLast:
    """Tests for progress_get_last tool."""

    @pytest.mark.asyncio
    async def test_get_last_single(self, project_with_progress):
        """Test getting last single entry."""
        result = await progress_get_last.handler({"count": 1})
        text = result["content"][0]["text"]

        assert "Session #3" in text
        assert "5/50 passing" in text
        assert "Implemented logout" in text

    @pytest.mark.asyncio
    async def test_get_last_multiple(self, project_with_progress):
        """Test getting multiple last entries."""
        result = await progress_get_last.handler({"count": 2})
        text = result["content"][0]["text"]

        assert "Session #3" in text
        assert "Session #2" in text
        # Session 1 should NOT be included
        assert text.count("Session #") == 2

    @pytest.mark.asyncio
    async def test_get_last_no_entries(self, temp_project_dir):
        """Test when no progress entries exist."""
        result = await progress_get_last.handler({"count": 1})
        text = result["content"][0]["text"]

        assert "No progress entries found" in text
        assert "first session" in text.lower()

    @pytest.mark.asyncio
    async def test_get_last_default_count(self, project_with_progress):
        """Test default count of 1."""
        result = await progress_get_last.handler({})
        text = result["content"][0]["text"]

        assert "LAST 1 PROGRESS" in text

    @pytest.mark.asyncio
    async def test_get_last_more_than_available(self, project_with_progress):
        """Test requesting more entries than available."""
        result = await progress_get_last.handler({"count": 10})
        text = result["content"][0]["text"]

        # Should return all 3 entries
        assert "Session #1" in text
        assert "Session #2" in text
        assert "Session #3" in text


class TestProgressAdd:
    """Tests for progress_add tool."""

    @pytest.mark.asyncio
    async def test_add_first_entry(self, temp_project_dir):
        """Test adding the first progress entry."""
        result = await progress_add.handler({
            "accomplished": ["Set up project"],
            "tests_status": "0/10 passing",
            "next_steps": ["Begin implementation"]
        })
        text = result["content"][0]["text"]

        assert "Session #1" in text
        assert "added successfully" in text

        # Verify file was created
        with open(temp_project_dir / PROGRESS_FILE) as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["session_id"] == 1

    @pytest.mark.asyncio
    async def test_add_subsequent_entry(self, project_with_progress):
        """Test adding an entry to existing progress."""
        result = await progress_add.handler({
            "accomplished": ["New feature"],
            "tests_completed": [5, 6],
            "tests_status": "7/50 passing",
            "issues_found": ["New issue"],
            "issues_fixed": [],
            "next_steps": ["Continue work"],
            "notes": "Session 4"
        })
        text = result["content"][0]["text"]

        assert "Session #4" in text
        assert "added successfully" in text

        # Verify file was updated
        with open(project_with_progress / PROGRESS_FILE) as f:
            data = json.load(f)
        assert len(data["entries"]) == 4
        assert data["entries"][3]["session_id"] == 4

    @pytest.mark.asyncio
    async def test_add_with_minimal_fields(self, temp_project_dir):
        """Test adding with only required fields."""
        result = await progress_add.handler({
            "accomplished": ["Did something"],
            "tests_status": "1/5 passing",
            "next_steps": ["Do more"]
        })
        text = result["content"][0]["text"]

        assert "added successfully" in text

    @pytest.mark.asyncio
    async def test_add_includes_timestamp(self, temp_project_dir):
        """Test that added entry includes timestamp."""
        await progress_add.handler({
            "accomplished": ["Test"],
            "tests_status": "0/1",
            "next_steps": ["Next"]
        })

        with open(temp_project_dir / PROGRESS_FILE) as f:
            data = json.load(f)

        timestamp = data["entries"][0]["timestamp"]
        # Should be valid ISO format
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class TestProgressSummary:
    """Tests for progress_summary tool."""

    @pytest.mark.asyncio
    async def test_summary_with_entries(self, project_with_progress):
        """Test summary with existing entries."""
        result = await progress_summary.handler({})
        text = result["content"][0]["text"]

        assert "PROJECT PROGRESS SUMMARY" in text
        assert "Total sessions:        3" in text
        assert "Total accomplishments: 6" in text
        assert "Total tests completed: 5" in text
        assert "Total issues fixed:    2" in text
        assert "5/50 passing" in text
        assert "Implement password reset" in text

    @pytest.mark.asyncio
    async def test_summary_no_entries(self, temp_project_dir):
        """Test summary with no entries."""
        result = await progress_summary.handler({})
        text = result["content"][0]["text"]

        assert "No progress entries found" in text
        assert "new project" in text.lower()

    @pytest.mark.asyncio
    async def test_summary_shows_recent_sessions(self, project_with_progress):
        """Test that summary shows recent sessions."""
        result = await progress_summary.handler({})
        text = result["content"][0]["text"]

        assert "Recent sessions:" in text
        assert "Session #1" in text
        assert "Session #2" in text
        assert "Session #3" in text


class TestProgressSearch:
    """Tests for progress_search tool."""

    @pytest.mark.asyncio
    async def test_search_found(self, project_with_progress):
        """Test searching and finding entries."""
        result = await progress_search.handler({"query": "form validation"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "Session #2" in text

    @pytest.mark.asyncio
    async def test_search_multiple_matches(self, project_with_progress):
        """Test searching with multiple matches."""
        result = await progress_search.handler({"query": "button"})
        text = result["content"][0]["text"]

        # Should match session 2 (issue found) and session 3 (issue fixed)
        assert "2 matches" in text

    @pytest.mark.asyncio
    async def test_search_no_matches(self, project_with_progress):
        """Test searching with no matches."""
        result = await progress_search.handler({"query": "xyz123nonexistent"})
        text = result["content"][0]["text"]

        assert "No progress entries found matching" in text

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, project_with_progress):
        """Test case-insensitive search."""
        result = await progress_search.handler({"query": "TYPESCRIPT"})
        text = result["content"][0]["text"]

        # TypeScript appears in issues_found (session 1) and issues_fixed (session 2)
        assert "2 matches" in text

    @pytest.mark.asyncio
    async def test_search_in_notes(self, project_with_progress):
        """Test searching in notes field."""
        result = await progress_search.handler({"query": "good progress"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "Session #3" in text


class TestProgressGetIssues:
    """Tests for progress_get_issues tool."""

    @pytest.mark.asyncio
    async def test_get_unresolved_issues(self, project_with_progress):
        """Test getting unresolved issues."""
        # In sample data: TypeScript config was found in session 1, fixed in session 2
        # Button alignment was found in session 2, fixed in session 3
        # So all issues should be resolved
        result = await progress_get_issues.handler({})
        text = result["content"][0]["text"]

        assert "All discovered issues have been fixed" in text

    @pytest.mark.asyncio
    async def test_get_unresolved_with_pending_issues(self, temp_project_dir):
        """Test with unresolved issues."""
        data = {
            "entries": [
                {
                    "session_id": 1,
                    "timestamp": "2024-01-15T10:00:00+00:00",
                    "accomplished": [],
                    "tests_completed": [],
                    "tests_status": "0/10",
                    "issues_found": ["Bug A", "Bug B"],
                    "issues_fixed": [],
                    "next_steps": []
                },
                {
                    "session_id": 2,
                    "timestamp": "2024-01-15T14:00:00+00:00",
                    "accomplished": [],
                    "tests_completed": [],
                    "tests_status": "0/10",
                    "issues_found": ["Bug C"],
                    "issues_fixed": ["Bug A"],
                    "next_steps": []
                }
            ]
        }
        with open(temp_project_dir / PROGRESS_FILE, "w") as f:
            json.dump(data, f)

        result = await progress_get_issues.handler({})
        text = result["content"][0]["text"]

        assert "UNRESOLVED ISSUES (2 total)" in text
        assert "Bug B" in text
        assert "Bug C" in text
        assert "Bug A" not in text  # Was fixed

    @pytest.mark.asyncio
    async def test_get_issues_no_entries(self, temp_project_dir):
        """Test with no entries."""
        result = await progress_get_issues.handler({})
        text = result["content"][0]["text"]

        assert "No progress entries found" in text


class TestCreateProgressToolsServer:
    """Tests for create_progress_tools_server function."""

    def test_creates_server(self, temp_project_dir):
        """Test that server is created successfully."""
        server = create_progress_tools_server(temp_project_dir)

        assert server is not None
        assert isinstance(server, dict)
        assert server.get("type") == "sdk"
        assert server.get("name") == "progress"

    def test_sets_project_dir(self, temp_project_dir):
        """Test that project directory is set correctly."""
        create_progress_tools_server(temp_project_dir)

        assert progress_tools._project_dir == temp_project_dir


class TestProgressToolsList:
    """Tests for PROGRESS_TOOLS constant."""

    def test_all_tools_listed(self):
        """Test that all tools are in the list."""
        expected_tools = [
            "mcp__progress__progress_get_last",
            "mcp__progress__progress_add",
            "mcp__progress__progress_summary",
            "mcp__progress__progress_search",
            "mcp__progress__progress_get_issues",
        ]

        assert PROGRESS_TOOLS == expected_tools

    def test_tool_count(self):
        """Test correct number of tools."""
        assert len(PROGRESS_TOOLS) == 5


class TestProgressFileHandling:
    """Tests for file handling edge cases."""

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self, temp_project_dir):
        """Test handling of malformed JSON file."""
        with open(temp_project_dir / PROGRESS_FILE, "w") as f:
            f.write("not valid json {")

        result = await progress_get_last.handler({"count": 1})
        text = result["content"][0]["text"]

        # Should handle gracefully
        assert "No progress entries found" in text

    @pytest.mark.asyncio
    async def test_handles_missing_entries_key(self, temp_project_dir):
        """Test handling JSON without entries key."""
        with open(temp_project_dir / PROGRESS_FILE, "w") as f:
            json.dump({"other_key": "value"}, f)

        result = await progress_get_last.handler({"count": 1})
        text = result["content"][0]["text"]

        # Should handle gracefully
        assert "No progress entries found" in text

    @pytest.mark.asyncio
    async def test_session_id_increments_correctly(self, temp_project_dir):
        """Test that session IDs increment correctly."""
        # Add first entry
        await progress_add.handler({
            "accomplished": ["First"],
            "tests_status": "0/1",
            "next_steps": ["Next"]
        })

        # Add second entry
        await progress_add.handler({
            "accomplished": ["Second"],
            "tests_status": "1/1",
            "next_steps": ["Done"]
        })

        with open(temp_project_dir / PROGRESS_FILE) as f:
            data = json.load(f)

        assert data["entries"][0]["session_id"] == 1
        assert data["entries"][1]["session_id"] == 2


class TestProgressEntryFormatting:
    """Tests for entry formatting."""

    @pytest.mark.asyncio
    async def test_verbose_output_includes_notes(self, project_with_progress):
        """Test that verbose output includes notes."""
        result = await progress_get_last.handler({"count": 1})
        text = result["content"][0]["text"]

        # Session 3 has notes "Good progress today"
        assert "Good progress today" in text

    @pytest.mark.asyncio
    async def test_shows_all_sections(self, project_with_progress):
        """Test that all sections are shown when present."""
        result = await progress_get_last.handler({"count": 3})
        text = result["content"][0]["text"]

        assert "Accomplished:" in text
        assert "Issues fixed:" in text
        assert "Issues found" in text
        assert "Next steps:" in text
