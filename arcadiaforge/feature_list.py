"""
Feature List Utilities
======================

Specialized operations for managing features - the source of truth
for what needs to be built and tested in autonomous coding sessions.

Features are now stored in the database (.arcadia/project.db) instead of JSON.

Includes salience scoring for intelligent feature prioritization.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from arcadiaforge.db.models import Feature as DBFeature
from arcadiaforge.db.connection import get_session_maker


@dataclass
class Feature:
    """Represents a single feature/test case with salience tracking."""
    index: int
    category: str
    description: str
    steps: list[str]
    passes: bool
    audit: dict | None = None
    metadata: dict = field(default_factory=dict)

    # Salience fields
    priority: int = 3  # 1=critical, 2=high, 3=medium, 4=low
    failure_count: int = 0  # Times this feature has failed
    last_worked: Optional[str] = None  # ISO timestamp
    blocked_by: list[int] = field(default_factory=list)  # Features this depends on
    blocks: list[int] = field(default_factory=list)  # Features that depend on this

    # Computed salience (not persisted, calculated on demand)
    _salience_score: Optional[float] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Convert to dictionary format for JSON serialization (legacy support)."""
        result = {
            "category": self.category,
            "description": self.description,
            "steps": self.steps,
            "passes": self.passes,
        }
        if self.audit is not None:
            result["audit"] = self.audit
        # Only include salience fields if they have non-default values
        if self.priority != 3:
            result["priority"] = self.priority
        if self.failure_count > 0:
            result["failure_count"] = self.failure_count
        if self.last_worked:
            result["last_worked"] = self.last_worked
        if self.blocked_by:
            result["blocked_by"] = self.blocked_by
        if self.blocks:
            result["blocks"] = self.blocks
        if self.metadata:
            result.update(self.metadata)
        return result

    def to_db_model(self) -> DBFeature:
        """Convert to database model."""
        return DBFeature(
            index=self.index,
            category=self.category,
            description=self.description,
            steps=self.steps,
            passes=self.passes,
            audit_status=self.audit.get("status") if self.audit else None,
            audit_notes=self.audit.get("notes", []) if self.audit else [],
            audit_reviewer=self.audit.get("reviewer") if self.audit else None,
            priority=self.priority,
            failure_count=self.failure_count,
            last_worked=self.last_worked,
            blocked_by=self.blocked_by,
            blocks=self.blocks,
            feature_metadata=self.metadata,
        )

    @classmethod
    def from_db_model(cls, db_feature: DBFeature) -> "Feature":
        """Create a Feature from a database model."""
        # Reconstruct audit dict from separate fields
        audit = None
        if db_feature.audit_status:
            audit = {
                "status": db_feature.audit_status,
                "notes": db_feature.audit_notes or [],
            }
            if db_feature.audit_reviewer:
                audit["reviewer"] = db_feature.audit_reviewer
            if db_feature.audit_time:
                audit["time"] = db_feature.audit_time.isoformat()

        return cls(
            index=db_feature.index,
            category=db_feature.category,
            description=db_feature.description,
            steps=db_feature.steps,
            passes=db_feature.passes,
            audit=audit,
            metadata=db_feature.feature_metadata or {},
            priority=db_feature.priority,
            failure_count=db_feature.failure_count,
            last_worked=db_feature.last_worked,
            blocked_by=db_feature.blocked_by or [],
            blocks=db_feature.blocks or [],
        )

    @classmethod
    def from_dict(cls, data: dict, index: int) -> "Feature":
        """Create a Feature from a dictionary."""
        metadata = {
            k: v for k, v in data.items()
            if k not in {
                "category",
                "description",
                "steps",
                "passes",
                "audit",
                "priority",
                "failure_count",
                "last_worked",
                "blocked_by",
                "blocks",
            }
        }
        return cls(
            index=index,
            category=data.get("category", "functional"),
            description=data.get("description", ""),
            steps=data.get("steps", []),
            passes=data.get("passes", False),
            audit=data.get("audit"),
            metadata=metadata,
            priority=data.get("priority", 3),
            failure_count=data.get("failure_count", 0),
            last_worked=data.get("last_worked"),
            blocked_by=data.get("blocked_by", []),
            blocks=data.get("blocks", []),
        )

    def record_attempt(self, success: bool) -> None:
        """Record an attempt to implement this feature."""
        self.last_worked = datetime.now(timezone.utc).isoformat()
        if not success:
            self.failure_count += 1
        else:
            # Reset failure count on success
            self.failure_count = 0

    def is_blocked(self, feature_status: dict[int, bool]) -> bool:
        """
        Check if this feature is blocked by dependencies.

        Args:
            feature_status: Dict mapping feature index to passes status

        Returns:
            True if any blocking feature is not passing
        """
        for blocker_idx in self.blocked_by:
            if not feature_status.get(blocker_idx, False):
                return True
        return False


