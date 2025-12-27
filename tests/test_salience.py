"""
Tests for Salience Scoring
===========================

Tests for the salience scoring system in feature_list.py.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from arcadiaforge.feature_list import (
    Feature,
    FeatureList,
    calculate_salience,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def feature_list(temp_project):
    """Create a FeatureList with test data."""
    fl = FeatureList(temp_project)

    # Create test features
    features_data = [
        {"category": "functional", "description": "Login feature", "steps": ["Step 1"], "passes": False, "priority": 1},
        {"category": "functional", "description": "Dashboard display", "steps": ["Step 1"], "passes": False, "priority": 2},
        {"category": "functional", "description": "User profile", "steps": ["Step 1"], "passes": True, "priority": 3},
        {"category": "style", "description": "Button styling", "steps": ["Step 1"], "passes": False, "priority": 4},
        {"category": "functional", "description": "Authentication flow", "steps": ["Step 1"], "passes": False, "priority": 2, "blocked_by": [0]},
    ]

    with open(temp_project / "feature_list.json", "w") as f:
        json.dump(features_data, f)

    fl.load()
    return fl


# =============================================================================
# Feature Salience Fields Tests
# =============================================================================

class TestFeatureSalienceFields:
    """Tests for Feature salience fields."""

    def test_default_values(self):
        """Test default salience field values."""
        feature = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
        )

        assert feature.priority == 3
        assert feature.failure_count == 0
        assert feature.last_worked is None
        assert feature.blocked_by == []
        assert feature.blocks == []

    def test_record_attempt_success(self):
        """Test recording a successful attempt."""
        feature = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
            failure_count=3,
        )

        feature.record_attempt(success=True)

        assert feature.last_worked is not None
        assert feature.failure_count == 0  # Reset on success

    def test_record_attempt_failure(self):
        """Test recording a failed attempt."""
        feature = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
            failure_count=1,
        )

        feature.record_attempt(success=False)

        assert feature.last_worked is not None
        assert feature.failure_count == 2

    def test_is_blocked(self):
        """Test is_blocked check."""
        feature = Feature(
            index=5,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
            blocked_by=[0, 1, 2],
        )

        # All blockers passing
        status_all_pass = {0: True, 1: True, 2: True, 5: False}
        assert feature.is_blocked(status_all_pass) is False

        # One blocker not passing
        status_one_fail = {0: True, 1: False, 2: True, 5: False}
        assert feature.is_blocked(status_one_fail) is True

    def test_serialization_with_salience_fields(self):
        """Test that salience fields are serialized correctly."""
        feature = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
            priority=1,
            failure_count=2,
            last_worked="2025-12-18T10:00:00Z",
            blocked_by=[1, 2],
            blocks=[3, 4],
        )

        data = feature.to_dict()

        assert data["priority"] == 1
        assert data["failure_count"] == 2
        assert data["last_worked"] == "2025-12-18T10:00:00Z"
        assert data["blocked_by"] == [1, 2]
        assert data["blocks"] == [3, 4]

    def test_serialization_default_values_omitted(self):
        """Test that default salience values are not serialized."""
        feature = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=["Step 1"],
            passes=False,
        )

        data = feature.to_dict()

        # Default values should not be included
        assert "priority" not in data
        assert "failure_count" not in data
        assert "last_worked" not in data
        assert "blocked_by" not in data
        assert "blocks" not in data


# =============================================================================
# Calculate Salience Tests
# =============================================================================

class TestCalculateSalience:
    """Tests for calculate_salience function."""

    def test_base_priority_scoring(self):
        """Test that priority affects base score."""
        critical = Feature(index=0, category="functional", description="Test", steps=[], passes=False, priority=1)
        high = Feature(index=1, category="functional", description="Test", steps=[], passes=False, priority=2)
        medium = Feature(index=2, category="functional", description="Test", steps=[], passes=False, priority=3)
        low = Feature(index=3, category="functional", description="Test", steps=[], passes=False, priority=4)

        score_critical = calculate_salience(critical)
        score_high = calculate_salience(high)
        score_medium = calculate_salience(medium)
        score_low = calculate_salience(low)

        assert score_critical > score_high
        assert score_high > score_medium
        assert score_medium > score_low

    def test_failure_penalty(self):
        """Test that failure count reduces salience."""
        no_failures = Feature(index=0, category="functional", description="Test", steps=[], passes=False, failure_count=0)
        some_failures = Feature(index=1, category="functional", description="Test", steps=[], passes=False, failure_count=2)
        many_failures = Feature(index=2, category="functional", description="Test", steps=[], passes=False, failure_count=5)

        score_no_fail = calculate_salience(no_failures)
        score_some_fail = calculate_salience(some_failures)
        score_many_fail = calculate_salience(many_failures)

        assert score_no_fail > score_some_fail
        assert score_some_fail > score_many_fail

    def test_failure_penalty_capped(self):
        """Test that failure penalty is capped at 3."""
        three_failures = Feature(index=0, category="functional", description="Test", steps=[], passes=False, failure_count=3)
        ten_failures = Feature(index=1, category="functional", description="Test", steps=[], passes=False, failure_count=10)

        score_three = calculate_salience(three_failures)
        score_ten = calculate_salience(ten_failures)

        # Should be the same due to cap
        assert score_three == score_ten

    def test_dependency_bonus(self):
        """Test that features that unblock others get a bonus."""
        no_blocks = Feature(index=0, category="functional", description="Test", steps=[], passes=False, blocks=[])
        blocks_one = Feature(index=1, category="functional", description="Test", steps=[], passes=False, blocks=[5])
        blocks_many = Feature(index=2, category="functional", description="Test", steps=[], passes=False, blocks=[5, 6, 7, 8])

        score_no_blocks = calculate_salience(no_blocks)
        score_one = calculate_salience(blocks_one)
        score_many = calculate_salience(blocks_many)

        assert score_one > score_no_blocks
        assert score_many > score_one

    def test_context_related_features_boost(self):
        """Test that related features get a boost."""
        feature = Feature(index=5, category="functional", description="Test", steps=[], passes=False)

        score_not_related = calculate_salience(feature, context={})
        score_related = calculate_salience(feature, context={"related_features": [5]})

        assert score_related > score_not_related

    def test_keyword_matching_boost(self):
        """Test that keyword matches boost salience."""
        feature = Feature(
            index=0,
            category="functional",
            description="Authentication login flow",
            steps=[],
            passes=False,
        )

        score_no_keywords = calculate_salience(feature, context={})
        score_one_match = calculate_salience(feature, context={"focus_keywords": ["login"]})
        score_two_matches = calculate_salience(feature, context={"focus_keywords": ["login", "auth"]})

        assert score_one_match > score_no_keywords
        assert score_two_matches > score_one_match

    def test_recency_penalty_for_recent_work(self):
        """Test that very recently worked features get a small penalty."""
        recent = datetime.now(timezone.utc).isoformat()
        feature_recent = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=[],
            passes=False,
            last_worked=recent,
        )
        feature_no_work = Feature(
            index=1,
            category="functional",
            description="Test",
            steps=[],
            passes=False,
            last_worked=None,
        )

        score_recent = calculate_salience(feature_recent)
        score_no_work = calculate_salience(feature_no_work)

        assert score_no_work > score_recent

    def test_recency_boost_for_neglected(self):
        """Test that neglected features get a small boost."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        feature_old = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=[],
            passes=False,
            last_worked=old_time,
        )
        feature_no_work = Feature(
            index=1,
            category="functional",
            description="Test",
            steps=[],
            passes=False,
            last_worked=None,
        )

        score_old = calculate_salience(feature_old)
        score_no_work = calculate_salience(feature_no_work)

        # Old features should get a boost
        assert score_old > score_no_work

    def test_score_bounds(self):
        """Test that salience score is always 0.0-1.0."""
        # Try to create extreme cases
        worst = Feature(
            index=0,
            category="functional",
            description="Test",
            steps=[],
            passes=False,
            priority=4,
            failure_count=10,
        )
        best = Feature(
            index=0,
            category="functional",
            description="Test auth login",
            steps=[],
            passes=False,
            priority=1,
            blocks=[1, 2, 3, 4, 5],
        )

        score_worst = calculate_salience(worst)
        score_best = calculate_salience(best, context={
            "related_features": [0],
            "focus_keywords": ["auth", "login", "test"],
        })

        assert 0.0 <= score_worst <= 1.0
        assert 0.0 <= score_best <= 1.0


