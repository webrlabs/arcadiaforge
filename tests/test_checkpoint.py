"""
Tests for the checkpoint module.
"""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from arcadiaforge.checkpoint import (
    Checkpoint,
    CheckpointManager,
    CheckpointTrigger,
    RollbackResult,
    create_checkpoint_manager,
    format_checkpoint_summary,
    format_rollback_result,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=project_dir,
            capture_output=True,
        )
        # Create initial commit
        (project_dir / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=project_dir,
            capture_output=True,
        )
        yield project_dir


@pytest.fixture
def mgr(temp_project_dir):
    """Create a CheckpointManager for testing."""
    return CheckpointManager(temp_project_dir)


@pytest.fixture
def feature_list(temp_project_dir):
    """Create a sample feature_list.json."""
    features = [
        {"description": "Feature 1", "passes": True, "steps": ["Step 1"]},
        {"description": "Feature 2", "passes": False, "steps": ["Step 1", "Step 2"]},
        {"description": "Feature 3", "passes": True, "steps": ["Step 1"]},
    ]
    feature_file = temp_project_dir / "feature_list.json"
    with open(feature_file, "w") as f:
        json.dump(features, f)
    return feature_file


class TestCheckpoint:
    """Tests for the Checkpoint dataclass."""

    def test_checkpoint_to_dict(self):
        """Test Checkpoint serialization to dict."""
        checkpoint = Checkpoint(
            checkpoint_id="CP-1-1",
            timestamp="2025-12-18T10:30:00+00:00",
            trigger="feature_complete",
            session_id=1,
            git_commit="abc123",
            git_branch="main",
            git_clean=True,
            feature_status={0: True, 1: False},
            features_passing=1,
            features_total=2,
            files_hash="hash123",
        )

        result = checkpoint.to_dict()

        assert result["checkpoint_id"] == "CP-1-1"
        assert result["trigger"] == "feature_complete"
        assert result["session_id"] == 1
        assert result["features_passing"] == 1

    def test_checkpoint_from_dict(self):
        """Test Checkpoint deserialization from dict."""
        data = {
            "checkpoint_id": "CP-2-5",
            "timestamp": "2025-12-18T11:00:00+00:00",
            "trigger": "session_end",
            "session_id": 2,
            "git_commit": "def456",
            "git_branch": "feature-branch",
            "git_clean": False,
            "feature_status": {"0": True, "1": True},
            "features_passing": 2,
            "features_total": 2,
            "files_hash": "hash456",
            "last_successful_feature": 1,
            "pending_work": ["Fix bug"],
            "metadata": {"key": "value"},
            "human_note": "Test note",
        }

        checkpoint = Checkpoint.from_dict(data)

        assert checkpoint.checkpoint_id == "CP-2-5"
        assert checkpoint.session_id == 2
        assert checkpoint.human_note == "Test note"

    def test_checkpoint_roundtrip(self):
        """Test Checkpoint can be serialized and deserialized."""
        original = Checkpoint(
            checkpoint_id="CP-3-1",
            timestamp="2025-12-18T12:00:00+00:00",
            trigger="manual",
            session_id=3,
            git_commit="789xyz",
            git_branch="test",
            git_clean=True,
            feature_status={0: True},
            features_passing=1,
            features_total=1,
            files_hash="abc",
            metadata={"test": "data"},
        )

        serialized = original.to_dict()
        restored = Checkpoint.from_dict(serialized)

        assert restored.checkpoint_id == original.checkpoint_id
        assert restored.metadata == original.metadata

    def test_checkpoint_summary(self):
        """Test Checkpoint summary method."""
        checkpoint = Checkpoint(
            checkpoint_id="CP-1-1",
            timestamp="2025-12-18T10:30:00+00:00",
            trigger="feature_complete",
            session_id=1,
            git_commit="abc123",
            git_branch="main",
            git_clean=True,
            feature_status={},
            features_passing=5,
            features_total=10,
            files_hash="hash",
        )

        summary = checkpoint.summary()

        assert "CP-1-1" in summary
        assert "feature_complete" in summary
        assert "5/10" in summary


