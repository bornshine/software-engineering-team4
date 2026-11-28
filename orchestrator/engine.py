from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import yaml

from .budget_guard import BudgetGuard
from .change_request import build_and_export_change_request
from .context_packer import pack_task_context
from .contract_validator import validate_handoff_bundle
from .cpm import KIND_ORDER, compute_cpm, dispatch_priority_key
from .dag_builder import build_task_graph
from .delta_reconciler import reconcile_delta_upgrade
from .estimator import add_rework_delay, apply_estimates, clamp_agent_estimate
from .handoff_loader import compute_file_sha256, load_handoff_bundle, stable_json_sha256
from .project_fsm import transition_project_state
from .schemas import (
    ArtifactFile,
    ArtifactManifest,
    BudgetState,
    ChangeRequest,
    DecisionKind,
    DeltaReport,
    GateDecision,
    HandoffBundle,
    OrchestratorError,
    ProjectState,
    SessionState,
    TaskAttemptRecord,
    TaskKind,
    TaskRecord,
    TaskStatus,
    TechProfile,
    VerifyReport,
)
from .state_store import StateStore, force_rmtree, utc_now_iso
from .tech_bootstrap import (
    build_asset_schemas_contract,
    build_state_events_contract,
    get_scenario_dir,
    propose_tech_profile,
)
from .verifier import (
    author_scenarios_for_sys,
    run_level1_checks,
    run_level2_qa,
    should_require_spot_check,
)
from .verifier.scenario_runner import load_scenarios_from_dir
from .workers import ApiWorker, CliWorker, MockWorker, WorkerAdapter, WorkerResult
from .workspace_manager import AttemptWorkspace, WorkspaceManager


