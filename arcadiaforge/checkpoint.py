"""
Checkpoint System for Autonomous Coding Framework (Database Only)
==================================================================

Provides semantic checkpointing at meaningful points in the development process,
enabling rollback and recovery without losing significant work.

All checkpoint data is stored in the SQLite database.

Checkpoints are triggered at:
- Feature completion (after feature_mark)
- Before risky operations
- On error recovery
- Human request
- Session end

Usage:
    from arcadiaforge.checkpoint import CheckpointManager, CheckpointTrigger

    manager = CheckpointManager(project_dir)

    # Create a checkpoint
    cp = await manager.create_checkpoint(
        trigger=CheckpointTrigger.FEATURE_COMPLETE,
        session_id=1,
        metadata={"feature_index": 42}
    )

    # List checkpoints
    checkpoints = await manager.list_checkpoints()

    # Rollback to a checkpoint
    await manager.rollback_to(checkpoint_id)
"""

import asyncio
import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import json

from sqlalchemy import select
from arcadiaforge.db.models import Checkpoint as DBCheckpoint
from arcadiaforge.db.connection import get_session_maker
from arcadiaforge.feature_list import FeatureList


class CheckpointTrigger(Enum):
    """Triggers that cause a checkpoint to be created."""
    FEATURE_COMPLETE = "feature_complete"      # After successfully marking a feature as passing
    BEFORE_RISKY_OP = "before_risky_op"        # Before operations that could corrupt state
    ERROR_RECOVERY = "error_recovery"          # After recovering from an error
    HUMAN_REQUEST = "human_request"            # Explicitly requested by human
    SESSION_END = "session_end"                # At the end of a session
    SESSION_START = "session_start"            # At the start of a session (baseline)
    MANUAL = "manual"                          # Manual checkpoint for testing


@dataclass
class Checkpoint:
    """
    A semantic checkpoint capturing project state at a meaningful point.

    Checkpoints enable rollback without re-running everything from scratch.
    """
    checkpoint_id: str              # Unique ID: "CP-{session}-{seq}"
    timestamp: str                  # ISO format timestamp
    trigger: str                    # CheckpointTrigger value
    session_id: int

    # Git state
    git_commit: str                 # HEAD commit hash at checkpoint time
    git_branch: str                 # Current branch name
    git_clean: bool                 # Whether working directory was clean

    # Feature state
    feature_status: dict            # {feature_index: passes} for all features
    features_passing: int           # Count of passing features
    features_total: int             # Total feature count

    # File state
    files_hash: str                 # Hash of all tracked files

    # Recovery information
    last_successful_feature: Optional[int] = None  # Last feature marked passing
    pending_work: list = field(default_factory=list)  # Work in progress

    # Metadata
    metadata: dict = field(default_factory=dict)  # Trigger-specific data
    human_note: Optional[str] = None  # Optional human annotation

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        """Create Checkpoint from dictionary."""
        return cls(**data)

    def summary(self) -> str:
        """Return a brief summary string."""
        return (
            f"[{self.checkpoint_id}] {self.trigger} at {self.timestamp[:19]} "
            f"({self.features_passing}/{self.features_total} passing)"
        )


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    checkpoint_id: str
    message: str
    git_reset: bool = False         # Whether git was reset
    features_restored: bool = False  # Whether feature_list was restored
    files_affected: int = 0         # Number of files changed


