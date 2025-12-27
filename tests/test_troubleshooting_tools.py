"""
Tests for troubleshooting_tools.py - Custom MCP tools for troubleshooting knowledge base.
"""

import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
import pytest

from arcadiaforge import troubleshooting_tools
from arcadiaforge.troubleshooting_tools import (
    create_troubleshooting_tools_server,
    troubleshoot_search,
    troubleshoot_add,
    troubleshoot_get_recent,
    troubleshoot_get_by_category,
    troubleshoot_list_categories,
    TROUBLESHOOTING_TOOLS,
    TROUBLESHOOTING_FILE,
    CATEGORIES,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    tmp_dir = Path(tempfile.mkdtemp())
    # Set the global project directory
    troubleshooting_tools._project_dir = tmp_dir
    yield tmp_dir
    # Cleanup
    shutil.rmtree(tmp_dir)


@pytest.fixture
def sample_troubleshooting():
    """Sample troubleshooting entries for testing."""
    return {
        "entries": [
            {
                "id": 1,
                "timestamp": "2024-01-15T10:00:00+00:00",
                "category": "build",
                "error_message": "Module not found: 'react-router-dom'",
                "symptoms": ["npm run build fails", "Error in terminal"],
                "cause": "Missing dependency",
                "solution": "Install the missing package",
                "steps_to_fix": ["Run npm install react-router-dom", "Restart dev server"],
                "prevention": "Check imports match installed packages",
                "tags": ["npm", "dependency", "react"]
            },
            {
                "id": 2,
                "timestamp": "2024-01-15T14:00:00+00:00",
                "category": "styling",
                "error_message": "White text on white background",
                "symptoms": ["Text invisible", "Poor contrast"],
                "cause": "CSS specificity issue",
                "solution": "Override with more specific selector",
                "steps_to_fix": ["Find the conflicting style", "Add !important or more specific selector"],
                "prevention": "Use consistent theming system",
                "tags": ["css", "contrast", "accessibility"]
            },
            {
                "id": 3,
                "timestamp": "2024-01-16T09:00:00+00:00",
                "category": "runtime",
                "error_message": "TypeError: Cannot read property 'map' of undefined",
                "symptoms": ["Page crashes on load", "React error boundary triggered"],
                "cause": "API response not properly awaited",
                "solution": "Add loading state and null check",
                "steps_to_fix": ["Add loading state", "Check if data exists before mapping"],
                "prevention": "Always handle async data properly",
                "tags": ["react", "async", "null-check"]
            },
            {
                "id": 4,
                "timestamp": "2024-01-16T11:00:00+00:00",
                "category": "build",
                "error_message": "TypeScript error: Property 'x' does not exist",
                "symptoms": ["Build fails", "Red squiggles in IDE"],
                "cause": "Missing type definition",
                "solution": "Add proper type annotation",
                "steps_to_fix": ["Define interface", "Apply to variable"],
                "prevention": "Use strict TypeScript settings",
                "tags": ["typescript", "types"]
            }
        ]
    }


@pytest.fixture
def project_with_troubleshooting(temp_project_dir, sample_troubleshooting):
    """Create a project with a troubleshooting.json file."""
    ts_file = temp_project_dir / TROUBLESHOOTING_FILE
    with open(ts_file, "w", encoding="utf-8") as f:
        json.dump(sample_troubleshooting, f, indent=2)
    return temp_project_dir


class TestTroubleshootSearch:
    """Tests for troubleshoot_search tool."""

    @pytest.mark.asyncio
    async def test_search_by_error_message(self, project_with_troubleshooting):
        """Test searching by error message."""
        result = await troubleshoot_search.handler({"query": "Module not found"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "react-router-dom" in text

    @pytest.mark.asyncio
    async def test_search_by_tag(self, project_with_troubleshooting):
        """Test searching by tag."""
        result = await troubleshoot_search.handler({"query": "react"})
        text = result["content"][0]["text"]

        # Should match entries with react tag
        assert "matches" in text
        assert "react" in text.lower()

    @pytest.mark.asyncio
    async def test_search_by_symptom(self, project_with_troubleshooting):
        """Test searching by symptom."""
        result = await troubleshoot_search.handler({"query": "invisible"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "White text" in text

    @pytest.mark.asyncio
    async def test_search_no_results(self, project_with_troubleshooting):
        """Test search with no matches."""
        result = await troubleshoot_search.handler({"query": "nonexistent123xyz"})
        text = result["content"][0]["text"]

        assert "No troubleshooting entries found matching" in text
        assert "troubleshoot_add" in text  # Should suggest adding

    @pytest.mark.asyncio
    async def test_search_empty_database(self, temp_project_dir):
        """Test search on empty database."""
        result = await troubleshoot_search.handler({"query": "anything"})
        text = result["content"][0]["text"]

        assert "knowledge base is empty" in text

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, project_with_troubleshooting):
        """Test case-insensitive search."""
        result = await troubleshoot_search.handler({"query": "TYPESCRIPT"})
        text = result["content"][0]["text"]

        assert "1 matches" in text

    @pytest.mark.asyncio
    async def test_search_shows_solution(self, project_with_troubleshooting):
        """Test that search results include the solution."""
        result = await troubleshoot_search.handler({"query": "npm"})
        text = result["content"][0]["text"]

        assert "Solution:" in text
        assert "Install" in text


class TestTroubleshootAdd:
    """Tests for troubleshoot_add tool."""

    @pytest.mark.asyncio
    async def test_add_entry(self, temp_project_dir):
        """Test adding a new entry."""
        result = await troubleshoot_add.handler({
            "category": "dependency",
            "error_message": "Package version conflict",
            "symptoms": ["npm install fails"],
            "cause": "Conflicting peer dependencies",
            "solution": "Use --legacy-peer-deps flag",
            "steps_to_fix": ["Run npm install --legacy-peer-deps"],
            "prevention": "Check peer deps before updating",
            "tags": ["npm", "peer-deps"]
        })
        text = result["content"][0]["text"]

        assert "added successfully" in text
        assert "#1" in text

        # Verify file was created
        with open(temp_project_dir / TROUBLESHOOTING_FILE) as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["category"] == "dependency"

    @pytest.mark.asyncio
    async def test_add_with_minimal_fields(self, temp_project_dir):
        """Test adding with only required fields."""
        result = await troubleshoot_add.handler({
            "category": "other",
            "error_message": "Some error",
            "solution": "Fixed it"
        })
        text = result["content"][0]["text"]

        assert "added successfully" in text

    @pytest.mark.asyncio
    async def test_add_increments_id(self, project_with_troubleshooting):
        """Test that ID increments correctly."""
        result = await troubleshoot_add.handler({
            "category": "config",
            "error_message": "Config error",
            "solution": "Fix config"
        })
        text = result["content"][0]["text"]

        # Should be #5 since sample has 4 entries
        assert "#5" in text

    @pytest.mark.asyncio
    async def test_add_invalid_category_defaults_to_other(self, temp_project_dir):
        """Test that invalid category defaults to 'other'."""
        await troubleshoot_add.handler({
            "category": "invalid_category",
            "error_message": "Error",
            "solution": "Solution"
        })

        with open(temp_project_dir / TROUBLESHOOTING_FILE) as f:
            data = json.load(f)
        assert data["entries"][0]["category"] == "other"

    @pytest.mark.asyncio
    async def test_add_lowercases_tags(self, temp_project_dir):
        """Test that tags are lowercased."""
        await troubleshoot_add.handler({
            "category": "build",
            "error_message": "Error",
            "solution": "Solution",
            "tags": ["React", "TypeScript", "NPM"]
        })

        with open(temp_project_dir / TROUBLESHOOTING_FILE) as f:
            data = json.load(f)
        assert data["entries"][0]["tags"] == ["react", "typescript", "npm"]

    @pytest.mark.asyncio
    async def test_add_includes_timestamp(self, temp_project_dir):
        """Test that entry includes timestamp."""
        await troubleshoot_add.handler({
            "category": "runtime",
            "error_message": "Error",
            "solution": "Solution"
        })

        with open(temp_project_dir / TROUBLESHOOTING_FILE) as f:
            data = json.load(f)

        timestamp = data["entries"][0]["timestamp"]
        # Should be valid ISO format
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class TestTroubleshootGetRecent:
    """Tests for troubleshoot_get_recent tool."""

    @pytest.mark.asyncio
    async def test_get_recent_default(self, project_with_troubleshooting):
        """Test getting recent entries with default count."""
        result = await troubleshoot_get_recent.handler({})
        text = result["content"][0]["text"]

        # Should show entries (default is 5, we have 4)
        assert "#4" in text
        assert "#1" in text

    @pytest.mark.asyncio
    async def test_get_recent_limited(self, project_with_troubleshooting):
        """Test getting limited recent entries."""
        result = await troubleshoot_get_recent.handler({"count": 2})
        text = result["content"][0]["text"]

        assert "2 shown" in text
        assert "#4" in text
        assert "#3" in text

    @pytest.mark.asyncio
    async def test_get_recent_empty(self, temp_project_dir):
        """Test getting recent from empty database."""
        result = await troubleshoot_get_recent.handler({"count": 5})
        text = result["content"][0]["text"]

        assert "knowledge base is empty" in text

    @pytest.mark.asyncio
    async def test_get_recent_caps_at_20(self, project_with_troubleshooting):
        """Test that count is capped at 20."""
        result = await troubleshoot_get_recent.handler({"count": 100})
        text = result["content"][0]["text"]

        # Should still work without error
        assert "TROUBLESHOOTING" in text


class TestTroubleshootGetByCategory:
    """Tests for troubleshoot_get_by_category tool."""

    @pytest.mark.asyncio
    async def test_get_by_category(self, project_with_troubleshooting):
        """Test getting entries by category."""
        result = await troubleshoot_get_by_category.handler({"category": "build"})
        text = result["content"][0]["text"]

        assert "BUILD" in text
        assert "2 entries" in text
        assert "Module not found" in text
        assert "TypeScript error" in text

    @pytest.mark.asyncio
    async def test_get_by_category_empty(self, project_with_troubleshooting):
        """Test category with no entries."""
        result = await troubleshoot_get_by_category.handler({"category": "database"})
        text = result["content"][0]["text"]

        assert "No troubleshooting entries found for category" in text

    @pytest.mark.asyncio
    async def test_get_by_invalid_category(self, project_with_troubleshooting):
        """Test invalid category."""
        result = await troubleshoot_get_by_category.handler({"category": "notacategory"})
        text = result["content"][0]["text"]

        assert "Unknown category" in text
        assert "Available categories" in text

    @pytest.mark.asyncio
    async def test_get_by_category_case_insensitive(self, project_with_troubleshooting):
        """Test case-insensitive category lookup."""
        result = await troubleshoot_get_by_category.handler({"category": "BUILD"})
        text = result["content"][0]["text"]

        assert "2 entries" in text


class TestTroubleshootListCategories:
    """Tests for troubleshoot_list_categories tool."""

    @pytest.mark.asyncio
    async def test_list_categories(self, project_with_troubleshooting):
        """Test listing categories with counts."""
        result = await troubleshoot_list_categories.handler({})
        text = result["content"][0]["text"]

        assert "TROUBLESHOOTING KNOWLEDGE BASE" in text
        assert "Total entries: 4" in text
        assert "build" in text
        assert "2" in text  # 2 build entries
        assert "styling" in text
        assert "runtime" in text

    @pytest.mark.asyncio
    async def test_list_categories_empty(self, temp_project_dir):
        """Test listing categories with empty database."""
        result = await troubleshoot_list_categories.handler({})
        text = result["content"][0]["text"]

        assert "No troubleshooting entries found" in text

    @pytest.mark.asyncio
    async def test_list_shows_common_tags(self, project_with_troubleshooting):
        """Test that common tags are shown."""
        result = await troubleshoot_list_categories.handler({})
        text = result["content"][0]["text"]

        assert "Common tags:" in text


class TestCreateTroubleshootingToolsServer:
    """Tests for create_troubleshooting_tools_server function."""

    def test_creates_server(self, temp_project_dir):
        """Test that server is created successfully."""
        server = create_troubleshooting_tools_server(temp_project_dir)

        assert server is not None
        assert isinstance(server, dict)
        assert server.get("type") == "sdk"
        assert server.get("name") == "troubleshooting"

    def test_sets_project_dir(self, temp_project_dir):
        """Test that project directory is set correctly."""
        create_troubleshooting_tools_server(temp_project_dir)

        assert troubleshooting_tools._project_dir == temp_project_dir


class TestTroubleshootingToolsList:
    """Tests for TROUBLESHOOTING_TOOLS constant."""

    def test_all_tools_listed(self):
        """Test that all tools are in the list."""
        expected_tools = [
            "mcp__troubleshooting__troubleshoot_search",
            "mcp__troubleshooting__troubleshoot_add",
            "mcp__troubleshooting__troubleshoot_get_recent",
            "mcp__troubleshooting__troubleshoot_get_by_category",
            "mcp__troubleshooting__troubleshoot_list_categories",
        ]

        assert TROUBLESHOOTING_TOOLS == expected_tools

    def test_tool_count(self):
        """Test correct number of tools."""
        assert len(TROUBLESHOOTING_TOOLS) == 5


class TestCategories:
    """Tests for CATEGORIES constant."""

    def test_categories_exist(self):
        """Test that categories are defined."""
        assert len(CATEGORIES) > 0

    def test_common_categories_present(self):
        """Test that common categories are present."""
        assert "build" in CATEGORIES
        assert "runtime" in CATEGORIES
        assert "dependency" in CATEGORIES
        assert "config" in CATEGORIES
        assert "other" in CATEGORIES


class TestTroubleshootingFileHandling:
    """Tests for file handling edge cases."""

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self, temp_project_dir):
        """Test handling of malformed JSON file."""
        with open(temp_project_dir / TROUBLESHOOTING_FILE, "w") as f:
            f.write("not valid json {")

        result = await troubleshoot_search.handler({"query": "test"})
        text = result["content"][0]["text"]

        # Should handle gracefully
        assert "knowledge base is empty" in text

    @pytest.mark.asyncio
    async def test_handles_missing_entries_key(self, temp_project_dir):
        """Test handling JSON without entries key."""
        with open(temp_project_dir / TROUBLESHOOTING_FILE, "w") as f:
            json.dump({"other_key": "value"}, f)

        result = await troubleshoot_search.handler({"query": "test"})
        text = result["content"][0]["text"]

        # Should handle gracefully
        assert "knowledge base is empty" in text

    @pytest.mark.asyncio
    async def test_id_increments_correctly(self, temp_project_dir):
        """Test that IDs increment correctly."""
        # Add first entry
        await troubleshoot_add.handler({
            "category": "build",
            "error_message": "Error 1",
            "solution": "Solution 1"
        })

        # Add second entry
        await troubleshoot_add.handler({
            "category": "runtime",
            "error_message": "Error 2",
            "solution": "Solution 2"
        })

        with open(temp_project_dir / TROUBLESHOOTING_FILE) as f:
            data = json.load(f)

        assert data["entries"][0]["id"] == 1
        assert data["entries"][1]["id"] == 2


class TestEntryFormatting:
    """Tests for entry formatting."""

    @pytest.mark.asyncio
    async def test_verbose_format_includes_all_fields(self, project_with_troubleshooting):
        """Test that verbose format includes all fields."""
        result = await troubleshoot_search.handler({"query": "npm"})
        text = result["content"][0]["text"]

        assert "Symptoms:" in text
        assert "Cause:" in text
        assert "Solution:" in text
        assert "Steps to fix:" in text
        assert "Prevention:" in text
        assert "Tags:" in text

    @pytest.mark.asyncio
    async def test_brief_format_omits_some_fields(self, project_with_troubleshooting):
        """Test that brief format omits detailed fields."""
        result = await troubleshoot_get_recent.handler({"count": 1})
        text = result["content"][0]["text"]

        # Brief format should still show key info
        assert "Error:" in text
        assert "Solution:" in text


class TestSearchMultipleFields:
    """Tests for searching across multiple fields."""

    @pytest.mark.asyncio
    async def test_search_finds_in_cause(self, project_with_troubleshooting):
        """Test searching finds matches in cause field."""
        result = await troubleshoot_search.handler({"query": "specificity"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "CSS" in text

    @pytest.mark.asyncio
    async def test_search_finds_in_steps(self, project_with_troubleshooting):
        """Test searching finds matches in steps_to_fix field."""
        result = await troubleshoot_search.handler({"query": "Restart dev server"})
        text = result["content"][0]["text"]

        assert "1 matches" in text

    @pytest.mark.asyncio
    async def test_search_finds_in_prevention(self, project_with_troubleshooting):
        """Test searching finds matches in prevention field."""
        result = await troubleshoot_search.handler({"query": "theming system"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