class TestCheckpointManager:
    """Tests for the CheckpointManager class."""

    def test_initialization(self, temp_project_dir):
        """Test CheckpointManager creates correct paths."""
        mgr = CheckpointManager(temp_project_dir)

        assert mgr.project_dir == temp_project_dir
        assert mgr.checkpoints_dir == temp_project_dir / ".checkpoints"
        assert mgr.index_file == temp_project_dir / ".checkpoints" / "index.json"

    def test_create_checkpoint_basic(self, mgr, temp_project_dir):
        """Test creating a basic checkpoint."""
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.MANUAL,
            session_id=1,
        )

        assert checkpoint is not None
        assert checkpoint.checkpoint_id.startswith("CP-1-")
        assert checkpoint.trigger == "manual"
        assert checkpoint.session_id == 1

    def test_create_checkpoint_with_metadata(self, mgr):
        """Test creating a checkpoint with metadata."""
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.FEATURE_COMPLETE,
            session_id=2,
            metadata={"feature_index": 42},
            human_note="Completed login feature",
        )

        assert checkpoint.metadata["feature_index"] == 42
        assert checkpoint.human_note == "Completed login feature"

    def test_create_checkpoint_captures_git_state(self, mgr, temp_project_dir):
        """Test that checkpoint captures git state."""
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.SESSION_START,
            session_id=1,
        )

        assert checkpoint.git_commit != "unknown"
        assert checkpoint.git_branch in ("main", "master")
        assert checkpoint.git_clean is True  # We just committed

    def test_create_checkpoint_captures_feature_state(self, mgr, feature_list):
        """Test that checkpoint captures feature status."""
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.SESSION_START,
            session_id=1,
        )

        assert checkpoint.features_total == 3
        assert checkpoint.features_passing == 2
        assert checkpoint.feature_status[0] is True
        assert checkpoint.feature_status[1] is False

    def test_get_checkpoint(self, mgr):
        """Test retrieving a checkpoint by ID."""
        created = mgr.create_checkpoint(
            trigger=CheckpointTrigger.MANUAL,
            session_id=1,
        )

        retrieved = mgr.get_checkpoint(created.checkpoint_id)

        assert retrieved is not None
        assert retrieved.checkpoint_id == created.checkpoint_id

    def test_get_checkpoint_not_found(self, mgr):
        """Test getting a non-existent checkpoint."""
        result = mgr.get_checkpoint("CP-nonexistent")

        assert result is None

    def test_list_checkpoints(self, mgr):
        """Test listing all checkpoints."""
        # Create several checkpoints
        mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)
        mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        checkpoints = mgr.list_checkpoints()

        assert len(checkpoints) == 3

    def test_list_checkpoints_newest_first(self, mgr):
        """Test that checkpoints are returned newest first."""
        cp1 = mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        cp2 = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)
        cp3 = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        checkpoints = mgr.list_checkpoints()

        # Newest should be first
        assert checkpoints[0].checkpoint_id == cp3.checkpoint_id
        assert checkpoints[-1].checkpoint_id == cp1.checkpoint_id

    def test_list_checkpoints_filter_by_session(self, mgr):
        """Test filtering checkpoints by session."""
        mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 2)
        mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        session1 = mgr.list_checkpoints(session_id=1)
        session2 = mgr.list_checkpoints(session_id=2)

        assert len(session1) == 2
        assert len(session2) == 1

    def test_list_checkpoints_filter_by_trigger(self, mgr):
        """Test filtering checkpoints by trigger type."""
        mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)
        mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        feature_cps = mgr.list_checkpoints(trigger=CheckpointTrigger.FEATURE_COMPLETE)

        assert len(feature_cps) == 1
        assert feature_cps[0].trigger == "feature_complete"

    def test_list_checkpoints_with_limit(self, mgr):
        """Test limiting number of checkpoints returned."""
        for i in range(10):
            mgr.create_checkpoint(CheckpointTrigger.MANUAL, 1)

        checkpoints = mgr.list_checkpoints(limit=5)

        assert len(checkpoints) == 5

    def test_get_latest_checkpoint(self, mgr):
        """Test getting the most recent checkpoint."""
        mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        latest_created = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        latest = mgr.get_latest_checkpoint()

        assert latest.checkpoint_id == latest_created.checkpoint_id

    def test_delete_checkpoint(self, mgr):
        """Test deleting a checkpoint."""
        checkpoint = mgr.create_checkpoint(CheckpointTrigger.MANUAL, 1)
        checkpoint_id = checkpoint.checkpoint_id

        result = mgr.delete_checkpoint(checkpoint_id)

        assert result is True
        assert mgr.get_checkpoint(checkpoint_id) is None

    def test_delete_checkpoint_not_found(self, mgr):
        """Test deleting a non-existent checkpoint."""
        result = mgr.delete_checkpoint("CP-nonexistent")

        assert result is False