# =============================================================================
# FeatureList Salience Methods Tests
# =============================================================================

class TestFeatureListSalienceMethods:
    """Tests for FeatureList salience-aware methods."""

    def test_get_next_by_salience(self, feature_list):
        """Test getting next feature by salience."""
        # Feature 0 has priority 1 (critical), should be returned
        next_feature = feature_list.get_next_by_salience()

        assert next_feature is not None
        assert next_feature.priority == 1

    def test_get_next_by_salience_with_context(self, feature_list):
        """Test salience with context boosts."""
        # Give feature 1 (Dashboard) a context boost
        context = {"related_features": [1], "focus_keywords": ["dashboard"]}
        next_feature = feature_list.get_next_by_salience(context=context)

        # Depending on the weights, this might change the result
        assert next_feature is not None

    def test_get_next_by_salience_category_filter(self, feature_list):
        """Test category filter with salience."""
        # Only style features
        next_feature = feature_list.get_next_by_salience(category="style")

        assert next_feature is not None
        assert next_feature.category == "style"

    def test_get_next_by_salience_exclude_blocked(self, feature_list):
        """Test that blocked features are excluded."""
        # Feature 4 depends on feature 0 which is not passing
        next_feature = feature_list.get_next_by_salience(exclude_blocked=True)

        # Should not return feature 4
        assert next_feature is not None
        assert next_feature.index != 4

    def test_get_next_by_salience_include_blocked(self, feature_list):
        """Test including blocked features."""
        # Set feature 0 as passing
        feature_list.mark_passing(0)
        feature_list.mark_passing(1)
        feature_list.mark_passing(3)

        # Now only feature 4 should be available (and unblocked)
        next_feature = feature_list.get_next_by_salience(exclude_blocked=True)

        assert next_feature is not None
        assert next_feature.index == 4

    def test_get_features_by_salience(self, feature_list):
        """Test getting features ranked by salience."""
        ranked = feature_list.get_features_by_salience(limit=3)

        assert len(ranked) == 3
        # Should be sorted by salience (highest first)
        assert ranked[0][1] >= ranked[1][1]
        assert ranked[1][1] >= ranked[2][1]

    def test_record_attempt(self, feature_list):
        """Test recording attempts."""
        feature_list.record_attempt(0, success=False)
        feature_list.record_attempt(0, success=False)

        feature = feature_list.get_feature(0)
        assert feature.failure_count == 2
        assert feature.last_worked is not None

    def test_set_priority(self, feature_list):
        """Test setting priority."""
        feature_list.set_priority(3, priority=1)  # Make button styling critical

        feature = feature_list.get_feature(3)
        assert feature.priority == 1

    def test_set_priority_clamped(self, feature_list):
        """Test that priority is clamped to valid range."""
        feature_list.set_priority(0, priority=0)  # Below minimum
        feature_list.set_priority(1, priority=10)  # Above maximum

        assert feature_list.get_feature(0).priority == 1
        assert feature_list.get_feature(1).priority == 4

    def test_add_dependency(self, feature_list):
        """Test adding dependencies."""
        # Make feature 3 depend on feature 1
        result = feature_list.add_dependency(3, depends_on=1)

        assert result is True
        feature = feature_list.get_feature(3)
        blocker = feature_list.get_feature(1)

        assert 1 in feature.blocked_by
        assert 3 in blocker.blocks

    def test_add_dependency_self_reference(self, feature_list):
        """Test that self-reference is rejected."""
        result = feature_list.add_dependency(0, depends_on=0)
        assert result is False

    def test_remove_dependency(self, feature_list):
        """Test removing dependencies."""
        feature_list.add_dependency(3, depends_on=1)
        result = feature_list.remove_dependency(3, depends_on=1)

        assert result is True
        feature = feature_list.get_feature(3)
        blocker = feature_list.get_feature(1)

        assert 1 not in feature.blocked_by
        assert 3 not in blocker.blocks

    def test_get_blocked_features(self, feature_list):
        """Test getting blocked features."""
        blocked = feature_list.get_blocked_features()

        # Feature 4 is blocked by feature 0
        assert any(f.index == 4 for f in blocked)

    def test_get_unblocked_features(self, feature_list):
        """Test getting unblocked features."""
        unblocked = feature_list.get_unblocked_features()

        # Feature 4 should not be in unblocked list
        assert not any(f.index == 4 for f in unblocked)
        # Features 0, 1, 3 should be unblocked (2 is passing)
        unblocked_indices = [f.index for f in unblocked]
        assert 0 in unblocked_indices
        assert 1 in unblocked_indices

    def test_get_high_failure_features(self, feature_list):
        """Test getting high failure features."""
        feature_list.record_attempt(0, success=False)
        feature_list.record_attempt(0, success=False)
        feature_list.record_attempt(0, success=False)

        high_fail = feature_list.get_high_failure_features(min_failures=3)
        assert len(high_fail) == 1
        assert high_fail[0].index == 0

    def test_salience_persistence(self, temp_project):
        """Test that salience fields persist across load/save."""
        fl1 = FeatureList(temp_project)
        features_data = [
            {"category": "functional", "description": "Test", "steps": ["Step 1"], "passes": False},
        ]
        with open(temp_project / "feature_list.json", "w") as f:
            json.dump(features_data, f)
        fl1.load()

        # Modify salience fields
        fl1.set_priority(0, 1)
        fl1.record_attempt(0, success=False)
        fl1.add_dependency(0, depends_on=0)  # Will fail, but let's add blocks manually
        fl1._features[0].blocks = [1, 2]
        fl1.save()

        # Load in new instance
        fl2 = FeatureList(temp_project)
        fl2.load()

        feature = fl2.get_feature(0)
        assert feature.priority == 1
        assert feature.failure_count == 1
        assert feature.blocks == [1, 2]
