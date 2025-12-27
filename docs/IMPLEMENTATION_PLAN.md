# Autonomous Coding Framework - Implementation Plan

**Document Version:** 1.5
**Created:** 2025-12-18
**Last Updated:** 2025-12-19
**Status:** Phase 5 Complete - All Phases Done

---

## Overview

This document outlines a phased implementation plan to address the gaps identified in the production readiness audit. The plan prioritizes **reliability and human-in-the-loop** capabilities before adding advanced autonomy features.

### Guiding Principles

1. **Reliability before autonomy** - The system must be stable before we increase its independence
2. **Fail cheap** - Any failure should be recoverable without losing significant work
3. **Human strategically in the loop** - Humans intervene rarely but decisively
4. **Artifacts over conversation** - Persistent state, not transient context

---

## Phase Overview

| Phase | Focus | Status | Deliverables |
|-------|-------|--------|--------------|
| **Phase 1** | Reliability Foundation | ✅ **COMPLETE** | Event logging, checkpoints, validation, artifact store |
| **Phase 2** | Human-in-the-Loop | ✅ **COMPLETE** | Injection points, pause/resume, escalation, decisions |
| **Phase 3** | Memory Architecture | ✅ **COMPLETE** | Tiered memory, salience scoring, hypotheses tracking |
| **Phase 4** | Observability | ✅ **COMPLETE** | Metrics, run reconstruction, failure analysis |
| **Phase 5** | Advanced Autonomy | ✅ **COMPLETE** | Autonomy levels, risk classification, learning |

**Phase 1 Completed:** 2025-12-18
**Phase 2 Completed:** 2025-12-18
**Phase 3 Completed:** 2025-12-18
**Phase 4 Completed:** 2025-12-19
**Phase 5 Completed:** 2025-12-19

---

## Phase 1: Reliability Foundation ✅ COMPLETE

**Goal:** Ensure the system can survive failures and maintain consistent state.

**Priority:** CRITICAL - Must complete before production use

**Status:** ✅ **ALL TASKS COMPLETE** (2025-12-18)

### 1.1 Event Logging System

**New File:** `observability.py`

**Purpose:** Append-only event log that survives crashes

**Schema:**
```python
@dataclass
class Event:
    event_id: str           # UUID
    timestamp: datetime     # ISO format
    session_id: int
    event_type: str         # Enum: tool_call, tool_result, decision, checkpoint, error
    data: dict              # Event-specific payload
```

**Implementation Tasks:**

- [x] Create `observability.py` with `Observability` class
- [x] Add `log_event()` method with immediate file write
- [x] Add `reconstruct_run()` method to replay events
- [x] Integrate into `agent.py:run_agent_session()`
- [x] Log events: session_start, session_end, tool_call, tool_result, error, blocked

**Integration Points:**
```python
# agent.py - Add after imports
from arcadiaforge.observability import Observability

# In run_autonomous_agent, before main loop
obs = Observability(project_dir)

# In run_agent_session, log each tool interaction
obs.log_event("tool_call", {"tool": tool_name, "input": tool_input})
obs.log_event("tool_result", {"tool": tool_name, "success": not is_error})
```

**Acceptance Criteria:**
- [x] Events written to `.events.jsonl` on every tool call
- [x] Can reconstruct session sequence from log file
- [x] Log survives process crash

---

### 1.2 Semantic Checkpoints

**New File:** `checkpoint.py`

**Purpose:** Create recoverable snapshots at meaningful points, not just time intervals

**Schema:**
```python
@dataclass
class Checkpoint:
    checkpoint_id: str      # "CP-{session}-{seq}"
    timestamp: datetime
    trigger: CheckpointTrigger

    # State snapshot
    git_commit: str
    feature_status: dict[int, bool]
    files_hash: str

    # Recovery info
    last_successful_feature: int
    pending_work: list[str]

class CheckpointTrigger(Enum):
    FEATURE_COMPLETE = "feature_complete"
    BEFORE_RISKY_OP = "before_risky_op"
    ERROR_RECOVERY = "error_recovery"
    HUMAN_REQUEST = "human_request"
    SESSION_END = "session_end"
```

**Implementation Tasks:**

- [x] Create `checkpoint.py` with `CheckpointManager` class
- [x] Implement `create_checkpoint()` with git commit + state snapshot
- [x] Implement `rollback_to()` to restore previous state
- [x] Add checkpoint trigger in `feature_tools.py:feature_mark()`
- [x] Add checkpoint trigger before external side effects

**Integration Points:**
```python
# feature_tools.py - After marking feature passing
checkpoint_mgr.create_checkpoint(
    trigger=CheckpointTrigger.FEATURE_COMPLETE,
    metadata={"feature_index": index}
)

# agent.py - Before risky operations
checkpoint_mgr.create_checkpoint(
    trigger=CheckpointTrigger.BEFORE_RISKY_OP,
    metadata={"operation": "npm install"}
)
```

