"""
Tests for DB-backed MemoryManager.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from arcadiaforge.db import init_db
from arcadiaforge.db.connection import get_session_maker, _engine
from arcadiaforge.db.models import HotMemory as DBHotMemory, WarmMemory as DBWarmMemory
from arcadiaforge.memory import MemoryManager


@pytest.mark.asyncio
async def test_memory_manager_initializes_hot_memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        await init_db(project_dir)

        manager = MemoryManager(project_dir, session_id=42)
        await manager._init_hot_memory()

        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(DBHotMemory).where(DBHotMemory.session_id == 42)
            )
            assert result.scalar_one_or_none() is not None

        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_memory_manager_saves_warm_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        await init_db(project_dir)

        manager = MemoryManager(project_dir, session_id=7)
        summary = manager.end_session(
            ending_state="completed",
            features_started=1,
            features_completed=1,
        )
        await manager._save_warm_memory(summary)

        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(DBWarmMemory).where(DBWarmMemory.session_id == 7)
            )
            row = result.scalar_one_or_none()
            assert row is not None
            assert row.features_completed == 1
            assert row.ending_state == "completed"

        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_memory_manager_persists_hot_updates():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        await init_db(project_dir)

        manager = MemoryManager(project_dir, session_id=3)
        manager.record_action("Read file", "Success", tool="Read")
        manager.set_focus(feature=5, task="Testing", keywords=["auth"])
        manager.add_to_hot({"type": "user_hint", "message": "Use caching"})
        manager.record_error("TypeError", "Bad call")

        await asyncio.sleep(0.1)

        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(DBHotMemory).where(DBHotMemory.session_id == 3)
            )
            row = result.scalar_one_or_none()
            assert row is not None
            assert row.current_feature == 5
            assert row.current_task == "Testing"
            assert row.recent_actions
            assert row.active_errors

        if _engine:
            await _engine.dispose()
