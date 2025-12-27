"""
Artifact Store for Autonomous Coding Framework (Database Only)
==============================================================

Provides persistent storage for all session artifacts including:
- Verification screenshots
- Test results
- Git commit metadata
- File snapshots

Artifacts are stored on disk and tracked in the SQLite database.
"""

import hashlib
import asyncio
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from arcadiaforge.db.models import Artifact as DBArtifact
from arcadiaforge.db.connection import get_session_maker

class ArtifactType(Enum):
    """Types of artifacts that can be stored."""
    SCREENSHOT = "screenshot"           # Verification screenshots
    TEST_RESULT = "test_result"         # Test output/results
    GIT_COMMIT = "git_commit"           # Commit metadata
    FILE_SNAPSHOT = "file_snapshot"     # Snapshot of a file
    LOG = "log"                         # Log files
    ERROR = "error"                     # Error dumps
    VERIFICATION = "verification"       # General verification evidence


@dataclass
class Artifact:
    """Represents a stored artifact."""
    artifact_id: str
    timestamp: str
    artifact_type: str
    session_id: int
    original_name: str
    stored_path: str
    checksum: str
    size_bytes: int
    feature_index: Optional[int] = None
    description: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    parent_artifact_id: Optional[str] = None
    related_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, data: dict) -> "Artifact": return cls(**data)
    def summary(self) -> str:
        feature_str = f" feature=#{self.feature_index}" if self.feature_index is not None else ""
        return f"[{self.artifact_id}] {self.artifact_type}{feature_str} - {self.original_name}"