**Acceptance Criteria:**
- [x] Checkpoint created after every successful `feature_mark`
- [x] Can rollback to any checkpoint and resume work
- [x] Checkpoint includes all state needed for recovery

---

### 1.3 Step Validation

**Modified File:** `feature_tools.py`

**Purpose:** Require verification artifacts before marking features complete

**Implementation Tasks:**

- [x] Add verification directory check in `feature_mark()`
- [x] Require screenshot evidence before marking passing
- [x] Add validation schema for verification artifacts
- [x] Create helper tool `feature_verify` for pre-mark checks (via `skip_verification` parameter)

**Code Changes:**
```python
# feature_tools.py - Replace feature_mark

@tool("feature_mark", ...)
async def feature_mark(args: dict[str, Any]) -> dict[str, Any]:
    index = args["index"]
    features = _load_features()

    # Validate feature exists
    if index < 0 or index >= len(features):
        return error_response(f"Feature #{index} not found")

    # VALIDATION: Require verification evidence
    verification_dir = _project_dir / "verification"
    screenshots = list(verification_dir.glob(f"feature_{index}_*.png"))

    if not screenshots:
        return {
            "content": [{
                "type": "text",
                "text": (
                    f"VALIDATION FAILED: Cannot mark feature #{index} as passing.\n\n"
                    f"Required: Take verification screenshot first.\n"
                    f"Expected: verification/feature_{index}_<description>.png\n\n"
                    f"Use puppeteer_screenshot to capture evidence, then retry."
                )
            }],
            "is_error": True
        }

    # Validation passed - mark as passing
    features[index]["passes"] = True
    features[index]["verified_at"] = datetime.now(timezone.utc).isoformat()
    features[index]["verification_artifacts"] = [str(p) for p in screenshots]
    _save_features(features)

    # Create checkpoint
    # ... checkpoint code ...

    return success_response(f"Feature #{index} marked as PASSING with {len(screenshots)} verification artifacts")
```

**Acceptance Criteria:**
- [x] `feature_mark` fails without screenshot evidence (unless `skip_verification=true`)
- [x] Verification artifacts tracked in feature metadata (`verified_at`, `verification_artifacts`)
- [x] Clear error message guides agent to correct behavior

---

### 1.4 Artifact Store

**New File:** `artifact_store.py`

**Purpose:** Persistent storage for all session artifacts

**Schema:**
```python
@dataclass
class Artifact:
    artifact_id: str
    session_id: int
    timestamp: datetime
    artifact_type: str      # "screenshot", "file_write", "git_commit", "test_result"
    path: str               # Relative path in artifact store
    metadata: dict
    checksum: str
```

**Implementation Tasks:**

- [x] Create `artifact_store.py` with `ArtifactStore` class
- [x] Implement `store()` method to persist artifacts
- [x] Implement `retrieve()` and `list()` methods
- [x] Add artifact linking (parent/child relationships)
- [x] Integrate with verification workflow

**Directory Structure:**
```
.artifacts/
├── index.json              # Artifact manifest
├── session_1/
│   ├── screenshots/
│   │   └── feature_0_login.png
│   ├── commits/
│   │   └── abc123.json     # Commit metadata
│   └── test_results/
│       └── feature_0.json
└── session_2/
    └── ...
```

**Acceptance Criteria:**
- [x] All verification screenshots stored in artifact store
- [x] Artifacts indexed and searchable
- [x] Artifacts survive session restarts

---

## Phase 2: Human-in-the-Loop ✅ COMPLETE

**Goal:** Enable strategic human intervention without destroying session state.

**Priority:** CRITICAL - Required for safe autonomous operation

**Status:** ✅ **ALL TASKS COMPLETE** (2025-12-18)

### 2.1 Human Injection Points

**New File:** `human_interface.py`

**Purpose:** Create explicit points where humans can inject input

**Schema:**
```python
@dataclass
class InjectionPoint:
    point_id: str
    timestamp: datetime
    point_type: InjectionType
    context: dict           # What agent was doing
    options: list[str]      # Agent's suggested options
    recommendation: str     # Agent's preferred choice

    # Response
    response: Optional[str]
    responded_at: Optional[datetime]
    responded_by: str       # "human" or "timeout_default"

class InjectionType(Enum):
    DECISION = "decision"           # Choose between options
    APPROVAL = "approval"           # Yes/no for risky action
    GUIDANCE = "guidance"           # Free-form input needed
    REVIEW = "review"               # Human should review output
    REDIRECT = "redirect"           # Change goals/direction
```