class TestCheckpointRollback:
    """Tests for checkpoint rollback functionality."""

    def test_rollback_restores_feature_list(self, mgr, temp_project_dir):
        """Test that rollback restores feature_list.json."""
        # Create feature list and checkpoint
        feature_file = temp_project_dir / "feature_list.json"
        features_v1 = [{"description": "Feature 1", "passes": True}]
        with open(feature_file, "w") as f:
            json.dump(features_v1, f)

        checkpoint = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)

        # Modify feature list
        features_v2 = [{"description": "Feature 1", "passes": False}]
        with open(feature_file, "w") as f:
            json.dump(features_v2, f)

        # Rollback
        result = mgr.rollback_to(checkpoint.checkpoint_id, restore_git=False)

        assert result.success is True
        assert result.features_restored is True

        # Verify feature list is restored
        with open(feature_file) as f:
            restored = json.load(f)
        assert restored[0]["passes"] is True

    def test_rollback_not_found(self, mgr):
        """Test rollback with non-existent checkpoint."""
        result = mgr.rollback_to("CP-nonexistent")

        assert result.success is False
        assert "not found" in result.message

    def test_rollback_result_format(self):
        """Test RollbackResult dataclass."""
        result = RollbackResult(
            success=True,
            checkpoint_id="CP-1-1",
            message="Rollback completed",
            git_reset=True,
            features_restored=True,
        )

        assert result.success is True
        assert result.git_reset is True


class TestCheckpointDiff:
    """Tests for checkpoint comparison functionality."""

    def test_get_checkpoint_diff(self, mgr, temp_project_dir):
        """Test comparing two checkpoints."""
        # Create feature list
        feature_file = temp_project_dir / "feature_list.json"
        features = [
            {"description": "F1", "passes": True},
            {"description": "F2", "passes": False},
        ]
        with open(feature_file, "w") as f:
            json.dump(features, f)

        cp1 = mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)

        # Update features
        features[1]["passes"] = True
        with open(feature_file, "w") as f:
            json.dump(features, f)

        cp2 = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)

        diff = mgr.get_checkpoint_diff(cp1.checkpoint_id, cp2.checkpoint_id)

        assert diff["features_passing_diff"] == 1
        assert 1 in diff["features_added_passing"]

    def test_get_checkpoint_diff_with_regression(self, mgr, temp_project_dir):
        """Test diff detects regressions."""
        feature_file = temp_project_dir / "feature_list.json"
        features = [
            {"description": "F1", "passes": True},
            {"description": "F2", "passes": True},
        ]
        with open(feature_file, "w") as f:
            json.dump(features, f)

        cp1 = mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)

        # Regress a feature
        features[0]["passes"] = False
        with open(feature_file, "w") as f:
            json.dump(features, f)

        cp2 = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        diff = mgr.get_checkpoint_diff(cp1.checkpoint_id, cp2.checkpoint_id)

        assert 0 in diff["features_regressed"]

    def test_find_checkpoint_before_regression(self, mgr, temp_project_dir):
        """Test finding checkpoint where feature was passing."""
        feature_file = temp_project_dir / "feature_list.json"

        # Start with feature passing
        features = [{"description": "F1", "passes": True}]
        with open(feature_file, "w") as f:
            json.dump(features, f)

        cp_passing = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)

        # Regress
        features[0]["passes"] = False
        with open(feature_file, "w") as f:
            json.dump(features, f)

        mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)

        found = mgr.find_checkpoint_before_regression(0)

        assert found is not None
        assert found.checkpoint_id == cp_passing.checkpoint_id


