"""
Tests for feature_tools.py - Custom MCP tools for feature list management.
"""

import asyncio
import json
import tempfile
import shutil
from pathlib import Path
import pytest

from arcadiaforge import feature_tools
from arcadiaforge.feature_tools import (
    create_feature_tools_server,
    feature_stats,
    feature_next,
    feature_show,
    feature_list,
    feature_search,
    feature_mark,
    FEATURE_TOOLS,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    tmp_dir = Path(tempfile.mkdtemp())
    # Set the global project directory
    feature_tools._project_dir = tmp_dir
    yield tmp_dir
    # Cleanup
    shutil.rmtree(tmp_dir)


@pytest.fixture
def sample_features():
    """Sample feature list for testing."""
    return [
        {
            "category": "functional",
            "description": "User can log in with email and password",
            "steps": ["Navigate to login page", "Enter credentials", "Click submit", "Verify redirect"],
            "passes": True
        },
        {
            "category": "functional",
            "description": "User can register a new account",
            "steps": ["Navigate to register", "Fill form", "Submit"],
            "passes": False
        },
        {
            "category": "style",
            "description": "Dark mode toggle changes theme colors",
            "steps": ["Click toggle", "Verify dark colors"],
            "passes": False
        },
        {
            "category": "functional",
            "description": "User can reset password via email",
            "steps": ["Click forgot password", "Enter email", "Check inbox"],
            "passes": False
        },
        {
            "category": "style",
            "description": "Buttons have hover states",
            "steps": ["Hover over button", "Verify color change"],
            "passes": True
        },
    ]


@pytest.fixture
def project_with_features(temp_project_dir, sample_features):
    """Create a project with a feature_list.json file."""
    feature_file = temp_project_dir / "feature_list.json"
    with open(feature_file, "w", encoding="utf-8") as f:
        json.dump(sample_features, f, indent=2)
    return temp_project_dir


class TestFeatureStats:
    """Tests for feature_stats tool."""

    @pytest.mark.asyncio
    async def test_stats_with_features(self, project_with_features):
        """Test stats with existing features."""
        result = await feature_stats.handler({})
        text = result["content"][0]["text"]

        assert "Total features:    5" in text
        assert "Passing:           2" in text
        assert "Failing:           3" in text
        # 3 functional features (1 passing), 2 style features (1 passing)
        assert "Functional:      1/3" in text
        assert "Style:           1/2" in text

    @pytest.mark.asyncio
    async def test_stats_no_file(self, temp_project_dir):
        """Test stats when feature_list.json doesn't exist."""
        result = await feature_stats.handler({})
        text = result["content"][0]["text"]

        assert "not found or empty" in text

    @pytest.mark.asyncio
    async def test_stats_empty_file(self, temp_project_dir):
        """Test stats with empty feature list."""
        feature_file = temp_project_dir / "feature_list.json"
        with open(feature_file, "w") as f:
            json.dump([], f)

        result = await feature_stats.handler({})
        text = result["content"][0]["text"]

        assert "not found or empty" in text


class TestFeatureNext:
    """Tests for feature_next tool."""

    @pytest.mark.asyncio
    async def test_next_single(self, project_with_features):
        """Test getting next single feature."""
        result = await feature_next.handler({"count": 1})
        text = result["content"][0]["text"]

        assert "[#1]" in text
        assert "register" in text.lower()
        assert "Test Steps:" in text

    @pytest.mark.asyncio
    async def test_next_multiple(self, project_with_features):
        """Test getting multiple next features."""
        result = await feature_next.handler({"count": 3})
        text = result["content"][0]["text"]

        assert "[#1]" in text
        assert "[#2]" in text
        assert "[#3]" in text

    @pytest.mark.asyncio
    async def test_next_all_complete(self, temp_project_dir):
        """Test when all features are complete."""
        features = [
            {"category": "functional", "description": "Test", "steps": ["Step 1"], "passes": True}
        ]
        with open(temp_project_dir / "feature_list.json", "w") as f:
            json.dump(features, f)

        result = await feature_next.handler({"count": 1})
        text = result["content"][0]["text"]

        assert "ALL FEATURES COMPLETE" in text

    @pytest.mark.asyncio
    async def test_next_default_count(self, project_with_features):
        """Test default count of 1."""
        result = await feature_next.handler({})
        text = result["content"][0]["text"]

        assert "NEXT 1 FEATURE" in text


class TestFeatureShow:
    """Tests for feature_show tool."""

    @pytest.mark.asyncio
    async def test_show_passing_feature(self, project_with_features):
        """Test showing a passing feature."""
        result = await feature_show.handler({"index": 0})
        text = result["content"][0]["text"]

        assert "FEATURE #0" in text
        assert "PASSING" in text
        assert "log in" in text.lower()

    @pytest.mark.asyncio
    async def test_show_failing_feature(self, project_with_features):
        """Test showing a failing feature."""
        result = await feature_show.handler({"index": 1})
        text = result["content"][0]["text"]

        assert "FEATURE #1" in text
        assert "FAILING" in text
        assert "register" in text.lower()

    @pytest.mark.asyncio
    async def test_show_invalid_index(self, project_with_features):
        """Test showing feature with invalid index."""
        result = await feature_show.handler({"index": 999})

        assert result.get("is_error") is True
        assert "not found" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_show_negative_index(self, project_with_features):
        """Test showing feature with negative index."""
        result = await feature_show.handler({"index": -1})

        assert result.get("is_error") is True


class TestFeatureList:
    """Tests for feature_list tool."""

    @pytest.mark.asyncio
    async def test_list_incomplete(self, project_with_features):
        """Test listing incomplete features."""
        result = await feature_list.handler({"passing": False})
        text = result["content"][0]["text"]

        assert "INCOMPLETE FEATURES (3 total)" in text
        assert "#  1" in text
        assert "#  2" in text
        assert "#  3" in text

    @pytest.mark.asyncio
    async def test_list_passing(self, project_with_features):
        """Test listing passing features."""
        result = await feature_list.handler({"passing": True})
        text = result["content"][0]["text"]

        assert "PASSING FEATURES (2 total)" in text
        assert "#  0" in text
        assert "#  4" in text

    @pytest.mark.asyncio
    async def test_list_default_incomplete(self, project_with_features):
        """Test default lists incomplete features."""
        result = await feature_list.handler({})
        text = result["content"][0]["text"]

        assert "INCOMPLETE" in text


class TestFeatureSearch:
    """Tests for feature_search tool."""

    @pytest.mark.asyncio
    async def test_search_found(self, project_with_features):
        """Test searching and finding features."""
        result = await feature_search.handler({"query": "dark mode"})
        text = result["content"][0]["text"]

        assert "1 matches" in text
        assert "dark mode" in text.lower()

    @pytest.mark.asyncio
    async def test_search_multiple_matches(self, project_with_features):
        """Test searching with multiple matches."""
        result = await feature_search.handler({"query": "user"})
        text = result["content"][0]["text"]

        # Should match "User can log in" and "User can register" and "User can reset"
        assert "3 matches" in text

    @pytest.mark.asyncio
    async def test_search_no_matches(self, project_with_features):
        """Test searching with no matches."""
        result = await feature_search.handler({"query": "xyz123nonexistent"})
        text = result["content"][0]["text"]

        assert "0 matches" in text

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, project_with_features):
        """Test case-insensitive search."""
        result = await feature_search.handler({"query": "DARK"})
        text = result["content"][0]["text"]

        assert "1 matches" in text


