from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schemas import HandoffBundle, SessionState, TaskKind, TaskRecord, TaskStatus


def build_acceptance_criteria(req_id: str, criteria_texts: List[str]) -> List[Dict[str, str]]:
    return [{"ac_id": f"{req_id}-AC{idx}", "text": txt} for idx, txt in enumerate(criteria_texts, start=1)]


def pack_task_context(
    session: SessionState,
    bundle: HandoffBundle,
    task: TaskRecord,
    *,
    scenario_payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    §7.6 最小闭环上下文打包：
    只携带本任务所需的需求原文、工种上栏、关联契约、命中 Canon/ADR、前置摘要与独占路径；
    绝对不包含 memory/ideas_backlog.md 与全量无关会话历史。
    """
    gdd_mod = next((m for m in bundle.gdd_index.modules if m.gdd_id == task.gdd_ref), None)
    contract = session.state_events
    schemas = session.asset_schemas.schemas if session.asset_schemas else {}

    requirement_obj: Dict[str, Any] = {}
    discipline_gc: Dict[str, Any] = {}
    acceptance_list: List[Dict[str, str]] = []
    relevant_state_ids: set[str] = set()
    relevant_event_ids: set[str] = set()
    canon_refs: List[str] = []
    asset_schema: Dict[str, Any] = {}
    ref_images: List[str] = []
    understanding_echo: Optional[Dict[str, Any]] = None
    system_interaction_rules: List[Dict[str, Any]] = []

    if task.kind == TaskKind.TECH:
        discipline_gc = bundle.system_requirements.global_constraints
        if bundle.system_requirements.understanding_echo is not None:
            understanding_echo = bundle.system_requirements.understanding_echo.model_dump(mode="json")
        system_interaction_rules = [
            r.model_dump(mode="json") for r in bundle.system_requirements.system_interaction_matrix
        ]
        requirement_obj = {
            "task_id": task.task_id,
            "scope_tier": bundle.manifest.scope_tier,
            "lead_pillars": bundle.manifest.lead_pillars,
            "system_inputs": [
                {"req_id": d.req_id, "inputs": d.inputs}
                for d in bundle.system_requirements.stage_deliverables
            ],
        }
        acceptance_list = [
            {"ac_id": "TECH-001-AC1", "text": "生成共享状态/事件契约、数据格式契约、工程骨架与回放测试桩。"}
        ]
        if contract:
            relevant_state_ids = {s.id for s in contract.states}
            relevant_event_ids = {e.id for e in contract.events}
    elif task.kind == TaskKind.SYS and task.req_id:
        item = next(d for d in bundle.system_requirements.stage_deliverables if d.req_id == task.req_id)
        requirement_obj = item.model_dump(mode="json")
        discipline_gc = bundle.system_requirements.global_constraints
        if bundle.system_requirements.understanding_echo is not None:
            understanding_echo = bundle.system_requirements.understanding_echo.model_dump(mode="json")
        system_interaction_rules = [
            r.model_dump(mode="json")
            for r in bundle.system_requirements.system_interaction_matrix
            if not r.pair or task.req_id in r.pair
        ]
        acceptance_list = build_acceptance_criteria(item.req_id, item.acceptance_criteria)
        relevant_state_ids = {s.id for s in item.exposed_state_ids}
        relevant_event_ids = {e.id for e in item.emitted_event_ids}
        if contract:
            for s in contract.states:
                if item.req_id in s.referenced_by:
                    relevant_state_ids.add(s.id)
            for e in contract.events:
                if item.req_id in e.referenced_by:
                    relevant_event_ids.add(e.id)
    elif task.kind == TaskKind.NAR and task.req_id:
        item = next(d for d in bundle.narrative_requirements.stage_deliverables if d.req_id == task.req_id)
        requirement_obj = item.model_dump(mode="json")
        discipline_gc = bundle.narrative_requirements.global_constraints
        if bundle.narrative_requirements.understanding_echo is not None:
            understanding_echo = bundle.narrative_requirements.understanding_echo.model_dump(mode="json")
        acceptance_list = build_acceptance_criteria(item.req_id, item.acceptance_criteria)
        relevant_state_ids = set(item.linked_state_ids)
        relevant_event_ids = set(item.trigger_event_ids)
        canon_refs = list(item.canon_refs)
        asset_schema = schemas.get("narrative_line", {})
    elif task.kind == TaskKind.ART and task.req_id:
        item = next(d for d in bundle.art_requirements.stage_deliverables if d.req_id == task.req_id)
        requirement_obj = item.model_dump(mode="json")
        discipline_gc = bundle.art_requirements.global_constraints
        if bundle.art_requirements.understanding_echo is not None:
            understanding_echo = bundle.art_requirements.understanding_echo.model_dump(mode="json")
        acceptance_list = build_acceptance_criteria(item.req_id, item.acceptance_criteria)
        relevant_state_ids = set(item.linked_state_ids)
        relevant_event_ids = set(item.trigger_event_ids)
        asset_schema = schemas.get("art_asset", {})
        ref_images = list(bundle.reference_images)
    elif task.kind == TaskKind.AUD and task.req_id:
        item = next(d for d in bundle.audio_requirements.stage_deliverables if d.req_id == task.req_id)
        requirement_obj = item.model_dump(mode="json")
        discipline_gc = bundle.audio_requirements.global_constraints
        if bundle.audio_requirements.understanding_echo is not None:
            understanding_echo = bundle.audio_requirements.understanding_echo.model_dump(mode="json")
        acceptance_list = build_acceptance_criteria(item.req_id, item.acceptance_criteria)
        relevant_state_ids = set(item.linked_state_ids)
        relevant_event_ids = set(item.trigger_event_ids)
        asset_schema = schemas.get("audio_asset", {})
    elif task.kind == TaskKind.INTEG and task.gdd_ref:
        discipline_gc = bundle.system_requirements.global_constraints
        system_interaction_rules = [
            r.model_dump(mode="json")
            for r in bundle.system_requirements.system_interaction_matrix
            if not r.pair or any(dep in r.pair for dep in task.depends_on)
        ]
        child_items = []
        for dep_id in task.depends_on:
            dep_task = session.tasks.get(dep_id)
            if dep_task:
                child_items.append(
                    {
                        "task_id": dep_id,
                        "kind": dep_task.kind.value,
                        "state": dep_task.state.value,
                        "artifacts": [a.model_dump(mode="json") for a in dep_task.artifacts],
                    }
                )
        requirement_obj = {
            "gdd_module": gdd_mod.model_dump(mode="json") if gdd_mod else {},
            "child_deliverables": child_items,
        }
        acceptance_list = [
            {
                "ac_id": f"{task.task_id}-AC1",
                "text": f"完成模块 {task.gdd_ref} 下全部系统与表现资源的集成绑定并复跑场景通过。",
            }
        ]
        if contract:
            for s in contract.states:
                if any(dep_id in s.referenced_by for dep_id in task.depends_on):
                    relevant_state_ids.add(s.id)
            for e in contract.events:
                if any(dep_id in e.referenced_by for dep_id in task.depends_on):
                    relevant_event_ids.add(e.id)
    elif task.kind == TaskKind.QA_FINAL:
        discipline_gc = bundle.system_requirements.global_constraints
        requirement_obj = {
            "non_functional_targets": discipline_gc.get("non_functional_targets", {}),
            "waived_tasks": session.cpm.waived_tasks,
            "modules": [m.model_dump(mode="json") for m in bundle.gdd_index.modules],
        }
        acceptance_list = [
            {"ac_id": "QA-FINAL-AC1", "text": "全量单元测试与验收场景全部通过，非功能指标及 Canon 无违背。"}
        ]
        if contract:
            relevant_state_ids = {s.id for s in contract.states}
            relevant_event_ids = {e.id for e in contract.events}

    # 筛选状态、事件与输入动作契约
    se_payload: Dict[str, Any] = {"states": [], "events": [], "inputs": []}
    if contract:
        se_payload["states"] = [
            s.model_dump(mode="json") for s in contract.states if s.id in relevant_state_ids
        ]
        se_payload["events"] = [
            e.model_dump(mode="json") for e in contract.events if e.id in relevant_event_ids
        ]
        if task.kind in (TaskKind.TECH, TaskKind.SYS, TaskKind.INTEG, TaskKind.QA_FINAL):
            target_reqs = (
                {task.req_id}
                if task.kind == TaskKind.SYS
                else set(task.depends_on)
                if task.kind == TaskKind.INTEG
                else {i.req_id for i in contract.inputs}
            )
            se_payload["inputs"] = [
                i.model_dump(mode="json") for i in contract.inputs if i.req_id in target_reqs
            ]

    # Canon 仅取 canon_refs 命中的条目（QA_FINAL 除外，用于全量防吃书）
    if task.kind == TaskKind.QA_FINAL:
        canon_entries = [c.model_dump(mode="json") for c in bundle.canon_registry.entries]
    else:
        canon_entries = [
            c.model_dump(mode="json") for c in bundle.canon_registry.entries if c.canon_id in canon_refs
        ]

    # ADR 仅取 impacted_refs 命中本任务 req_id 或 linked_gdd_ref 的条目
    adr_targets = {x for x in (task.req_id, task.gdd_ref) if x}
    if task.kind == TaskKind.QA_FINAL:
        adr_entries = [a.model_dump(mode="json") for a in bundle.adr_records]
    else:
        adr_entries = [
            a.model_dump(mode="json")
            for a in bundle.adr_records
            if any(ref in adr_targets for ref in a.impacted_refs)
        ]

    # C-1 同 reuse_group 已完成产物的参考引用
    reuse_refs: List[Dict[str, Any]] = []
    if task.reuse_group:
        for other in sorted(session.tasks.values(), key=lambda x: x.task_id):
            if (
                other.task_id != task.task_id
                and other.reuse_group == task.reuse_group
                and other.state == TaskStatus.SUCCEEDED
            ):
                reuse_refs.append(
                    {
                        "task_id": other.task_id,
                        "reuse_group": other.reuse_group,
                        "artifacts": [a.model_dump(mode="json") for a in other.artifacts],
                    }
                )

    upstream_artifacts: List[Dict[str, Any]] = []
    tech_task = session.tasks.get("TECH-001")
    if task.kind != TaskKind.TECH and tech_task and tech_task.artifacts:
        upstream_artifacts.append(
            {
                "task_id": "TECH-001",
                "files": [a.path for a in tech_task.artifacts[:10]],
            }
        )

    previous_failures = [
        {"attempt": h.attempt, "result": h.result, "report": h.report_path, "summary": h.summary}
        for h in task.history
        if h.result in ("FAILED", "REJECTED")
    ]

    payload = {
        "task_id": task.task_id,
        "kind": task.kind.value,
        "spec_version": session.spec_version,
        "attempt": task.next_attempt_seq,
        "attempt_epoch": task.attempt_epoch,
        "role": task.role,
        "requirement": requirement_obj,
        "discipline_global_constraints": discipline_gc,
        "gdd_module": gdd_mod.model_dump(mode="json") if gdd_mod else None,
        "state_event_contract": se_payload,
        "asset_schema": asset_schema,
        "canon_entries": canon_entries,
        "adr_entries": adr_entries,
        "reference_images": ref_images,
        "reuse_references": reuse_refs,
        "upstream_artifacts": upstream_artifacts,
        "scenarios_readonly": scenario_payloads or [],
        "tech_profile_excerpt": session.tech_profile.model_dump(mode="json"),
        "writable_paths": list(task.writable_paths),
        "acceptance_criteria": acceptance_list,
        "previous_failures": previous_failures,
        "guidance_notes": list(task.guidance_notes),
        "runtime_limits": {
            "per_attempt_call_cap": session.budget.per_attempt_call_cap,
            "budget_remaining_calls": max(0, session.budget.calls_cap - session.budget.calls_used),
        },
        "injected_faults": list(session.demo_faults.get(task.task_id, [])),
    }
    if understanding_echo is not None:
        payload["understanding_echo"] = understanding_echo
    if system_interaction_rules:
        payload["system_interaction_matrix"] = system_interaction_rules
    return payload
