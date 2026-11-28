from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class OrchestratorError(Exception):
    """编排器统一结构化错误，携带确定性错误码与上下文细节。"""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"error_code": self.code, "message": self.message, "details": self.details}


# ---------------------------------------------------------------------------
# 第一层（讨论层）交接契约模型：严格 Schema（禁止未声明扩展字段）
# ---------------------------------------------------------------------------


class ApprovalSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    approved_by: str = ""
    approved_at: str = ""
    note: str = ""


class InterceptorsPassed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked_gdd_ref_integrity: bool
    system_no_how_blacklist_clean: bool
    cross_table_state_event_closed: bool
    feasibility_cold_reader_audit: bool
    # v1.1 / v1.2 向后兼容新增拦截器字段
    gdd_bidirectional_na_closed: Optional[bool] = None
    no_placeholder_words_clean: Optional[bool] = None
    pacing_and_cognitive_load_audit: Optional[bool] = None
    understanding_echo_aligned: Optional[bool] = None


class ManifestFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    role: str
    sha256: str
    item_count: int = 0


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    project_id: str
    spec_version: str
    parent_version: Optional[str] = None
    canonical_sha256: str
    scope_tier: str
    lead_pillars: List[str]
    derived_pillars: List[str]
    approval_signature: ApprovalSignature
    interceptors_passed: InterceptorsPassed
    files: List[ManifestFileEntry]
    diff_summary_ref: Optional[str] = None


