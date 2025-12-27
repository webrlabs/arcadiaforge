"""
Database Package
================

Exports key database components.
"""

from arcadiaforge.db.models import (
    # Base
    Base,
    # Core tables
    Session, Event, Feature, Artifact,
    Checkpoint, Decision, Hypothesis,
    # Memory tables
    HotMemory, WarmMemory, WarmMemoryIssue, WarmMemoryPattern,
    ColdMemory, ColdMemoryKnowledge,
    # Progress
    ProgressEntry,
    # Autonomy tables (replaces .autonomy/)
    AutonomyConfigModel, AutonomyMetricsModel, AutonomyDecisionModel,
    # Escalation tables (replaces .escalation/)
    EscalationRuleModel, EscalationLogModel,
    # Risk tables (replaces .risk/)
    RiskPatternModel, RiskAssessmentModel,
    # Failure analysis tables (replaces .failure_reports/)
    FailureReportModel,
    # Human interface tables (replaces .human/)
    InjectionPointModel,
    # Intervention learning tables (replaces .learning/)
    InterventionModel, InterventionPatternModel,
)
from arcadiaforge.db.connection import init_db, get_session_maker, get_db
