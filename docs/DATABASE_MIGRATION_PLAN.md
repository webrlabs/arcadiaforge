# Database Migration Plan: File-Based Storage to SQLite

## Overview

This document outlines the migration strategy for consolidating all file-based storage (dot directories) into the centralized SQLite database located at `.arcadia/project.db`.

**Current State**: 9 dot directories with JSON/JSONL/CSV files
**Target State**: Single `.arcadia/project.db` SQLite database
**Estimated Scope**: 7 new tables, 2 table modifications, 8 module updates

---

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Target Architecture](#target-architecture)
3. [New Database Tables](#new-database-tables)
4. [Migration Phases](#migration-phases)
5. [Implementation Details](#implementation-details)
6. [Rollback Strategy](#rollback-strategy)
7. [Testing Plan](#testing-plan)

---

## Current Architecture

### Existing Database Tables (models.py)

The following tables already exist in `.arcadia/project.db`:

| Table | Purpose |
|-------|---------|
| `sessions` | Execution sessions |
| `events` | System events (tool use, logs, errors) |
| `features` | Feature requirements |
| `artifacts` | Generated files/assets |
| `checkpoints` | Semantic checkpoints |
| `decisions` | Logged decisions |
| `hypotheses` | Tracked hypotheses |
| `hot_memory` | Current session state |
| `warm_memory` | Recent session context |
| `warm_memory_issues` | Unresolved issues |
| `warm_memory_patterns` | Proven patterns |
| `cold_memory` | Archived sessions |
| `cold_memory_knowledge` | Proven knowledge |
| `progress_entries` | Progress logs |

### File-Based Storage to Migrate

| Directory | Module | Files | Data Type |
|-----------|--------|-------|-----------|
| `.autonomy/` | `autonomy.py` | `config.json`, `metrics.json`, `decisions.jsonl` | Autonomy state |
| `.escalation/` | `escalation.py` | `rules.json`, `escalations.jsonl` | Escalation rules/logs |
| `.risk/` | `risk.py` | `assessments.jsonl`, `patterns.json` | Risk assessments |
| `.failure_reports/` | `failure_analysis.py` | `failure_report_*.json` | Failure reports |
| `.human/` | `human_interface.py` | `pending/`, `responses/`, `completed/`, `history.jsonl` | Human injections |
| `.learning/` | `intervention_learning.py` | `interventions.jsonl`, `patterns.json` | Intervention learning |
| `.metrics/` | `metrics.py` | `metrics.json`, `*.csv` | Metrics exports |
| `.memory/` | `memory/*.py` | Various JSON/JSONL | Memory tiers (partial) |

---

## Target Architecture

After migration, the project structure will be:

```
project/
├── .arcadia/
│   └── project.db          # All persistent state
├── src/                    # Project source code
└── ...
```

All dot directories (`.autonomy/`, `.escalation/`, `.risk/`, `.failure_reports/`, `.human/`, `.learning/`, `.metrics/`, `.memory/`) will be removed.

---

## New Database Tables

### 1. `autonomy_config` (Single Row)

Stores the current autonomy configuration.

```python
class AutonomyConfig(Base):
    """Stores autonomy configuration (single row table)."""
    __tablename__ = "autonomy_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    level: Mapped[int] = mapped_column(Integer, default=3)  # AutonomyLevel value
    action_levels: Mapped[Dict[str, int]] = mapped_column(JSON, default=dict)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    error_demotion_count: Mapped[int] = mapped_column(Integer, default=3)
    success_promotion_count: Mapped[int] = mapped_column(Integer, default=10)
    auto_adjust: Mapped[bool] = mapped_column(Boolean, default=True)
    min_level: Mapped[int] = mapped_column(Integer, default=1)
    max_level: Mapped[int] = mapped_column(Integer, default=4)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 2. `autonomy_metrics` (Single Row)

Stores performance metrics for autonomy adjustments.

```python
class AutonomyMetrics(Base):
    """Stores autonomy performance metrics (single row table)."""
    __tablename__ = "autonomy_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    total_actions: Mapped[int] = mapped_column(Integer, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, default=0)
    recent_outcomes: Mapped[List[bool]] = mapped_column(JSON, default=list)
    level_changes: Mapped[List[Dict]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 3. `autonomy_decisions`

Stores autonomy decision records (replaces `decisions.jsonl`).

```python
class AutonomyDecision(Base):
    """Records of autonomy permission checks."""
    __tablename__ = "autonomy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    action: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(50))
    allowed: Mapped[bool] = mapped_column(Boolean)
    required_level: Mapped[int] = mapped_column(Integer)
    current_level: Mapped[int] = mapped_column(Integer)
    effective_level: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    alternatives: Mapped[List[str]] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
```

### 4. `escalation_rules`

Stores custom escalation rules.

```python
class EscalationRule(Base):
    """Custom escalation rules."""
    __tablename__ = "escalation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)

    condition_type: Mapped[str] = mapped_column(String(50))
    condition_params: Mapped[Dict] = mapped_column(JSON, default=dict)

    severity: Mapped[int] = mapped_column(Integer, default=3)
    injection_type: Mapped[str] = mapped_column(String(50))
    message_template: Mapped[str] = mapped_column(Text)
    suggested_actions: Mapped[List[str]] = mapped_column(JSON, default=list)

    auto_pause: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    default_action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    is_custom: Mapped[bool] = mapped_column(Boolean, default=True)  # False for built-in
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 5. `escalation_logs`

Stores escalation trigger history.

```python
class EscalationLog(Base):
    """Log of triggered escalations."""
    __tablename__ = "escalation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    rule_id: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    context_summary: Mapped[Dict] = mapped_column(JSON, default=dict)
```

### 6. `risk_patterns`

Stores custom risk patterns.

```python
class RiskPattern(Base):
    """Custom risk classification patterns."""
    __tablename__ = "risk_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)

    tool: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    input_pattern: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    input_field: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    risk_level: Mapped[int] = mapped_column(Integer)
    is_reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    affects_source_of_truth: Mapped[bool] = mapped_column(Boolean, default=False)
    has_external_side_effects: Mapped[bool] = mapped_column(Boolean, default=False)

    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    mitigation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_custom: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 7. `risk_assessments`

Stores risk assessment history.

```python
class RiskAssessment(Base):
    """Log of risk assessments performed."""
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    action: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(50))
    input_summary: Mapped[str] = mapped_column(Text)

    risk_level: Mapped[int] = mapped_column(Integer)
    is_reversible: Mapped[bool] = mapped_column(Boolean)
    affects_source_of_truth: Mapped[bool] = mapped_column(Boolean)
    has_external_side_effects: Mapped[bool] = mapped_column(Boolean)

    concerns: Mapped[List[str]] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_mitigation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

### 8. `failure_reports`

Stores failure analysis reports.

```python
class FailureReport(Base):
    """Failure analysis reports."""
    __tablename__ = "failure_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    failure_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[int] = mapped_column(Integer)

    last_successful_action: Mapped[str] = mapped_column(Text, default="")
    failing_action: Mapped[str] = mapped_column(Text, default="")
    error_messages: Mapped[List[str]] = mapped_column(JSON, default=list)

    likely_cause: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    patterns_detected: Mapped[List[Dict]] = mapped_column(JSON, default=list)
    similar_past_failures: Mapped[List[Dict]] = mapped_column(JSON, default=list)

    suggested_fixes: Mapped[List[str]] = mapped_column(JSON, default=list)
    failure_timeline: Mapped[List[Dict]] = mapped_column(JSON, default=list)

    error_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_actions: Mapped[int] = mapped_column(Integer, default=0)
```

### 9. `injection_points`

Stores human injection points (replaces `.human/` directory).

```python
class InjectionPoint(Base):
    """Human injection points for agent intervention."""
    __tablename__ = "injection_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    point_type: Mapped[str] = mapped_column(String(50))
    context: Mapped[Dict] = mapped_column(JSON, default=dict)
    options: Mapped[List[str]] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text)

    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    default_on_timeout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Response fields
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_by: Mapped[str] = mapped_column(String(50), default="pending")

    # Status: pending, responded, timeout, cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    escalation_rule_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[int] = mapped_column(Integer, default=3)
```

### 10. `interventions`

Stores human interventions for learning.

```python
class Intervention(Base):
    """Human interventions for pattern learning."""
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    intervention_type: Mapped[str] = mapped_column(String(50))
    context_signature: Mapped[Dict] = mapped_column(JSON)
    context_details: Mapped[Dict] = mapped_column(JSON, default=dict)

    original_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_action: Mapped[str] = mapped_column(Text, default="")
    human_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    outcome_tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

### 11. `intervention_patterns`

Stores learned intervention patterns.

```python
class InterventionPattern(Base):
    """Learned patterns from interventions."""
    __tablename__ = "intervention_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    context_signature: Mapped[Dict] = mapped_column(JSON)

    times_matched: Mapped[int] = mapped_column(Integer, default=0)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    recommended_action: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")

    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    min_confidence_for_auto: Mapped[float] = mapped_column(Float, default=0.8)

    source_intervention_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_matched: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

## Migration Phases

### Phase 1: Database Schema (Priority: HIGH)

**Files to modify**: `arcadiaforge/db/models.py`

1. Add all new table definitions listed above
2. Add indexes for frequently queried columns
3. Ensure proper foreign key relationships

**Estimated effort**: 2-3 hours

### Phase 2: Autonomy Module (Priority: HIGH)

**Files to modify**: `arcadiaforge/autonomy.py`

1. Replace file operations with async database calls
2. Update `AutonomyManager.__init__()` to load from DB
3. Update `_save_config()`, `_save_metrics()`, `_log_decision()`
4. Add data access layer functions
5. Remove directory creation logic

**Data Migration**:
- `config.json` → `autonomy_config` table
- `metrics.json` → `autonomy_metrics` table
- `decisions.jsonl` → `autonomy_decisions` table

**Estimated effort**: 3-4 hours

### Phase 3: Escalation Module (Priority: HIGH)

**Files to modify**: `arcadiaforge/escalation.py`

1. Replace file operations with database calls
2. Update `EscalationEngine.__init__()` to load rules from DB
3. Update `_load_custom_rules()`, `_save_custom_rules()`
4. Update `_log_escalation()` to write to DB
5. Update `get_escalation_history()` to query DB

**Data Migration**:
- `rules.json` → `escalation_rules` table
- `escalations.jsonl` → `escalation_logs` table

**Estimated effort**: 2-3 hours

### Phase 4: Risk Module (Priority: MEDIUM)

**Files to modify**: `arcadiaforge/risk.py`

1. Replace file operations with database calls
2. Update `RiskClassifier._load_patterns()` to query DB
3. Update `add_pattern()` to insert into DB
4. Update `_log_assessment()` to insert into DB
5. Update `get_assessment_history()` to query DB

**Data Migration**:
- `patterns.json` → `risk_patterns` table
- `assessments.jsonl` → `risk_assessments` table

**Estimated effort**: 2-3 hours

### Phase 5: Failure Analysis Module (Priority: MEDIUM)

**Files to modify**: `arcadiaforge/failure_analysis.py`

1. Replace file operations with database calls
2. Update `FailureAnalyzer._save_report()` to insert into DB
3. Update `get_report()` to query DB
4. Remove `.failure_reports/` directory creation

**Data Migration**:
- `failure_report_*.json` → `failure_reports` table

**Estimated effort**: 2 hours

### Phase 6: Human Interface Module (Priority: HIGH)

**Files to modify**: `arcadiaforge/human_interface.py`

1. **Major refactor**: Replace file-polling with DB-based communication
2. Update `request_input()` to insert into `injection_points`
3. Update `_poll_for_response()` to poll DB instead of file
4. Update `respond()` to update DB record
5. Update `get_pending()` to query DB
6. Remove all directory creation logic

**Note**: This is the most complex migration due to the file-based polling mechanism.

**Data Migration**:
- `pending/*.json` → `injection_points` (status='pending')
- `completed/*.json` → `injection_points` (status='responded'/'timeout')
- `history.jsonl` → Already captured in `injection_points`

**Estimated effort**: 4-5 hours

### Phase 7: Intervention Learning Module (Priority: MEDIUM)

**Files to modify**: `arcadiaforge/intervention_learning.py`

1. Replace file operations with database calls
2. Update `InterventionLearner._load_patterns()` to query DB
3. Update `_save_patterns()` to update DB
4. Update `_log_intervention()` to insert into DB
5. Update `record_outcome()` to update DB

**Data Migration**:
- `interventions.jsonl` → `interventions` table
- `patterns.json` → `intervention_patterns` table

**Estimated effort**: 3 hours

### Phase 8: Metrics Module (Priority: LOW)

**Files to modify**: `arcadiaforge/metrics.py`

The metrics module is primarily for **export** functionality. The underlying data already comes from the database via `Observability`. Only the export functions need modification.

1. Update `export_to_json()` to use DB-backed storage
2. Update `export_to_csv()` similarly
3. Remove `.metrics/` directory usage

**Note**: Metrics exports could remain as files since they're output artifacts, not state.

**Estimated effort**: 1-2 hours

### Phase 9: Memory Modules (Priority: LOW)

**Files to modify**: `arcadiaforge/memory/hot.py`, `warm.py`, `cold.py`

The memory modules already have database tables (`HotMemory`, `WarmMemory`, etc.). Verify they're using DB exclusively and remove any file-based fallbacks.

**Estimated effort**: 1-2 hours

### Phase 10: Cleanup (Priority: HIGH - Final Step)

1. Remove all dot directory creation code
2. Add migration script for existing projects
3. Update documentation
4. Add deprecation warnings for old file locations

**Estimated effort**: 2 hours

---

## Implementation Details

### Database Access Pattern

All modules should use the same async pattern:

```python
from arcadiaforge.db.connection import get_session_maker
from sqlalchemy import select, update

async def load_config(self) -> AutonomyConfig:
    """Load autonomy config from database."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        result = await session.execute(
            select(AutonomyConfigModel).where(AutonomyConfigModel.id == 1)
        )
        row = result.scalar_one_or_none()
        if row:
            return AutonomyConfig.from_db(row)
        return AutonomyConfig()  # Default

async def save_config(self, config: AutonomyConfig) -> None:
    """Save autonomy config to database."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        await session.merge(config.to_db_model())
        await session.commit()
```

### Sync/Async Compatibility

Some modules are currently synchronous. Options:

1. **Make modules async**: Preferred for new code
2. **Use sync wrappers**: `asyncio.run()` for backward compatibility
3. **Use sync database sessions**: SQLAlchemy supports sync sessions

Recommendation: Add async versions of methods, keep sync wrappers for CLI tools.

### Transaction Safety

Ensure atomic operations for multi-step updates:

```python
async with session_maker() as session:
    async with session.begin():
        # Multiple operations in single transaction
        await session.execute(...)
        await session.execute(...)
        # Auto-commit on success, auto-rollback on exception
```

---

## Rollback Strategy

### Phase Rollback

Each phase can be rolled back independently:

1. Keep file-based code paths behind feature flag initially
2. Add `USE_DB_STORAGE` config option
3. Run both paths in parallel for validation period
4. Remove file paths after validation

### Data Recovery

If migration fails:

1. Database tables can be dropped
2. Original dot directories preserved during migration
3. Re-run migration after fixing issues

### Feature Flag Pattern

```python
from arcadiaforge.config import USE_DB_STORAGE

class AutonomyManager:
    def _save_config(self) -> None:
        if USE_DB_STORAGE:
            asyncio.run(self._save_config_db())
        else:
            self._save_config_file()  # Legacy
```

---

## Testing Plan

### Unit Tests

For each migrated module:

1. Test database read/write operations
2. Test data type conversions
3. Test edge cases (empty tables, null values)
4. Test concurrent access

### Integration Tests

1. Full workflow with database storage
2. Session persistence across restarts
3. Query performance benchmarks
4. Data consistency checks

### Migration Tests

1. Migrate test project with known data
2. Verify data integrity post-migration
3. Test rollback procedure
4. Performance comparison (file vs DB)

### Test Data

Create fixtures for:

```python
@pytest.fixture
async def db_session():
    """Create test database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine)
    async with session_maker() as session:
        yield session
```

---

## Migration Script

Create `scripts/migrate_to_db.py`:

```python
#!/usr/bin/env python
"""
Migrate file-based storage to database.

Usage:
    python scripts/migrate_to_db.py --project-dir ./my_project
    python scripts/migrate_to_db.py --project-dir ./my_project --dry-run
"""

import asyncio
import argparse
import json
from pathlib import Path

async def migrate_autonomy(project_dir: Path, dry_run: bool = False):
    """Migrate .autonomy/ to database."""
    autonomy_dir = project_dir / ".autonomy"
    if not autonomy_dir.exists():
        return

    # Migrate config
    config_file = autonomy_dir / "config.json"
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
        if not dry_run:
            # Insert into autonomy_config table
            ...
        print(f"  Migrated: {config_file}")

    # Migrate decisions
    decisions_file = autonomy_dir / "decisions.jsonl"
    if decisions_file.exists():
        count = 0
        with open(decisions_file) as f:
            for line in f:
                if line.strip():
                    decision = json.loads(line)
                    if not dry_run:
                        # Insert into autonomy_decisions table
                        ...
                    count += 1
        print(f"  Migrated: {count} decisions")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Migrating: {args.project_dir}")

    await migrate_autonomy(args.project_dir, args.dry_run)
    # ... other migrations

    if not args.dry_run:
        print("\nMigration complete. You can now remove dot directories.")
    else:
        print("\nDry run complete. No changes made.")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary

### Priority Order

1. **Phase 1**: Database Schema (foundation)
2. **Phase 2**: Autonomy Module (frequently accessed)
3. **Phase 3**: Escalation Module (tied to autonomy)
4. **Phase 6**: Human Interface (complex but critical)
5. **Phase 4**: Risk Module
6. **Phase 5**: Failure Analysis
7. **Phase 7**: Intervention Learning
8. **Phase 8-9**: Metrics/Memory (lowest priority)
9. **Phase 10**: Cleanup

### Effort Estimates

| Phase | Effort | Priority | Status |
|-------|--------|----------|--------|
| Schema | 2-3 hrs | HIGH | COMPLETED |
| Autonomy | 3-4 hrs | HIGH | COMPLETED |
| Escalation | 2-3 hrs | HIGH | COMPLETED |
| Human Interface | 4-5 hrs | HIGH | COMPLETED |
| Risk | 2-3 hrs | MEDIUM | COMPLETED |
| Failure Analysis | 2 hrs | MEDIUM | COMPLETED |
| Intervention | 3 hrs | MEDIUM | COMPLETED |
| Metrics | 1-2 hrs | LOW | COMPLETED |
| Memory | 1-2 hrs | LOW | COMPLETED |
| Cleanup | 2 hrs | HIGH | COMPLETED |

**Total Estimated Effort**: 22-29 hours

### Migration Completed

All phases have been successfully implemented:

- All 11 new database tables created
- All modules updated with async DB methods
- Sync wrappers added for backward compatibility
- Factory functions (`create_*_async`) added for each module
- No dot directories created (verified)
- All imports working correctly

### Success Criteria

1. All data persisted in `.arcadia/project.db`
2. No dot directories created (except `.arcadia/`)
3. All existing tests pass
4. Query performance within acceptable limits
5. Successful migration of existing projects
