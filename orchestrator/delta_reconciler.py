from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Set, Tuple

from .cpm import compute_cpm
from .dag_builder import build_task_graph
from .estimator import apply_estimates
from .handoff_loader import stable_json_sha256
from .project_fsm import transition_project_state
from .schemas import (
    DeltaReport,
    HandoffBundle,
    OrchestratorError,
    ProjectState,
    SessionState,
    TaskKind,
    TaskRecord,
    TaskStatus,
    TombstoneRecord,
)
from .state_store import StateStore, utc_now_iso
from .tech_bootstrap import build_state_events_contract, get_task_writable_paths
from .workspace_manager import WorkspaceManager


def _collect_downstream_closure(seeds: Set[str], edges: List[List[str]]) -> Set[str]:
    adj: Dict[str, List[str]] = {}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)
    closure: Set[str] = set(seeds)
    q = deque(sorted(seeds))
    while q:
        curr = q.popleft()
        for nxt in adj.get(curr, []):
            if nxt not in closure:
                closure.add(nxt)
                q.append(nxt)
    return closure


def _task_referenced_contract_ids(bundle: HandoffBundle, req_id: str) -> Set[str]:
    ids: Set[str] = set()
    for s in bundle.system_requirements.stage_deliverables:
        if s.req_id == req_id:
            ids.update(st.id for st in s.exposed_state_ids)
            ids.update(ev.id for ev in s.emitted_event_ids)
            return ids
    for group in (
        bundle.narrative_requirements.stage_deliverables,
        bundle.art_requirements.stage_deliverables,
        bundle.audio_requirements.stage_deliverables,
    ):
        for item in group:
            if item.req_id == req_id:
                ids.update(item.linked_state_ids)
                ids.update(item.trigger_event_ids)
                return ids
    return ids