**Implementation Tasks:**

- [x] Create `human_interface.py` with `HumanInterface` class
- [x] Implement `request_input()` with file-based communication
- [x] Implement `check_for_response()` polling mechanism
- [x] Add timeout handling with configurable defaults
- [x] Create CLI tool for human to respond to injection points (`respond.py`)

**Integration Points:**
```python
# agent.py - At decision points
human = HumanInterface(project_dir)

# When confidence is low
if decision.confidence < 0.5:
    response = await human.request_input(
        point_type=InjectionType.DECISION,
        context={"decision": decision.choice, "alternatives": decision.alternatives},
        options=decision.alternatives,
        recommendation=decision.choice,
        timeout_seconds=300
    )
    if response:
        decision.choice = response
```

**Human Response CLI:**
```bash
# New tool for humans to respond
python respond.py --point-id INJ-123 --response "Use approach B"
python respond.py --list  # Show pending injection points
```

**Acceptance Criteria:**
- [x] Agent can create injection points and wait for response
- [x] Human can respond via CLI tool (`respond.py`)
- [x] Timeout defaults to agent's recommendation
- [x] Injection points logged for learning (in `.human/history.jsonl`)

---

### 2.2 Pause/Resume Capability

**Modified Files:** `agent.py`, `checkpoint.py`

**Purpose:** Allow session to pause and resume without losing state

**Implementation Tasks:**

- [x] Add `pause_session()` method to save full state (`SessionPauseManager`)
- [x] Add `resume_session()` method to restore and continue
- [x] Create pause checkpoint with conversation context (`PausedSession` dataclass)
- [x] Handle graceful shutdown signals (SIGINT, SIGTERM)

**State to Preserve:**
```python
@dataclass
class PausedSession:
    session_id: int
    paused_at: datetime

    # Work state
    current_feature: Optional[int]
    pending_decisions: list[dict]

    # Checkpoint reference
    last_checkpoint_id: str

    # Resume instructions
    resume_prompt: str      # What to tell agent when resuming

    # Human notes
    pause_reason: str
    human_notes: Optional[str]
```

**Code Changes:**
```python
# agent.py - Add pause handling

async def run_autonomous_agent(...):
    # Check for paused session
    paused = PausedSession.load(project_dir)
    if paused:
        print_info(f"Resuming paused session {paused.session_id}")
        iteration = paused.session_id
        prompt = paused.resume_prompt

    # ... main loop ...

    # Handle pause request
    if should_pause:
        paused = PausedSession(
            session_id=iteration,
            current_feature=current_feature_index,
            last_checkpoint_id=checkpoint_mgr.latest_id,
            resume_prompt=generate_resume_prompt(context)
        )
        paused.save(project_dir)
        print_info("Session paused. Run again to resume.")
        return
```

**Acceptance Criteria:**
- [x] Ctrl+C creates pause checkpoint instead of losing state
- [x] Session resumes from pause point with context
- [x] Human can add notes before resuming (`pause_manager.update_pause_notes()`)

---

### 2.3 Escalation Rules Engine

**New File:** `escalation.py`

**Purpose:** Explicit rules for when to escalate to human

**Schema:**
```python
@dataclass
class EscalationRule:
    rule_id: str
    name: str
    condition: Callable[[dict], bool]  # Function that evaluates context
    severity: int           # 1-5
    injection_type: InjectionType
    message_template: str
    suggested_actions: list[str]
    auto_pause: bool        # Should agent pause automatically?

@dataclass
class EscalationResult:
    rule_triggered: EscalationRule
    context: dict
    recommended_action: str
```

**Default Rules:**
```python
DEFAULT_RULES = [
    EscalationRule(
        rule_id="low_confidence",
        name="Low Confidence Decision",
        condition=lambda ctx: ctx.get("confidence", 1.0) < 0.5,
        severity=3,
        injection_type=InjectionType.DECISION,
        message_template="Agent confidence is {confidence:.0%} for: {decision}",
        suggested_actions=["Approve agent choice", "Select alternative", "Provide guidance"],
        auto_pause=False
    ),
    EscalationRule(
        rule_id="feature_regression",
        name="Feature Regression Detected",
        condition=lambda ctx: ctx.get("previously_passing") and not ctx.get("currently_passing"),
        severity=4,
        injection_type=InjectionType.REVIEW,
        message_template="Feature #{feature_id} regressed from passing to failing",
        suggested_actions=["Investigate", "Rollback", "Accept regression"],
        auto_pause=True
    ),
    EscalationRule(
        rule_id="multiple_failures",
        name="Multiple Consecutive Failures",
        condition=lambda ctx: ctx.get("consecutive_failures", 0) >= 3,
        severity=4,
        injection_type=InjectionType.GUIDANCE,
        message_template="Agent has failed {consecutive_failures} times on feature #{feature_id}",
        suggested_actions=["Skip feature", "Provide hints", "Take over manually"],
        auto_pause=True
    ),
    EscalationRule(
        rule_id="irreversible_action",
        name="Irreversible Action Requested",
        condition=lambda ctx: ctx.get("is_irreversible", False),
        severity=5,
        injection_type=InjectionType.APPROVAL,
        message_template="Agent wants to perform irreversible action: {action}",
        suggested_actions=["Approve", "Deny", "Request checkpoint first"],
        auto_pause=True
    ),
]
```

