"""
Tests for the artifact store module.
"""

import json
import tempfile
from pathlib import Path

import pytest

from arcadiaforge.artifact_store import (
    Artifact,
    ArtifactStore,
    ArtifactType,
    create_artifact_store,
    find_verification_screenshots,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def store(temp_project_dir):
    """Create an ArtifactStore for testing."""
    return ArtifactStore(temp_project_dir)


@pytest.fixture
def sample_file(temp_project_dir):
    """Create a sample file for testing."""
    file_path = temp_project_dir / "sample.txt"
    file_path.write_text("Hello, World!")
    return file_path


@pytest.fixture
def sample_screenshot(temp_project_dir):
    """Create a sample screenshot file for testing."""
    # Create verification directory
    verification_dir = temp_project_dir / "verification"
    verification_dir.mkdir(exist_ok=True)

    # Create a fake PNG file (just bytes for testing)
    screenshot_path = verification_dir / "feature_0_login.png"
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake image data")
    return screenshot_path


class TestArtifact:
    """Tests for the Artifact dataclass."""

    def test_artifact_to_dict(self):
        """Test Artifact serialization to dict."""
        artifact = Artifact(
            artifact_id="ART-1-1",
            timestamp="2025-12-18T10:30:00+00:00",
            artifact_type="screenshot",
            session_id=1,
            original_name="screenshot.png",
            stored_path="session_1/screenshots/ART-1-1_screenshot.png",
            checksum="abc123",
            size_bytes=1024,
            feature_index=5,
        )

        result = artifact.to_dict()

        assert result["artifact_id"] == "ART-1-1"
        assert result["artifact_type"] == "screenshot"
        assert result["feature_index"] == 5

    def test_artifact_from_dict(self):
        """Test Artifact deserialization from dict."""
        data = {
            "artifact_id": "ART-2-5",
            "timestamp": "2025-12-18T11:00:00+00:00",
            "artifact_type": "test_result",
            "session_id": 2,
            "original_name": "results.json",
            "stored_path": "session_2/test_results/ART-2-5_results.json",
            "checksum": "def456",
            "size_bytes": 512,
            "feature_index": 10,
            "description": "Test results",
            "metadata": {"pass_count": 5},
            "parent_artifact_id": None,
            "related_artifacts": [],
        }

        artifact = Artifact.from_dict(data)

        assert artifact.artifact_id == "ART-2-5"
        assert artifact.feature_index == 10
        assert artifact.metadata["pass_count"] == 5

    def test_artifact_roundtrip(self):
        """Test Artifact can be serialized and deserialized."""
        original = Artifact(
            artifact_id="ART-3-1",
            timestamp="2025-12-18T12:00:00+00:00",
            artifact_type="screenshot",
            session_id=3,
            original_name="test.png",
            stored_path="session_3/screenshots/test.png",
            checksum="xyz789",
            size_bytes=2048,
            metadata={"key": "value"},
        )

        serialized = original.to_dict()
        restored = Artifact.from_dict(serialized)

        assert restored.artifact_id == original.artifact_id
        assert restored.metadata == original.metadata

    def test_artifact_summary(self):
        """Test Artifact summary method."""
        artifact = Artifact(
            artifact_id="ART-1-1",
            timestamp="2025-12-18T10:30:00+00:00",
            artifact_type="screenshot",
            session_id=1,
            original_name="login.png",
            stored_path="path/to/file",
            checksum="abc",
            size_bytes=100,
            feature_index=5,
        )

        summary = artifact.summary()

        assert "ART-1-1" in summary
        assert "screenshot" in summary
        assert "feature=#5" in summary
        assert "login.png" in summary


class TestArtifactStore:
    """Tests for the ArtifactStore class."""

    def test_initialization(self, temp_project_dir):
        """Test ArtifactStore creates correct paths."""
        store = ArtifactStore(temp_project_dir)

        assert store.project_dir == temp_project_dir
        assert store.artifacts_dir == temp_project_dir / ".artifacts"
        assert store.index_file == temp_project_dir / ".artifacts" / "index.json"
        assert store.artifacts_dir.exists()

    def test_store_file(self, store, sample_file, temp_project_dir):
        """Test storing a file artifact."""
        artifact = store.store(
            artifact_type=ArtifactType.LOG,
            source_path=sample_file,
            session_id=1,
        )

        assert artifact is not None
        assert artifact.artifact_id.startswith("ART-1-")
        assert artifact.artifact_type == "log"
        assert artifact.session_id == 1
        assert artifact.original_name == "sample.txt"
        assert artifact.size_bytes == 13  # "Hello, World!" = 13 bytes

    def test_store_with_metadata(self, store, sample_file):
        """Test storing artifact with metadata."""
        artifact = store.store(
            artifact_type=ArtifactType.SCREENSHOT,
            source_path=sample_file,
            session_id=2,
            feature_index=42,
            description="Login screenshot",
            metadata={"resolution": "1920x1080"},
        )

        assert artifact.feature_index == 42
        assert artifact.description == "Login screenshot"
        assert artifact.metadata["resolution"] == "1920x1080"

    def test_store_creates_session_directory(self, store, sample_file, temp_project_dir):
        """Test that storing creates session directory structure."""
        store.store(
            artifact_type=ArtifactType.SCREENSHOT,
            source_path=sample_file,
            session_id=5,
        )

        session_dir = temp_project_dir / ".artifacts" / "session_5" / "screenshots"
        assert session_dir.exists()

    def test_store_copies_file(self, store, sample_file, temp_project_dir):
        """Test that file is actually copied to store."""
        artifact = store.store(
            artifact_type=ArtifactType.LOG,
            source_path=sample_file,
            session_id=1,
        )

        stored_path = temp_project_dir / ".artifacts" / artifact.stored_path
        assert stored_path.exists()
        assert stored_path.read_text() == "Hello, World!"

    def test_store_content(self, store):
        """Test storing content directly."""
        content = '{"test": "data"}'
        artifact = store.store_content(
            artifact_type=ArtifactType.TEST_RESULT,
            content=content,
            filename="results.json",
            session_id=1,
            feature_index=5,
        )

        assert artifact is not None
        assert artifact.original_name == "results.json"

        # Verify content was stored
        stored_path = store.get_path(artifact.artifact_id)
        assert stored_path.read_text() == content

    def test_store_binary_content(self, store):
        """Test storing binary content."""
        content = b"\x89PNG\r\n\x1a\nfake image"
        artifact = store.store_content(
            artifact_type=ArtifactType.SCREENSHOT,
            content=content,
            filename="test.png",
            session_id=1,
        )

        stored_path = store.get_path(artifact.artifact_id)
        assert stored_path.read_bytes() == content

    def test_get_artifact(self, store, sample_file):
        """Test retrieving artifact by ID."""
        created = store.store(
            artifact_type=ArtifactType.LOG,
            source_path=sample_file,
            session_id=1,
        )

        retrieved = store.get(created.artifact_id)

        assert retrieved is not None
        assert retrieved.artifact_id == created.artifact_id
        assert retrieved.checksum == created.checksum

    def test_get_artifact_not_found(self, store):
        """Test getting non-existent artifact."""
        result = store.get("ART-nonexistent")
        assert result is None

    def test_get_path(self, store, sample_file, temp_project_dir):
        """Test getting full path to stored artifact."""
        artifact = store.store(
            artifact_type=ArtifactType.LOG,
            source_path=sample_file,
            session_id=1,
        )

        path = store.get_path(artifact.artifact_id)

        assert path is not None
        assert path.exists()
        assert path.parent.parent.name == "session_1"

    def test_list_artifacts(self, store, sample_file):
        """Test listing all artifacts."""
        store.store(ArtifactType.LOG, sample_file, session_id=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1)
        store.store(ArtifactType.TEST_RESULT, sample_file, session_id=2)

        artifacts = store.list_artifacts()

        assert len(artifacts) == 3

    def test_list_artifacts_filter_by_session(self, store, sample_file):
        """Test filtering artifacts by session."""
        store.store(ArtifactType.LOG, sample_file, session_id=1)
        store.store(ArtifactType.LOG, sample_file, session_id=2)
        store.store(ArtifactType.LOG, sample_file, session_id=1)

        session1 = store.list_artifacts(session_id=1)
        session2 = store.list_artifacts(session_id=2)

        assert len(session1) == 2
        assert len(session2) == 1

    def test_list_artifacts_filter_by_type(self, store, sample_file):
        """Test filtering artifacts by type."""
        store.store(ArtifactType.LOG, sample_file, session_id=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1)

        screenshots = store.list_artifacts(artifact_type=ArtifactType.SCREENSHOT)
        logs = store.list_artifacts(artifact_type=ArtifactType.LOG)

        assert len(screenshots) == 2
        assert len(logs) == 1

    def test_list_artifacts_filter_by_feature(self, store, sample_file):
        """Test filtering artifacts by feature index."""
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=2)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=1)

        feature1 = store.list_artifacts(feature_index=1)
        feature2 = store.list_artifacts(feature_index=2)

        assert len(feature1) == 2
        assert len(feature2) == 1

    def test_list_artifacts_with_limit(self, store, sample_file):
        """Test limiting number of artifacts returned."""
        for _ in range(10):
            store.store(ArtifactType.LOG, sample_file, session_id=1)

        artifacts = store.list_artifacts(limit=5)

        assert len(artifacts) == 5

    def test_list_for_feature(self, store, sample_file):
        """Test listing artifacts for a specific feature."""
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=5)
        store.store(ArtifactType.TEST_RESULT, sample_file, session_id=1, feature_index=5)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=6)

        feature5_artifacts = store.list_for_feature(5)

        assert len(feature5_artifacts) == 2

    def test_get_verification_artifacts(self, store, sample_file):
        """Test getting verification artifacts."""
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=5)
        store.store(ArtifactType.TEST_RESULT, sample_file, session_id=1, feature_index=5)
        store.store(ArtifactType.LOG, sample_file, session_id=1, feature_index=5)

        verification = store.get_verification_artifacts(5)

        # Should include screenshot and test_result, not log
        assert len(verification) == 2
        types = {a.artifact_type for a in verification}
        assert "screenshot" in types
        assert "test_result" in types
        assert "log" not in types

    def test_has_verification(self, store, sample_file):
        """Test checking for verification artifacts."""
        assert not store.has_verification(5)

        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1, feature_index=5)

        assert store.has_verification(5)
        assert not store.has_verification(6)

    def test_delete_artifact(self, store, sample_file, temp_project_dir):
        """Test deleting an artifact."""
        artifact = store.store(ArtifactType.LOG, sample_file, session_id=1)
        artifact_id = artifact.artifact_id
        stored_path = temp_project_dir / ".artifacts" / artifact.stored_path

        assert stored_path.exists()

        result = store.delete(artifact_id)

        assert result is True
        assert store.get(artifact_id) is None
        assert not stored_path.exists()

    def test_delete_artifact_not_found(self, store):
        """Test deleting non-existent artifact."""
        result = store.delete("ART-nonexistent")
        assert result is False

    def test_cleanup_session(self, store, sample_file):
        """Test cleaning up all artifacts for a session."""
        store.store(ArtifactType.LOG, sample_file, session_id=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1)
        store.store(ArtifactType.LOG, sample_file, session_id=2)

        deleted = store.cleanup_session(1)

        assert deleted == 2
        assert len(store.list_artifacts(session_id=1)) == 0
        assert len(store.list_artifacts(session_id=2)) == 1

    def test_get_stats(self, store, sample_file):
        """Test getting artifact store statistics."""
        store.store(ArtifactType.LOG, sample_file, session_id=1)
        store.store(ArtifactType.SCREENSHOT, sample_file, session_id=1)
        store.store(ArtifactType.LOG, sample_file, session_id=2)

        stats = store.get_stats()

        assert stats["total_artifacts"] == 3
        assert stats["by_type"]["log"] == 2
        assert stats["by_type"]["screenshot"] == 1
        assert stats["by_session"][1] == 2
        assert stats["by_session"][2] == 1


