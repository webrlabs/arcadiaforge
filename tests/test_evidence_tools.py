"""
Tests for Evidence Management MCP Tools
========================================

Tests for arcadiaforge/evidence_tools.py
"""

import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from arcadiaforge import evidence_tools
from arcadiaforge.evidence_tools import (
    set_project_dir,
    get_project_dir,
    evidence_set_context,
    evidence_save,
    evidence_list,
    evidence_get_latest,
)


class TestProjectDirManagement:
    """Tests for project directory management."""

    def test_set_and_get_project_dir(self, tmp_path):
        """Test setting and getting project directory."""
        set_project_dir(tmp_path)
        assert get_project_dir() == tmp_path

    def test_get_project_dir_fallback(self):
        """Test that get_project_dir falls back to cwd when not set."""
        evidence_tools._project_dir = None
        result = get_project_dir()
        assert result == Path.cwd()


class TestEvidenceSetContext:
    """Tests for evidence_set_context()"""

    @patch('arcadiaforge.evidence_tools.screenshot_hook')
    def test_set_context_basic(self, mock_hook):
        """Test setting basic screenshot context."""
        result = evidence_set_context(feature_id=107)

        assert result["success"]
        assert "107" in result["message"]
        assert result["settings"]["feature_id"] == 107
        mock_hook.set_screenshot_context.assert_called_once()

    @patch('arcadiaforge.evidence_tools.screenshot_hook')
    def test_set_context_with_all_options(self, mock_hook):
        """Test setting context with all options."""
        result = evidence_set_context(
            feature_id=42,
            name="custom_name",
            auto_save=False,
            description="Test description"
        )

        assert result["success"]
        assert result["settings"]["feature_id"] == 42
        assert result["settings"]["custom_name"] == "custom_name"
        assert result["settings"]["auto_save"] is False
        assert result["settings"]["description"] == "Test description"

        mock_hook.set_screenshot_context.assert_called_once_with(
            name="custom_name",
            feature_id=42,
            auto_evidence=False,
            description="Test description"
        )

    @patch('arcadiaforge.evidence_tools.screenshot_hook')
    def test_set_context_returns_settings(self, mock_hook):
        """Test that context returns complete settings."""
        result = evidence_set_context(feature_id=99, description="Modal shown")

        assert "settings" in result
        assert result["settings"]["feature_id"] == 99
        assert result["settings"]["description"] == "Modal shown"
        assert result["settings"]["auto_save"] is True  # default


class TestEvidenceSave:
    """Tests for evidence_save()"""

    def test_save_from_latest_screenshot(self, tmp_path):
        """Test saving the latest screenshot as evidence."""
        set_project_dir(tmp_path)

        # Create screenshots directory with test files
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        old_screenshot = screenshots_dir / "old.png"
        old_screenshot.write_bytes(b"old image data")

        time.sleep(0.1)  # Ensure different mtime

        new_screenshot = screenshots_dir / "new.png"
        new_screenshot.write_bytes(b"new image data")

        result = evidence_save(feature_id=105)

        assert result["success"]
        assert result["feature_id"] == 105
        assert "new.png" in result["source"]

        # Check evidence was created
        evidence_path = tmp_path / "verification" / "feature_105_evidence.png"
        assert evidence_path.exists()
        assert evidence_path.read_bytes() == b"new image data"

    def test_save_specific_screenshot(self, tmp_path):
        """Test saving a specific screenshot as evidence."""
        set_project_dir(tmp_path)

        # Create a specific screenshot
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()
        source = screenshots_dir / "specific.png"
        source.write_bytes(b"specific image")

        result = evidence_save(
            feature_id=106,
            source_screenshot=str(source)
        )

        assert result["success"]
        assert result["feature_id"] == 106

        evidence_path = tmp_path / "verification" / "feature_106_evidence.png"
        assert evidence_path.exists()
        assert evidence_path.read_bytes() == b"specific image"

    def test_save_relative_path(self, tmp_path):
        """Test saving with relative screenshot path."""
        set_project_dir(tmp_path)

        # Create screenshot in project-relative path
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()
        source = screenshots_dir / "relative.png"
        source.write_bytes(b"relative image")

        result = evidence_save(
            feature_id=107,
            source_screenshot="screenshots/relative.png"
        )

        assert result["success"]
        assert result["feature_id"] == 107

    def test_save_no_screenshots_dir(self, tmp_path):
        """Test save fails gracefully when no screenshots directory."""
        set_project_dir(tmp_path)

        result = evidence_save(feature_id=100)

        assert not result["success"]
        assert "No screenshots directory" in result["error"]

    def test_save_no_screenshots_found(self, tmp_path):
        """Test save fails gracefully when no screenshots exist."""
        set_project_dir(tmp_path)
        (tmp_path / "screenshots").mkdir()

        result = evidence_save(feature_id=100)

        assert not result["success"]
        assert "No screenshots found" in result["error"]

    def test_save_source_not_found(self, tmp_path):
        """Test save fails gracefully when source doesn't exist."""
        set_project_dir(tmp_path)

        result = evidence_save(
            feature_id=100,
            source_screenshot="nonexistent.png"
        )

        assert not result["success"]
        assert "not found" in result["error"]

    def test_save_creates_verification_dir(self, tmp_path):
        """Test that save creates verification directory if needed."""
        set_project_dir(tmp_path)

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_bytes(b"test")

        # verification dir doesn't exist yet
        assert not (tmp_path / "verification").exists()

        result = evidence_save(feature_id=50)

        assert result["success"]
        assert (tmp_path / "verification").exists()