**Implementation Tasks:**

- [x] Create `escalation.py` with `EscalationEngine` class
- [x] Implement `evaluate()` to check all rules against context
- [x] Implement `add_rule()` for custom rules
- [x] Integrate with human injection system
- [x] Add escalation logging for learning (in `.escalation/escalations.jsonl`)

**Acceptance Criteria:**
- [x] Rules evaluated at each decision point (in `agent.py`)
- [x] Matching rules trigger appropriate injection type
- [x] High-severity rules can auto-pause
- [x] Escalations logged for pattern analysis

---

### 2.4 Decision Logging

**New File:** `decision.py`

**Purpose:** Structured logging of all agent decisions with rationale

**Schema:**
```python
@dataclass
class Decision:
    decision_id: str        # "D-{session}-{seq}"
    timestamp: datetime
    session_id: int

    # The decision
    decision_type: DecisionType
    context: str            # What prompted this decision
    choice: str             # What was decided
    alternatives: list[str] # What else was considered

    # Rationale
    rationale: str          # Why this choice
    confidence: float       # 0.0-1.0
    inputs_consulted: list[str]  # Files, features, errors reviewed

    # Outcome (filled in later)
    outcome: Optional[str]
    outcome_success: Optional[bool]

    # Traceability
    related_features: list[int]
    git_commit: Optional[str]
    checkpoint_id: Optional[str]

class DecisionType(Enum):
    FEATURE_SELECTION = "feature_selection"
    IMPLEMENTATION_APPROACH = "implementation_approach"
    BUG_FIX_STRATEGY = "bug_fix_strategy"
    SKIP_FEATURE = "skip_feature"
    TOOL_CHOICE = "tool_choice"
    ERROR_HANDLING = "error_handling"
```

**Implementation Tasks:**

- [x] Create `decision.py` with `DecisionLogger` class
- [x] Implement `log_decision()` with immediate persistence
- [x] Implement `update_outcome()` to record results
- [x] Add decision context to prompts (guide agent to explain choices)
- [x] Create `get_decisions_for_feature()` query method

**Prompt Updates:**
```markdown
<!-- Add to coding_prompt.md -->

### Decision Documentation

When making significant decisions, document your reasoning:

1. **Feature Selection:** Why this feature next?
2. **Implementation Approach:** What alternatives did you consider?
3. **Confidence Level:** How confident are you (0-100%)?

Use the `decision_log` tool to record decisions:
```
decision_log with:
  decision_type: "implementation_approach"
  context: "Implementing user authentication"
  choice: "Use JWT tokens with refresh"
  alternatives: ["Session cookies", "OAuth only", "Basic auth"]
  rationale: "JWT allows stateless scaling, refresh tokens improve security"
  confidence: 0.8
  related_features: [15, 16, 17]
```
```

**Acceptance Criteria:**
- [x] Major decisions logged with rationale (in `.decisions/decisions.jsonl`)
- [x] Confidence captured for escalation rules
- [x] Outcomes updated after implementation (`update_outcome()`)
- [x] Can trace any feature to its decision history (`get_decisions_for_feature()`)

---

## Phase 3: Memory Architecture ✅ COMPLETE

**Goal:** Implement tiered memory for efficient context management.

**Priority:** IMPORTANT - Enables smarter agent behavior

**Status:** ✅ **ALL TASKS COMPLETE** (2025-12-18)

### 3.1 Tiered Memory System

**New Directory:** `memory/`

**Purpose:** Separate hot/warm/cold memory tiers

**Structure:**
```
memory/
├── hot/                    # Current session (cleared on session end)
│   ├── working_context.json
│   ├── active_errors.json
│   └── pending_decisions.json
├── warm/                   # Recent sessions (last 5)
│   ├── session_summaries/
│   └── unresolved_issues.json
└── cold/                   # Historical (compressed)
    ├── archive/
    └── proven_solutions.json
```

**Implementation Tasks:**