class TestFindVerificationScreenshots:
    """Tests for the find_verification_screenshots helper."""

    def test_find_in_verification_dir(self, temp_project_dir):
        """Test finding screenshots in verification directory."""
        verification_dir = temp_project_dir / "verification"
        verification_dir.mkdir()

        (verification_dir / "feature_5_login.png").write_bytes(b"fake")
        (verification_dir / "feature_5_dashboard.png").write_bytes(b"fake")
        (verification_dir / "feature_6_other.png").write_bytes(b"fake")

        screenshots = find_verification_screenshots(temp_project_dir, 5)

        assert len(screenshots) == 2
        names = {s.name for s in screenshots}
        assert "feature_5_login.png" in names
        assert "feature_5_dashboard.png" in names

    def test_find_in_screenshots_dir(self, temp_project_dir):
        """Test finding screenshots in screenshots directory."""
        screenshots_dir = temp_project_dir / "screenshots"
        screenshots_dir.mkdir()

        (screenshots_dir / "feature_3_test.png").write_bytes(b"fake")

        screenshots = find_verification_screenshots(temp_project_dir, 3)

        assert len(screenshots) == 1
        assert screenshots[0].name == "feature_3_test.png"

    def test_find_jpg_files(self, temp_project_dir):
        """Test finding JPG screenshots."""
        verification_dir = temp_project_dir / "verification"
        verification_dir.mkdir()

        (verification_dir / "feature_1_test.jpg").write_bytes(b"fake")
        (verification_dir / "feature_1_test.jpeg").write_bytes(b"fake")

        screenshots = find_verification_screenshots(temp_project_dir, 1)

        assert len(screenshots) == 2

    def test_no_screenshots_found(self, temp_project_dir):
        """Test when no screenshots exist."""
        screenshots = find_verification_screenshots(temp_project_dir, 99)
        assert len(screenshots) == 0


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_artifact_store(self, temp_project_dir):
        """Test create_artifact_store factory function."""
        store = create_artifact_store(temp_project_dir)

        assert isinstance(store, ArtifactStore)
        assert store.project_dir == temp_project_dir


class TestChecksumVerification:
    """Tests for checksum computation."""

    def test_checksum_computed(self, store, sample_file):
        """Test that checksum is computed on store."""
        artifact = store.store(
            artifact_type=ArtifactType.LOG,
            source_path=sample_file,
            session_id=1,
        )

        assert artifact.checksum is not None
        assert len(artifact.checksum) == 64  # SHA256 hex = 64 chars

    def test_checksum_consistent(self, store, sample_file):
        """Test that same content produces same checksum."""
        artifact1 = store.store(ArtifactType.LOG, sample_file, session_id=1)

        # Create another file with same content
        another_file = sample_file.parent / "another.txt"
        another_file.write_text("Hello, World!")

        artifact2 = store.store(ArtifactType.LOG, another_file, session_id=1)

        assert artifact1.checksum == artifact2.checksum