@dataclass
class FeatureStats:
    """Statistics about the feature list."""
    total: int
    passing: int
    failing: int
    functional_total: int
    functional_passing: int
    style_total: int
    style_passing: int

    @property
    def progress_percent(self) -> float:
        """Calculate progress as a percentage."""
        if self.total == 0:
            return 0.0
        return (self.passing / self.total) * 100

    def __str__(self) -> str:
        return (
            f"Progress: {self.passing}/{self.total} ({self.progress_percent:.1f}%)\n"
            f"  Functional: {self.functional_passing}/{self.functional_total}\n"
            f"  Style: {self.style_passing}/{self.style_total}"
        )


class FeatureList:
    """
    Manages features with database-backed storage.

    Usage:
        fl = FeatureList(project_dir)
        fl.load()

        # Get stats
        stats = fl.get_stats()
        print(f"{stats.passing}/{stats.total} features passing")

        # Get next feature to work on
        feature = fl.get_next_incomplete()
        if feature:
            print(f"Next: {feature.description}")

        # Mark feature as passing
        fl.mark_passing(feature.index)
        fl.save()
    """

    def __init__(self, project_dir: Path):
        """
        Initialize FeatureList for a project directory.

        Args:
            project_dir: Path to the project directory
        """
        self.project_dir = Path(project_dir)
        self._features: list[Feature] = []
        self._loaded = False

    def exists(self) -> bool:
        """
        Check if features exist in the database.

        Returns True if there are features in the database.
        Uses synchronous database check to work in any context.
        """
        # First check if already loaded
        if self._loaded and len(self._features) > 0:
            return True

        # Check database file directly using synchronous SQLite
        db_path = self.project_dir / ".arcadia" / "project.db"
        if not db_path.exists():
            return False

        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM features")
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    def load(self) -> bool:
        """
        Load features from database.

        For async contexts, use load_async() instead.

        Returns:
            True if loaded successfully, False otherwise
        """
        # Try to load from database (sync version)
        # First check if we can use asyncio.run (no running event loop)
        can_use_asyncio_run = True
        try:
            asyncio.get_running_loop()
            can_use_asyncio_run = False
        except RuntimeError:
            # No running event loop, asyncio.run is safe to use
            pass

        if can_use_asyncio_run:
            try:
                self._features = asyncio.run(self._load_from_db())
                self._loaded = True
                return True
            except Exception:
                pass

        # Database load failed - return empty list
        self._features = []
        self._loaded = False
        return False

    async def load_async(self) -> bool:
        """
        Load features from database (async version).

        Use this method when already in an async context.

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            self._features = await self._load_from_db()
            self._loaded = True
            return True
        except Exception:
            pass

        # Database load failed - return empty list
        self._features = []
        self._loaded = False
        return False

    async def _load_from_db(self) -> list[Feature]:
        """Load features from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBFeature).order_by(DBFeature.index)
                )
                db_features = result.scalars().all()
                return [Feature.from_db_model(f) for f in db_features]
        except Exception:
            return []

    def save(self) -> bool:
        """
        Save features to database (fire-and-forget).

        Returns:
            True if save was scheduled successfully
        """
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._save_to_db())
                return True
        except RuntimeError:
            pass

        # No event loop, try sync save
        try:
            asyncio.run(self._save_to_db())
            return True
        except Exception:
            return False

    async def _save_to_db(self):
        """Save all features to database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                for feature in self._features:
                    # Update or insert each feature
                    result = await session.execute(
                        select(DBFeature).where(DBFeature.index == feature.index)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        # Update existing feature
                        existing.category = feature.category
                        existing.description = feature.description
                        existing.steps = feature.steps
                        existing.passes = feature.passes
                        existing.audit_status = feature.audit.get("status") if feature.audit else None
                        existing.audit_notes = feature.audit.get("notes", []) if feature.audit else []
                        existing.audit_reviewer = feature.audit.get("reviewer") if feature.audit else None
                        existing.priority = feature.priority
                        existing.failure_count = feature.failure_count
                        existing.last_worked = feature.last_worked
                        existing.blocked_by = feature.blocked_by
                        existing.blocks = feature.blocks
                        existing.feature_metadata = feature.metadata
                    else:
                        # Insert new feature
                        db_feature = feature.to_db_model()
                        session.add(db_feature)

                await session.commit()
        except Exception:
            pass

    def get_stats(self) -> FeatureStats:
        """Get statistics about the feature list."""
        if not self._loaded:
            self.load()

        total = len(self._features)
        passing = sum(1 for f in self._features if f.passes)
        failing = total - passing

        functional = [f for f in self._features if f.category == "functional"]
        style = [f for f in self._features if f.category == "style"]

        return FeatureStats(
            total=total,
            passing=passing,
            failing=failing,
            functional_total=len(functional),
            functional_passing=sum(1 for f in functional if f.passes),
            style_total=len(style),
            style_passing=sum(1 for f in style if f.passes),
        )

    def get_audit_summary(self) -> dict:
        """Get audit summary for features."""
        if not self._loaded:
            self.load()

        summary = {
            "flagged": [],
            "ok": 0,
            "pending": 0,
            "none": 0,
        }

        for feature in self._features:
            audit = feature.audit or {}
            status = audit.get("status")
            if status == "flagged":
                summary["flagged"].append(feature.index)
            elif status == "ok":
                summary["ok"] += 1
            elif status == "pending":
                summary["pending"] += 1
            else:
                summary["none"] += 1

        return summary

    def get_next_incomplete(self, category: Optional[str] = None) -> Optional[Feature]:
        """
        Get the highest-priority incomplete feature.

        Features are ordered by priority in the file, so the first
        incomplete feature is the highest priority.

        Args:
            category: Optional filter by category ("functional" or "style")

        Returns:
            The next Feature to work on, or None if all complete
        """
        if not self._loaded:
            self.load()

        for feature in self._features:
            if not feature.passes:
                if category is None or feature.category == category:
                    return feature
        return None

    def get_feature(self, index: int) -> Optional[Feature]:
        """
        Get a feature by its index.

        Args:
            index: 0-based index of the feature

        Returns:
            The Feature at that index, or None if out of bounds
        """
        if not self._loaded:
            self.load()

        if 0 <= index < len(self._features):
            return self._features[index]
        return None

    def mark_passing(self, index: int) -> bool:
        """
        Mark a feature as passing and persist to database.

        Args:
            index: 0-based index of the feature

        Returns:
            True if marked successfully, False if index invalid
        """
        if not self._loaded:
            self.load()

        if 0 <= index < len(self._features):
            self._features[index].passes = True
            # Persist to database
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._update_feature_in_db(index))
            except RuntimeError:
                pass
            return True
        return False

    def mark_failing(self, index: int) -> bool:
        """
        Mark a feature as failing (revert to not passing) and persist to database.

        Args:
            index: 0-based index of the feature

        Returns:
            True if marked successfully, False if index invalid
        """
        if not self._loaded:
            self.load()

        if 0 <= index < len(self._features):
            self._features[index].passes = False
            # Persist to database
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._update_feature_in_db(index))
            except RuntimeError:
                pass
            return True
        return False

    async def _update_feature_in_db(self, index: int):
        """Update a single feature in the database."""
        try:
            if not (0 <= index < len(self._features)):
                return

            feature = self._features[index]
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBFeature).where(DBFeature.index == index)
                )
                db_feature = result.scalar_one_or_none()

                if db_feature:
                    # Update existing
                    db_feature.category = feature.category
                    db_feature.description = feature.description
                    db_feature.steps = feature.steps
                    db_feature.passes = feature.passes
                    db_feature.audit_status = feature.audit.get("status") if feature.audit else None
                    db_feature.audit_notes = feature.audit.get("notes", []) if feature.audit else []
                    db_feature.audit_reviewer = feature.audit.get("reviewer") if feature.audit else None
                    db_feature.priority = feature.priority
                    db_feature.failure_count = feature.failure_count
                    db_feature.last_worked = feature.last_worked
                    db_feature.blocked_by = feature.blocked_by
                    db_feature.blocks = feature.blocks
                    db_feature.feature_metadata = feature.metadata
                else:
                    # Insert new
                    db_feature = feature.to_db_model()
                    session.add(db_feature)

                await session.commit()
        except Exception:
            pass

    def list_features(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Feature]:
        """
        List features with optional filtering.

        Args:
            status: Filter by "passing", "failing", or None for all
            category: Filter by "functional", "style", or None for all
            limit: Maximum number of features to return

        Returns:
            List of matching Feature objects
        """
        if not self._loaded:
            self.load()

        result = []
        for feature in self._features:
            # Filter by status
            if status == "passing" and not feature.passes:
                continue
            if status == "failing" and feature.passes:
                continue

            # Filter by category
            if category and feature.category != category:
                continue

            result.append(feature)

            if limit and len(result) >= limit:
                break

        return result

    def search(self, query: str, limit: Optional[int] = None) -> list[Feature]:
        """
        Search features by description (case-insensitive).

        Args:
            query: Text to search for in feature descriptions
            limit: Maximum number of results

        Returns:
            List of matching Feature objects
        """
        if not self._loaded:
            self.load()

        query_lower = query.lower()
        result = []

        for feature in self._features:
            if query_lower in feature.description.lower():
                result.append(feature)
                if limit and len(result) >= limit:
                    break

        return result

    def add_feature(
        self,
        description: str,
        steps: list[str],
        category: str = "functional",
    ) -> Feature:
        """
        Add a new feature to the list and persist to database.

        Args:
            description: Feature description
            steps: List of test steps
            category: "functional" or "style"

        Returns:
            The newly created Feature
        """
        if not self._loaded:
            self.load()

        new_index = len(self._features)
        feature = Feature(
            index=new_index,
            category=category,
            description=description,
            steps=steps,
            passes=False,
        )
        self._features.append(feature)

        # Persist to database
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._add_feature_to_db(feature))
        except RuntimeError:
            pass

        return feature

    async def _add_feature_to_db(self, feature: Feature):
        """Add a feature to the database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_feature = feature.to_db_model()
                session.add(db_feature)
                await session.commit()
        except Exception:
            pass

    def add_features_from_list(self, features_data: list[dict]) -> int:
        """
        Add multiple features from a list of dictionaries.

        Args:
            features_data: List of feature dictionaries with category, description, steps

        Returns:
            Number of features added
        """
        if not self._loaded:
            self.load()

        count = 0
        for data in features_data:
            self.add_feature(
                description=data.get("description", ""),
                steps=data.get("steps", []),
                category=data.get("category", "functional"),
            )
            count += 1

        return count

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate the feature list for common issues.

        Returns:
            (is_valid, list_of_issues) tuple
        """
        if not self._loaded:
            self.load()

        issues = []

        for feature in self._features:
            idx = feature.index

            # Check for empty description
            if not feature.description.strip():
                issues.append(f"Feature {idx}: Empty description")

            # Check for empty steps
            if not feature.steps:
                issues.append(f"Feature {idx}: No test steps")

            # Check for invalid category
            if feature.category not in ("functional", "style"):
                issues.append(f"Feature {idx}: Invalid category '{feature.category}'")

            # Check for very short descriptions
            if len(feature.description) < 10:
                issues.append(f"Feature {idx}: Description too short")

        return len(issues) == 0, issues

    def get_summary_text(self) -> str:
        """
        Generate a human-readable summary of the feature list.

        Returns:
            Multi-line string with feature list summary
        """
        stats = self.get_stats()

        lines = [
            "Feature List Summary",
            "=" * 40,
            f"Total features: {stats.total}",
            f"Passing: {stats.passing} ({stats.progress_percent:.1f}%)",
            f"Failing: {stats.failing}",
            "",
            "By Category:",
            f"  Functional: {stats.functional_passing}/{stats.functional_total}",
            f"  Style: {stats.style_passing}/{stats.style_total}",
        ]

        next_feature = self.get_next_incomplete()
        if next_feature:
            lines.extend([
                "",
                "Next Feature to Implement:",
                f"  [{next_feature.index}] {next_feature.description[:60]}...",
            ])

        return "\n".join(lines)

    def __len__(self) -> int:
        """Return the number of features."""
        if not self._loaded:
            self.load()
        return len(self._features)

    def __iter__(self):
        """Iterate over features."""
        if not self._loaded:
            self.load()
        return iter(self._features)

    # =========================================================================
    # Salience-Aware Methods
    # =========================================================================

    def get_next_by_salience(
        self,
        context: Optional[dict] = None,
        category: Optional[str] = None,
        exclude_blocked: bool = True,
    ) -> Optional[Feature]:
        """
        Get the next feature to work on based on salience scoring.

        Unlike get_next_incomplete() which uses file order, this method
        calculates salience scores and returns the highest-priority feature.

        Args:
            context: Optional context dict with:
                - related_features: list[int] - features related to recent work
                - focus_keywords: list[str] - keywords from current focus
            category: Optional filter by category
            exclude_blocked: If True, skip features blocked by dependencies

        Returns:
            The highest-salience incomplete Feature, or None if all complete
        """
        if not self._loaded:
            self.load()

        context = context or {}

        # Build feature status map for dependency checking
        feature_status = {f.index: f.passes for f in self._features}

        # Calculate salience for all incomplete features
        candidates = []
        for feature in self._features:
            if feature.passes:
                continue
            if category and feature.category != category:
                continue
            if exclude_blocked and feature.is_blocked(feature_status):
                continue

            salience = calculate_salience(feature, context)
            candidates.append((feature, salience))

        if not candidates:
            return None

        # Sort by salience (highest first)
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def get_features_by_salience(
        self,
        context: Optional[dict] = None,
        limit: int = 10,
        include_passing: bool = False,
    ) -> list[tuple[Feature, float]]:
        """
        Get features ranked by salience score.

        Args:
            context: Optional context for salience calculation
            limit: Maximum number of features to return
            include_passing: If True, include passing features

        Returns:
            List of (Feature, salience_score) tuples, sorted by salience
        """
        if not self._loaded:
            self.load()

        context = context or {}
        results = []

        for feature in self._features:
            if not include_passing and feature.passes:
                continue

            salience = calculate_salience(feature, context)
            results.append((feature, salience))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def record_attempt(self, index: int, success: bool) -> bool:
        """
        Record an attempt to implement a feature and persist to database.

        This updates the feature's last_worked timestamp and failure_count.

        Args:
            index: Feature index
            success: Whether the attempt was successful

        Returns:
            True if recorded successfully
        """
        if not self._loaded:
            self.load()

        if 0 <= index < len(self._features):
            self._features[index].record_attempt(success)
            # Persist to database
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._update_feature_in_db(index))
            except RuntimeError:
                pass
            return True
        return False

    def set_priority(self, index: int, priority: int) -> bool:
        """
        Set a feature's priority and persist to database.

        Args:
            index: Feature index
            priority: Priority level (1=critical, 2=high, 3=medium, 4=low)

        Returns:
            True if set successfully
        """
        if not self._loaded:
            self.load()

        if 0 <= index < len(self._features):
            self._features[index].priority = max(1, min(4, priority))
            # Persist to database
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._update_feature_in_db(index))
            except RuntimeError:
                pass
            return True
        return False

    def add_dependency(self, feature_index: int, depends_on: int) -> bool:
        """
        Add a dependency between features and persist to database.

        Args:
            feature_index: The feature that has the dependency
            depends_on: The feature it depends on

        Returns:
            True if added successfully
        """
        if not self._loaded:
            self.load()

        if not (0 <= feature_index < len(self._features)):
            return False
        if not (0 <= depends_on < len(self._features)):
            return False
        if feature_index == depends_on:
            return False

        feature = self._features[feature_index]
        blocker = self._features[depends_on]

        # Add to blocked_by if not already there
        if depends_on not in feature.blocked_by:
            feature.blocked_by.append(depends_on)

        # Update the blocker's "blocks" list
        if feature_index not in blocker.blocks:
            blocker.blocks.append(feature_index)

        # Persist both features to database
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._update_feature_in_db(feature_index))
                loop.create_task(self._update_feature_in_db(depends_on))
        except RuntimeError:
            pass

        return True

    def remove_dependency(self, feature_index: int, depends_on: int) -> bool:
        """
        Remove a dependency between features and persist to database.

        Args:
            feature_index: The feature that has the dependency
            depends_on: The feature it depends on

        Returns:
            True if removed successfully
        """
        if not self._loaded:
            self.load()

        if not (0 <= feature_index < len(self._features)):
            return False
        if not (0 <= depends_on < len(self._features)):
            return False

        feature = self._features[feature_index]
        blocker = self._features[depends_on]

        if depends_on in feature.blocked_by:
            feature.blocked_by.remove(depends_on)
        if feature_index in blocker.blocks:
            blocker.blocks.remove(feature_index)

        # Persist both features to database
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._update_feature_in_db(feature_index))
                loop.create_task(self._update_feature_in_db(depends_on))
        except RuntimeError:
            pass

        return True

    def get_blocked_features(self) -> list[Feature]:
        """
        Get all features that are blocked by dependencies.

        Returns:
            List of blocked features
        """
        if not self._loaded:
            self.load()

        feature_status = {f.index: f.passes for f in self._features}
        return [
            f for f in self._features
            if not f.passes and f.is_blocked(feature_status)
        ]

    def get_unblocked_features(self) -> list[Feature]:
        """
        Get all incomplete features that are not blocked.

        Returns:
            List of unblocked incomplete features
        """
        if not self._loaded:
            self.load()

        feature_status = {f.index: f.passes for f in self._features}
        return [
            f for f in self._features
            if not f.passes and not f.is_blocked(feature_status)
        ]

    def get_high_failure_features(self, min_failures: int = 3) -> list[Feature]:
        """
        Get features with high failure counts.

        Args:
            min_failures: Minimum failure count to include

        Returns:
            List of features with high failure counts
        """
        if not self._loaded:
            self.load()

        return [
            f for f in self._features
            if f.failure_count >= min_failures
        ]


# =============================================================================
# Salience Scoring
# =============================================================================

def calculate_salience(feature: Feature, context: Optional[dict] = None) -> float:
    """
    Calculate dynamic salience score for a feature.

    The salience score determines how important/urgent a feature is to work on.
    Higher scores indicate higher priority.

    Scoring factors:
    - Base priority (critical=0.4, high=0.3, medium=0.2, low=0.1)
    - Failure penalty (repeated failures = deprioritize)
    - Dependency bonus (features that unblock others)
    - Context boost (related to recent work)
    - Recency factor (balance between fresh and neglected)

    Args:
        feature: The feature to score
        context: Optional context dict with:
            - related_features: list[int] - features related to recent work
            - focus_keywords: list[str] - keywords from current focus

    Returns:
        Salience score between 0.0 and 1.0
    """
    context = context or {}
    score = 0.0

    # Base priority score
    priority_weights = {1: 0.40, 2: 0.30, 3: 0.20, 4: 0.10}
    score += priority_weights.get(feature.priority, 0.20)

    # Failure penalty (repeated failures = try something else)
    # Cap at 3 failures to prevent complete deprioritization
    failure_penalty = 0.08 * min(feature.failure_count, 3)
    score -= failure_penalty

    # Dependency bonus (if this unblocks others)
    # Features that unblock many others are more valuable
    dependency_bonus = 0.04 * min(len(feature.blocks), 5)
    score += dependency_bonus

    # Context boost (related to recent work)
    related_features = context.get("related_features", [])
    if feature.index in related_features:
        score += 0.15

    # Keyword matching boost
    focus_keywords = context.get("focus_keywords", [])
    if focus_keywords:
        description_lower = feature.description.lower()
        keyword_matches = sum(
            1 for kw in focus_keywords
            if kw.lower() in description_lower
        )
        # Cap at 3 keyword matches
        score += 0.05 * min(keyword_matches, 3)

    # Recency factor
    # Features not worked on recently get a small boost (avoid starvation)
    # Features worked on very recently get a small penalty (give others a chance)
    if feature.last_worked:
        try:
            last_dt = datetime.fromisoformat(feature.last_worked.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            hours_ago = (now - last_dt).total_seconds() / 3600

            if hours_ago < 1:
                # Very recently worked - small penalty
                score -= 0.05
            elif hours_ago > 24:
                # Not worked on in a while - small boost
                score += 0.03
        except (ValueError, TypeError):
            pass

    # Ensure score is in valid range
    return max(0.0, min(1.0, score))


# Convenience functions for quick access

def load_feature_list(project_dir: Path) -> FeatureList:
    """
    Load a feature list from a project directory.

    Args:
        project_dir: Path to project directory

    Returns:
        Loaded FeatureList instance
    """
    fl = FeatureList(project_dir)
    fl.load()
    return fl


def get_feature_stats(project_dir: Path) -> FeatureStats:
    """
    Get feature statistics for a project.

    Args:
        project_dir: Path to project directory

    Returns:
        FeatureStats with counts and percentages
    """
    fl = FeatureList(project_dir)
    fl.load()
    return fl.get_stats()


def get_next_feature(project_dir: Path) -> Optional[Feature]:
    """
    Get the next incomplete feature for a project.

    Args:
        project_dir: Path to project directory

    Returns:
        Next Feature to work on, or None if all complete
    """
    fl = FeatureList(project_dir)
    fl.load()
    return fl.get_next_incomplete()


def mark_feature_passing(project_dir: Path, index: int) -> bool:
    """
    Mark a feature as passing and save the file.

    Args:
        project_dir: Path to project directory
        index: 0-based feature index

    Returns:
        True if successful
    """
    fl = FeatureList(project_dir)
    fl.load()
    if fl.mark_passing(index):
        return fl.save()
    return False


def generate_status_file(project_dir: Path, session_number: int = 0) -> bool:
    """
    Generate a compact status.txt file for the agent to read.

    This creates a small, focused file with essential information
    so the agent doesn't need to read the large claude-progress.txt file.

    Args:
        project_dir: Path to project directory
        session_number: Current session number

    Returns:
        True if file was written successfully
    """
    from datetime import datetime

    project_dir = Path(project_dir)
    fl = FeatureList(project_dir)

    if not fl.exists():
        # No feature list yet - this is likely the first run
        content = f"""# Project Status
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Session: {session_number}

