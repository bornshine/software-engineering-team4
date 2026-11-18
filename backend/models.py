from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CollaborationMode(str, Enum):
    DISPERSED = "DISPERSED"         # 散开并行
    JOINT = "JOINT"                 # 联合合流
    CONCENTRATED = "CONCENTRATED"   # 集中收口


class TaskStatus(str, Enum):
    PENDING = "PENDING"                   # 未就绪
    READY = "READY"                       # 就绪待调度
    RUNNING = "RUNNING"                   # 执行中
    WAITING_DECISION = "WAITING_DECISION" # 待主策拍案
    WAITING_VERIFY = "WAITING_VERIFY"     # 待独立QA验收
    SUCCEEDED = "SUCCEEDED"               # 已完成
    FAILED = "FAILED"                     # 失败
    BLOCKED = "BLOCKED"                   # 阻塞
    SKIPPED = "SKIPPED"                   # 已跳过


class BotCard(BaseModel):
    bot_id: str                           # 如 "art_bot_01"
    role_code: str                        # ROLE_PLANNER / ROLE_ART_2D / ROLE_DEV_2D / ROLE_QA_INTEG
    display_name: str
    model_tier: str                       # "flagship" (仅主策) / "standard" (其余Bot)
    capabilities: List[str]               # 能力标签集合(仅限2D/2.5D白名单)
    current_load_hours: float = 0.0
    model_name: str = "tier2-fast"
    has_long_term_memory: bool = False


class GameDevTask(BaseModel):
    task_id: str                          # 如 "TASK-S2-01"
    title: str
    stage_id: str                         # STAGE_1 ~ STAGE_5
    collaboration_mode: CollaborationMode
    task_type: str                        # design / art_2d / dev_2d / qa_integ
    required_tags: List[str]
    assigned_bot_id: str
    collaborator_bot_ids: List[str] = Field(default_factory=list)
    assignment_reason: str                # 三维可解释分配说明
    depends_on: List[str] = Field(default_factory=list)
    duration_hours: float
    delay_hours: float = 0.0              # 运行期延期工时
    es: float = 0.0                       # 最早开始(h)
    ef: float = 0.0                       # 最早结束(h)
    ls: float = 0.0                       # 最晚开始(h)
    lf: float = 0.0                       # 最晚结束(h)
    slack: float = 0.0                    # 浮动时间(h), slack==0 即为关键路径
    is_critical: bool = False
    acceptance_criteria: List[str]
    verify_mode: str = "HYBRID"           # AUTO / HUMAN / HYBRID
    source_clause_ref: str                # 计划书原文追溯锚点
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    git_commit_hash: Optional[str] = None
    deliverable_summary: Optional[str] = None
    # 运行时辅助字段（向后兼容契约）
    progress_hours: float = 0.0
    ambiguity_note: Optional[str] = None
    dirty_flag: bool = False
    verdict_id: Optional[str] = None
    execution_logs: List[str] = Field(default_factory=list)


class PitfallMemoryItem(BaseModel):
    memory_id: str
    context_scenario: str                 # 情境
    past_failure: str                     # 踩过的坑
    lesson_learned: str                   # 可解释的教训(禁绝工作流僵化禁令)
    source_event_id: str                  # 溯源事件ID
    active: bool = True


class PlannerVerdictRecord(BaseModel):
    verdict_id: str
    timestamp: str
    planner_model_tier: str = "flagship (Tier-1)"
    trigger_reason: str
    target_task_ids: List[str]
    decision_conclusion: str
    rationale: str
    memory_ref_id: Optional[str] = None


class StageDefinition(BaseModel):
    stage_id: str
    order: int
    name: str
    dominant_mode: CollaborationMode
    exit_criteria: str
    description: str


class SpecClause(BaseModel):
    clause_id: str
    section: str
    text: str


class SpecDocument(BaseModel):
    spec_id: str
    title: str
    genre: str
    dimension_mode: str = "2D"            # "2D" or "2.5D"
    spec_version: str = "v1.0"
    content_sha256: str = ""
    git_commit_hash: Optional[str] = None
    change_log: List[str] = Field(default_factory=list)
    raw_markdown: str
    clauses: List[SpecClause] = Field(default_factory=list)


class EnvSignalRecord(BaseModel):
    signal_id: str
    timestamp: str
    source_type: str                      # PLAYER_FEEDBACK / TEAM_DISCUSSION
    raw_text: str
    category: str                         # FEATURE_CHANGE / BUG / NOISE
    urgency: int                          # 1~10
    impact: int                           # 1~10
    total_score: int
    filtered_as_noise: bool
    requires_planner_verdict: bool
    extracted_summary: str
    status: str = "PENDING"               # PENDING / IGNORED_NOISE / APPROVED / REJECTED


class ChangeRequestRecord(BaseModel):
    cr_id: str
    signal_id: str
    timestamp: str
    spec_version_before: str
    spec_version_after: str
    dirty_task_ids: List[str]
    preserved_succeeded_ids: List[str]
    added_task_ids: List[str]
    summary: str
    verdict_id: str
    git_commit_hash: Optional[str] = None


class GitCommitRecord(BaseModel):
    commit_hash: str
    parent_hashes: List[str] = Field(default_factory=list)
    branch: str
    message: str
    timestamp: str
    event_type: str                       # SPEC_INIT / VERDICT / TASK_DONE / HOT_REPLAN / ROLLBACK
    related_ids: List[str] = Field(default_factory=list)


class StageSnapshot(BaseModel):
    snapshot_id: str
    stage_id: str
    label: str
    timestamp: str
    sim_clock_hours: float
    tasks_data: List[Dict]
    bot_loads: Dict[str, float]
