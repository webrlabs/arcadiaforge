"""
Database Models for Arcadia Forge
=================================

SQLAlchemy models for persisting project state, events, and artifacts.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, JSON, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Session(Base):
    """Represents a single execution session of the agent."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Using string for UUID to be SQLite friendly
    session_uuid: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, completed, failed
    total_cost: Mapped[float] = mapped_column(Integer, default=0.0)
    
    events: Mapped[List["Event"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    artifacts: Mapped[List["Artifact"]] = relationship(back_populates="session")

class Event(Base):
    """Represents a single event in the system (tool use, log, error)."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    type: Mapped[str] = mapped_column(String(50))  # tool_use, tool_result, log, error
    source: Mapped[str] = mapped_column(String(50), default="system")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)
    
    session: Mapped["Session"] = relationship(back_populates="events")

class Feature(Base):
    """Represents a feature requirement to be implemented."""
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The 0-based index from the original JSON list (for compatibility)
    index: Mapped[int] = mapped_column(Integer, unique=True)

    category: Mapped[str] = mapped_column(String(50), default="functional")
    description: Mapped[str] = mapped_column(Text)
    steps: Mapped[List[str]] = mapped_column(JSON)

    # Status tracking
    passes: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit info
    audit_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True) # ok, flagged, pending
    audit_notes: Mapped[List[str]] = mapped_column(JSON, default=list)
    audit_reviewer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    audit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Salience fields for intelligent prioritization
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1=critical, 2=high, 3=medium, 4=low
    failure_count: Mapped[int] = mapped_column(Integer, default=0)  # Times this feature has failed
    last_worked: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # ISO timestamp
    blocked_by: Mapped[List[int]] = mapped_column(JSON, default=list)  # Features this depends on
    blocks: Mapped[List[int]] = mapped_column(JSON, default=list)  # Features that depend on this

    # Additional metadata storage (JSON blob for flexibility)
    feature_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Relationships
    artifacts: Mapped[List["Artifact"]] = relationship(back_populates="feature")

class Artifact(Base):
    """Represents a file or digital asset generated during the process."""
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    feature_index: Mapped[Optional[int]] = mapped_column(ForeignKey("features.index"), nullable=True)
    
    type: Mapped[str] = mapped_column(String(50)) # screenshot, patch, log
    path: Mapped[str] = mapped_column(String(255)) # Relative path to project root
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="artifacts")
    feature: Mapped["Feature"] = relationship(back_populates="artifacts")


class Checkpoint(Base):
    """Represents a semantic checkpoint capturing project state."""
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkpoint_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "CP-{session}-{seq}"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trigger: Mapped[str] = mapped_column(String(50))  # CheckpointTrigger value
    session_id: Mapped[int] = mapped_column(Integer)

    # Git state
    git_commit: Mapped[str] = mapped_column(String(100))
    git_branch: Mapped[str] = mapped_column(String(100))
    git_clean: Mapped[bool] = mapped_column(Boolean, default=False)

    # Feature state
    feature_status: Mapped[Dict[str, Any]] = mapped_column(JSON)  # {feature_index: passes}
    features_passing: Mapped[int] = mapped_column(Integer, default=0)
    features_total: Mapped[int] = mapped_column(Integer, default=0)

    # File state
    files_hash: Mapped[str] = mapped_column(String(100))

    # Recovery information
    last_successful_feature: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending_work: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Metadata (renamed to avoid SQLAlchemy reserved name)
    checkpoint_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    human_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Decision(Base):
    """Represents a logged decision with full context and rationale."""
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "D-{session}-{seq}"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    # The decision
    decision_type: Mapped[str] = mapped_column(String(50))  # DecisionType value
    context: Mapped[str] = mapped_column(Text)
    choice: Mapped[str] = mapped_column(Text)
    alternatives: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Rationale
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Integer, default=0.5)
    inputs_consulted: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Outcome (filled in later)
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    outcome_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Traceability
    related_features: Mapped[List[int]] = mapped_column(JSON, default=list)
    git_commit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    checkpoint_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Metadata (renamed to avoid SQLAlchemy reserved name)
    decision_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class Hypothesis(Base):
    """Represents a hypothesis or observation tracked across sessions."""
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hypothesis_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "HYP-{session}-{seq}"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_session: Mapped[int] = mapped_column(Integer, index=True)

    hypothesis_type: Mapped[str] = mapped_column(String(50))  # HypothesisType value
    observation: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Integer, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="open")  # HypothesisStatus value

    # Context
    context_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    related_features: Mapped[List[int]] = mapped_column(JSON, default=list)
    related_errors: Mapped[List[str]] = mapped_column(JSON, default=list)
    related_files: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Evidence (stored as JSON)
    evidence_for: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_against: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Resolution
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_session: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    superseded_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Tracking
    last_reviewed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    sessions_seen: Mapped[List[int]] = mapped_column(JSON, default=list)


class HotMemory(Base):
    """Represents current session working state (hot memory tier)."""
    __tablename__ = "hot_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Working context
    current_feature: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_task: Mapped[str] = mapped_column(Text, default="")
    recent_actions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    recent_files: Mapped[List[str]] = mapped_column(JSON, default=list)
    focus_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Active errors
    active_errors: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Pending decisions
    pending_decisions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Current hypotheses
    current_hypotheses: Mapped[List[str]] = mapped_column(JSON, default=list)  # List of hypothesis_ids


class WarmMemory(Base):
    """Represents recent session context (warm memory tier)."""
    __tablename__ = "warm_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float] = mapped_column(Integer, default=0.0)

    # Progress
    features_started: Mapped[int] = mapped_column(Integer, default=0)
    features_completed: Mapped[int] = mapped_column(Integer, default=0)
    features_regressed: Mapped[int] = mapped_column(Integer, default=0)

    # Key events
    key_decisions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    errors_encountered: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    errors_resolved: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # State at end
    last_feature_worked: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_checkpoint_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ending_state: Mapped[str] = mapped_column(String(20), default="completed")

    # Learnings
    patterns_discovered: Mapped[List[str]] = mapped_column(JSON, default=list)
    warnings_for_next: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Metrics
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    escalations: Mapped[int] = mapped_column(Integer, default=0)
    human_interventions: Mapped[int] = mapped_column(Integer, default=0)


class WarmMemoryIssue(Base):
    """Represents an unresolved issue in warm memory."""
    __tablename__ = "warm_memory_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_session: Mapped[int] = mapped_column(Integer)

    issue_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1=high, 5=low

    related_features: Mapped[List[int]] = mapped_column(JSON, default=list)
    related_files: Mapped[List[str]] = mapped_column(JSON, default=list)
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    attempted_solutions: Mapped[List[str]] = mapped_column(JSON, default=list)
    last_seen_session: Mapped[int] = mapped_column(Integer)
    times_encountered: Mapped[int] = mapped_column(Integer, default=1)


class WarmMemoryPattern(Base):
    """Represents a proven pattern in warm memory."""
    __tablename__ = "warm_memory_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_session: Mapped[int] = mapped_column(Integer)

    pattern_type: Mapped[str] = mapped_column(String(50))
    pattern: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text)
    success_count: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Integer, default=0.5)

    context_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    source_sessions: Mapped[List[int]] = mapped_column(JSON, default=list)
    last_used_session: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ColdMemory(Base):
    """Represents archived historical data (cold memory tier)."""
    __tablename__ = "cold_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ending_state: Mapped[str] = mapped_column(String(20))
    features_completed: Mapped[int] = mapped_column(Integer, default=0)
    features_regressed: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Integer, default=0.0)


class ColdMemoryKnowledge(Base):
    """Represents proven knowledge extracted from history."""
    __tablename__ = "cold_memory_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge_type: Mapped[str] = mapped_column(String(50))  # fix, pattern, warning, best_practice
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)

    context_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    source_sessions: Mapped[List[int]] = mapped_column(JSON, default=list)
    times_verified: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Integer, default=0.5)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProgressEntry(Base):
    """Represents a progress log entry from a coding session."""
    __tablename__ = "progress_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # What was done
    accomplished: Mapped[List[str]] = mapped_column(JSON, default=list)
    tests_completed: Mapped[List[int]] = mapped_column(JSON, default=list)
    tests_status: Mapped[str] = mapped_column(String(50), default="unknown")

    # Issues
    issues_found: Mapped[List[str]] = mapped_column(JSON, default=list)
    issues_fixed: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Planning
    next_steps: Mapped[List[str]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# =============================================================================
# Autonomy Module Tables (replaces .autonomy/ directory)
# =============================================================================

class AutonomyConfigModel(Base):
    """
    Stores autonomy configuration (single row table).
    Replaces: .autonomy/config.json
    """
    __tablename__ = "autonomy_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    level: Mapped[int] = mapped_column(Integer, default=3)  # AutonomyLevel value (1-5)
    action_levels: Mapped[Dict[str, int]] = mapped_column(JSON, default=dict)  # tool_name -> level
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    error_demotion_count: Mapped[int] = mapped_column(Integer, default=3)
    success_promotion_count: Mapped[int] = mapped_column(Integer, default=10)
    auto_adjust: Mapped[bool] = mapped_column(Boolean, default=True)
    min_level: Mapped[int] = mapped_column(Integer, default=1)
    max_level: Mapped[int] = mapped_column(Integer, default=4)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutonomyMetricsModel(Base):
    """
    Stores autonomy performance metrics (single row table).
    Replaces: .autonomy/metrics.json
    """
    __tablename__ = "autonomy_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    total_actions: Mapped[int] = mapped_column(Integer, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, default=0)
    recent_outcomes: Mapped[List[bool]] = mapped_column(JSON, default=list)  # Last N outcomes
    level_changes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)  # History of level changes
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutonomyDecisionModel(Base):
    """
    Records of autonomy permission checks.
    Replaces: .autonomy/decisions.jsonl
    """
    __tablename__ = "autonomy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    action: Mapped[str] = mapped_column(String(255))  # Brief action description
    tool: Mapped[str] = mapped_column(String(50), index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, index=True)
    required_level: Mapped[int] = mapped_column(Integer)
    current_level: Mapped[int] = mapped_column(Integer)
    effective_level: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    alternatives: Mapped[List[str]] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# =============================================================================
# Escalation Module Tables (replaces .escalation/ directory)
# =============================================================================

class EscalationRuleModel(Base):
    """
    Custom escalation rules.
    Replaces: .escalation/rules.json
    """
    __tablename__ = "escalation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)

    # Condition configuration
    condition_type: Mapped[str] = mapped_column(String(50))  # threshold_below, threshold_above, equals, etc.
    condition_params: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Escalation configuration
    severity: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    injection_type: Mapped[str] = mapped_column(String(50))  # decision, approval, guidance, review, redirect
    message_template: Mapped[str] = mapped_column(Text)
    suggested_actions: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Behavior
    auto_pause: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    default_action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Metadata
    is_custom: Mapped[bool] = mapped_column(Boolean, default=True)  # False for built-in rules
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EscalationLogModel(Base):
    """
    Log of triggered escalations.
    Replaces: .escalation/escalations.jsonl
    """
    __tablename__ = "escalation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    rule_id: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    context_summary: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


# =============================================================================
# Risk Module Tables (replaces .risk/ directory)
# =============================================================================

class RiskPatternModel(Base):
    """
    Custom risk classification patterns.
    Replaces: .risk/patterns.json
    """
    __tablename__ = "risk_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)

    # Pattern matching
    tool: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # None means any tool
    input_pattern: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Regex pattern
    input_field: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Which field to check

    # Risk characteristics
    risk_level: Mapped[int] = mapped_column(Integer)  # 1-5 (RiskLevel enum value)
    is_reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    affects_source_of_truth: Mapped[bool] = mapped_column(Boolean, default=False)
    has_external_side_effects: Mapped[bool] = mapped_column(Boolean, default=False)

    # Gating requirements
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    mitigation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    is_custom: Mapped[bool] = mapped_column(Boolean, default=True)  # False for built-in patterns
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskAssessmentModel(Base):
    """
    Log of risk assessments performed.
    Replaces: .risk/assessments.jsonl
    """
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    action: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(50), index=True)
    input_summary: Mapped[str] = mapped_column(Text)

    risk_level: Mapped[int] = mapped_column(Integer, index=True)  # 1-5
    is_reversible: Mapped[bool] = mapped_column(Boolean)
    affects_source_of_truth: Mapped[bool] = mapped_column(Boolean)
    has_external_side_effects: Mapped[bool] = mapped_column(Boolean)

    concerns: Mapped[List[str]] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_mitigation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# =============================================================================
# Failure Analysis Tables (replaces .failure_reports/ directory)
# =============================================================================

class FailureReportModel(Base):
    """
    Failure analysis reports.
    Replaces: .failure_reports/failure_report_*.json
    """
    __tablename__ = "failure_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    failure_type: Mapped[str] = mapped_column(String(50), index=True)  # FailureType enum value
    severity: Mapped[int] = mapped_column(Integer)  # 1-4 (Severity enum value)

    # Context
    last_successful_action: Mapped[str] = mapped_column(Text, default="")
    failing_action: Mapped[str] = mapped_column(Text, default="")
    error_messages: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Analysis
    likely_cause: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    patterns_detected: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    similar_past_failures: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Recommendations
    suggested_fixes: Mapped[List[str]] = mapped_column(JSON, default=list)
    failure_timeline: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Statistics
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_actions: Mapped[int] = mapped_column(Integer, default=0)


# =============================================================================
# Human Interface Tables (replaces .human/ directory)
# =============================================================================

class InjectionPointModel(Base):
    """
    Human injection points for agent intervention.
    Replaces: .human/pending/, .human/responses/, .human/completed/, .human/history.jsonl
    """
    __tablename__ = "injection_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "INJ-{session}-{seq}"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    # Request details
    point_type: Mapped[str] = mapped_column(String(50))  # InjectionType enum value
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    options: Mapped[List[str]] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text)

    # Timeout configuration
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    default_on_timeout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Response fields
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_by: Mapped[str] = mapped_column(String(50), default="pending")  # pending, human, timeout_default, cancelled

    # Status: pending, responded, timeout, cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # Additional context
    escalation_rule_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[int] = mapped_column(Integer, default=3)


# =============================================================================
# Intervention Learning Tables (replaces .learning/ directory)
# =============================================================================

class InterventionModel(Base):
    """
    Human interventions for pattern learning.
    Replaces: .learning/interventions.jsonl
    """
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "INT-{seq}"
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Type and context
    intervention_type: Mapped[str] = mapped_column(String(50))  # InterventionType enum value
    context_signature: Mapped[Dict[str, Any]] = mapped_column(JSON)  # ContextSignature as dict
    context_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Original action
    original_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Human intervention
    human_action: Mapped[str] = mapped_column(Text, default="")
    human_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Outcome tracking
    outcome_tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class InterventionPatternModel(Base):
    """
    Learned patterns from interventions.
    Replaces: .learning/patterns.json
    """
    __tablename__ = "intervention_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "PAT-{seq}"
    context_signature: Mapped[Dict[str, Any]] = mapped_column(JSON)  # ContextSignature as dict

    # Statistics
    times_matched: Mapped[int] = mapped_column(Integer, default=0)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    # Learned intervention
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")

    # Auto-apply settings
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    min_confidence_for_auto: Mapped[float] = mapped_column(Float, default=0.8)

    # Source tracking
    source_intervention_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_matched: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# =============================================================================
# Troubleshooting Knowledge Base Tables (replaces troubleshooting.json)
# =============================================================================

class TroubleshootingEntry(Base):
    """
    Troubleshooting knowledge base entry.
    Replaces: troubleshooting.json
    """
    __tablename__ = "troubleshooting_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Classification
    category: Mapped[str] = mapped_column(String(50), index=True)  # build, runtime, dependency, etc.
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Problem
    error_message: Mapped[str] = mapped_column(Text)
    symptoms: Mapped[List[str]] = mapped_column(JSON, default=list)
    cause: Mapped[str] = mapped_column(Text, default="")

    # Solution
    solution: Mapped[str] = mapped_column(Text)
    steps_to_fix: Mapped[List[str]] = mapped_column(JSON, default=list)
    prevention: Mapped[str] = mapped_column(Text, default="")


# =============================================================================
# Agent Communication Tables (cross-session messaging)
# =============================================================================

class AgentMessage(Base):
    """
    Messages for cross-session agent communication.

    Allows agents to leave messages, warnings, hints, and handoff notes
    for future sessions to read.
    """
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "MSG-{session}-{seq}"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_session: Mapped[int] = mapped_column(Integer, index=True)

    # Message classification
    message_type: Mapped[str] = mapped_column(String(20), index=True)  # warning, hint, blocker, discovery, handoff
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1=critical, 2=high, 3=normal, 4=low, 5=info

    # Content
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)

    # Context
    related_features: Mapped[List[int]] = mapped_column(JSON, default=list)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)

    # Read tracking (persists indefinitely until acknowledged)
    read_by_sessions: Mapped[List[int]] = mapped_column(JSON, default=list)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by_session: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SystemCapability(Base):
    """
    Tracks available system capabilities (docker, node, git, etc.).

    Checked at startup and cached in database for agent queries.
    """
    __tablename__ = "system_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_name: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    # Availability
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Check status
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Additional details (JSON blob for flexibility)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class StallRecord(Base):
    """
    Tracks stall detection across sessions.

    Records when progress stalls and tracks resolution.
    """
    __tablename__ = "stall_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[int] = mapped_column(Integer, index=True)

    # Stall classification
    stall_type: Mapped[str] = mapped_column(String(30), index=True)  # no_progress, cyclic, capability_missing

    # Progress tracking
    consecutive_sessions: Mapped[int] = mapped_column(Integer, default=1)
    last_passing_count: Mapped[int] = mapped_column(Integer, default=0)
    last_git_hash: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Blocker info
    blocked_on: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Description of what's blocking
    blocked_features: Mapped[List[int]] = mapped_column(JSON, default=list)
    missing_capability: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Resolution
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
