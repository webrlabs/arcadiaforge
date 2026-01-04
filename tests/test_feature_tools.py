"""
Tests for feature_tools.py - DB-backed feature management tools.
"""

import asyncio
import tempfile
import shutil
from pathlib import Path

import pytest

from arcadiaforge import feature_tools
from arcadiaforge.db import init_db
from arcadiaforge.db.connection import get_session_maker, _engine
from arcadiaforge.db.models import Feature as DBFeature
from arcadiaforge.feature_tools import (
    feature_stats,
    feature_next,
    feature_show,
    feature_list,
    feature_search,
    feature_mark,
    feature_add,
)


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
    tmp_dir = Path(tempfile.mkdtemp())
    feature_tools._project_dir = tmp_dir
    asyncio.run(init_db(tmp_dir))
    yield tmp_dir
    if _engine:
        asyncio.run(_engine.dispose())
    shutil.rmtree(tmp_dir)


@pytest.fixture
def sample_features():
    return [
        {
            "category": "functional",
            "description": "User can log in with email and password",
            "steps": ["Navigate to login page", "Enter credentials", "Click submit", "Verify redirect"],
            "passes": True,
        },
        {
            "category": "functional",
            "description": "User can register a new account",
            "steps": ["Navigate to register", "Fill form", "Submit"],
            "passes": False,
        },
        {
            "category": "style",
            "description": "Dark mode toggle changes theme colors",
            "steps": ["Click toggle", "Verify dark colors"],
            "passes": False,
        },
        {
            "category": "functional",
            "description": "User can reset password via email",
            "steps": ["Click forgot password", "Enter email", "Check inbox"],
            "passes": False,
        },
        {
            "category": "style",
            "description": "Buttons have hover states",
            "steps": ["Hover over button", "Verify color change"],
            "passes": True,
        },
    ]


@pytest.fixture
def project_with_features(temp_project_dir, sample_features):
    asyncio.run(seed_features(temp_project_dir, sample_features))
    return temp_project_dir


class TestFeatureStats:
    @pytest.mark.asyncio
    async def test_stats_with_features(self, project_with_features):
        result = await feature_stats.handler({})
        text = result["content"][0]["text"]
        assert "Progress: 2/5" in text

    @pytest.mark.asyncio
    async def test_stats_no_features(self, temp_project_dir):
        result = await feature_stats.handler({})
        assert "No features found" in result["content"][0]["text"]


class TestFeatureNext:
    @pytest.mark.asyncio
    async def test_next_single(self, project_with_features):
        result = await feature_next.handler({"count": 1, "skip_blocked": False})
        text = result["content"][0]["text"]
        assert "NEXT 1 FEATURE" in text
        assert "[#1]" in text

    @pytest.mark.asyncio
    async def test_next_all_complete(self, temp_project_dir):
        features = [
            {"category": "functional", "description": "Test", "steps": ["Step 1"], "passes": True}
        ]
        asyncio.run(seed_features(temp_project_dir, features))
        result = await feature_next.handler({"count": 1})
        assert "All features complete" in result["content"][0]["text"]


class TestFeatureShow:
    @pytest.mark.asyncio
    async def test_show_passing_feature(self, project_with_features):
        result = await feature_show.handler({"index": 0})
        text = result["content"][0]["text"]
        assert "Feature #0" in text
        assert "Status: PASS" in text

    @pytest.mark.asyncio
    async def test_show_invalid_index(self, project_with_features):
        result = await feature_show.handler({"index": 999})
        assert result.get("is_error") is True


class TestFeatureList:
    @pytest.mark.asyncio
    async def test_list_incomplete(self, project_with_features):
        result = await feature_list.handler({"passing": False})
        text = result["content"][0]["text"]
        assert "INCOMPLETE FEATURES (3)" in text

    @pytest.mark.asyncio
    async def test_list_passing(self, project_with_features):
        result = await feature_list.handler({"passing": True})
        text = result["content"][0]["text"]
        assert "PASSING FEATURES (2)" in text


class TestFeatureSearch:
    @pytest.mark.asyncio
    async def test_search_matches(self, project_with_features):
        result = await feature_search.handler({"query": "password"})
        text = result["content"][0]["text"]
        assert "Found 1 matches" in text


class TestFeatureMark:
    @pytest.mark.asyncio
    async def test_mark_feature(self, project_with_features):
        result = await feature_mark.handler({"index": 1, "passing": True, "skip_verification": True})
        assert "Feature #1" in result["content"][0]["text"]


class TestFeatureAdd:
    @pytest.mark.asyncio
    async def test_add_feature(self, temp_project_dir):
        result = await feature_add.handler({
            "category": "functional",
            "description": "New feature",
            "steps": ["Step 1"],
        })
        assert "Feature #0 added successfully" in result["content"][0]["text"]