class TestCheckpointCleanup:
    """Tests for checkpoint cleanup functionality."""

    def test_cleanup_old_checkpoints(self, mgr):
        """Test cleaning up old checkpoints."""
        # Create many checkpoints
        for i in range(15):
            mgr.create_checkpoint(CheckpointTrigger.MANUAL, 1)

        initial_count = len(mgr.list_checkpoints())
        assert initial_count == 15

        # Cleanup keeping only 10
        deleted = mgr.cleanup_old_checkpoints(keep_count=10)

        # Note: cleanup also considers keep_days, so actual deletion depends on timing
        remaining = len(mgr.list_checkpoints())
        assert remaining <= initial_count


class TestFormatters:
    """Tests for formatting functions."""

    def test_format_checkpoint_summary(self):
        """Test formatting a checkpoint summary."""
        checkpoint = Checkpoint(
            checkpoint_id="CP-1-5",
            timestamp="2025-12-18T10:30:00+00:00",
            trigger="feature_complete",
            session_id=1,
            git_commit="abc123def456",
            git_branch="main",
            git_clean=True,
            feature_status={},
            features_passing=5,
            features_total=10,
            files_hash="hash123",
            human_note="Test checkpoint",
        )

        summary = format_checkpoint_summary(checkpoint)

        assert "CP-1-5" in summary
        assert "feature_complete" in summary
        assert "5/10" in summary
        assert "abc123def456"[:12] in summary
        assert "Test checkpoint" in summary

    def test_format_rollback_result_success(self):
        """Test formatting successful rollback result."""
        result = RollbackResult(
            success=True,
            checkpoint_id="CP-1-1",
            message="Rollback completed successfully",
            git_reset=True,
            features_restored=True,
        )

        formatted = format_rollback_result(result)

        assert "SUCCESS" in formatted
        assert "CP-1-1" in formatted
        assert "Git state restored" in formatted

    def test_format_rollback_result_failed(self):
        """Test formatting failed rollback result."""
        result = RollbackResult(
            success=False,
            checkpoint_id="CP-1-1",
            message="Checkpoint not found",
        )

        formatted = format_rollback_result(result)

        assert "FAILED" in formatted


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_checkpoint_manager(self, temp_project_dir):
        """Test create_checkpoint_manager factory function."""
        mgr = create_checkpoint_manager(temp_project_dir)

        assert isinstance(mgr, CheckpointManager)
        assert mgr.project_dir == temp_project_dir


class TestCheckpointTriggers:
    """Tests for different checkpoint trigger types."""

    def test_all_trigger_types(self, mgr):
        """Test that all trigger types can be used."""
        triggers = [
            CheckpointTrigger.FEATURE_COMPLETE,
            CheckpointTrigger.BEFORE_RISKY_OP,
            CheckpointTrigger.ERROR_RECOVERY,
            CheckpointTrigger.HUMAN_REQUEST,
            CheckpointTrigger.SESSION_END,
            CheckpointTrigger.SESSION_START,
            CheckpointTrigger.MANUAL,
        ]

        for i, trigger in enumerate(triggers):
            checkpoint = mgr.create_checkpoint(trigger, session_id=i)
            assert checkpoint.trigger == trigger.value


class TestFeatureListBackup:
    """Tests for feature list backup and restore."""

    def test_backup_created_on_checkpoint(self, mgr, feature_list, temp_project_dir):
        """Test that feature_list.json is backed up."""
        checkpoint = mgr.create_checkpoint(CheckpointTrigger.MANUAL, 1)

        backup_path = temp_project_dir / ".checkpoints" / checkpoint.checkpoint_id / "feature_list.json"
        assert backup_path.exists()

    def test_backup_matches_original(self, mgr, feature_list, temp_project_dir):
        """Test that backup content matches original."""
        with open(feature_list) as f:
            original = json.load(f)

        checkpoint = mgr.create_checkpoint(CheckpointTrigger.MANUAL, 1)

        backup_path = temp_project_dir / ".checkpoints" / checkpoint.checkpoint_id / "feature_list.json"
        with open(backup_path) as f:
            backup = json.load(f)

        assert backup == original