## Status
This appears to be a NEW PROJECT - no features in database yet.
You are the INITIALIZER agent. Populate the features database first.

## Your Task
1. Read app_spec.txt to understand the project requirements
2. Populate the features database with ~200 detailed test cases
3. Create init.sh/init.bat for environment setup
4. Initialize git repository
5. Set up basic project structure
"""
    else:
        fl.load()
        stats = fl.get_stats()
        next_feature = fl.get_next_incomplete()
        audit_summary = fl.get_audit_summary()
        flagged = audit_summary["flagged"]
        flagged_preview = ", ".join(str(i) for i in flagged[:5]) if flagged else "none"

        # Get recent git commits
        import subprocess
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            recent_commits = result.stdout.strip() if result.returncode == 0 else "No git history"
        except Exception:
            recent_commits = "Unable to get git history"

        # Build next feature info
        if next_feature:
            next_info = f"""## Next Feature to Implement
Index: #{next_feature.index}
Category: {next_feature.category}
Description: {next_feature.description}
Steps: {len(next_feature.steps)} steps
"""
        else:
            next_info = "## Status: ALL FEATURES COMPLETE!"

        content = f"""# Project Status
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Session: {session_number}

## Progress
Tests Passing: {stats.passing}/{stats.total} ({stats.progress_percent:.1f}%)
Tests Remaining: {stats.failing}