class TestEvidenceList:
    """Tests for evidence_list()"""

    def test_list_empty(self, tmp_path):
        """Test listing when no evidence exists."""
        set_project_dir(tmp_path)

        result = evidence_list()

        assert result["success"]
        assert result["evidence"] == []
        assert result["count"] == 0

    def test_list_all_evidence(self, tmp_path):
        """Test listing all evidence files."""
        set_project_dir(tmp_path)

        verification_dir = tmp_path / "verification"
        verification_dir.mkdir()
        (verification_dir / "feature_101_evidence.png").write_bytes(b"1")
        (verification_dir / "feature_102_evidence.png").write_bytes(b"2")
        (verification_dir / "feature_103_evidence.png").write_bytes(b"3")

        result = evidence_list()

        assert result["success"]
        assert result["count"] == 3
        assert len(result["evidence"]) == 3

        # Should be sorted by feature ID
        feature_ids = [e["feature_id"] for e in result["evidence"]]
        assert feature_ids == [101, 102, 103]

    def test_list_filtered_by_ids(self, tmp_path):
        """Test listing evidence filtered by feature IDs."""
        set_project_dir(tmp_path)

        verification_dir = tmp_path / "verification"
        verification_dir.mkdir()
        (verification_dir / "feature_101_evidence.png").write_bytes(b"1")
        (verification_dir / "feature_102_evidence.png").write_bytes(b"2")
        (verification_dir / "feature_103_evidence.png").write_bytes(b"3")

        result = evidence_list(feature_ids=[101, 103])

        assert result["success"]
        assert result["count"] == 2
        feature_ids = [e["feature_id"] for e in result["evidence"]]
        assert feature_ids == [101, 103]

    def test_list_returns_metadata(self, tmp_path):
        """Test that list returns file metadata."""
        set_project_dir(tmp_path)

        verification_dir = tmp_path / "verification"
        verification_dir.mkdir()
        evidence_file = verification_dir / "feature_50_evidence.png"
        evidence_file.write_bytes(b"test content here")

        result = evidence_list()

        assert result["success"]
        assert result["count"] == 1

        evidence = result["evidence"][0]
        assert evidence["feature_id"] == 50
        assert evidence["filename"] == "feature_50_evidence.png"
        assert evidence["size"] > 0
        assert "modified" in evidence
        assert "path" in evidence

    def test_list_ignores_invalid_filenames(self, tmp_path):
        """Test that list ignores files with invalid naming."""
        set_project_dir(tmp_path)

        verification_dir = tmp_path / "verification"
        verification_dir.mkdir()
        (verification_dir / "feature_100_evidence.png").write_bytes(b"valid")
        (verification_dir / "random_file.png").write_bytes(b"invalid")
        (verification_dir / "feature_abc_evidence.png").write_bytes(b"invalid")

        result = evidence_list()

        assert result["success"]
        assert result["count"] == 1
        assert result["evidence"][0]["feature_id"] == 100