class UnderstandingEcho(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    anti_examples: List[str] = Field(default_factory=list)


class SystemInteractionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: List[str] = Field(default_factory=list)
    concurrent_trigger: str = ""
    resolution_rule: str = ""


class GddModule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gdd_id: str
    title: str
    pillar_origin: str
    priority: str = "P0"
    focus_tier: Optional[Literal["ANCHOR", "FLOW", "UTILITY"]] = None
    anchor_heading: str
    summary: str = ""
    entry_trigger: str = ""
    core_rules: str = ""
    win_exit: str = ""
    fail_exit: str = ""
    experience_intent: str = ""
    acceptance_oracle: str = ""


class GddIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    source_document: str
    rubric_coverage_map: Dict[str, str] = Field(default_factory=dict)
    pacing_summary: Dict[str, Any] = Field(default_factory=dict)
    modules: List[GddModule]


class StateDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    value_type: str
    meaning: str


class EventDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    meaning: str


class SystemDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    tree_path: Optional[str] = None
    title: str
    linked_gdd_ref: str
    priority: str = "P0"
    inputs: List[str] = Field(default_factory=list)
    business_rules: List[str] = Field(default_factory=list)
    edge_cases: List[str] = Field(default_factory=list)
    exposed_state_ids: List[StateDef] = Field(default_factory=list)
    emitted_event_ids: List[EventDef] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    size_hint: Optional[Literal["S", "M", "L"]] = None


class SystemRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    discipline: Literal["system"]
    milestone_scope: str
    understanding_echo: Optional[UnderstandingEcho] = None
    explicit_na_refs: List[Any] = Field(default_factory=list)
    global_constraints: Dict[str, Any]
    system_interaction_matrix: List[SystemInteractionRule] = Field(default_factory=list)
    stage_deliverables: List[SystemDeliverable]


class NarrativeDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    tree_path: Optional[str] = None
    title: str
    linked_gdd_ref: str
    priority: str = "P0"
    linked_state_ids: List[str] = Field(default_factory=list)
    trigger_event_ids: List[str] = Field(default_factory=list)
    canon_refs: List[str] = Field(default_factory=list)
    deliverable_spec: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    size_hint: Optional[Literal["S", "M", "L"]] = None


class NarrativeRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    discipline: Literal["narrative"]
    milestone_scope: str
    understanding_echo: Optional[UnderstandingEcho] = None
    explicit_na_refs: List[Any] = Field(default_factory=list)
    global_constraints: Dict[str, Any]
    stage_deliverables: List[NarrativeDeliverable]


class ArtDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    tree_path: Optional[str] = None
    title: str
    linked_gdd_ref: str
    priority: str = "P0"
    linked_state_ids: List[str] = Field(default_factory=list)
    trigger_event_ids: List[str] = Field(default_factory=list)
    reuse_group: Optional[str] = None
    deliverable_spec: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    size_hint: Optional[Literal["S", "M", "L"]] = None


class ArtRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    discipline: Literal["art"]
    milestone_scope: str
    understanding_echo: Optional[UnderstandingEcho] = None
    explicit_na_refs: List[Any] = Field(default_factory=list)
    global_constraints: Dict[str, Any]
    stage_deliverables: List[ArtDeliverable]


class AudioDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    tree_path: Optional[str] = None
    title: str
    linked_gdd_ref: str
    priority: str = "P0"
    linked_state_ids: List[str] = Field(default_factory=list)
    trigger_event_ids: List[str] = Field(default_factory=list)
    deliverable_spec: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    size_hint: Optional[Literal["S", "M", "L"]] = None


class AudioRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    discipline: Literal["audio"]
    milestone_scope: str
    understanding_echo: Optional[UnderstandingEcho] = None
    explicit_na_refs: List[Any] = Field(default_factory=list)
    global_constraints: Dict[str, Any]
    stage_deliverables: List[AudioDeliverable]


class CanonEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canon_id: str
    category: str
    name: str
    immutable_facts: List[str] = Field(default_factory=list)


class CanonRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    entries: List[CanonEntry] = Field(default_factory=list)


class AdrRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    adr_id: str
    created_at: str
    status: str
    trigger: str
    context: str
    decision: str
    rationale: str
    impacted_refs: List[str] = Field(default_factory=list)


class DiffModifiedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    req_id: str
    discipline: str
    reason: str = ""


class DiffChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_ids: List[str] = Field(default_factory=list)
    modified_ids: List[DiffModifiedItem] = Field(default_factory=list)
    deprecated_ids: List[str] = Field(default_factory=list)
    unchanged_ids: List[str] = Field(default_factory=list)


class DiffSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    from_version: str
    to_version: str
    change_request_id: Optional[str] = None
    delta_tier: Literal["TIER_A_LOCAL_TUNING", "TIER_B_CHAPTER_EXTEND", "TIER_C_CORE_PIVOT"]
    global_constraints_changed: bool = False
    changes: DiffChanges


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "change_request/v1"
    request_id: str
    project_id: str
    base_spec_version: str
    trigger_source: Literal["playtest_feedback", "visual_first_frame", "scope_cut", "new_chapter"]
    impacted_req_ids: List[str]
    problem_statement: str
    requested_delta: str


class AuxiliaryFileRecord(BaseModel):
    path: str
    sha256: str
    listed_in_manifest: bool
    kind: str


class HandoffBundle(BaseModel):
    """已加载并解析完成的冻结交接包（物理隔离 ideas_backlog.md）。"""

    source_dir: str
    manifest: Manifest
    master_gdd_markdown: str
    gdd_index: GddIndex
    system_requirements: SystemRequirements
    narrative_requirements: NarrativeRequirements
    art_requirements: ArtRequirements
    audio_requirements: AudioRequirements
    canon_registry: CanonRegistry
    adr_records: List[AdrRecord] = Field(default_factory=list)
    reference_images: List[str] = Field(default_factory=list)
    diff_summary: Optional[DiffSummary] = None
    auxiliary_files: List[AuxiliaryFileRecord] = Field(default_factory=list)
    backlog_audit_sha256: Optional[str] = None
    global_constraints_hashes: Dict[str, str] = Field(default_factory=dict)
    raw_searchable_texts: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 第二层（编排器）运行态、契约、验收与门禁模型
# ---------------------------------------------------------------------------


class ProjectState(str, Enum):
    LOADED = "LOADED"
    AWAITING_TECH_CONFIRM = "AWAITING_TECH_CONFIRM"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    AWAITING_RELEASE = "AWAITING_RELEASE"
    RELEASED = "RELEASED"
    APPLYING_DELTA = "APPLYING_DELTA"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_VERIFY = "WAITING_VERIFY"
    WAITING_DECISION = "WAITING_DECISION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class TaskKind(str, Enum):
    TECH = "TECH"
    SYS = "SYS"
    NAR = "NAR"
    ART = "ART"
    AUD = "AUD"
    INTEG = "INTEG"
    QA_FINAL = "QA_FINAL"


class DecisionKind(str, Enum):
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    REQUIREMENT_DEFECT = "REQUIREMENT_DEFECT"
    SCENARIO_DISPUTE = "SCENARIO_DISPUTE"
    SPOT_CHECK = "SPOT_CHECK"


class TechProfile(BaseModel):
    schema_version: str = "tech_profile/v1"
    platform: str = "web"
    language: str = "typescript"
    render: str = "canvas2d"
    data_format: Literal["yaml", "json"] = "yaml"
    directories: Dict[str, str] = Field(
        default_factory=lambda: {
            "systems": "game/src/systems/",
            "narrative": "game/data/narrative/",
            "art": "game/assets/art/",
            "audio": "game/assets/audio/",
            "modules": "game/src/modules/",
            "generated": "game/src/generated/",
        }
    )
    runtime_harness: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {
            "build": "npm run build",
            "unit_test": "npm test",
            "scenario_replay": "npm run replay -- {scenario_file}",
            "perf_probe": "npm run perf -- --seconds 30",
            "save_load_roundtrip": "npm run saveload-check",
            "render_preview": "npm run preview -- {asset_file} --size 1280x720",
        }
    )
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None