- [x] Create `memory/` module with `MemoryManager` class
- [x] Implement `HotMemory` for current session working state
- [x] Implement `WarmMemory` for recent session context
- [x] Implement `ColdMemory` for archived historical data
- [x] Add automatic promotion/demotion logic
- [x] Integrate with agent.py session lifecycle

**Acceptance Criteria:**
- [x] Hot memory cleared at session end
- [x] Warm memory retains last 5 session summaries
- [x] Cold memory compressed and queryable
- [x] Memory tiers integrated with agent

---

### 3.2 Salience Scoring

**Modified File:** `feature_list.py`

**Purpose:** Score features by importance, not just position

**Schema Updates:**
```python
@dataclass
class Feature:
    index: int
    category: str
    description: str
    steps: list[str]
    passes: bool

    # NEW: Salience fields
    priority: int           # 1=critical, 2=high, 3=medium, 4=low
    salience_score: float   # 0.0-1.0, computed dynamically
    last_worked: Optional[datetime]
    failure_count: int
    blocked_by: list[int]   # Features this depends on
    blocks: list[int]       # Features that depend on this
```

**Salience Calculation:**
```python
def calculate_salience(feature: Feature, context: dict) -> float:
    """Calculate dynamic salience score."""
    score = 0.0

    # Base priority
    priority_weights = {1: 0.4, 2: 0.3, 3: 0.2, 4: 0.1}
    score += priority_weights.get(feature.priority, 0.1)

    # Failure penalty (repeated failures = try something else)
    if feature.failure_count > 0:
        score -= 0.1 * min(feature.failure_count, 3)

    # Dependency bonus (if this unblocks others)
    score += 0.05 * len(feature.blocks)

    # Recency decay (haven't worked on it recently = lower salience)
    if feature.last_worked:
        days_ago = (datetime.now() - feature.last_worked).days
        score -= 0.02 * min(days_ago, 5)

    # Context boost (related to recent work)
    if feature.index in context.get("related_features", []):
        score += 0.2

    return max(0.0, min(1.0, score))
```

**Implementation Tasks:**

- [x] Add salience fields to Feature schema
- [x] Implement `calculate_salience()` function
- [x] Add `get_next_by_salience()` method to FeatureList
- [x] Add dependency tracking between features
- [x] Implement `record_attempt()` for failure tracking

**Acceptance Criteria:**
- [x] Features ranked by salience, not just position
- [x] High-failure features deprioritized
- [x] Dependencies respected in ordering
- [x] Agent guided toward highest-impact work

---

### 3.3 Hypothesis Tracking

**New File:** `hypotheses.py`

**Purpose:** Track uncertainties and "may matter later" observations

**Schema:**
```python
@dataclass
class Hypothesis:
    hypothesis_id: str
    created_session: int
    created_at: datetime

    # The hypothesis
    observation: str        # What was observed
    hypothesis: str         # What might be causing it
    confidence: float       # 0.0-1.0

    # Evidence
    evidence_for: list[str]
    evidence_against: list[str]

    # Status
    status: HypothesisStatus  # open, confirmed, rejected, irrelevant
    resolved_session: Optional[int]
    resolution: Optional[str]

    # Relationships
    related_features: list[int]
    related_errors: list[str]

class HypothesisStatus(Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    IRRELEVANT = "irrelevant"
```

**Implementation Tasks:**

- [x] Create `hypotheses.py` with `HypothesisTracker` class
- [x] Implement `add_hypothesis()`, `add_evidence()`, `resolve()` methods
- [x] Add `find_matching()` for context-aware hypothesis retrieval
- [x] Implement `get_session_review_list()` for session start review
- [x] Auto-flag when hypothesis context reappears via `matches_context()`

**Acceptance Criteria:**
- [x] Agent can record observations that "may matter later"
- [x] Hypotheses retrievable by matching context
- [x] Confirmed hypotheses tracked with resolution
- [x] Rejected hypotheses archived with reason

---

## Phase 4: Observability ✅ COMPLETE

**Goal:** Full visibility into agent behavior for debugging and improvement.

**Priority:** IMPORTANT - Required for production operations

**Status:** ✅ **ALL TASKS COMPLETE** (2025-12-19)

### 4.1 Metrics System

**New File:** `metrics.py`

**Purpose:** Track quantitative measures across runs

**Metrics to Track:**
```python
@dataclass
class RunMetrics:
    run_id: str
    started_at: datetime
    ended_at: Optional[datetime]

    # Session metrics
    sessions_total: int
    sessions_successful: int
    sessions_failed: int

    # Feature metrics
    features_attempted: int
    features_completed: int
    features_regressed: int
    features_skipped: int

    # Time metrics
    total_duration_seconds: float
    avg_session_duration_seconds: float

    # Cost metrics (if available)
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float

    # Quality metrics
    verification_screenshots_taken: int
    decisions_logged: int
    escalations_triggered: int
    human_interventions: int
```

