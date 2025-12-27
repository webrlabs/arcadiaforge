"""
Test database integration to ensure components can use the database.
"""

import asyncio
import tempfile
from pathlib import Path
import pytest

from arcadiaforge.db import init_db
from arcadiaforge.observability import Observability, EventType
from arcadiaforge.decision import DecisionLogger, DecisionType
from arcadiaforge.checkpoint import CheckpointManager, CheckpointTrigger
from arcadiaforge.hypotheses import HypothesisTracker, HypothesisType
from arcadiaforge.feature_list import FeatureList


@pytest.mark.asyncio
async def test_observability_db():
    """Test that Observability can write to and read from database."""
    print("Testing Observability database integration...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize database
        await init_db(project_dir)

        # Create observability instance
        obs = Observability(project_dir)

        # Log an event
        event_id = obs.log_event(
            EventType.SESSION_START,
            data={"test": "data"},
            session_id=1
        )

        # Wait a moment for async write to complete
        await asyncio.sleep(0.5)

        # Query events
        events = await obs.get_events(session_id=1)

        assert len(events) > 0, "Should have at least one event"
        assert events[0].session_id == 1, "Event should have correct session_id"

        print("[PASS] Observability database integration works!")

        # Close database connections before cleanup
        from arcadiaforge.db.connection import _engine
        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_decision_logger_db():
    """Test that DecisionLogger can write to and read from database."""
    print("Testing DecisionLogger database integration...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize database
        await init_db(project_dir)

        # Create decision logger
        logger = DecisionLogger(project_dir)

        # Log a decision
        decision = logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Test context",
            choice="Test choice",
            alternatives=["Alt 1", "Alt 2"],
            rationale="Test rationale",
            confidence=0.8,
        )

        # Wait for async write
        await asyncio.sleep(0.5)

        # Retrieve decision
        retrieved = await logger.get(decision.decision_id)

        assert retrieved is not None, "Should be able to retrieve decision"
        assert retrieved.choice == "Test choice", "Decision should have correct data"

        print("[PASS] DecisionLogger database integration works!")

        # Close database connections before cleanup
        from arcadiaforge.db.connection import _engine
        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_checkpoint_manager_db():
    """Test that CheckpointManager can write to and read from database."""
    print("Testing CheckpointManager database integration...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize database
        await init_db(project_dir)

        # Create checkpoint manager
        mgr = CheckpointManager(project_dir)

        # Create a checkpoint
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.MANUAL,
            session_id=1,
            metadata={"test": "checkpoint"}
        )

        # Wait for async write
        await asyncio.sleep(0.5)

        # List checkpoints
        checkpoints = await mgr.list_checkpoints(session_id=1)

        assert len(checkpoints) > 0, "Should have at least one checkpoint"
        assert checkpoints[0].session_id == 1, "Checkpoint should have correct session_id"

        print("[PASS] CheckpointManager database integration works!")

        # Close database connections before cleanup
        from arcadiaforge.db.connection import _engine
        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_hypothesis_tracker_db():
    """Test that HypothesisTracker can write to and read from database."""
    print("Testing HypothesisTracker database integration...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize database
        await init_db(project_dir)

        # Create hypothesis tracker
        tracker = HypothesisTracker(project_dir, session_id=1)

        # Add a hypothesis
        hyp = tracker.add_hypothesis(
            hypothesis_type=HypothesisType.ROOT_CAUSE,
            observation="Test observation",
            hypothesis="Test hypothesis",
            confidence=0.7,
        )

        # Wait for async write
        await asyncio.sleep(0.5)

        # Retrieve hypotheses
        hypotheses = await tracker.list_hypotheses(session_id=1)

        assert len(hypotheses) > 0, "Should have at least one hypothesis"
        assert hypotheses[0].observation == "Test observation", "Hypothesis should have correct data"

        print("[PASS] HypothesisTracker database integration works!")

        # Close database connections before cleanup
        from arcadiaforge.db.connection import _engine
        if _engine:
            await _engine.dispose()


@pytest.mark.asyncio
async def test_feature_list_db():
    """Test that FeatureList can write to and read from database."""
    print("Testing FeatureList database integration...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize database
        await init_db(project_dir)

        # Create feature list and load async (starts empty)
        fl = FeatureList(project_dir)
        await fl.load_async()

        # Add a feature
        feature = fl.add_feature(
            description="Test feature",
            steps=["Step 1", "Step 2"],
            category="functional"
        )

        # Wait for async write
        await asyncio.sleep(0.5)

        # Mark it as passing
        fl.mark_passing(feature.index)

        # Wait for async write
        await asyncio.sleep(0.5)

        # Create a new feature list instance and load from DB
        fl2 = FeatureList(project_dir)
        await fl2.load_async()

        # Verify the feature was persisted
        assert len(fl2._features) > 0, "Should have at least one feature"
        assert fl2._features[0].description == "Test feature", "Feature should have correct description"
        assert fl2._features[0].passes == True, "Feature should be marked as passing"
        assert fl2._features[0].steps == ["Step 1", "Step 2"], "Feature should have correct steps"

        print("[PASS] FeatureList database integration works!")

        # Close database connections before cleanup
        from arcadiaforge.db.connection import _engine
        if _engine:
            await _engine.dispose()


async def main():
    """Run all database integration tests."""
    print("=" * 60)
    print("Database Integration Tests")
    print("=" * 60)
    print()

    try:
        await test_observability_db()
        print()
        await test_decision_logger_db()
        print()
        await test_checkpoint_manager_db()
        print()
        await test_hypothesis_tracker_db()
        print()
        await test_feature_list_db()
        print()
        print("=" * 60)
        print("✓ All database integration tests passed!")
        print("=" * 60)
    except Exception as e:
        print()
        print("=" * 60)
        print(f"✗ Test failed: {e}")
        print("=" * 60)
        raise


if __name__ == "__main__":
    asyncio.run(main())