class StateContractItem(BaseModel):
    id: str
    value_type: str
    owner_req: str
    referenced_by: List[str] = Field(default_factory=list)
    meaning: str


class EventContractItem(BaseModel):
    id: str
    owner_req: str
    referenced_by: List[str] = Field(default_factory=list)
    meaning: str = ""


class InputActionDef(BaseModel):
    id: str
    req_id: str
    source_text: str


class StateEventsContract(BaseModel):
    schema_version: str = "state_events/v1"
    source: str = "requirements/system_requirements.yaml"
    source_sha256: str
    states: List[StateContractItem] = Field(default_factory=list)
    events: List[EventContractItem] = Field(default_factory=list)
    inputs: List[InputActionDef] = Field(default_factory=list)
    contract_sha256: str = ""


class AssetSchemasContract(BaseModel):
    schema_version: str = "asset_schemas/v1"
    schemas: Dict[str, Any] = Field(default_factory=dict)
    contract_sha256: str = ""


class ScenarioStep(BaseModel):
    frame: int
    actions: List[Dict[str, str]] = Field(default_factory=list)


class ScenarioExpect(BaseModel):
    final_state: Dict[str, Any] = Field(default_factory=dict)
    events_include: List[str] = Field(default_factory=list)
    events_exclude: List[str] = Field(default_factory=list)


class ScenarioSpec(BaseModel):
    schema_version: str = "scenario/v1"
    scenario_id: str
    req_id: str
    covers: List[str] = Field(default_factory=list)
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    steps: List[ScenarioStep] = Field(default_factory=list)
    expect: ScenarioExpect = Field(default_factory=ScenarioExpect)


class ArtifactFile(BaseModel):
    path: str
    sha256: str
    source_route: Optional[str] = None


class ArtifactManifest(BaseModel):
    task_id: str
    attempt: int
    files: List[ArtifactFile] = Field(default_factory=list)
    scenario_dispute: Optional[Dict[str, str]] = None
    summary: str = ""
    api_calls: int = 0
    cost: float = 0.0


class VerifyFinding(BaseModel):
    ac_id: str
    result: Literal["PASS", "FAIL"]
    defect_type: Optional[Literal["IMPLEMENTATION", "REQUIREMENT_DEFECT"]] = None
    evidence: str = ""
    requirement_quote: Optional[str] = None
    fix_hint: str = ""


class Level1Report(BaseModel):
    passed: bool
    failed_checks: List[str] = Field(default_factory=list)
    manual_required: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class Level2Report(BaseModel):
    decision: Literal["PASS", "FAIL", "SKIPPED"]
    reviewer_model: str = "mock-qa"
    findings: List[VerifyFinding] = Field(default_factory=list)
    notes: str = ""


class VerifyReport(BaseModel):
    schema_version: str = "verify_report/v1"
    task_id: str
    attempt: int
    level1: Level1Report
    level2: Optional[Level2Report] = None
    created_at: str = ""


class GateDecision(BaseModel):
    gate_id: Literal["G1", "G2", "G3", "G4"]
    target: str
    decision_kind: Optional[str] = None
    option: str
    note: str = ""
    decided_by: str = "human_director"
    decided_at: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


class SkipInfo(BaseModel):
    waiver: Optional[bool] = None
    reason: str = ""


class TaskAttemptRecord(BaseModel):
    attempt: int
    epoch: int = 1
    result: str
    report_path: Optional[str] = None
    context_path: Optional[str] = None
    patch_path: Optional[str] = None
    runtime_sec: float = 0.0
    summary: str = ""
    timestamp: str = ""


