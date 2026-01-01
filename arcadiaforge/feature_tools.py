"""
Custom MCP Tools for Feature List Management (Database Backed)
==============================================================

These tools allow the agent to directly query and manage features
via the project's SQLite database (.arcadia/project.db).

All feature state is stored in the database - no JSON files needed.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List, Dict

from sqlalchemy import select, update
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import Feature
from arcadiaforge.db.connection import get_session_maker, get_db

# Global project directory - set when server is created
_project_dir: Path | None = None

# Global checkpoint manager and session ID - set externally for checkpoint creation
_checkpoint_manager: Optional[Any] = None
_current_session_id: int = 0

# Global artifact store - set externally for verification storage
_artifact_store: Optional[Any] = None

# Configuration for step validation
_require_verification: bool = True 

def set_artifact_store(store: Any) -> None:
    global _artifact_store
    _artifact_store = store

def set_require_verification(require: bool) -> None:
    global _require_verification
    _require_verification = require

def set_checkpoint_manager(manager: Any, session_id: int = 0) -> None:
    global _checkpoint_manager, _current_session_id
    _checkpoint_manager = manager
    _current_session_id = session_id

def update_session_id(session_id: int) -> None:
    global _current_session_id
    _current_session_id = session_id

async def _load_features() -> List[Dict]:
    """
    Load features from database.

    All feature data is read from/written to the database.
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        # Load from database
        result = await session.execute(select(Feature).order_by(Feature.index))
        db_features = result.scalars().all()

        if db_features:
            # Convert DB models to list of dicts (compatible format)
            return [
                {
                    "category": f.category,
                    "description": f.description,
                    "steps": f.steps,
                    "passes": f.passes,
                    "verified_at": f.verified_at.isoformat() if f.verified_at else None,
                    "audit": {
                        "status": f.audit_status,
                        "notes": f.audit_notes,
                        "reviewer": f.audit_reviewer
                    } if f.audit_status else {}
                }
                for f in db_features
            ]

        return []