**Implementation Tasks:**

- [x] Create `metrics.py` with `MetricsCollector` class
- [x] Compute metrics from event log (ComprehensiveMetrics, ToolMetrics, FeatureMetrics)
- [x] Add metrics dashboard command (`metrics_cli.py dashboard`)
- [x] Export metrics to JSON/CSV for analysis
- [x] Add metrics to session end summary (integrated with agent.py)

**Acceptance Criteria:**
- [x] Metrics computed from event log (single source of truth)
- [x] Dashboard shows key metrics at a glance
- [x] Historical metrics comparable across runs

---

### 4.2 Run Reconstruction

**New File:** `debug.py`

**Purpose:** Replay any run step-by-step for debugging

**Implementation Tasks:**

- [x] Implement `reconstruct_session()` via `debug.py reconstruct`
- [x] Add `replay_to_point()` for time-travel debugging via `debug.py replay`
- [x] Create visualization of session flow via `debug.py timeline`
- [x] Add filtering (by tool, by feature, by error) via `debug.py events`

**CLI Tool:**
```bash
# Reconstruct a run
python debug.py reconstruct --session 5

# Show what agent knew at a specific time
python debug.py context --timestamp "2025-12-18T10:30:00"

# Filter to specific tool calls
python debug.py events --tool puppeteer_screenshot --session 5

# Show decision chain for a feature
python debug.py decisions --feature 42
```

**Acceptance Criteria:**
- [x] Can reconstruct any session from event log
- [x] Can answer "what did it know at time X?" via `debug.py context`
- [x] Can trace decision chain for any feature via `debug.py decisions`

---

### 4.3 Failure Analysis

**New File:** `failure_analysis.py`

**Purpose:** Automated analysis of why runs fail

**Implementation Tasks:**

- [x] Create `FailureAnalyzer` class
- [x] Implement pattern detection (cyclic errors, blocked commands, tool chains)
- [x] Generate failure reports with root cause analysis
- [x] Suggest fixes based on known patterns and error analysis

**Failure Report Schema:**
```python
@dataclass
class FailureReport:
    session_id: int
    failure_type: str       # "cyclic_error", "blocked", "timeout", "crash"

    # Context
    last_successful_action: str
    failing_action: str
    error_messages: list[str]

    # Analysis
    likely_cause: str
    confidence: float
    similar_past_failures: list[str]

    # Recommendations
    suggested_fixes: list[str]
    relevant_kb_entries: list[str]  # From troubleshooting tools
```

**Acceptance Criteria:**
- [x] Automatic failure report on session end with errors (integrated with agent.py)
- [x] Pattern matching against past failures via `find_similar_failures()`
- [x] Actionable fix suggestions based on failure type and patterns

---

## Phase 5: Advanced Autonomy ✅ COMPLETE

**Goal:** Increase agent independence where safe to do so.

**Priority:** FUTURE - Only after Phases 1-4 complete

**Status:** ✅ **ALL TASKS COMPLETE** (2025-12-19)

### 5.1 Explicit Autonomy Levels

**New File:** `autonomy.py`

**Purpose:** Define and enforce graduated autonomy levels

**Schema:**
```python
class AutonomyLevel(Enum):
    OBSERVE = 1         # Read-only, no actions
    PLAN = 2            # Can plan, requires approval for actions
    EXECUTE_SAFE = 3    # Can execute pre-approved safe actions
    EXECUTE_REVIEW = 4  # Can execute all, human reviews after
    FULL_AUTO = 5       # Full autonomy within security bounds

@dataclass
class AutonomyConfig:
    level: AutonomyLevel

    # Per-action overrides
    action_levels: dict[str, AutonomyLevel]  # e.g., {"feature_mark": EXECUTE_REVIEW}

    # Dynamic adjustment
    confidence_threshold: float     # Below this, reduce level
    error_demotion_count: int       # After N errors, reduce level
    success_promotion_count: int    # After N successes, increase level
```

**Implementation Tasks:**

- [x] Create `autonomy.py` with `AutonomyManager` class
- [x] Implement level checking for each action
- [x] Add dynamic level adjustment based on performance
- [x] Integrate with agent.py
- [x] Add autonomy level to session config

**Acceptance Criteria:**
- [x] Autonomy level explicit in configuration
- [x] Actions gated by autonomy level
- [x] Level adjusts based on agent performance

---

### 5.2 Risk Classification

**New File:** `risk.py`

**Purpose:** Classify actions by risk before execution