class TaskRecord(BaseModel):
    task_id: str
    title: str
    kind: TaskKind
    dev_stage: str                      # DEV_STAGE_1..DEV_STAGE_4
    role: str
    req_id: Optional[str] = None
    gdd_ref: Optional[str] = None
    priority: str = "P0"
    reuse_group: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    state: TaskStatus = TaskStatus.PENDING
    decision_kind: Optional[DecisionKind] = None
    skip: SkipInfo = Field(default_factory=SkipInfo)
    attempts_failed: int = 0
    attempt_epoch: int = 1
    next_attempt_seq: int = 1
    estimate_hours: float = 4.0
    delay_hours: float = 0.0
    actual_runtime_sec: float = 0.0
    es: float = 0.0
    ef: float = 0.0
    ls: float = 0.0
    lf: float = 0.0
    slack: float = 0.0
    resource_wait_hours: float = 0.0
    is_critical: bool = False
    on_main_critical_path: bool = False
    oversized: bool = False
    artifacts: List[ArtifactFile] = Field(default_factory=list)
    produced_in_version: Optional[str] = None
    last_commit: Optional[str] = None
    writable_paths: List[str] = Field(default_factory=list)
    scenario_paths: List[str] = Field(default_factory=list)
    history: List[TaskAttemptRecord] = Field(default_factory=list)
    guidance_notes: List[str] = Field(default_factory=list)
    override_worker_mode: Optional[str] = None
    delta_tag: Optional[Literal["REUSED", "DIRTY_RERUN", "NEW", "RETAINED"]] = None


class TombstoneRecord(BaseModel):
    req_id: str
    deprecated_in: str
    archived_dir: Optional[str] = None
    recorded_at: str = ""


class BudgetState(BaseModel):
    cost_used: float = 0.0
    cost_cap: float = 50.0
    calls_used: int = 0
    calls_cap: int = 2000
    per_attempt_call_cap: int = 40


class CpmSummary(BaseModel):
    cp_length_hours: float = 0.0
    total_all_hours: float = 0.0
    baseline_cp_length_hours: float = 0.0
    main_path: List[str] = Field(default_factory=list)
    progress_cp: float = 0.0
    progress_all: float = 0.0
    waived_tasks: List[str] = Field(default_factory=list)


class DeltaReport(BaseModel):
    from_version: str
    to_version: str
    delta_tier: str
    reused_ids: List[str] = Field(default_factory=list)
    dirty_ids: List[str] = Field(default_factory=list)
    added_ids: List[str] = Field(default_factory=list)
    deprecated_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    saved_estimate_hours: float = 0.0
    applied_at: str = ""


class TaskGraph(BaseModel):
    project_id: str
    spec_version: str
    tasks: List[TaskRecord]
    edges: List[List[str]] = Field(default_factory=list)


class GitCommitEntry(BaseModel):
    commit_hash: str
    branch: str = "main"
    message: str
    task_id: Optional[str] = None
    spec_version: Optional[str] = None
    tag: Optional[str] = None
    timestamp: str = ""


class SessionState(BaseModel):
    schema_version: str = "orchestrator_session/v1"
    project_id: str
    spec_version: str
    parent_version: Optional[str] = None
    canonical_sha256: str
    scope_tier: str
    lead_pillars: List[str] = Field(default_factory=list)
    derived_pillars: List[str] = Field(default_factory=list)
    project_state: ProjectState = ProjectState.LOADED
    handoff_dir: str
    tech_profile: TechProfile = Field(default_factory=TechProfile)
    tech_profile_ref: str = "contracts/tech_profile.yaml"
    state_events: Optional[StateEventsContract] = None
    asset_schemas: Optional[AssetSchemasContract] = None
    contract_sha256: Dict[str, str] = Field(default_factory=dict)
    tasks: Dict[str, TaskRecord] = Field(default_factory=dict)
    edges: List[List[str]] = Field(default_factory=list)
    tombstones: List[TombstoneRecord] = Field(default_factory=list)
    budget: BudgetState = Field(default_factory=BudgetState)
    cpm: CpmSummary = Field(default_factory=CpmSummary)
    warnings: List[str] = Field(default_factory=list)
    gate_decisions: List[GateDecision] = Field(default_factory=list)
    change_requests: List[ChangeRequest] = Field(default_factory=list)
    delta_history: List[DeltaReport] = Field(default_factory=list)
    manual_required_items: List[str] = Field(default_factory=list)
    git_commits: List[GitCommitEntry] = Field(default_factory=list)
    git_sync_pending: bool = False
    global_constraints_hashes: Dict[str, str] = Field(default_factory=dict)
    canon_hashes: Dict[str, str] = Field(default_factory=dict)
    adr_hashes: Dict[str, str] = Field(default_factory=dict)
    last_event_seq: int = 0
    demo_faults: Dict[str, List[str]] = Field(default_factory=dict)
