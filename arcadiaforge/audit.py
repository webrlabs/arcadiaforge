"""
Audit Utilities for Autonomous Coding Framework
===============================================

Runs periodic audits of completed features and records findings in the database.
"""

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arcadiaforge.checkpoint import CheckpointManager
from arcadiaforge.feature_list import FeatureList


AUDIT_STATE_FILE = ".audit_state.json"

# Default audit configuration
AUDIT_CADENCE_FEATURES = 10
AUDIT_MAX_CANDIDATES = 8
AUDIT_RANDOM_COUNT = 3
AUDIT_HIGH_RISK_COUNT = 3
AUDIT_STEP_THRESHOLD = 8

HIGH_RISK_KEYWORDS = {
    "auth",
    "login",
    "logout",
    "password",
    "payment",
    "billing",
    "checkout",
    "admin",
    "permissions",
    "security",
    "oauth",
    "token",
    "encryption",
    "bank",
    "card",
    "subscription",
}


@dataclass
class AuditState:
    """Tracks when the last audit ran."""
    last_passing_count: int = 0
    last_audit_at: str = ""


def _state_path(project_dir: Path) -> Path:
    return Path(project_dir) / AUDIT_STATE_FILE


def load_audit_state(project_dir: Path) -> AuditState:
    """Load audit state from disk."""
    path = _state_path(project_dir)
    if not path.exists():
        return AuditState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AuditState(
            last_passing_count=int(data.get("last_passing_count", 0)),
            last_audit_at=data.get("last_audit_at", ""),
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return AuditState()


def save_audit_state(project_dir: Path, passing_count: int) -> None:
    """Persist audit state to disk."""
    path = _state_path(project_dir)
    data = {
        "last_passing_count": passing_count,
        "last_audit_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def should_run_audit(project_dir: Path, passing_count: int, cadence: int) -> bool:
    """Return True if an audit is due based on cadence."""
    state = load_audit_state(project_dir)
    return (passing_count - state.last_passing_count) >= cadence


def _collect_regressions(checkpoint_mgr: CheckpointManager, project_dir: Path) -> list[int]:
    """Find features that regressed since the latest checkpoint."""
    latest = checkpoint_mgr.get_latest_checkpoint()
    if not latest:
        return []

    fl = FeatureList(project_dir)
    fl.load()
    current = {f.index: f.passes for f in fl}

    regressions = []
    for idx, was_passing in latest.feature_status.items():
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        if was_passing and not current.get(idx_int, False):
            regressions.append(idx_int)

    return regressions


def _is_high_risk(feature) -> bool:
    """Heuristic for high-risk features."""
    text = f"{feature.description} " + " ".join(feature.steps)
    lowered = text.lower()
    if len(feature.steps) >= AUDIT_STEP_THRESHOLD:
        return True
    return any(keyword in lowered for keyword in HIGH_RISK_KEYWORDS)


def select_audit_candidates(
    project_dir: Path,
    checkpoint_mgr: CheckpointManager,
    max_candidates: int = AUDIT_MAX_CANDIDATES,
    high_risk_count: int = AUDIT_HIGH_RISK_COUNT,
    random_count: int = AUDIT_RANDOM_COUNT,
) -> tuple[list[int], list[int]]:
    """
    Select candidate features for audit.

    Returns:
        (candidate_indices, regression_indices)
    """
    fl = FeatureList(project_dir)
    fl.load()

    regressions = _collect_regressions(checkpoint_mgr, project_dir)

    passing = [f for f in fl if f.passes]
    flagged = [f for f in passing if (f.audit or {}).get("status") == "flagged"]
    high_risk = [f for f in passing if _is_high_risk(f)]

    candidates: list[int] = []

    def _add(indices: list[int]) -> None:
        for idx in indices:
            if idx not in candidates:
                candidates.append(idx)

    _add(regressions)
    _add([f.index for f in flagged])
    _add([f.index for f in high_risk[:high_risk_count]])

    remaining = [f.index for f in passing if f.index not in candidates]
    if remaining and random_count > 0:
        random.shuffle(remaining)
        _add(remaining[:random_count])

    return candidates[:max_candidates], regressions