**Schema:**
```python
@dataclass
class RiskAssessment:
    action: str
    tool: str
    input_summary: str

    # Risk dimensions
    risk_level: int         # 1-5
    is_reversible: bool
    affects_source_of_truth: bool
    has_external_side_effects: bool

    # Cost
    estimated_time_seconds: Optional[int]
    estimated_token_cost: Optional[int]

    # Gating
    requires_approval: bool
    requires_checkpoint: bool
    suggested_mitigation: Optional[str]
```

**Risk Rules:**
```python
RISK_RULES = {
    "Write": lambda input: RiskAssessment(
        risk_level=4 if "feature_list.json" in input.get("file_path", "") else 2,
        is_reversible=True,  # Git can recover
        affects_source_of_truth="feature_list.json" in input.get("file_path", ""),
        requires_checkpoint="feature_list.json" in input.get("file_path", ""),
        suggested_mitigation="Use feature_mark tool instead" if "feature_list.json" in input.get("file_path", "") else None
    ),
    "Bash": lambda input: assess_bash_risk(input.get("command", "")),
    "feature_mark": lambda input: RiskAssessment(
        risk_level=3,
        is_reversible=True,
        affects_source_of_truth=True,
        requires_checkpoint=True
    ),
}
```

**Implementation Tasks:**

- [x] Create `risk.py` with `RiskClassifier` class
- [x] Implement risk rules for each tool
- [x] Integrate with agent.py tool calls
- [x] Add risk assessment logging
- [x] Gate high-risk actions appropriately

**Acceptance Criteria:**
- [x] All actions classified before execution
- [x] High-risk actions flagged with warnings
- [x] Risk-appropriate autonomy applied

---

### 5.3 Intervention Learning

**New File:** `intervention_learning.py`

**Purpose:** Learn from human interventions to improve future autonomy

**Schema:**
```python
@dataclass
class InterventionPattern:
    pattern_id: str

    # Context signature (for matching)
    context_signature: str      # Hash of relevant context features
    trigger_conditions: dict    # What triggered intervention

    # The intervention
    intervention_type: str
    human_action: str
    human_rationale: Optional[str]

    # Outcome
    outcome_success: bool

    # Learning
    times_matched: int
    auto_apply: bool            # Should we auto-apply this intervention?
    confidence: float
```

**Implementation Tasks:**

- [x] Create `intervention_learning.py` with `InterventionLearner` class
- [x] Implement context signature computation
- [x] Implement pattern matching for similar contexts
- [x] Add auto-apply for high-confidence patterns
- [x] Track pattern success rates

**Acceptance Criteria:**
- [x] Interventions recorded with context
- [x] Similar contexts flagged automatically
- [x] Proven interventions can be auto-applied
- [x] Learning improves over time

---

## Implementation Schedule

### Week 1-2: Phase 1 (Reliability)
- Day 1-2: Event logging system
- Day 3-4: Checkpoint system
- Day 5-6: Step validation
- Day 7-8: Artifact store
- Day 9-10: Integration testing

### Week 3-5: Phase 2 (Human-in-the-Loop)
- Day 11-13: Human injection points
- Day 14-16: Pause/resume capability
- Day 17-19: Escalation rules engine
- Day 20-22: Decision logging
- Day 23-25: Integration testing

### Week 6-7: Phase 3 (Memory)
- Day 26-28: Tiered memory system
- Day 29-31: Salience scoring
- Day 32-34: Hypothesis tracking
- Day 35: Integration testing

### Week 8: Phase 4 (Observability)
- Day 36-37: Metrics system
- Day 38-39: Run reconstruction
- Day 40: Failure analysis

### Week 9-10: Phase 5 (Autonomy)
- Day 41-43: Autonomy levels
- Day 44-46: Risk classification
- Day 47-49: Intervention learning
- Day 50: Final integration

---

## Success Criteria

### Phase 1 Complete When: ✅ DONE
- [x] Process crash loses < 1 minute of work (checkpoints at feature completion)
- [x] Can rollback to any checkpoint (`checkpoint_cli.py rollback`)
- [x] Features cannot be marked passing without evidence (`feature_mark` requires screenshots)

### Phase 2 Complete When: ✅ DONE
- [x] Human can intervene without restart (via `respond.py` and injection points)
- [x] Escalation rules trigger appropriately (8 default rules in `EscalationEngine`)
- [x] All major decisions are logged (via `DecisionLogger`)

### Phase 3 Complete When: ✅ DONE
- [x] Tiered memory system implemented (hot/warm/cold)
- [x] Agent prioritizes highest-impact features (salience scoring)
- [x] Uncertainties tracked across sessions (hypothesis tracking)

### Phase 4 Complete When: ✅ DONE
- [x] Can reconstruct any run end-to-end (`debug.py reconstruct`, `debug.py timeline`)
- [x] Failure reports identify root cause (`FailureAnalyzer.analyze_session()`)
- [x] Metrics enable trend analysis (`MetricsCollector.get_comprehensive_metrics()`)