async def _save_features(features: List[Dict]) -> None:
    """Save features to database only."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        for idx, item in enumerate(features):
            # Upsert logic (simplistic: select then update/insert)
            stmt = select(Feature).where(Feature.index == idx)
            result = await session.execute(stmt)
            feat = result.scalar_one_or_none()

            if not feat:
                feat = Feature(index=idx)
                session.add(feat)

            feat.category = item.get("category", "functional")
            feat.description = item.get("description", "")
            feat.steps = item.get("steps", [])
            feat.passes = item.get("passes", False)

            if item.get("verified_at"):
                feat.verified_at = datetime.fromisoformat(item["verified_at"])

            if item.get("verification_skipped"):
                feat.verification_skipped = True

            if "audit" in item:
                audit = item["audit"]
                feat.audit_status = audit.get("status")
                feat.audit_notes = audit.get("notes", [])
                feat.audit_reviewer = audit.get("reviewer")

        await session.commit()

@tool("feature_stats", "Get completion statistics.", {})
async def feature_stats(args: dict) -> dict:
    features = await _load_features()
    if not features: return {"content": [{"type": "text", "text": "No features found"}]}
    
    total = len(features)
    passing = sum(1 for f in features if f.get("passes", False))
    percent = (passing / total * 100) if total > 0 else 0
    
    return {"content": [{"type": "text", "text": f"Progress: {passing}/{total} ({percent:.1f}%)"}]}

async def _get_blocked_keywords() -> list:
    """
    Get list of keywords that indicate blocked features based on unavailable capabilities.

    Checks the database for capability status and returns keywords to filter out.
    """
    blocked_keywords = []

    try:
        from arcadiaforge.db.models import SystemCapability
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(select(SystemCapability))
            capabilities = {c.capability_name: c.is_available for c in result.scalars().all()}

            if not capabilities.get("docker", False):
                blocked_keywords.extend(["docker", "container", "docker-compose", "dockerfile"])
            if not capabilities.get("postgres", False):
                blocked_keywords.extend(["postgresql", "postgres", "psql"])
    except Exception:
        pass

    return blocked_keywords


def _is_feature_blocked(feature: dict, blocked_keywords: list) -> bool:
    """Check if a feature is blocked by missing capabilities."""
    if not blocked_keywords:
        return False

    title_lower = feature.get("description", "").lower()
    steps_text = " ".join(feature.get("steps", [])).lower()

    for keyword in blocked_keywords:
        if keyword in title_lower or keyword in steps_text:
            return True

    # Check if explicitly marked as blocked (in metadata)
    metadata = feature.get("metadata", {})
    if metadata.get("blocked_by_capability"):
        return True

    return False


@tool("feature_next", "Get next feature(s).", {"count": int, "skip_blocked": bool})
async def feature_next(args: dict) -> dict:
    """
    Get next features to implement.

    Args:
        count: Number of features to return (default: 1)
        skip_blocked: Whether to skip features blocked by missing capabilities (default: True)
    """
    count = max(1, args.get("count", 1))
    skip_blocked = args.get("skip_blocked", True)  # Default to skipping blocked features

    features = await _load_features()
    incomplete = [(i, f) for i, f in enumerate(features) if not f.get("passes", False)]

    if not incomplete:
        return {"content": [{"type": "text", "text": "All features complete!"}]}

    # Filter out blocked features if requested
    skipped_count = 0
    if skip_blocked:
        blocked_keywords = await _get_blocked_keywords()
        filtered = []
        for idx, feat in incomplete:
            if _is_feature_blocked(feat, blocked_keywords):
                skipped_count += 1
            else:
                filtered.append((idx, feat))
        incomplete = filtered

    if not incomplete:
        return {"content": [{"type": "text", "text": f"No actionable features! ({skipped_count} blocked by missing capabilities)"}]}

    lines = [f"NEXT {min(count, len(incomplete))} FEATURE(S)", "="*40]
    for idx, feat in incomplete[:count]:
        lines.append(f"[#{idx}] {feat.get('description', '')[:100]}")

    if skipped_count > 0:
        lines.append(f"\n({skipped_count} features skipped - blocked by missing capabilities)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}

@tool("feature_show", "Show feature details.", {"index": int})
async def feature_show(args: dict) -> dict:
    idx = args["index"]
    features = await _load_features()
    if idx < 0 or idx >= len(features):
        return {"content": [{"type": "text", "text": "Index out of range"}], "is_error": True}
        
    feat = features[idx]
    status = "PASS" if feat.get("passes") else "FAIL"
    steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(feat.get("steps", [])))
    
    text = f"Feature #{idx}\nStatus: {status}\nDesc: {feat.get('description')}\n\nSteps:\n{steps}"
    return {"content": [{"type": "text", "text": text}]}

@tool("feature_list", "List features.", {"passing": bool})
async def feature_list(args: dict) -> dict:
    passing = args.get("passing", False)
    features = await _load_features()
    
    filtered = [(i, f) for i, f in enumerate(features) if f.get("passes", False) == passing]
    lines = [f"{ 'PASSING' if passing else 'INCOMPLETE' } FEATURES ({len(filtered)})"]
    for i, f in filtered:
        lines.append(f"[#{i}] {f.get('description', '')[:60]}")
        
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}

@tool("feature_search", "Search features.", {"query": str})
async def feature_search(args: dict) -> dict:
    query = args["query"].lower()
    features = await _load_features()
    matches = []
    for i, f in enumerate(features):
        if query in f.get("description", "").lower():
            matches.append((i, f))
            
    lines = [f"Found {len(matches)} matches for '{query}'"]
    for i, f in matches:
         lines.append(f"[#{i}] {f.get('description', '')[:60]}")
         
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}

@tool("feature_mark", "Mark feature as passing or failing.", {"index": int, "passing": bool, "skip_verification": bool})
async def feature_mark(args: dict) -> dict:
    idx = args["index"]
    passing = args.get("passing", True)  # Default to marking as passing
    skip = args.get("skip_verification", False)
    features = await _load_features()

    if idx < 0 or idx >= len(features):
        return {"content": [{"type": "text", "text": "Index out of range"}], "is_error": True}

    # Verification Logic only applies when marking as passing
    if passing and _require_verification and not skip:
        from arcadiaforge.artifact_store import find_verification_screenshots
        if not find_verification_screenshots(_project_dir, idx):
             return {
                "content": [{"type": "text", "text": f"VALIDATION FAILED: No screenshots found for feature #{idx}. Save to 'verification/feature_{idx}_evidence.png' first."}],
                "is_error": True
            }

    features[idx]["passes"] = passing
    if passing:
        features[idx]["verified_at"] = datetime.now(timezone.utc).isoformat()
        if skip: features[idx]["verification_skipped"] = True

    await _save_features(features)

    # Checkpoint logic only for passing features
    if passing and _checkpoint_manager:
        try:
             from arcadiaforge.checkpoint import CheckpointTrigger
             _checkpoint_manager.create_checkpoint(
                 trigger=CheckpointTrigger.FEATURE_COMPLETE,
                 session_id=_current_session_id,
                 metadata={"feature_index": idx}
             )
        except: pass

    status = "PASSING" if passing else "FAILING"
    return {"content": [{"type": "text", "text": f"Marked feature #{idx} as {status}"}]}

@tool("feature_mark_blocked", "Mark features as blocked by missing capability.", {"feature_ids": list, "reason": str})
async def feature_mark_blocked(args: dict) -> dict:
    """
    Mark features as blocked by a missing capability.

    Use this when features require capabilities (like Docker) that are not available.

    Args:
        feature_ids: List of feature indices to mark as blocked
        reason: Reason for blocking (e.g., "docker_unavailable", "postgres_unavailable")
    """
    feature_ids = args.get("feature_ids", [])
    reason = args.get("reason", "capability_unavailable")

    if not feature_ids:
        return {"content": [{"type": "text", "text": "Error: No feature IDs provided"}], "is_error": True}

    session_maker = get_session_maker()
    blocked_count = 0

    async with session_maker() as session:
        for fid in feature_ids:
            result = await session.execute(select(Feature).where(Feature.index == fid))
            feature = result.scalar_one_or_none()
            if feature:
                # Store blocking reason in feature_metadata
                metadata = feature.feature_metadata or {}
                metadata["blocked_by_capability"] = reason
                feature.feature_metadata = metadata
                blocked_count += 1

        await session.commit()

    return {
        "content": [{
            "type": "text",
            "text": f"Marked {blocked_count} feature(s) as blocked (reason: {reason})"
        }]
    }


@tool("feature_unblock", "Remove blocked status from features.", {"feature_ids": list})
async def feature_unblock(args: dict) -> dict:
    """
    Remove blocked status from features.

    Use this when a capability becomes available and features can be implemented.

    Args:
        feature_ids: List of feature indices to unblock (or empty to unblock all)
    """
    feature_ids = args.get("feature_ids", [])

    session_maker = get_session_maker()
    unblocked_count = 0

    async with session_maker() as session:
        if feature_ids:
            # Unblock specific features
            for fid in feature_ids:
                result = await session.execute(select(Feature).where(Feature.index == fid))
                feature = result.scalar_one_or_none()
                if feature:
                    metadata = feature.feature_metadata or {}
                    if "blocked_by_capability" in metadata:
                        del metadata["blocked_by_capability"]
                        feature.feature_metadata = metadata
                        unblocked_count += 1
        else:
            # Unblock all features (need to check each one)
            result = await session.execute(select(Feature))
            features = result.scalars().all()
            for feature in features:
                metadata = feature.feature_metadata or {}
                if "blocked_by_capability" in metadata:
                    del metadata["blocked_by_capability"]
                    feature.feature_metadata = metadata
                    unblocked_count += 1

        await session.commit()

    return {
        "content": [{
            "type": "text",
            "text": f"Unblocked {unblocked_count} feature(s)"
        }]
    }


@tool("feature_list_blocked", "List features blocked by missing capabilities.", {})
async def feature_list_blocked(args: dict) -> dict:
    """List all features that are blocked by missing capabilities."""
    session_maker = get_session_maker()

    async with session_maker() as session:
        result = await session.execute(select(Feature))
        all_features = result.scalars().all()

    # Filter to blocked features
    blocked_features = []
    for f in all_features:
        metadata = f.feature_metadata or {}
        if metadata.get("blocked_by_capability"):
            blocked_features.append((f, metadata["blocked_by_capability"]))

    if not blocked_features:
        return {"content": [{"type": "text", "text": "No blocked features."}]}

    lines = [f"BLOCKED FEATURES ({len(blocked_features)})", "="*40]

    # Group by reason
    by_reason = {}
    for feat, reason in blocked_features:
        if reason not in by_reason:
            by_reason[reason] = []
        by_reason[reason].append(feat)

    for reason, features in by_reason.items():
        lines.append(f"\n[{reason}]")
        for feat in features:
            lines.append(f"  #{feat.index}: {feat.description[:60]}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool("feature_audit", "Audit feature.", {"index": int, "status": str, "notes": list})
async def feature_audit(args: dict) -> dict:
    idx = args["index"]
    features = await _load_features()
    if idx < 0 or idx >= len(features): return {"is_error": True}

    features[idx]["audit"] = {
        "status": args.get("status"),
        "notes": args.get("notes", []),
        "reviewer": args.get("reviewer", "audit-agent")
    }
    await _save_features(features)
    return {"content": [{"type": "text", "text": "Audit recorded"}]}

@tool("feature_audit_list", "List audits.", {"status": str})
async def feature_audit_list(args: dict) -> dict:
    status = args.get("status", "flagged")
    features = await _load_features()
    matches = [(i, f) for i, f in enumerate(features) if f.get("audit", {}).get("status") == status]
    
    lines = [f"Features with audit status '{status}':"]
    for i, f in matches:
        lines.append(f"[#{i}] {f.get('description')}")
        
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}

@tool("feature_add", "Add a new feature to the database.", {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "Category: 'functional' or 'style'"
        },
        "description": {
            "type": "string",
            "description": "Brief description of the feature"
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of verification steps"
        }
    },
    "required": ["category", "description", "steps"]
})
async def feature_add(args: dict) -> dict:
    """Add a new feature to the database."""
    category = args.get("category", "functional")
    if category not in ("functional", "style"):
        category = "functional"

    description = args.get("description", "")
    steps = args.get("steps", [])

    if not description:
        return {"content": [{"type": "text", "text": "Error: description is required"}], "is_error": True}
    if not steps:
        return {"content": [{"type": "text", "text": "Error: steps are required"}], "is_error": True}

    # Get current features to determine next index
    features = await _load_features()
    next_index = len(features)

    # Add to database directly
    session_maker = get_session_maker()
    async with session_maker() as session:
        new_feature = Feature(
            index=next_index,
            category=category,
            description=description,
            steps=steps,
            passes=False,
        )
        session.add(new_feature)
        await session.commit()

    return {
        "content": [{
            "type": "text",
            "text": f"Feature #{next_index} added successfully.\nCategory: {category}\nDescription: {description}\nSteps: {len(steps)}"
        }]
    }

FEATURE_TOOLS = [
    "mcp__features__feature_stats",
    "mcp__features__feature_next",
    "mcp__features__feature_show",
    "mcp__features__feature_list",
    "mcp__features__feature_search",
    "mcp__features__feature_mark",
    "mcp__features__feature_mark_blocked",
    "mcp__features__feature_unblock",
    "mcp__features__feature_list_blocked",
    "mcp__features__feature_add",
    "mcp__features__feature_audit",
    "mcp__features__feature_audit_list",
]

def create_feature_tools_server(project_dir: Path) -> McpSdkServerConfig:
    global _project_dir
    _project_dir = project_dir
    return create_sdk_mcp_server(
        name="features",
        version="1.0.0",
        tools=[
            feature_stats,
            feature_next,
            feature_show,
            feature_list,
            feature_search,
            feature_mark,
            feature_mark_blocked,
            feature_unblock,
            feature_list_blocked,
            feature_add,
            feature_audit,
            feature_audit_list,
        ]
    )