By Category:
  Functional: {stats.functional_passing}/{stats.functional_total}
  Style: {stats.style_passing}/{stats.style_total}

Audit Flags: {len(flagged)} flagged
Flagged indices (up to 5): {flagged_preview}

{next_info}
## Recent Git Commits
{recent_commits}

## Instructions
1. Run verification tests on 1-2 existing passing tests
2. If issues found, fix them before new work
3. Implement the next incomplete feature
4. Test thoroughly with browser automation
5. Mark feature as passing using `feature_mark` tool
6. Commit your progress

## Available MCP Tools

### Feature Management
- `feature_stats` - Show progress stats
- `feature_next` with count=1 - Show next feature to implement
- `feature_show` with index=42 - Show details for feature #42
- `feature_list` with passing=false - List incomplete features
- `feature_search` with query="keyword" - Search features
- `feature_mark` with index=42 - Mark feature #42 as passing
- `feature_audit` with index=42 status="flagged" - Record audit result
- `feature_audit_list` with status="flagged" - List audit status

### Progress Tracking
- `progress_get_last` with count=1 - Get last session's progress
- `progress_add` - Add progress entry at end of session

### Troubleshooting
- `troubleshoot_search` with query="error" - Search for solutions
- `troubleshoot_add` - Record solution after fixing an issue

## Notes
- Do NOT access the database directly (use MCP tools)
- Features are stored in .arcadia/project.db
- Use git log for history
"""

    # Write the status file
    status_file = project_dir / "status.txt"
    try:
        status_file.write_text(content, encoding="utf-8")
        return True
    except IOError:
        return False