### Phase 5 Complete When: ✅ DONE
- [x] Autonomy levels enforce graduated trust
- [x] Risk classification gates dangerous actions
- [x] System learns from interventions

---

## Appendix: New Files Summary

| File | Phase | Purpose | Status |
|------|-------|---------|--------|
| `observability.py` | 1 | Event logging and metrics | ✅ Complete |
| `events_cli.py` | 1 | CLI for viewing events | ✅ Complete |
| `checkpoint.py` | 1 | Semantic checkpoints and rollback | ✅ Complete |
| `checkpoint_cli.py` | 1 | CLI for checkpoint management | ✅ Complete |
| `artifact_store.py` | 1 | Persistent artifact storage | ✅ Complete |
| `tests/test_observability.py` | 1 | Observability tests (33 tests) | ✅ Complete |
| `tests/test_checkpoint.py` | 1 | Checkpoint tests (33 tests) | ✅ Complete |
| `tests/test_artifact_store.py` | 1 | Artifact store tests (33 tests) | ✅ Complete |
| `human_interface.py` | 2 | Human injection points | ✅ Complete |
| `respond.py` | 2 | CLI tool for human responses | ✅ Complete |
| `escalation.py` | 2 | Escalation rules engine | ✅ Complete |
| `decision.py` | 2 | Decision logging | ✅ Complete |
| `tests/test_decision.py` | 2 | Decision logging tests (23 tests) | ✅ Complete |
| `tests/test_escalation.py` | 2 | Escalation engine tests (30 tests) | ✅ Complete |
| `tests/test_human_interface.py` | 2 | Human interface tests (28 tests) | ✅ Complete |
| `tests/test_pause_resume.py` | 2 | Pause/resume tests (27 tests) | ✅ Complete |
| `memory/__init__.py` | 3 | MemoryManager orchestrating tiers | ✅ Complete |
| `memory/hot.py` | 3 | Current session memory (HotMemory) | ✅ Complete |
| `memory/warm.py` | 3 | Recent session memory (WarmMemory) | ✅ Complete |
| `memory/cold.py` | 3 | Archived memory (ColdMemory) | ✅ Complete |
| `hypotheses.py` | 3 | Hypothesis tracking (HypothesisTracker) | ✅ Complete |
| `tests/test_memory.py` | 3 | Memory module tests (47 tests) | ✅ Complete |
| `tests/test_salience.py` | 3 | Salience scoring tests (31 tests) | ✅ Complete |
| `tests/test_hypotheses.py` | 3 | Hypothesis tracking tests (38 tests) | ✅ Complete |
| `metrics.py` | 4 | MetricsCollector with comprehensive metrics | ✅ Complete |
| `metrics_cli.py` | 4 | CLI for metrics dashboard and export | ✅ Complete |
| `debug.py` | 4 | CLI for run reconstruction and debugging | ✅ Complete |
| `failure_analysis.py` | 4 | FailureAnalyzer with pattern detection | ✅ Complete |
| `tests/test_metrics.py` | 4 | Metrics module tests (29 tests) | ✅ Complete |
| `tests/test_failure_analysis.py` | 4 | Failure analysis tests (37 tests) | ✅ Complete |
| `autonomy.py` | 5 | Autonomy levels (AutonomyManager) | ✅ Complete |
| `risk.py` | 5 | Risk classification (RiskClassifier) | ✅ Complete |
| `intervention_learning.py` | 5 | Learning from interventions (InterventionLearner) | ✅ Complete |
| `tests/test_autonomy.py` | 5 | Autonomy module tests (44 tests) | ✅ Complete |
| `tests/test_risk.py` | 5 | Risk module tests (43 tests) | ✅ Complete |
| `tests/test_intervention_learning.py` | 5 | Intervention learning tests (44 tests) | ✅ Complete |

---

## Appendix: Modified Files Summary

| File | Phase | Changes | Status |
|------|-------|---------|--------|
| `agent.py` | 1,2,3,4,5 | Add logging, checkpoints, pause/resume, escalation, decision logging, memory, metrics, failure analysis, autonomy, risk, learning | ✅ Complete |
| `feature_tools.py` | 1,3 | Add validation, salience fields | ✅ Complete |
| `checkpoint.py` | 1,2 | Add pause/resume support (PausedSession, SessionPauseManager) | ✅ Complete |
| `feature_list.py` | 3 | Add salience scoring (calculate_salience, get_next_by_salience) | ✅ Complete |
| `progress_tools.py` | 2 | Add decision context | ✅ Complete |
| `prompts/*.md` | 2,3 | Add decision guidance, hypothesis prompts | ✅ Complete |