class TestEvidenceGetLatest:
    """Tests for evidence_get_latest()"""

    def test_get_latest_empty(self, tmp_path):
        """Test getting latest when no screenshots exist."""
        set_project_dir(tmp_path)

        result = evidence_get_latest()

        assert result["success"]
        assert result["screenshots"] == []
        assert result["count"] == 0

    def test_get_latest_no_directory(self, tmp_path):
        """Test getting latest when screenshots dir doesn't exist."""
        set_project_dir(tmp_path)

        result = evidence_get_latest()

        assert result["success"]
        assert result["count"] == 0

    def test_get_latest_default_count(self, tmp_path):
        """Test getting latest with default count."""
        set_project_dir(tmp_path)

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # Create 10 screenshots with different times
        for i in range(10):
            f = screenshots_dir / f"screenshot_{i}.png"
            f.write_bytes(f"content {i}".encode())
            time.sleep(0.05)

        result = evidence_get_latest()

        assert result["success"]
        assert result["count"] == 5  # default
        assert result["total_available"] == 10

    def test_get_latest_custom_count(self, tmp_path):
        """Test getting latest with custom count."""
        set_project_dir(tmp_path)

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        for i in range(5):
            f = screenshots_dir / f"screenshot_{i}.png"
            f.write_bytes(f"content {i}".encode())
            time.sleep(0.05)

        result = evidence_get_latest(count=3)

        assert result["success"]
        assert result["count"] == 3
        assert result["total_available"] == 5

    def test_get_latest_sorted_by_time(self, tmp_path):
        """Test that latest screenshots are sorted by modification time."""
        set_project_dir(tmp_path)

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # Create old screenshot
        old = screenshots_dir / "old.png"
        old.write_bytes(b"old")

        time.sleep(0.1)

        # Create new screenshot
        new = screenshots_dir / "new.png"
        new.write_bytes(b"new")

        result = evidence_get_latest(count=2)

        assert result["success"]
        assert result["count"] == 2
        # Most recent should be first
        assert result["screenshots"][0]["filename"] == "new.png"
        assert result["screenshots"][1]["filename"] == "old.png"

    def test_get_latest_returns_metadata(self, tmp_path):
        """Test that latest returns file metadata."""
        set_project_dir(tmp_path)

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_bytes(b"test content")

        result = evidence_get_latest()

        assert result["success"]
        assert result["count"] == 1

        screenshot = result["screenshots"][0]
        assert "path" in screenshot
        assert screenshot["filename"] == "test.png"
        assert screenshot["size"] > 0
        assert "modified" in screenshot


class TestEvidenceToolsList:
    """Tests for EVIDENCE_TOOLS constant."""

    def test_evidence_tools_contains_all_tools(self):
        """Test that EVIDENCE_TOOLS lists all available tools."""
        from arcadiaforge.evidence_tools import EVIDENCE_TOOLS

        expected_tools = [
            "mcp__evidence__evidence_set_context",
            "mcp__evidence__evidence_save",
            "mcp__evidence__evidence_list",
            "mcp__evidence__evidence_get_latest",
        ]

        assert EVIDENCE_TOOLS == expected_tools


class TestCreateEvidenceToolsServer:
    """Tests for create_evidence_tools_server()"""

    def test_creates_server_config(self, tmp_path):
        """Test creating server configuration."""
        from arcadiaforge.evidence_tools import create_evidence_tools_server

        config = create_evidence_tools_server(tmp_path)

        assert config["type"] == "stdio"
        assert config["command"] == "python"
        assert "-m" in config["args"]
        assert "arcadiaforge.evidence_tools" in config["args"]
        assert config["cwd"] == str(tmp_path)

    def test_sets_project_dir(self, tmp_path):
        """Test that creating server sets project directory."""
        from arcadiaforge.evidence_tools import create_evidence_tools_server

        create_evidence_tools_server(tmp_path)

        assert get_project_dir() == tmp_path