class TestFeatureMark:
    """Tests for feature_mark tool."""

    @pytest.mark.asyncio
    async def test_mark_as_passing(self, project_with_features):
        """Test marking a feature as passing."""
        verification_dir = project_with_features / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)
        (verification_dir / "feature_1_test.png").write_bytes(b"fake")

        result = await feature_mark.handler({"index": 1})
        text = result["content"][0]["text"]

        assert "Marked feature #1 as PASSING" in text
        assert "Progress:" in text

        # Verify file was updated
        with open(project_with_features / "feature_list.json") as f:
            features = json.load(f)
        assert features[1]["passes"] is True

    @pytest.mark.asyncio
    async def test_mark_already_passing(self, project_with_features):
        """Test marking an already passing feature."""
        result = await feature_mark.handler({"index": 0})
        text = result["content"][0]["text"]

        assert "already marked as passing" in text

    @pytest.mark.asyncio
    async def test_mark_invalid_index(self, project_with_features):
        """Test marking with invalid index."""
        result = await feature_mark.handler({"index": 999})

        assert result.get("is_error") is True
        assert "not found" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_mark_updates_stats(self, project_with_features):
        """Test that marking updates the stats correctly."""
        # Mark feature #1
        verification_dir = project_with_features / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)
        (verification_dir / "feature_1_test.png").write_bytes(b"fake")

        result = await feature_mark.handler({"index": 1})

        # Check stats
        stats_result = await feature_stats.handler({})
        text = stats_result["content"][0]["text"]

        assert "Passing:           3" in text  # Was 2, now 3


class TestCreateFeatureToolsServer:
    """Tests for create_feature_tools_server function."""

    def test_creates_server(self, temp_project_dir):
        """Test that server is created successfully."""
        server = create_feature_tools_server(temp_project_dir)

        assert server is not None
        assert isinstance(server, dict)
        assert server.get("type") == "sdk"
        assert server.get("name") == "features"

    def test_sets_project_dir(self, temp_project_dir):
        """Test that project directory is set correctly."""
        create_feature_tools_server(temp_project_dir)

        assert feature_tools._project_dir == temp_project_dir


class TestFeatureToolsList:
    """Tests for FEATURE_TOOLS constant."""

    def test_all_tools_listed(self):
        """Test that all tools are in the list."""
        expected_tools = [
            "mcp__features__feature_stats",
            "mcp__features__feature_next",
            "mcp__features__feature_show",
            "mcp__features__feature_list",
            "mcp__features__feature_search",
            "mcp__features__feature_mark",
            "mcp__features__feature_audit",
            "mcp__features__feature_audit_list",
        ]

        assert FEATURE_TOOLS == expected_tools

    def test_tool_count(self):
        """Test correct number of tools."""
        assert len(FEATURE_TOOLS) == 8


class TestObjectFormatFeatureList:
    """Tests for feature_list.json in object format."""

    @pytest.mark.asyncio
    async def test_object_format_with_features_key(self, temp_project_dir):
        """Test handling object format with 'features' key."""
        data = {
            "features": [
                {"category": "functional", "description": "Test", "steps": ["Step"], "passes": True}
            ]
        }
        with open(temp_project_dir / "feature_list.json", "w") as f:
            json.dump(data, f)

        result = await feature_stats.handler({})
        text = result["content"][0]["text"]

        assert "Total features:    1" in text
        assert "Passing:           1" in text
