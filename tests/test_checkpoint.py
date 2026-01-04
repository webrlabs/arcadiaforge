"""
Tests for the checkpoint module (DB-backed).
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from arcadiaforge.checkpoint import (
    CheckpointManager,
    CheckpointTrigger,
    create_checkpoint_manager,
)
from arcadiaforge.db import init_db
from arcadiaforge.db.connection import get_session_maker, _engine
from arcadiaforge.db.models import Feature as DBFeature


async def seed_features(project_dir: Path, features: list[dict]) -> None:
    session_maker = get_session_maker()
    async with session_maker() as session:
        for idx, item in enumerate(features):
            session.add(
                DBFeature(
                    index=idx,
                    category=item.get("category", "functional"),
                    description=item.get("description", ""),
                    steps=item.get("steps", []),
                    passes=item.get("passes", False),
                )
            )
        await session.commit()


@pytest.fixture
def temp_project_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        asyncio.run(init_db(project_dir))
        yield project_dir
        if _engine:
            asyncio.run(_engine.dispose())


@pytest.fixture
def mgr(temp_project_dir):
    return CheckpointManager(temp_project_dir)


@pytest.fixture
def seeded_features(temp_project_dir):
    features = [
        {"description": "Feature 1", "passes": True, "steps": ["Step 1"]},
        {"description": "Feature 2", "passes": False, "steps": ["Step 1", "Step 2"]},
        {"description": "Feature 3", "passes": True, "steps": ["Step 1"]},
    ]
    asyncio.run(seed_features(temp_project_dir, features))
    return features


class TestCheckpointManager:
    def test_initialization(self, temp_project_dir):
        manager = CheckpointManager(temp_project_dir)
        assert manager.project_dir == temp_project_dir

    def test_create_checkpoint_captures_feature_state(self, mgr, seeded_features):
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.SESSION_START,
            session_id=1,
        )
        assert checkpoint.features_total == len(seeded_features)
        assert checkpoint.features_passing == 2
        assert checkpoint.feature_status[0] is True
        assert checkpoint.feature_status[1] is False

    def test_persist_and_fetch_checkpoint(self, mgr, seeded_features):
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.MANUAL,
            session_id=1,
        )
        asyncio.run(mgr._persist_to_db(checkpoint))

        fetched = asyncio.run(mgr.get_checkpoint(checkpoint.checkpoint_id))
        assert fetched is not None
        assert fetched.checkpoint_id == checkpoint.checkpoint_id

    def test_list_checkpoints_newest_first(self, mgr, seeded_features):
        cp1 = mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        asyncio.run(mgr._persist_to_db(cp1))
        cp2 = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)
        asyncio.run(mgr._persist_to_db(cp2))
        cp3 = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)
        asyncio.run(mgr._persist_to_db(cp3))

        checkpoints = asyncio.run(mgr.list_checkpoints())
        assert checkpoints[0].checkpoint_id == cp3.checkpoint_id
        assert checkpoints[-1].checkpoint_id == cp1.checkpoint_id

    def test_get_latest_checkpoint(self, mgr, seeded_features):
        cp1 = mgr.create_checkpoint(CheckpointTrigger.SESSION_START, 1)
        asyncio.run(mgr._persist_to_db(cp1))
        cp2 = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)
        asyncio.run(mgr._persist_to_db(cp2))

        latest = asyncio.run(mgr.get_latest_checkpoint())
        assert latest is not None
        assert latest.checkpoint_id == cp2.checkpoint_id

    def test_get_recovery_checkpoint(self, mgr, seeded_features):
        cp1 = mgr.create_checkpoint(CheckpointTrigger.FEATURE_COMPLETE, 1)
        asyncio.run(mgr._persist_to_db(cp1))
        cp2 = mgr.create_checkpoint(CheckpointTrigger.SESSION_END, 1)
        asyncio.run(mgr._persist_to_db(cp2))

        recovery = asyncio.run(mgr.get_recovery_checkpoint())
        assert recovery is not None
        assert recovery.checkpoint_id == cp1.checkpoint_id

    def test_rollback_not_implemented(self, mgr):
        result = mgr.rollback_to("CP-1-1", reset_git=False)
        assert result.success is False
        assert "not implemented" in result.message


class TestConvenienceFunctions:
    def test_create_checkpoint_manager(self, temp_project_dir):
        manager = create_checkpoint_manager(temp_project_dir)
        assert isinstance(manager, CheckpointManager)