def reconcile_delta_upgrade(
    session: SessionState,
    old_bundle: HandoffBundle,
    new_bundle: HandoffBundle,
    *,
    config: Dict[str, Any],
    store: StateStore,
    workspace_mgr: WorkspaceManager,
    aux_warnings: List[str],
) -> Tuple[DeltaReport, List[str]]:
    """
    §9.2 增量热重排核心算法（步骤 0 ~ 9）：
    - 先排空在途 RUNNING / WAITING_VERIFY 任务（取消不计失败，清理 attempts/）；
    - 独立校验共享契约变化、上栏约束哈希变化、ADR 与 Canon 变化；
    - 仅重跑脏节点传递闭包，未在脏集合内且已 SUCCEEDED 的产物 100% 原样保留哈希。
    """
    diff = new_bundle.diff_summary
    if diff is None:
        raise OrchestratorError("ERR_VERSION_CHAIN_BROKEN", "升版交接包缺少 diff_summary.yaml。")
    if diff.from_version != session.spec_version or diff.to_version != new_bundle.manifest.spec_version:
        raise OrchestratorError(
            "ERR_VERSION_CHAIN_BROKEN",
            "diff_summary.yaml 版本号与当前运行态不匹配。",
            {"session": session.spec_version, "from": diff.from_version, "to": diff.to_version},
        )

    # 步骤 0：项目切入 APPLYING_DELTA，排空全部在途任务
    session.project_state = transition_project_state(session.project_state, ProjectState.APPLYING_DELTA)
    store.append_event(
        session,
        "PROJECT_STATE_CHANGED",
        payload={"project_state": ProjectState.APPLYING_DELTA.value, "reason": "delta_upgrade"},
    )
    canceled_ids: List[str] = []
    for t in session.tasks.values():
        if t.state in (TaskStatus.RUNNING, TaskStatus.WAITING_VERIFY):
            t.state = TaskStatus.READY
            canceled_ids.append(t.task_id)
            store.append_event(
                session,
                "ATTEMPT_CANCELED",
                task_id=t.task_id,
                payload={"reason": "delta_drain", "attempts_failed_unchanged": t.attempts_failed},
            )
    workspace_mgr.cleanup_all_attempts(session.project_id)

    # 步骤 2：重算共享状态/事件/输入契约并检测变更 ID
    old_se = session.state_events
    new_se, new_or_changed_inputs = build_state_events_contract(new_bundle, old_se)
    changed_contract_ids: Set[str] = set()
    if old_se is not None:
        old_states = {s.id: s.model_dump() for s in old_se.states}
        new_states = {s.id: s.model_dump() for s in new_se.states}
        old_events = {e.id: e.model_dump() for e in old_se.events}
        new_events = {e.id: e.model_dump() for e in new_se.events}
        old_inputs = {i.id: i.model_dump() for i in old_se.inputs}
        new_inputs = {i.id: i.model_dump() for i in new_se.inputs}
        for k in set(old_states) | set(new_states):
            if old_states.get(k) != new_states.get(k):
                changed_contract_ids.add(k)
        for k in set(old_events) | set(new_events):
            if old_events.get(k) != new_events.get(k):
                changed_contract_ids.add(k)
        for k in set(old_inputs) | set(new_inputs):
            if old_inputs.get(k) != new_inputs.get(k):
                changed_contract_ids.add(k)

    # 步骤 3：确定性建出新版 TaskGraph 并估算工期
    new_graph = build_task_graph(new_bundle)
    apply_estimates(new_graph.tasks, config)
    new_task_map: Dict[str, TaskRecord] = {t.task_id: t for t in new_graph.tasks}

    # 步骤 4：计算独立种子脏集合 seeds
    warnings: List[str] = list(aux_warnings)
    seeds: Set[str] = set()
    for mod in diff.changes.modified_ids:
        seeds.add(mod.req_id)
    for add_id in diff.changes.added_ids:
        seeds.add(add_id)

    if changed_contract_ids or new_or_changed_inputs:
        seeds.add("TECH-001")
        for tid in new_task_map:
            if _task_referenced_contract_ids(new_bundle, tid) & changed_contract_ids:
                seeds.add(tid)
        if old_se:
            for inp in old_se.inputs:
                if inp.id in changed_contract_ids:
                    seeds.add(inp.req_id)
        for inp in new_se.inputs:
            if inp.id in new_or_changed_inputs:
                seeds.add(inp.req_id)

    # 逐工种比较上栏 global_constraints 哈希
    disc_to_kind = {
        "system": TaskKind.SYS,
        "narrative": TaskKind.NAR,
        "art": TaskKind.ART,
        "audio": TaskKind.AUD,
    }
    any_gc_changed = False
    for disc, new_hash in new_bundle.global_constraints_hashes.items():
        old_hash = session.global_constraints_hashes.get(disc)
        if old_hash is not None and old_hash != new_hash:
            any_gc_changed = True
            target_kind = disc_to_kind[disc]
            for tid, task_obj in new_task_map.items():
                if task_obj.kind == target_kind:
                    seeds.add(tid)

    if any_gc_changed != diff.global_constraints_changed:
        msg = (
            f"CONSISTENCY_WARNING: diff_summary.global_constraints_changed={diff.global_constraints_changed}，"
            f"但实际逐工种上栏哈希比对结果为 {any_gc_changed}，以编排器核对结果为准。"
        )
        warnings.append(msg)
        store.append_event(session, "CONSISTENCY_WARNING", payload={"message": msg})

    # 检测新增或内容变化的 ADR (O15)
    new_adr_hashes = {a.adr_id: stable_json_sha256(a.model_dump(mode="json")) for a in new_bundle.adr_records}
    for adr in new_bundle.adr_records:
        old_h = session.adr_hashes.get(adr.adr_id)
        if old_h is None or old_h != new_adr_hashes[adr.adr_id]:
            for ref in adr.impacted_refs:
                if ref in new_task_map:
                    seeds.add(ref)
                for tid, t_obj in new_task_map.items():
                    if t_obj.gdd_ref == ref and t_obj.kind in (
                        TaskKind.SYS,
                        TaskKind.NAR,
                        TaskKind.ART,
                        TaskKind.AUD,
                        TaskKind.INTEG,
                    ):
                        seeds.add(tid)

    # 检测内容变化的 Canon
    new_canon_hashes = {
        c.canon_id: stable_json_sha256(c.model_dump(mode="json")) for c in new_bundle.canon_registry.entries
    }
    changed_canons = {cid for cid, h in new_canon_hashes.items() if session.canon_hashes.get(cid) != h}
    if changed_canons:
        for nar_item in new_bundle.narrative_requirements.stage_deliverables:
            if set(nar_item.canon_refs) & changed_canons:
                seeds.add(nar_item.req_id)

    # 步骤 7（部分前置计算）：废弃需求的归档与其所属 INTEG 节点加入 seeds
    existing_tombstones = {tb.req_id for tb in session.tombstones}
    for dep_id in diff.changes.deprecated_ids:
        old_task = session.tasks.get(dep_id)
        if old_task and old_task.gdd_ref:
            integ_id = f"INTEG-{old_task.gdd_ref}"
            if integ_id in new_task_map:
                seeds.add(integ_id)
        if dep_id not in existing_tombstones:
            wpaths = (
                old_task.writable_paths
                if old_task
                else get_task_writable_paths(TaskKind.SYS, req_id=dep_id)
            )
            arch_dir, dep_commit = workspace_mgr.archive_deprecated_task(
                session, dep_id, wpaths, diff.to_version
            )
            session.tombstones.append(
                TombstoneRecord(
                    req_id=dep_id,
                    deprecated_in=diff.to_version,
                    archived_dir=arch_dir,
                    recorded_at=utc_now_iso(),
                )
            )
            if dep_commit:
                session.git_commits.append(dep_commit)

    # 只保留新图中存在的种子节点
    valid_seeds = {s for s in seeds if s in new_task_map}

    # 步骤 5：下游传递闭包
    dirty = _collect_downstream_closure(valid_seeds, new_graph.edges)

    # 步骤 8：检查 unchanged_ids 是否被独立判定入脏
    unchanged_set = set(diff.changes.unchanged_ids)
    for uid in sorted(unchanged_set & dirty):
        msg = f"CONSISTENCY_WARNING: {uid} 在 diff_summary 中标为 unchanged，但受约束/契约/ADR 影响被编排器判定重跑。"
        warnings.append(msg)
        store.append_event(session, "CONSISTENCY_WARNING", task_id=uid, payload={"message": msg})

    # 步骤 6：逐节点状态与产物对账
    reused_ids: List[str] = []
    dirty_ids: List[str] = []
    added_ids: List[str] = []
    saved_hours = 0.0

    for tid, new_t in new_task_map.items():
        old_t = session.tasks.get(tid)
        if old_t is None:
            new_t.state = TaskStatus.PENDING
            new_t.delta_tag = "NEW"
            added_ids.append(tid)
            continue

        if tid in dirty:
            new_t.state = TaskStatus.PENDING
            new_t.attempts_failed = 0
            new_t.delay_hours = 0.0
            new_t.attempt_epoch = old_t.attempt_epoch + 1
            new_t.next_attempt_seq = old_t.next_attempt_seq
            new_t.history = list(old_t.history)
            new_t.delta_tag = "DIRTY_RERUN"
            dirty_ids.append(tid)
        elif old_t.state == TaskStatus.SUCCEEDED:
            # 100% 原样继承产物与哈希
            new_t.state = TaskStatus.SUCCEEDED
            new_t.artifacts = list(old_t.artifacts)
            new_t.produced_in_version = old_t.produced_in_version or session.spec_version
            new_t.last_commit = old_t.last_commit
            new_t.actual_runtime_sec = old_t.actual_runtime_sec
            new_t.history = list(old_t.history)
            new_t.attempts_failed = old_t.attempts_failed
            new_t.attempt_epoch = old_t.attempt_epoch
            new_t.next_attempt_seq = old_t.next_attempt_seq
            new_t.scenario_paths = list(old_t.scenario_paths)
            new_t.delta_tag = "REUSED"
            reused_ids.append(tid)
            saved_hours = round(saved_hours + new_t.estimate_hours, 2)
        elif old_t.state == TaskStatus.SKIPPED:
            new_t.state = TaskStatus.SKIPPED
            new_t.skip = old_t.skip.model_copy()
            new_t.history = list(old_t.history)
            new_t.delta_tag = "RETAINED"
        elif old_t.state == TaskStatus.BLOCKED:
            new_t.state = TaskStatus.BLOCKED
            new_t.history = list(old_t.history)
            new_t.delta_tag = "RETAINED"
            if tid in unchanged_set:
                msg = f"任务 {tid} 原因变更单阻塞但新版本未修改该条目。"
                warnings.append(msg)
                store.append_event(session, "CONSISTENCY_WARNING", task_id=tid, payload={"message": msg})
        else:
            new_t.state = old_t.state
            new_t.decision_kind = old_t.decision_kind
            new_t.attempts_failed = old_t.attempts_failed
            new_t.attempt_epoch = old_t.attempt_epoch
            new_t.next_attempt_seq = old_t.next_attempt_seq
            new_t.delay_hours = old_t.delay_hours
            new_t.guidance_notes = list(old_t.guidance_notes)
            new_t.history = list(old_t.history)
            new_t.delta_tag = "RETAINED"

    # 更新会话元数据到新版本
    session.parent_version = session.spec_version
    session.spec_version = new_bundle.manifest.spec_version
    session.canonical_sha256 = new_bundle.manifest.canonical_sha256
    session.scope_tier = new_bundle.manifest.scope_tier
    session.lead_pillars = list(new_bundle.manifest.lead_pillars)
    session.derived_pillars = list(new_bundle.manifest.derived_pillars)
    session.handoff_dir = new_bundle.source_dir
    session.state_events = new_se
    session.contract_sha256["state_events"] = new_se.contract_sha256
    session.tasks = new_task_map
    session.edges = new_graph.edges
    session.global_constraints_hashes = dict(new_bundle.global_constraints_hashes)
    session.canon_hashes = new_canon_hashes
    session.adr_hashes = new_adr_hashes
    session.warnings.extend(warnings)

    workspace_mgr.write_contracts_to_main(session)
    workspace_mgr.regenerate_shared_generated_files(session)

    # 重算 CPM
    concurrency = config.get("concurrency", {})
    session.cpm = compute_cpm(
        list(session.tasks.values()),
        session.lead_pillars,
        concurrency=concurrency,
    )

    report = DeltaReport(
        from_version=diff.from_version,
        to_version=diff.to_version,
        delta_tier=diff.delta_tier,
        reused_ids=sorted(reused_ids),
        dirty_ids=sorted(dirty_ids),
        added_ids=sorted(added_ids),
        deprecated_ids=list(diff.changes.deprecated_ids),
        warnings=warnings,
        saved_estimate_hours=saved_hours,
        applied_at=utc_now_iso(),
    )
    session.delta_history.append(report)

    store.append_event(
        session,
        "DELTA_APPLIED",
        payload=report.model_dump(mode="json"),
    )

    # 步骤 9：Tier C 回到 AWAITING_TECH_CONFIRM 过 G1，否则直接回到 RUNNING
    next_proj_state = (
        ProjectState.AWAITING_TECH_CONFIRM if diff.delta_tier == "TIER_C_CORE_PIVOT" else ProjectState.RUNNING
    )
    session.project_state = transition_project_state(session.project_state, next_proj_state)
    store.append_event(
        session,
        "PROJECT_STATE_CHANGED",
        payload={"project_state": session.project_state.value, "delta_tier": diff.delta_tier},
    )
    store.save_session(session)
    return report, canceled_ids