class CheckpointManager:
    """
    Manages checkpoints for a project (DB-backed).

    Creates, stores, lists, and restores checkpoints.
    """

    def __init__(self, project_dir: Path):
        """Initialize CheckpointManager for a project."""
        self.project_dir = Path(project_dir)
        self._seq = 1  # Will be dynamically set from DB

    async def _get_next_seq(self) -> int:
        """Get the next sequence number for checkpoint IDs from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(select(DBCheckpoint))
                checkpoints = result.scalars().all()
                if not checkpoints:
                    return 1
                max_seq = 0
                for cp in checkpoints:
                    try:
                        parts = cp.checkpoint_id.split("-")
                        if len(parts) >= 3:
                            seq = int(parts[-1])
                            max_seq = max(max_seq, seq)
                    except (ValueError, IndexError):
                        continue
                return max_seq + 1
        except Exception:
            return 1

    def _get_git_state(self) -> tuple[str, str, bool]:
        """
        Get current git state.

        Returns:
            (commit_hash, branch_name, is_clean)
        """
        try:
            # Get HEAD commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            commit = result.stdout.strip() if result.returncode == 0 else "unknown"

            # Get branch name
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            branch = result.stdout.strip() if result.returncode == 0 else "unknown"

            # Check if clean
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            is_clean = result.returncode == 0 and not result.stdout.strip()

            return commit, branch, is_clean

        except Exception:
            return "unknown", "unknown", False

    def _get_feature_status(self) -> tuple[dict, int, int]:
        """
        Get current feature status from database.

        Returns:
            (status_dict, passing_count, total_count)
        """
        try:
            fl = FeatureList(self.project_dir)
            if not fl.exists():
                return {}, 0, 0

            fl.load()
            stats = fl.get_stats()

            status = {}
            for feature in fl._features:
                status[feature.index] = feature.passes

            return status, stats.passing, stats.total

        except Exception:
            return {}, 0, 0

    def _compute_files_hash(self) -> str:
        """
        Compute a hash of all tracked files to detect changes.

        Returns:
            Hash string representing current file state
        """
        try:
            # Get list of tracked files from git
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return "unknown"

            files = result.stdout.strip().split("\n")
            files = [f for f in files if f]  # Remove empty strings

            # Compute combined hash
            hasher = hashlib.sha256()
            for filepath in sorted(files):
                full_path = self.project_dir / filepath
                if full_path.exists() and full_path.is_file():
                    try:
                        content = full_path.read_bytes()
                        hasher.update(filepath.encode())
                        hasher.update(content)
                    except IOError:
                        continue

            return hasher.hexdigest()[:16]

        except Exception:
            return "unknown"

    def create_checkpoint(
        self,
        trigger: CheckpointTrigger,
        session_id: int,
        metadata: dict = None,
        human_note: str = None,
        pending_work: list = None,
    ) -> Checkpoint:
        """
        Create a new checkpoint (synchronous wrapper).

        Args:
            trigger: What triggered this checkpoint
            session_id: Current session ID
            metadata: Additional trigger-specific data
            human_note: Optional human annotation
            pending_work: List of work in progress descriptions

        Returns:
            The created Checkpoint
        """
        # Generate checkpoint ID
        checkpoint_id = f"CP-{session_id}-{self._seq}"
        self._seq += 1

        # Gather state
        git_commit, git_branch, git_clean = self._get_git_state()
        feature_status, features_passing, features_total = self._get_feature_status()
        files_hash = self._compute_files_hash()

        # Find last successful feature
        last_successful = None
        if feature_status:
            passing_indices = [i for i, passes in feature_status.items() if passes]
            if passing_indices:
                last_successful = max(passing_indices)

        # Create checkpoint
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trigger=trigger.value if isinstance(trigger, CheckpointTrigger) else trigger,
            session_id=session_id,
            git_commit=git_commit,
            git_branch=git_branch,
            git_clean=git_clean,
            feature_status=feature_status,
            features_passing=features_passing,
            features_total=features_total,
            files_hash=files_hash,
            last_successful_feature=last_successful,
            pending_work=pending_work or [],
            metadata=metadata or {},
            human_note=human_note,
        )

        # Persist to DB (fire-and-forget if loop exists)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._persist_to_db(checkpoint))
        except RuntimeError:
            pass

        return checkpoint

    async def _persist_to_db(self, checkpoint: Checkpoint) -> None:
        """Persist checkpoint to database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_checkpoint = DBCheckpoint(
                    checkpoint_id=checkpoint.checkpoint_id,
                    timestamp=datetime.fromisoformat(checkpoint.timestamp),
                    trigger=checkpoint.trigger,
                    session_id=checkpoint.session_id,
                    git_commit=checkpoint.git_commit,
                    git_branch=checkpoint.git_branch,
                    git_clean=checkpoint.git_clean,
                    feature_status=checkpoint.feature_status,
                    features_passing=checkpoint.features_passing,
                    features_total=checkpoint.features_total,
                    files_hash=checkpoint.files_hash,
                    last_successful_feature=checkpoint.last_successful_feature,
                    pending_work=checkpoint.pending_work,
                    checkpoint_metadata=checkpoint.metadata,
                    human_note=checkpoint.human_note,
                )
                session.add(db_checkpoint)
                await session.commit()
        except Exception:
            pass

    async def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Get a checkpoint by ID from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBCheckpoint).where(DBCheckpoint.checkpoint_id == checkpoint_id)
                )
                db_cp = result.scalar_one_or_none()
                if db_cp:
                    return self._db_to_checkpoint(db_cp)
        except Exception:
            pass
        return None

    async def list_checkpoints(
        self,
        session_id: Optional[int] = None,
        trigger: Optional[CheckpointTrigger] = None,
        limit: Optional[int] = None,
    ) -> list[Checkpoint]:
        """List checkpoints with optional filters."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBCheckpoint).order_by(DBCheckpoint.timestamp.desc())

                if session_id is not None:
                    stmt = stmt.where(DBCheckpoint.session_id == session_id)
                if trigger is not None:
                    trigger_val = trigger.value if isinstance(trigger, CheckpointTrigger) else trigger
                    stmt = stmt.where(DBCheckpoint.trigger == trigger_val)
                if limit is not None:
                    stmt = stmt.limit(limit)

                result = await session.execute(stmt)
                db_checkpoints = result.scalars().all()
                return [self._db_to_checkpoint(db_cp) for db_cp in db_checkpoints]
        except Exception:
            return []

    async def get_latest_checkpoint(self, session_id: Optional[int] = None) -> Optional[Checkpoint]:
        """Get the most recent checkpoint."""
        checkpoints = await self.list_checkpoints(session_id=session_id, limit=1)
        return checkpoints[0] if checkpoints else None

    async def get_recovery_checkpoint(self) -> Optional[Checkpoint]:
        """Get the most recent checkpoint suitable for recovery."""
        checkpoints = await self.list_checkpoints(
            trigger=CheckpointTrigger.FEATURE_COMPLETE,
            limit=1
        )
        return checkpoints[0] if checkpoints else None

    def rollback_to(self, checkpoint_id: str, reset_git: bool = True) -> RollbackResult:
        """
        Rollback to a checkpoint (synchronous wrapper for backwards compatibility).

        Note: This is a simplified version. Full rollback would require:
        - Git hard reset
        - Feature list restoration
        - File system cleanup
        """
        # For now, return a basic result
        return RollbackResult(
            success=False,
            checkpoint_id=checkpoint_id,
            message="Rollback not implemented in DB-only mode. Please use git reset manually.",
        )

    def _db_to_checkpoint(self, db_cp: DBCheckpoint) -> Checkpoint:
        """Convert database model to Checkpoint dataclass."""
        return Checkpoint(
            checkpoint_id=db_cp.checkpoint_id,
            timestamp=db_cp.timestamp.isoformat(),
            trigger=db_cp.trigger,
            session_id=db_cp.session_id,
            git_commit=db_cp.git_commit,
            git_branch=db_cp.git_branch,
            git_clean=db_cp.git_clean,
            feature_status=db_cp.feature_status or {},
            features_passing=db_cp.features_passing,
            features_total=db_cp.features_total,
            files_hash=db_cp.files_hash,
            last_successful_feature=db_cp.last_successful_feature,
            pending_work=db_cp.pending_work or [],
            metadata=db_cp.checkpoint_metadata or {},
            human_note=db_cp.human_note,
        )


def create_checkpoint_manager(project_dir: Path) -> CheckpointManager:
    """Create a CheckpointManager for a project."""
    return CheckpointManager(project_dir)


# Stub implementations for backwards compatibility
class SessionPauseManager:
    """Stub for backwards compatibility."""
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def save_pause_state(self, *args, **kwargs):
        pass

    def load_pause_state(self, *args, **kwargs):
        return None

    def get_paused_session(self):
        """Check for paused session (stub - always returns None)."""
        return None

    def resume_session(self):
        """Resume paused session (stub - returns empty dict)."""
        return {}

    def pause_session(self, *args, **kwargs):
        """Pause current session (stub - does nothing)."""
        pass

    def clear_pause_state(self):
        """Clear pause state (stub - does nothing)."""
        pass


def format_paused_session(pause_state: dict) -> str:
    """Stub for backwards compatibility."""
    return "Paused session (stub)"