class OrchestratorEngine:
    """
    第二层编排器核心控制引擎：
    - 统一管理多项目运行态（StateStore）与沙箱 Git 工作区（WorkspaceManager）；
    - 贯彻双层状态机（7 态项目状态 + 9 态任务状态）、四处零绕过人类门禁、并发槽 + C-1 串行约束；
    - 并发在线程池执行 Worker，主循环单线程按 task_id 字典序验收与合并提交；
    - 支持实时 SSE 事件回调与 Delta RFC 增量热重排。
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        base_dir: Optional[Path] = None,
        force_mock: bool = False,
        worker_overrides: Optional[Dict[str, WorkerAdapter]] = None,
    ) -> None:
        self.base_dir = (base_dir or Path.cwd()).resolve()
        self.config: Dict[str, Any] = config or self._load_default_config()
        if force_mock:
            self.config.setdefault("test_mode", {})["all_workers_mock"] = True

        state_root = self._resolve_root(self.config.get("state_root", ".orchestrator/"))
        ws_root = self._resolve_root(self.config.get("workspace_root", "workspace/"))
        redact_patterns = self.config.get("safety", {}).get("redact_patterns")

        self.guard = BudgetGuard(redact_patterns)
        self.store = StateStore(state_root, self.guard)
        self.workspace_mgr = WorkspaceManager(ws_root, self.store)
        self.worker_overrides: Dict[str, WorkerAdapter] = worker_overrides or {}

        self._lock = threading.RLock()
        self._bundles: Dict[str, HandoffBundle] = {}
        self._sse_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._auto_threads: Dict[str, threading.Event] = {}

    def _resolve_root(self, raw: str) -> Path:
        p = Path(raw)
        return p if p.is_absolute() else (self.base_dir / p)

    def _load_default_config(self) -> Dict[str, Any]:
        cfg_file = self.base_dir / "orchestrator_runtime.yaml"
        if cfg_file.exists():
            return yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        return {
            "state_root": ".orchestrator/",
            "workspace_root": "workspace/",
            "ingest": {"auxiliary_files": "compat"},
            "concurrency": {
                "ROLE_TECH_LEAD": 1,
                "ROLE_SYS_DEV": 2,
                "ROLE_NARRATIVE": 1,
                "ROLE_ART_2D": 2,
                "ROLE_AUDIO": 1,
                "ROLE_QA_INTEG": 2,
            },
            "policy": {"max_attempts": 3, "human_spot_check": ["AUD"], "oversized_task_hours": 16},
            "budget": {"project_cost_cap": 50.0, "project_call_cap": 2000, "per_attempt_call_cap": 40},
            "estimation": {"mode": "baseline", "rework_ratio": 0.5},
            "test_mode": {"all_workers_mock": True},
        }

    def subscribe_sse(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._sse_listeners.append(callback)

    def unsubscribe_sse(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._sse_listeners = [cb for cb in self._sse_listeners if cb is not callback]

    def _emit(
        self,
        session: SessionState,
        event_type: str,
        *,
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        evt = self.store.append_event(session, event_type, task_id=task_id, payload=payload)
        for cb in list(self._sse_listeners):
            try:
                cb(evt)
            except Exception:
                pass
        return evt

    def is_mock_mode(self) -> bool:
        return bool(self.config.get("test_mode", {}).get("all_workers_mock", False))

    def list_projects(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for pid in self.store.list_project_ids():
            sess = self.store.load_session(pid)
            if sess:
                out.append(
                    {
                        "project_id": sess.project_id,
                        "spec_version": sess.spec_version,
                        "project_state": sess.project_state.value,
                        "scope_tier": sess.scope_tier,
                        "progress_cp": sess.cpm.progress_cp,
                        "progress_all": sess.cpm.progress_all,
                    }
                )
        return out

    def get_session(self, project_id: str) -> SessionState:
        with self._lock:
            sess = self.store.load_session(project_id)
            if sess is None:
                raise OrchestratorError("ERR_PROJECT_NOT_FOUND", f"项目 {project_id} 尚未加载。")
            return sess

    def _get_bundle(self, session: SessionState) -> HandoffBundle:
        if session.project_id in self._bundles:
            b = self._bundles[session.project_id]
            if b.manifest.spec_version == session.spec_version:
                return b
        aux_mode = self.config.get("ingest", {}).get("auxiliary_files", "compat")
        archived = self.store.project_dir(session.project_id) / "handoffs" / session.spec_version
        src = archived if archived.exists() else Path(session.handoff_dir)
        bundle = load_handoff_bundle(src, auxiliary_mode=aux_mode)
        self._bundles[session.project_id] = bundle
        return bundle

    # -----------------------------------------------------------------------
    # Phase A: 加载、校验、断点恢复与增量升版
    # -----------------------------------------------------------------------

    def load_project(
        self,
        handoff_dir: Path,
        *,
        force_new_project: bool = False,
        auxiliary_mode: Optional[str] = None,
    ) -> Tuple[SessionState, str]:
        with self._lock:
            aux_mode = auxiliary_mode or self.config.get("ingest", {}).get("auxiliary_files", "compat")
            bundle = load_handoff_bundle(handoff_dir, auxiliary_mode=aux_mode)
            pid = bundle.manifest.project_id
            existing = None if force_new_project else self.store.load_session(pid)

            val = validate_handoff_bundle(
                bundle,
                auxiliary_mode=aux_mode,
                existing_session=existing,
                force_new_project=force_new_project,
            )

            if val.load_mode == "NEW":
                if force_new_project:
                    self.stop_auto_run(pid)
                    force_rmtree(self.store.project_dir(pid))
                    force_rmtree(self.workspace_mgr.main_workspace(pid))
                return self._init_new_project(bundle, val.warnings), "NEW"

            assert existing is not None
            if val.load_mode == "RESUME":
                session = self._recover_existing_session(existing, bundle, val.warnings)
                return session, "RESUME"

            # UPGRADE
            old_bundle = self._get_bundle(existing)
            session = self._upgrade_existing_session(existing, old_bundle, bundle, val.warnings)
            return session, "UPGRADE"

    def _init_new_project(self, bundle: HandoffBundle, warnings: List[str]) -> SessionState:
        m = bundle.manifest
        graph = build_task_graph(bundle)
        apply_estimates(graph.tasks, self.config)

        concurrency = self.config.get("concurrency", {})
        cpm_summary = compute_cpm(graph.tasks, m.lead_pillars, concurrency=concurrency)
        tech_prop = propose_tech_profile(bundle)
        state_events, _ = build_state_events_contract(bundle)
        asset_schemas = build_asset_schemas_contract()

        budget_cfg = self.config.get("budget", {})
        budget = BudgetState(
            cost_cap=float(budget_cfg.get("project_cost_cap", 50.0)),
            calls_cap=int(budget_cfg.get("project_call_cap", 2000)),
            per_attempt_call_cap=int(budget_cfg.get("per_attempt_call_cap", 40)),
        )

        canon_hashes = {
            c.canon_id: stable_json_sha256(c.model_dump(mode="json")) for c in bundle.canon_registry.entries
        }
        adr_hashes = {a.adr_id: stable_json_sha256(a.model_dump(mode="json")) for a in bundle.adr_records}

        session = SessionState(
            project_id=m.project_id,
            spec_version=m.spec_version,
            parent_version=m.parent_version,
            canonical_sha256=m.canonical_sha256,
            scope_tier=m.scope_tier,
            lead_pillars=list(m.lead_pillars),
            derived_pillars=list(m.derived_pillars),
            project_state=ProjectState.LOADED,
            handoff_dir=bundle.source_dir,
            tech_profile=tech_prop,
            state_events=state_events,
            asset_schemas=asset_schemas,
            contract_sha256={
                "state_events": state_events.contract_sha256,
                "asset_schemas": asset_schemas.contract_sha256,
            },
            tasks={t.task_id: t for t in graph.tasks},
            edges=graph.edges,
            budget=budget,
            cpm=cpm_summary,
            warnings=list(warnings),
            global_constraints_hashes=dict(bundle.global_constraints_hashes),
            canon_hashes=canon_hashes,
            adr_hashes=adr_hashes,
        )

        self.store.archive_handoff_copy(m.project_id, m.spec_version, Path(bundle.source_dir))
        self.workspace_mgr.ensure_project_workspace(session)
        self._emit(
            session,
            "HANDOFF_ACCEPTED",
            payload={"spec_version": m.spec_version, "canonical_sha256": m.canonical_sha256},
        )
        for w in warnings:
            if w.startswith("WARN_UNHASHED_AUXILIARY_FILE"):
                self._emit(session, "WARN_UNHASHED_AUXILIARY_FILE", payload={"message": w})
        self._emit(
            session,
            "GRAPH_BUILT",
            payload={"node_count": len(graph.tasks), "edge_count": len(graph.edges)},
        )
        session.project_state = transition_project_state(session.project_state, ProjectState.AWAITING_TECH_CONFIRM)
        self._emit(
            session,
            "PROJECT_STATE_CHANGED",
            payload={"project_state": session.project_state.value},
        )
        self._emit(session, "TECH_PROFILE_PROPOSED", payload=tech_prop.model_dump(mode="json"))
        self.store.save_session(session)
        self._bundles[m.project_id] = bundle
        return session

    def _recover_existing_session(
        self, session: SessionState, bundle: HandoffBundle, warnings: List[str]
    ) -> SessionState:
        """§4.3 断点续跑：RUNNING / WAITING_VERIFY 回退为 READY（不计失败），清理残留尝试工作区。"""
        cleaned = self.workspace_mgr.cleanup_all_attempts(session.project_id)
        for task in sorted(session.tasks.values(), key=lambda t: t.task_id):
            if task.state in (TaskStatus.RUNNING, TaskStatus.WAITING_VERIFY):
                task.state = TaskStatus.READY
                self._emit(
                    session,
                    "ATTEMPT_CANCELED",
                    task_id=task.task_id,
                    payload={"reason": "crash_recovery", "attempts_failed_unchanged": task.attempts_failed},
                )
        for w in warnings:
            if w not in session.warnings:
                session.warnings.append(w)
        self._emit(
            session,
            "HANDOFF_ACCEPTED",
            payload={"mode": "RESUME", "cleaned_worktrees": cleaned},
        )
        self.store.save_session(session)
        self._bundles[session.project_id] = bundle
        return session

    def _upgrade_existing_session(
        self,
        session: SessionState,
        old_bundle: HandoffBundle,
        new_bundle: HandoffBundle,
        warnings: List[str],
    ) -> SessionState:
        self.stop_auto_run(session.project_id)
        self.store.archive_handoff_copy(
            session.project_id, new_bundle.manifest.spec_version, Path(new_bundle.source_dir)
        )
        reconcile_delta_upgrade(
            session,
            old_bundle,
            new_bundle,
            config=self.config,
            store=self.store,
            workspace_mgr=self.workspace_mgr,
            aux_warnings=warnings,
        )
        self._bundles[session.project_id] = new_bundle
        return session

    # -----------------------------------------------------------------------
    # 第十一章：四处人类门禁（G1 ~ G4，零绕过）
    # -----------------------------------------------------------------------

    def apply_gate_decision(
        self,
        project_id: str,
        gate_id: str,
        option: str,
        *,
        target: Optional[str] = None,
        note: str = "",
        decided_by: str = "human_director",
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionState:
        with self._lock:
            session = self.get_session(project_id)
            bundle = self._get_bundle(session)
            payload = payload or {}

            if gate_id == "G1":
                if session.project_state != ProjectState.AWAITING_TECH_CONFIRM:
                    raise OrchestratorError(
                        "ERR_GATE_NOT_READY",
                        f"项目当前状态 {session.project_state.value} 不允许操作 G1。",
                    )
                old_profile_hash = stable_json_sha256(
                    session.tech_profile.model_dump(exclude={"confirmed_by", "confirmed_at"})
                )
                edited = payload.get("tech_profile")
                if isinstance(edited, dict):
                    merged = session.tech_profile.model_dump()
                    for k in ("platform", "language", "render", "data_format", "runtime_harness"):
                        if k in edited:
                            merged[k] = edited[k]
                    session.tech_profile = TechProfile.model_validate(merged)

                session.tech_profile.confirmed_by = decided_by
                session.tech_profile.confirmed_at = utc_now_iso()
                new_profile_hash = stable_json_sha256(
                    session.tech_profile.model_dump(exclude={"confirmed_by", "confirmed_at"})
                )

                # 若 Tier C 升版期间人类修改了技术档案，TECH-001 与全部下游重新判脏
                if session.delta_history and session.delta_history[-1].delta_tier == "TIER_C_CORE_PIVOT":
                    if old_profile_hash != new_profile_hash:
                        for t in session.tasks.values():
                            t.state = TaskStatus.PENDING
                            t.attempt_epoch += 1
                            t.delta_tag = "DIRTY_RERUN"

                state_events, _ = build_state_events_contract(bundle, session.state_events)
                asset_schemas = build_asset_schemas_contract()
                session.state_events = state_events
                session.asset_schemas = asset_schemas
                session.contract_sha256 = {
                    "state_events": state_events.contract_sha256,
                    "asset_schemas": asset_schemas.contract_sha256,
                }
                self.workspace_mgr.write_contracts_to_main(session)
                git_g1 = self.workspace_mgr.git_for(project_id)
                c_g1, ok_g1 = git_g1.commit_all(
                    f"[{session.spec_version}] G1: lock tech_profile and shared contracts",
                    spec_version=session.spec_version,
                )
                if not ok_g1:
                    session.git_sync_pending = True
                if c_g1:
                    session.git_commits.append(c_g1)

                session.gate_decisions.append(
                    GateDecision(
                        gate_id="G1",
                        target=project_id,
                        option=option or "confirm",
                        note=note,
                        decided_by=decided_by,
                        decided_at=utc_now_iso(),
                        payload=payload,
                    )
                )
                session.project_state = transition_project_state(session.project_state, ProjectState.RUNNING)
                self._emit(
                    session,
                    "HUMAN_DECISION",
                    payload={"gate_id": "G1", "option": option, "decided_by": decided_by, "note": note},
                )
                self._emit(
                    session,
                    "PROJECT_STATE_CHANGED",
                    payload={"project_state": session.project_state.value},
                )
                self._refresh_dependencies_locked(session)
                self.store.save_session(session)
                return session

            if gate_id == "G2":
                task_id = target or ""
                task = session.tasks.get(task_id)
                if task is None:
                    raise OrchestratorError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
                if option == "undo_skip":
                    if task.state != TaskStatus.SKIPPED:
                        raise OrchestratorError("ERR_GATE_NOT_READY", f"任务 {task_id} 不处于 SKIPPED 状态。")
                    task.state = TaskStatus.READY
                    task.skip.waiver = None
                    task.skip.reason = ""
                    # 解除仅因前置阻塞而被标为 BLOCKED 的下游
                    self._unblock_downstream_if_ready_locked(session)
                else:
                    if task.state != TaskStatus.WAITING_DECISION:
                        raise OrchestratorError(
                            "ERR_GATE_NOT_READY",
                            f"任务 {task_id} 当前状态 {task.state.value}，无法执行 G2。",
                        )
                    kind = task.decision_kind
                    if option in ("skip_with_waiver", "skip_and_block"):
                        waiver = option == "skip_with_waiver"
                        task.state = TaskStatus.SKIPPED
                        task.decision_kind = None
                        task.skip.waiver = waiver
                        task.skip.reason = note or ("豁免放行" if waiver else "阻断下游跳过")
                        self._refresh_dependencies_locked(session)
                    elif kind == DecisionKind.SCENARIO_DISPUTE:
                        if option == "rewrite_scenario":
                            # 场景有误：QA 重写场景，不计作者尝试次数
                            sys_item = next(
                                d for d in bundle.system_requirements.stage_deliverables if d.req_id == task.req_id
                            )
                            _, rels = author_scenarios_for_sys(
                                bundle,
                                sys_item,
                                session.state_events,  # type: ignore[arg-type]
                                self.workspace_mgr.main_workspace(project_id),
                                force_revision_note=note or "依据 G2 争议裁决重写验收场景",
                            )
                            task.scenario_paths = rels
                            git_sc = self.workspace_mgr.git_for(project_id)
                            c_sc, ok_sc = git_sc.commit_all(
                                f"[{session.spec_version}] scenarios: rewrite for {task.req_id}",
                                task_id=task.task_id,
                                spec_version=session.spec_version,
                            )
                            if not ok_sc:
                                session.git_sync_pending = True
                            if c_sc:
                                session.git_commits.append(c_sc)
                            self._emit(
                                session,
                                "SCENARIO_AUTHORED",
                                task_id=task.task_id,
                                payload={"rewritten": True, "paths": rels},
                            )
                        else:
                            if note:
                                task.guidance_notes.append(f"[G2 争议裁决] {note}")
                        task.state = TaskStatus.READY
                        task.decision_kind = None
                    elif kind == DecisionKind.SPOT_CHECK:
                        if option == "approve":
                            self._finalize_spot_check_approval_locked(session, task)
                        else:
                            # 否决抽检：按实现缺陷重做
                            task.attempts_failed += 1
                            add_rework_delay(task, self.config)
                            if note:
                                task.guidance_notes.append(f"[G2 人工抽检否决] {note}")
                            self._clear_staged(project_id, task.task_id)
                            max_att = int(self.config.get("policy", {}).get("max_attempts", 3))
                            if task.attempts_failed >= max_att:
                                task.state = TaskStatus.WAITING_DECISION
                                task.decision_kind = DecisionKind.RETRY_EXHAUSTED
                            else:
                                task.state = TaskStatus.READY
                                task.decision_kind = None
                    else:
                        # RETRY_EXHAUSTED 或其他：retry_with_guidance / reassign_mode
                        if note:
                            task.guidance_notes.append(f"[G2 人工指导] {note}")
                        if payload.get("override_worker_mode"):
                            task.override_worker_mode = str(payload["override_worker_mode"])
                        task.attempts_failed = 0
                        task.state = TaskStatus.READY
                        task.decision_kind = None

                session.gate_decisions.append(
                    GateDecision(
                        gate_id="G2",
                        target=task_id,
                        decision_kind=task.decision_kind.value if task.decision_kind else option,
                        option=option,
                        note=note,
                        decided_by=decided_by,
                        decided_at=utc_now_iso(),
                        payload=payload,
                    )
                )
                self._emit(
                    session,
                    "HUMAN_DECISION",
                    task_id=task_id,
                    payload={"gate_id": "G2", "option": option, "note": note},
                )
                session.cpm = compute_cpm(
                    list(session.tasks.values()),
                    session.lead_pillars,
                    concurrency=self.config.get("concurrency", {}),
                    baseline_cp_length=session.cpm.baseline_cp_length_hours,
                )
                self.store.save_session(session)
                return session

            if gate_id == "G3":
                task_id = target or ""
                task = session.tasks.get(task_id)
                if task is None:
                    raise OrchestratorError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
                if option == "reject_defect":
                    # 驳回需求缺陷结论，改按实现缺陷重做
                    if note:
                        task.guidance_notes.append(f"[G3 驳回需求缺陷] {note}")
                    task.state = TaskStatus.READY
                    task.decision_kind = None
                else:
                    # 默认提交/导出 change_request.yaml
                    impacted = payload.get("impacted_req_ids") or ([task.req_id] if task.req_id else [task_id])
                    cr = build_and_export_change_request(
                        session,
                        self.store,
                        trigger_source=str(payload.get("trigger_source", "playtest_feedback")),
                        impacted_req_ids=list(impacted),
                        problem_statement=str(payload.get("problem_statement", note or "下游验收发现需求问题")),
                        requested_delta=str(payload.get("requested_delta", note or "请第一层按问题陈述调整需求")),
                    )
                    payload = {**payload, "request_id": cr.request_id}

                session.gate_decisions.append(
                    GateDecision(
                        gate_id="G3",
                        target=task_id,
                        decision_kind=DecisionKind.REQUIREMENT_DEFECT.value,
                        option=option,
                        note=note,
                        decided_by=decided_by,
                        decided_at=utc_now_iso(),
                        payload=payload,
                    )
                )
                self._emit(
                    session,
                    "HUMAN_DECISION",
                    task_id=task_id,
                    payload={"gate_id": "G3", "option": option, "note": note},
                )
                self.store.save_session(session)
                return session

            if gate_id == "G4":
                if session.project_state != ProjectState.AWAITING_RELEASE:
                    raise OrchestratorError(
                        "ERR_GATE_NOT_READY",
                        f"项目当前状态 {session.project_state.value} 尚未到达终验待封版阶段。",
                    )
                if option == "reject_tasks":
                    reject_ids = list(payload.get("task_ids", []))
                    if not reject_ids:
                        raise OrchestratorError("ERR_SCHEMA_INVALID", "G4 退回必须指定至少一个 task_id。")
                    closure = self._downstream_closure(session, set(reject_ids))
                    for tid in sorted(closure):
                        t = session.tasks.get(tid)
                        if t:
                            t.state = TaskStatus.PENDING
                            t.attempts_failed = 0
                            t.delay_hours = 0.0
                            t.attempt_epoch += 1
                    session.project_state = transition_project_state(session.project_state, ProjectState.RUNNING)
                else:
                    # 封版签字并打版本标签 spec/<spec_version>
                    git = self.workspace_mgr.git_for(project_id)
                    tag_name, sync_ok = git.tag_release(session.spec_version)
                    if not sync_ok:
                        session.git_sync_pending = True
                    session.project_state = transition_project_state(session.project_state, ProjectState.RELEASED)
                    self._emit(
                        session,
                        "RELEASE_SIGNED",
                        payload={
                            "spec_version": session.spec_version,
                            "tag": tag_name,
                            "manual_required": session.manual_required_items,
                            "waived_tasks": session.cpm.waived_tasks,
                            "warnings": session.warnings,
                        },
                    )

                session.gate_decisions.append(
                    GateDecision(
                        gate_id="G4",
                        target=project_id,
                        option=option or "sign_release",
                        note=note,
                        decided_by=decided_by,
                        decided_at=utc_now_iso(),
                        payload=payload,
                    )
                )
                self._emit(
                    session,
                    "HUMAN_DECISION",
                    payload={"gate_id": "G4", "option": option, "note": note},
                )
                session.cpm = compute_cpm(
                    list(session.tasks.values()),
                    session.lead_pillars,
                    concurrency=self.config.get("concurrency", {}),
                    baseline_cp_length=session.cpm.baseline_cp_length_hours,
                )
                self.store.save_session(session)
                return session

            raise OrchestratorError("ERR_SCHEMA_INVALID", f"未知门禁编号: {gate_id}")

    def create_change_request(
        self,
        project_id: str,
        *,
        trigger_source: str,
        impacted_req_ids: List[str],
        problem_statement: str,
        requested_delta: str,
    ) -> ChangeRequest:
        with self._lock:
            session = self.get_session(project_id)
            cr = build_and_export_change_request(
                session,
                self.store,
                trigger_source=trigger_source,
                impacted_req_ids=impacted_req_ids,
                problem_statement=problem_statement,
                requested_delta=requested_delta,
            )
            self.store.save_session(session)
            return cr

    # -----------------------------------------------------------------------
    # 第十二章：调度控制与主循环
    # -----------------------------------------------------------------------

    def control(self, project_id: str, action: str) -> Dict[str, Any]:
        with self._lock:
            session = self.get_session(project_id)
            if action == "pause":
                self.stop_auto_run(project_id)
                if session.project_state == ProjectState.RUNNING:
                    session.project_state = transition_project_state(session.project_state, ProjectState.PAUSED)
                    self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "PAUSED"})
                    self.store.save_session(session)
                return {"project_state": session.project_state.value}

            if action == "cancel_running":
                if session.project_state != ProjectState.PAUSED:
                    raise OrchestratorError("ERR_CONTROL_INVALID", "仅可在 PAUSED 状态下执行 cancel_running。")
                canceled = []
                for t in sorted(session.tasks.values(), key=lambda x: x.task_id):
                    if t.state == TaskStatus.RUNNING:
                        t.state = TaskStatus.READY
                        canceled.append(t.task_id)
                        self._emit(
                            session,
                            "ATTEMPT_CANCELED",
                            task_id=t.task_id,
                            payload={"reason": "manual_cancel_running"},
                        )
                self.workspace_mgr.cleanup_all_attempts(project_id)
                self.store.save_session(session)
                return {"project_state": session.project_state.value, "canceled": canceled}

            if action == "resume":
                if session.project_state == ProjectState.PAUSED:
                    session.project_state = transition_project_state(session.project_state, ProjectState.RUNNING)
                    self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "RUNNING"})
                    self.store.save_session(session)
                return {"project_state": session.project_state.value}

            if action == "step":
                if session.project_state not in (ProjectState.PAUSED, ProjectState.RUNNING):
                    raise OrchestratorError(
                        "ERR_CONTROL_INVALID",
                        f"项目处于 {session.project_state.value}，无法单步 step。",
                    )
                was_paused = session.project_state == ProjectState.PAUSED
                if was_paused:
                    session.project_state = transition_project_state(session.project_state, ProjectState.RUNNING)
                dispatched = self.run_wave(project_id, max_tasks=1)
                session = self.get_session(project_id)
                if session.project_state == ProjectState.RUNNING:
                    session.project_state = transition_project_state(session.project_state, ProjectState.PAUSED)
                    self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "PAUSED"})
                    self.store.save_session(session)
                return {"project_state": session.project_state.value, "stepped_tasks": dispatched}

            if action == "auto_start":
                self.start_auto_run(project_id)
                return {"project_state": session.project_state.value, "auto_running": True}

            raise OrchestratorError("ERR_CONTROL_INVALID", f"未知控制命令: {action}")

    def start_auto_run(self, project_id: str) -> None:
        with self._lock:
            self.stop_auto_run(project_id)
            stop_ev = threading.Event()
            self._auto_threads[project_id] = stop_ev

        def _loop() -> None:
            while not stop_ev.is_set():
                try:
                    sess = self.get_session(project_id)
                    if sess.project_state != ProjectState.RUNNING:
                        break
                    dispatched = self.run_wave(project_id)
                    if not dispatched:
                        break
                except Exception:
                    break
                time.sleep(0.25)

        t = threading.Thread(target=_loop, daemon=True, name=f"orch-auto-{project_id}")
        t.start()

    def stop_auto_run(self, project_id: str) -> None:
        ev = self._auto_threads.pop(project_id, None)
        if ev:
            ev.set()

    def run_until_settled(self, project_id: str, max_waves: int = 30) -> SessionState:
        """持续推进调度波次直到无可执行任务或进入等待门禁/暂停/待封版（多用于自动化测试）。"""
        for _ in range(max_waves):
            sess = self.get_session(project_id)
            if sess.project_state != ProjectState.RUNNING:
                return sess
            dispatched = self.run_wave(project_id)
            if not dispatched:
                return self.get_session(project_id)
        return self.get_session(project_id)

    def run_wave(self, project_id: str, *, max_tasks: Optional[int] = None) -> List[str]:
        """§7.2 调度循环的一轮完整执行：解锁 -> 派单 -> 并发 Worker -> 确定性顺序验收与合并提交。"""
        with self._lock:
            session = self.get_session(project_id)
            if session.project_state != ProjectState.RUNNING:
                return []
            bundle = self._get_bundle(session)
            self._refresh_dependencies_locked(session)

            qa_final = session.tasks.get("QA-FINAL")
            if qa_final and qa_final.state == TaskStatus.SUCCEEDED:
                session.project_state = transition_project_state(
                    session.project_state, ProjectState.AWAITING_RELEASE
                )
                self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "AWAITING_RELEASE"})
                self.store.save_session(session)
                return []

            ready_tasks = [t for t in session.tasks.values() if t.state == TaskStatus.READY]
            if not ready_tasks:
                self.store.save_session(session)
                return []

            # 按 §6.5 四级优先级排序
            ready_tasks.sort(key=lambda t: dispatch_priority_key(t, session.lead_pillars))

            concurrency_cfg = self.config.get("concurrency", {})
            running_counts: Dict[str, int] = {}
            active_reuse_groups: Set[str] = set()
            for t in session.tasks.values():
                if t.state == TaskStatus.RUNNING:
                    running_counts[t.role] = running_counts.get(t.role, 0) + 1
                    if t.reuse_group:
                        active_reuse_groups.add(t.reuse_group)

            selected: List[TaskRecord] = []
            for cand in ready_tasks:
                if max_tasks is not None and len(selected) >= max_tasks:
                    break
                cap = max(1, int(concurrency_cfg.get(cand.role, 1)))
                used = running_counts.get(cand.role, 0)
                if used >= cap:
                    continue
                # C-1 复用组串行约束
                if cand.reuse_group and cand.reuse_group in active_reuse_groups:
                    continue

                ok_budget, budget_reason = self.guard.can_dispatch(session.budget)
                if not ok_budget:
                    session.project_state = transition_project_state(session.project_state, ProjectState.PAUSED)
                    self._emit(session, "BUDGET_EXHAUSTED", payload={"reason": budget_reason})
                    self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "PAUSED"})
                    self.store.save_session(session)
                    return []

                running_counts[cand.role] = used + 1
                if cand.reuse_group:
                    active_reuse_groups.add(cand.reuse_group)
                selected.append(cand)

            if not selected:
                self.store.save_session(session)
                return []

            # 先为本波次内尚未编写验收场景的 SYS 任务独立生成并提交场景，确保后续 worktree 基线完整一致
            scenario_map: Dict[str, List[Dict[str, Any]]] = {}
            authored_any = False
            for task in selected:
                if task.kind == TaskKind.SYS and task.req_id:
                    existing_scenarios = load_scenarios_from_dir(
                        self.workspace_mgr.main_workspace(project_id), task.req_id
                    )
                    if not existing_scenarios:
                        sys_item = next(
                            d for d in bundle.system_requirements.stage_deliverables if d.req_id == task.req_id
                        )
                        assert session.state_events is not None
                        sc_specs, sc_rels = author_scenarios_for_sys(
                            bundle,
                            sys_item,
                            session.state_events,
                            self.workspace_mgr.main_workspace(project_id),
                        )
                        task.scenario_paths = sc_rels
                        authored_any = True
                        self._emit(
                            session,
                            "SCENARIO_AUTHORED",
                            task_id=task.task_id,
                            payload={"paths": sc_rels, "count": len(sc_specs)},
                        )
                        existing_scenarios = sc_specs
                    scenario_map[task.task_id] = [s.model_dump(mode="json") for s in existing_scenarios]

            if authored_any:
                git_sc = self.workspace_mgr.git_for(project_id)
                c_sc, ok_sc = git_sc.commit_all(
                    f"[{session.spec_version}] scenarios: lock QA acceptance scenarios",
                    spec_version=session.spec_version,
                )
                if not ok_sc:
                    session.git_sync_pending = True
                if c_sc:
                    session.git_commits.append(c_sc)

            # 为每个选中任务准备隔离尝试工作区与最小上下文包
            prepared: Dict[str, Tuple[AttemptWorkspace, Dict[str, Any], str, int]] = {}
            for task in selected:
                task.state = TaskStatus.RUNNING
                task.next_attempt_seq += 1
                attempt_no = task.next_attempt_seq - 1
                if attempt_no < 1:
                    attempt_no = 1
                    task.next_attempt_seq = 2

                scenario_payloads: List[Dict[str, Any]] = list(scenario_map.get(task.task_id, []))
                if task.kind in (TaskKind.INTEG, TaskKind.QA_FINAL):
                    for tid_other, other in sorted(session.tasks.items()):
                        if other.kind == TaskKind.SYS and other.req_id:
                            if task.kind == TaskKind.QA_FINAL or tid_other in task.depends_on:
                                scs = load_scenarios_from_dir(
                                    self.workspace_mgr.main_workspace(project_id), other.req_id
                                )
                                scenario_payloads.extend(s.model_dump(mode="json") for s in scs)

                attempt_ws = self.workspace_mgr.create_attempt_workspace(project_id, task.task_id, attempt_no)
                ctx = pack_task_context(session, bundle, task, scenario_payloads=scenario_payloads)
                ctx["attempt"] = attempt_no
                ctx_rel = self.store.write_context(project_id, task.task_id, attempt_no, ctx)

                self._emit(
                    session,
                    "WORKER_STARTED",
                    task_id=task.task_id,
                    payload={"attempt": attempt_no, "role": task.role, "context_path": ctx_rel},
                )
                prepared[task.task_id] = (attempt_ws, ctx, ctx_rel, attempt_no)

            self.store.save_session(session)

        # 线程池并发执行各 Worker（不持全局锁，允许外部真实并行执行）
        worker_results: Dict[str, WorkerResult] = {}
        timeout_map = self.config.get("workers", {})
        with ThreadPoolExecutor(max_workers=max(1, len(selected))) as pool:
            futs = {}
            for task in selected:
                attempt_ws, ctx, _, _ = prepared[task.task_id]
                adapter = self._resolve_worker(task)
                timeout_sec = int(timeout_map.get(task.role, {}).get("timeout_sec", 300))
                futs[task.task_id] = pool.submit(adapter.run, ctx, attempt_ws.attempt_dir, timeout_sec)
            for tid, fut in futs.items():
                try:
                    worker_results[tid] = fut.result()
                except Exception as exc:
                    worker_results[tid] = WorkerResult(ok=False, error_message=str(exc))

        # 主循环单线程按 task_id 字典序验收、状态迁移与合并提交
        with self._lock:
            session = self.get_session(project_id)
            bundle = self._get_bundle(session)
            max_attempts = int(self.config.get("policy", {}).get("max_attempts", 3))
            budget_exceeded = False

            for tid in sorted(prepared.keys()):
                task = session.tasks[tid]
                attempt_ws, ctx, ctx_rel, attempt_no = prepared[tid]
                wres = worker_results[tid]
                task.actual_runtime_sec = round(task.actual_runtime_sec + wres.runtime_sec, 4)

                # 先记录资源消耗，超限立即暂停且拒绝让超出产物入库 (O16)
                within_budget = self.guard.record_usage(
                    session.budget, calls=wres.api_calls, cost=wres.cost
                )
                if not within_budget:
                    budget_exceeded = True
                    task.state = TaskStatus.READY
                    self.workspace_mgr.cleanup_attempt_workspace(project_id, attempt_ws)
                    continue

                self._emit(
                    session,
                    "WORKER_FINISHED",
                    task_id=tid,
                    payload={"attempt": attempt_no, "ok": wres.ok, "runtime_sec": wres.runtime_sec},
                )

                if not wres.ok or wres.manifest is None:
                    self._record_attempt_failure_locked(
                        session,
                        task,
                        attempt_no,
                        attempt_ws,
                        ctx_rel,
                        reason=wres.error_message or "Worker 执行失败",
                        max_attempts=max_attempts,
                    )
                    continue

                manifest = wres.manifest
                # 校验尝试工作区实际发生的文件改动是否越界
                iso_ok, changed_files, violations, patch_rel = self.workspace_mgr.detect_and_check_changes(
                    project_id, task, attempt_no, attempt_ws
                )
                if not iso_ok:
                    self._emit(
                        session,
                        "WRITE_VIOLATION",
                        task_id=tid,
                        payload={"attempt": attempt_no, "violations": violations, "patch_path": patch_rel},
                    )
                    self._record_attempt_failure_locked(
                        session,
                        task,
                        attempt_no,
                        attempt_ws,
                        ctx_rel,
                        reason=f"越界写入被拦截: {violations}",
                        max_attempts=max_attempts,
                        patch_rel=patch_rel,
                    )
                    continue

                # 作者提出场景争议
                if manifest.scenario_dispute:
                    self.workspace_mgr.cleanup_attempt_workspace(project_id, attempt_ws)
                    task.state = TaskStatus.WAITING_DECISION
                    task.decision_kind = DecisionKind.SCENARIO_DISPUTE
                    task.history.append(
                        TaskAttemptRecord(
                            attempt=attempt_no,
                            epoch=task.attempt_epoch,
                            result="SCENARIO_DISPUTE",
                            context_path=ctx_rel,
                            runtime_sec=wres.runtime_sec,
                            summary=str(manifest.scenario_dispute.get("reason", "场景争议")),
                            timestamp=utc_now_iso(),
                        )
                    )
                    self._emit(
                        session,
                        "TASK_STATE_CHANGED",
                        task_id=tid,
                        payload={"state": task.state.value, "decision_kind": DecisionKind.SCENARIO_DISPUTE.value},
                    )
                    continue

                # 进 WAITING_VERIFY：作者无法直接置 SUCCEEDED (O9)
                task.state = TaskStatus.WAITING_VERIFY

                # Level 1 确定性检查
                l1 = run_level1_checks(session, bundle, task, manifest, attempt_ws.attempt_dir, changed_files)
                self._emit(
                    session,
                    "VERIFY_L1_DONE",
                    task_id=tid,
                    payload={"attempt": attempt_no, "passed": l1.passed, "failed": l1.failed_checks},
                )
                if not l1.passed:
                    vrep = VerifyReport(
                        task_id=tid,
                        attempt=attempt_no,
                        level1=l1,
                        level2=None,
                        created_at=utc_now_iso(),
                    )
                    rep_rel = self.store.write_report(project_id, tid, attempt_no, vrep.model_dump(mode="json"))
                    patch_rel = self.workspace_mgr.save_failed_patch(
                        project_id, tid, attempt_no, changed_files, "; ".join(l1.failed_checks)
                    )
                    self._record_attempt_failure_locked(
                        session,
                        task,
                        attempt_no,
                        attempt_ws,
                        ctx_rel,
                        reason="; ".join(l1.failed_checks),
                        max_attempts=max_attempts,
                        report_rel=rep_rel,
                        patch_rel=patch_rel,
                    )
                    continue

                # Level 2 独立 QA 审阅
                qa_cfg = self.config.get("workers", {}).get("ROLE_QA_INTEG", {})
                l2 = run_level2_qa(
                    task,
                    ctx,
                    l1,
                    bundle,
                    attempt_ws.attempt_dir,
                    is_mock_mode=self.is_mock_mode(),
                    qa_config=qa_cfg,
                )
                self._emit(
                    session,
                    "VERIFY_L2_DONE",
                    task_id=tid,
                    payload={"attempt": attempt_no, "decision": l2.decision},
                )
                vrep = VerifyReport(
                    task_id=tid,
                    attempt=attempt_no,
                    level1=l1,
                    level2=l2,
                    created_at=utc_now_iso(),
                )
                rep_rel = self.store.write_report(project_id, tid, attempt_no, vrep.model_dump(mode="json"))

                if l2.decision == "FAIL":
                    req_defects = [f for f in l2.findings if f.result == "FAIL" and f.defect_type == "REQUIREMENT_DEFECT"]
                    if req_defects:
                        self.workspace_mgr.cleanup_attempt_workspace(project_id, attempt_ws)
                        task.state = TaskStatus.WAITING_DECISION
                        task.decision_kind = DecisionKind.REQUIREMENT_DEFECT
                        task.history.append(
                            TaskAttemptRecord(
                                attempt=attempt_no,
                                epoch=task.attempt_epoch,
                                result="REQUIREMENT_DEFECT",
                                report_path=rep_rel,
                                context_path=ctx_rel,
                                runtime_sec=wres.runtime_sec,
                                summary=req_defects[0].evidence,
                                timestamp=utc_now_iso(),
                            )
                        )
                        self._emit(
                            session,
                            "TASK_STATE_CHANGED",
                            task_id=tid,
                            payload={"state": task.state.value, "decision_kind": DecisionKind.REQUIREMENT_DEFECT.value},
                        )
                        continue

                    patch_rel = self.workspace_mgr.save_failed_patch(
                        project_id, tid, attempt_no, changed_files, l2.notes or "L2 FAIL"
                    )
                    reason = "; ".join(f.evidence for f in l2.findings if f.result == "FAIL") or "L2 审阅不通过"
                    self._record_attempt_failure_locked(
                        session,
                        task,
                        attempt_no,
                        attempt_ws,
                        ctx_rel,
                        reason=reason,
                        max_attempts=max_attempts,
                        report_rel=rep_rel,
                        patch_rel=patch_rel,
                    )
                    continue

                # 若开启该工种人工抽检，先把产物暂存进 .orchestrator/<id>/staged/<tid>/ 等待 G2(SPOT_CHECK)
                if should_require_spot_check(task.kind, self.config) and "skip_spot_check" not in ctx["injected_faults"]:
                    self._stage_files_for_spot_check(project_id, tid, attempt_ws.attempt_dir, changed_files)
                    self.workspace_mgr.cleanup_attempt_workspace(project_id, attempt_ws)
                    task.state = TaskStatus.WAITING_DECISION
                    task.decision_kind = DecisionKind.SPOT_CHECK
                    task.artifacts = list(manifest.files)
                    task.history.append(
                        TaskAttemptRecord(
                            attempt=attempt_no,
                            epoch=task.attempt_epoch,
                            result="SPOT_CHECK",
                            report_path=rep_rel,
                            context_path=ctx_rel,
                            runtime_sec=wres.runtime_sec,
                            summary=manifest.summary,
                            timestamp=utc_now_iso(),
                        )
                    )
                    self._emit(
                        session,
                        "TASK_STATE_CHANGED",
                        task_id=tid,
                        payload={"state": task.state.value, "decision_kind": DecisionKind.SPOT_CHECK.value},
                    )
                    continue

                # 合并进主工作区 + 重新生成汇总文件 + 构建冒烟 + 提交 Git
                sim_break = "merge_build_break" in ctx.get("injected_faults", [])
                mres = self.workspace_mgr.merge_and_commit_task(
                    session,
                    task,
                    attempt_no,
                    attempt_ws,
                    changed_files,
                    is_mock_mode=self.is_mock_mode(),
                    simulate_merge_break=sim_break,
                )
                if not mres.ok:
                    self._record_attempt_failure_locked(
                        session,
                        task,
                        attempt_no,
                        attempt_ws,
                        ctx_rel,
                        reason=mres.error_reason,
                        max_attempts=max_attempts,
                        report_rel=rep_rel,
                    )
                    continue

                # 成功落定！
                self.workspace_mgr.cleanup_attempt_workspace(project_id, attempt_ws)
                task.state = TaskStatus.SUCCEEDED
                task.decision_kind = None
                task.artifacts = list(manifest.files)
                task.produced_in_version = session.spec_version
                task.delta_tag = None
                if mres.commit:
                    task.last_commit = mres.commit.commit_hash
                    session.git_commits.append(mres.commit)
                if task.kind == TaskKind.QA_FINAL and l1.manual_required:
                    session.manual_required_items = list(l1.manual_required)
                task.history.append(
                    TaskAttemptRecord(
                        attempt=attempt_no,
                        epoch=task.attempt_epoch,
                        result="SUCCEEDED",
                        report_path=rep_rel,
                        context_path=ctx_rel,
                        runtime_sec=wres.runtime_sec,
                        summary=manifest.summary,
                        timestamp=utc_now_iso(),
                    )
                )
                self._emit(
                    session,
                    "MERGE_APPLIED",
                    task_id=tid,
                    payload={"attempt": attempt_no, "commit": task.last_commit, "files": len(changed_files)},
                )
                self._emit(
                    session,
                    "TASK_STATE_CHANGED",
                    task_id=tid,
                    payload={"state": TaskStatus.SUCCEEDED.value},
                )

            if budget_exceeded:
                session.project_state = transition_project_state(session.project_state, ProjectState.PAUSED)
                self._emit(session, "BUDGET_EXHAUSTED", payload={"cost": session.budget.cost_used, "calls": session.budget.calls_used})
                self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": ProjectState.PAUSED.value})

            self._refresh_dependencies_locked(session)
            if session.tasks.get("QA-FINAL") and session.tasks["QA-FINAL"].state == TaskStatus.SUCCEEDED:
                if session.project_state == ProjectState.RUNNING:
                    session.project_state = transition_project_state(
                        session.project_state, ProjectState.AWAITING_RELEASE
                    )
                    self._emit(session, "PROJECT_STATE_CHANGED", payload={"project_state": "AWAITING_RELEASE"})

            session.cpm = compute_cpm(
                list(session.tasks.values()),
                session.lead_pillars,
                concurrency=self.config.get("concurrency", {}),
                baseline_cp_length=session.cpm.baseline_cp_length_hours,
            )
            self.store.save_session(session)
            return sorted(prepared.keys())

    # -----------------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------------

    def _resolve_worker(self, task: TaskRecord) -> WorkerAdapter:
        if task.task_id in self.worker_overrides:
            return self.worker_overrides[task.task_id]
        if task.role in self.worker_overrides:
            return self.worker_overrides[task.role]

        mode = task.override_worker_mode
        if self.is_mock_mode() and mode not in ("api", "cli"):
            return MockWorker(task.role)

        wcfg = self.config.get("workers", {}).get(task.role, {})
        resolved_mode = mode or wcfg.get("mode", "mock")
        if resolved_mode == "api":
            return ApiWorker(
                task.role,
                model=str(wcfg.get("model", "gpt-4o-mini")),
                max_backoff_retries=int(self.config.get("budget", {}).get("api_backoff", {}).get("max_retries", 3)),
                backoff_base_sec=float(self.config.get("budget", {}).get("api_backoff", {}).get("base_sec", 2.0)),
            )
        if resolved_mode == "cli":
            rt = str(wcfg.get("runtime", "codex-cli"))
            allow = self.config.get("safety", {}).get("env_allowlist", {}).get(rt, ["OPENAI_API_KEY"])
            return CliWorker(task.role, runtime=rt, env_allowlist=list(allow))
        return MockWorker(task.role)

    def _record_attempt_failure_locked(
        self,
        session: SessionState,
        task: TaskRecord,
        attempt_no: int,
        attempt_ws: AttemptWorkspace,
        ctx_rel: str,
        *,
        reason: str,
        max_attempts: int,
        report_rel: Optional[str] = None,
        patch_rel: Optional[str] = None,
    ) -> None:
        self.workspace_mgr.cleanup_attempt_workspace(session.project_id, attempt_ws)
        task.state = TaskStatus.FAILED
        task.attempts_failed += 1
        add_rework_delay(task, self.config)
        task.history.append(
            TaskAttemptRecord(
                attempt=attempt_no,
                epoch=task.attempt_epoch,
                result="FAILED",
                report_path=report_rel,
                context_path=ctx_rel,
                patch_path=patch_rel,
                summary=reason,
                timestamp=utc_now_iso(),
            )
        )
        self._emit(
            session,
            "TASK_STATE_CHANGED",
            task_id=task.task_id,
            payload={"state": TaskStatus.FAILED.value, "attempts_failed": task.attempts_failed, "reason": reason},
        )
        if task.attempts_failed >= max_attempts:
            task.state = TaskStatus.WAITING_DECISION
            task.decision_kind = DecisionKind.RETRY_EXHAUSTED
            self._emit(
                session,
                "TASK_STATE_CHANGED",
                task_id=task.task_id,
                payload={"state": task.state.value, "decision_kind": DecisionKind.RETRY_EXHAUSTED.value},
            )
        else:
            task.state = TaskStatus.READY
            self._emit(
                session,
                "TASK_STATE_CHANGED",
                task_id=task.task_id,
                payload={"state": TaskStatus.READY.value, "reason": "auto_retry"},
            )

    def _stage_files_for_spot_check(
        self, project_id: str, task_id: str, attempt_dir: Path, changed_files: List[str]
    ) -> None:
        staged = self.store.project_dir(project_id) / "staged" / task_id
        if staged.exists():
            force_rmtree(staged)
        staged.mkdir(parents=True, exist_ok=True)
        for rel in changed_files:
            src = attempt_dir / rel
            if src.exists() and src.is_file():
                dst = staged / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    def _clear_staged(self, project_id: str, task_id: str) -> None:
        staged = self.store.project_dir(project_id) / "staged" / task_id
        force_rmtree(staged)

    def _finalize_spot_check_approval_locked(self, session: SessionState, task: TaskRecord) -> None:
        staged = self.store.project_dir(session.project_id) / "staged" / task.task_id
        main_ws = self.workspace_mgr.main_workspace(session.project_id)
        if staged.exists():
            for p in staged.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(staged)
                    dst = main_ws / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dst)
        task.state = TaskStatus.SUCCEEDED
        task.decision_kind = None
        task.produced_in_version = session.spec_version
        self.workspace_mgr.regenerate_shared_generated_files(session)
        git = self.workspace_mgr.git_for(session.project_id)
        commit, sync_ok = git.commit_all(
            f"[{session.spec_version}] {task.task_id}: {task.title} (spot-check approved)",
            task_id=task.task_id,
            spec_version=session.spec_version,
        )
        if not sync_ok:
            session.git_sync_pending = True
        if commit:
            task.last_commit = commit.commit_hash
            session.git_commits.append(commit)
        self._clear_staged(session.project_id, task.task_id)
        self._emit(
            session,
            "MERGE_APPLIED",
            task_id=task.task_id,
            payload={"commit": task.last_commit, "spot_check_approved": True},
        )
        self._emit(
            session,
            "TASK_STATE_CHANGED",
            task_id=task.task_id,
            payload={"state": TaskStatus.SUCCEEDED.value, "spot_check_approved": True},
        )
        self._refresh_dependencies_locked(session)

    def _refresh_dependencies_locked(self, session: SessionState) -> None:
        """按拓扑逐层把前置已满足的 PENDING 解锁为 READY，被非豁免 SKIPPED/BLOCKED 阻断的置为 BLOCKED。"""
        changed = True
        while changed:
            changed = False
            for t in sorted(session.tasks.values(), key=lambda x: (KIND_ORDER[x.kind], x.task_id)):
                if t.state not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
                    continue
                preds = [session.tasks[d] for d in t.depends_on if d in session.tasks]
                has_blocker = any(
                    p.state == TaskStatus.BLOCKED or (p.state == TaskStatus.SKIPPED and p.skip.waiver is False)
                    for p in preds
                )
                all_satisfied = all(
                    p.state == TaskStatus.SUCCEEDED or (p.state == TaskStatus.SKIPPED and p.skip.waiver is True)
                    for p in preds
                )
                if has_blocker and t.state != TaskStatus.BLOCKED:
                    t.state = TaskStatus.BLOCKED
                    changed = True
                elif not has_blocker and t.state == TaskStatus.BLOCKED:
                    t.state = TaskStatus.READY if all_satisfied else TaskStatus.PENDING
                    changed = True
                elif all_satisfied and t.state == TaskStatus.PENDING:
                    t.state = TaskStatus.READY
                    changed = True

    def _unblock_downstream_if_ready_locked(self, session: SessionState) -> None:
        self._refresh_dependencies_locked(session)

    def _downstream_closure(self, session: SessionState, seeds: Set[str]) -> Set[str]:
        adj: Dict[str, List[str]] = {}
        for src, dst in session.edges:
            adj.setdefault(src, []).append(dst)
        visited = set(seeds)
        q = list(seeds)
        while q:
            curr = q.pop(0)
            for nxt in adj.get(curr, []):
                if nxt not in visited:
                    visited.add(nxt)
                    q.append(nxt)
        return visited

    def build_task_trace(self, project_id: str, task_id: str) -> Dict[str, Any]:
        """§12.1 全链血缘：任务 -> req_id -> GDD-Mxx -> ST_*/EVT_*/IN_* -> CANON/ADR -> Git 提交。"""
        with self._lock:
            session = self.get_session(project_id)
            bundle = self._get_bundle(session)
            task = session.tasks.get(task_id)
            if task is None:
                raise OrchestratorError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")

            gdd = next((m.model_dump(mode="json") for m in bundle.gdd_index.modules if m.gdd_id == task.gdd_ref), None)
            states: List[str] = []
            events: List[str] = []
            inputs: List[str] = []
            canons: List[str] = []
            if session.state_events:
                ref_key = task.req_id or ""
                states = [s.id for s in session.state_events.states if ref_key in s.referenced_by]
                events = [e.id for e in session.state_events.events if ref_key in e.referenced_by]
                inputs = [i.id for i in session.state_events.inputs if i.req_id == ref_key]

            for n in bundle.narrative_requirements.stage_deliverables:
                if n.req_id == task.req_id:
                    canons = list(n.canon_refs)

            adr_ids = [
                a.adr_id
                for a in bundle.adr_records
                if (task.req_id and task.req_id in a.impacted_refs) or (task.gdd_ref and task.gdd_ref in a.impacted_refs)
            ]
            commits = [c.model_dump(mode="json") for c in session.git_commits if c.task_id == task_id]
            return {
                "task_id": task_id,
                "req_id": task.req_id,
                "gdd_module": gdd,
                "state_ids": states,
                "event_ids": events,
                "input_ids": inputs,
                "canon_refs": canons,
                "adr_refs": adr_ids,
                "produced_in_version": task.produced_in_version,
                "last_commit": task.last_commit,
                "commits": commits,
                "artifacts": [a.model_dump(mode="json") for a in task.artifacts],
            }

    def get_task_detail(self, project_id: str, task_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self.get_session(project_id)
            task = session.tasks.get(task_id)
            if task is None:
                raise OrchestratorError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")

            pdir = self.store.project_dir(project_id)
            latest_context = None
            latest_report = None
            for rec in reversed(task.history):
                if not latest_context and rec.context_path and (pdir / rec.context_path).exists():
                    latest_context = (pdir / rec.context_path).read_text(encoding="utf-8")
                if not latest_report and rec.report_path and (pdir / rec.report_path).exists():
                    latest_report = (pdir / rec.report_path).read_text(encoding="utf-8")
            # 若尚无 history 但已写过 context
            if latest_context is None:
                cands = sorted((pdir / "contexts" / task_id).glob("*/task_context.json")) if (pdir / "contexts" / task_id).exists() else []
                if cands:
                    latest_context = cands[-1].read_text(encoding="utf-8")

            scenarios = []
            if task.req_id:
                main_ws = self.workspace_mgr.main_workspace(project_id)
                sc_file = main_ws / get_scenario_dir(task.req_id) / "index.yaml"
                if sc_file.exists():
                    scenarios = (yaml.safe_load(sc_file.read_text(encoding="utf-8")) or {}).get("scenarios", [])

            return {
                "task": task.model_dump(mode="json"),
                "latest_context": latest_context,
                "latest_report": latest_report,
                "scenarios": scenarios,
                "trace": self.build_task_trace(project_id, task_id),
            }

    def inject_demo_fault(self, project_id: str, task_id: str, faults: List[str]) -> SessionState:
        """供测试及可视化界面注入演示故障（如 write_violation / req_defect_valid / fail_once 等）。"""
        with self._lock:
            session = self.get_session(project_id)
            if task_id not in session.tasks:
                raise OrchestratorError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            if faults:
                session.demo_faults[task_id] = list(faults)
            else:
                session.demo_faults.pop(task_id, None)
            self.store.save_session(session)
            return session