class ArtifactStore:
    """Manages artifact storage for a project (DB-backed)."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        # Still need a directory for physical files, but no .artifacts subdir or index.json
        self._seq = 1  # Will be dynamically set from DB

    async def _get_next_seq(self) -> int:
        """Get next sequence number from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(select(DBArtifact))
                artifacts = result.scalars().all()
                if not artifacts:
                    return 1
                max_seq = 0
                for art in artifacts:
                    try:
                        parts = art.id.split("-")
                        if len(parts) >= 3:
                            seq = int(parts[-1])
                            max_seq = max(max_seq, seq)
                    except (ValueError, IndexError):
                        continue
                return max_seq + 1
        except Exception:
            return 1

    def _compute_checksum(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _get_type_subdir(self, artifact_type: ArtifactType) -> str:
        type_dirs = {
            ArtifactType.SCREENSHOT: "screenshots",
            ArtifactType.TEST_RESULT: "test_results",
            ArtifactType.GIT_COMMIT: "commits",
            ArtifactType.FILE_SNAPSHOT: "snapshots",
            ArtifactType.LOG: "logs",
            ArtifactType.ERROR: "errors",
            ArtifactType.VERIFICATION: "verification",
        }
        return type_dirs.get(artifact_type, "other")

    def store(
        self,
        artifact_type: ArtifactType,
        source_path: Path,
        session_id: int,
        feature_index: Optional[int] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        parent_artifact_id: Optional[str] = None,
    ) -> Artifact:
        """Store an artifact (synchronous wrapper)."""
        # For sync compatibility, we'll use asyncio.run if no loop is running
        try:
            loop = asyncio.get_running_loop()
            # If loop is running, we can't use asyncio.run, so we create a task
            # But this method is sync, so we need to handle this carefully
            # For now, use a synchronous seq counter and schedule DB write
            artifact_id = f"ART-{session_id}-{self._seq}"
            self._seq += 1
        except RuntimeError:
            # No loop running, safe to use sync counter
            artifact_id = f"ART-{session_id}-{self._seq}"
            self._seq += 1

        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        checksum = self._compute_checksum(source_path)
        size_bytes = source_path.stat().st_size
        type_subdir = self._get_type_subdir(artifact_type)

        # Store in artifacts/{type}/{session}/filename
        artifacts_dir = self.project_dir / "artifacts"
        session_dir = artifacts_dir / type_subdir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        original_name = source_path.name
        stored_name = f"{artifact_id}_{original_name}"
        stored_path = session_dir / stored_name
        shutil.copy2(source_path, stored_path)

        # Relative path from project root
        rel_path = stored_path.relative_to(self.project_dir)

        artifact = Artifact(
            artifact_id=artifact_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            artifact_type=artifact_type.value if isinstance(artifact_type, ArtifactType) else artifact_type,
            session_id=session_id,
            original_name=original_name,
            stored_path=str(rel_path),
            checksum=checksum,
            size_bytes=size_bytes,
            feature_index=feature_index,
            description=description,
            metadata=metadata or {},
            parent_artifact_id=parent_artifact_id,
        )

        # Write to DB (fire-and-forget if loop exists)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._persist_to_db(artifact))
        except RuntimeError:
            # No loop - skip DB write for now, will be picked up on next read
            pass

        return artifact

    async def _persist_to_db(self, artifact: Artifact) -> None:
        """Persist artifact to database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_art = DBArtifact(
                    id=artifact.artifact_id,
                    session_id=artifact.session_id,
                    feature_index=artifact.feature_index,
                    type=artifact.artifact_type,
                    path=artifact.stored_path,
                    description=artifact.description,
                    metadata_json=artifact.metadata,
                    created_at=datetime.fromisoformat(artifact.timestamp)
                )
                session.add(db_art)
                await session.commit()
        except Exception:
            pass

    async def get(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact by ID from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBArtifact).where(DBArtifact.id == artifact_id)
                )
                db_art = result.scalar_one_or_none()
                if not db_art:
                    return None

                return Artifact(
                    artifact_id=db_art.id,
                    timestamp=db_art.created_at.isoformat(),
                    artifact_type=db_art.type,
                    session_id=db_art.session_id,
                    original_name=Path(db_art.path).name,
                    stored_path=db_art.path,
                    checksum="",  # Not stored in DB
                    size_bytes=0,  # Not stored in DB
                    feature_index=db_art.feature_index,
                    description=db_art.description,
                    metadata=db_art.metadata_json or {},
                )
        except Exception:
            return None

    def get_path(self, artifact_id: str) -> Optional[Path]:
        """Get physical path to artifact (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            # Can't use async from sync context with running loop
            # Return None or use a different approach
            return None
        except RuntimeError:
            # No loop, can use asyncio.run
            import asyncio as aio
            artifact = aio.run(self.get(artifact_id))
            if artifact:
                return self.project_dir / artifact.stored_path
            return None

    async def list_artifacts(
        self,
        session_id: Optional[int] = None,
        artifact_type: Optional[ArtifactType] = None,
        feature_index: Optional[int] = None,
        limit: Optional[int] = None
    ) -> list[Artifact]:
        """List artifacts with filters."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBArtifact)

                if session_id is not None:
                    stmt = stmt.where(DBArtifact.session_id == session_id)
                if artifact_type is not None:
                    type_val = artifact_type.value if isinstance(artifact_type, ArtifactType) else artifact_type
                    stmt = stmt.where(DBArtifact.type == type_val)
                if feature_index is not None:
                    stmt = stmt.where(DBArtifact.feature_index == feature_index)

                stmt = stmt.order_by(DBArtifact.created_at.desc())
                if limit:
                    stmt = stmt.limit(limit)

                result = await session.execute(stmt)
                db_artifacts = result.scalars().all()

                return [
                    Artifact(
                        artifact_id=db_art.id,
                        timestamp=db_art.created_at.isoformat(),
                        artifact_type=db_art.type,
                        session_id=db_art.session_id,
                        original_name=Path(db_art.path).name,
                        stored_path=db_art.path,
                        checksum="",
                        size_bytes=0,
                        feature_index=db_art.feature_index,
                        description=db_art.description,
                        metadata=db_art.metadata_json or {},
                    )
                    for db_art in db_artifacts
                ]
        except Exception:
            return []

    async def list_for_feature(self, feature_index: int) -> list[Artifact]:
        """List all artifacts for a feature."""
        return await self.list_artifacts(feature_index=feature_index)

    async def get_verification_artifacts(self, feature_index: int, session_id: Optional[int] = None) -> list[Artifact]:
        """Get verification artifacts for a feature."""
        return await self.list_for_feature(feature_index)


def find_verification_screenshots(project_dir: Path, feature_index: int) -> list[Path]:
    """Find verification screenshots for a feature in file system."""
    screenshots = []
    verification_dir = project_dir / "verification"
    if verification_dir.exists():
        screenshots.extend(verification_dir.glob(f"feature_{feature_index}_*.png"))
    screenshots_dir = project_dir / "screenshots"
    if screenshots_dir.exists():
        screenshots.extend(screenshots_dir.glob(f"feature_{feature_index}_*.png"))
    screenshots.extend(project_dir.glob(f"feature_{feature_index}_*.png"))

    # Also check artifacts directory
    artifacts_dir = project_dir / "artifacts"
    if artifacts_dir.exists():
        screenshots.extend(artifacts_dir.glob(f"**/feature_{feature_index}_*.png"))
        screenshots.extend(artifacts_dir.glob(f"**/ART-*-*_{feature_index}_*.png"))

    return list(set(screenshots))


def create_artifact_store(project_dir: Path) -> ArtifactStore:
    """Create an artifact store instance."""
    return ArtifactStore(project_dir)
