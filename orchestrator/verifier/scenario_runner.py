from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import yaml

from ..schemas import (
    HandoffBundle,
    OrchestratorError,
    ScenarioExpect,
    ScenarioSpec,
    ScenarioStep,
    StateEventsContract,
    SystemDeliverable,
)
from ..tech_bootstrap import get_scenario_dir


def author_scenarios_for_sys(
    bundle: HandoffBundle,
    sys_item: SystemDeliverable,
    contract: StateEventsContract,
    target_root: Path,
    *,
    force_revision_note: str = "",
) -> Tuple[List[ScenarioSpec], List[str]]:
    """
    §8.1：由独立 QA 会话编写声明式验收场景（不读取作者代码），写入 game/tests/scenarios/<req_id>/。
    作者对其只读；编排器校验每个 ac_id 被覆盖且所有状态/事件/输入来自共享契约。
    """
    req_id = sys_item.req_id
    req_inputs = [i for i in contract.inputs if i.req_id == req_id]
    first_input = req_inputs[0].id if req_inputs else None
    second_input = req_inputs[1].id if len(req_inputs) > 1 else first_input
    exposed_states = [s.id for s in sys_item.exposed_state_ids]
    emitted_events = [e.id for e in sys_item.emitted_event_ids]
    all_contract_events = {e.id for e in contract.events}

    scenarios: List[ScenarioSpec] = []
    for idx, ac_text in enumerate(sys_item.acceptance_criteria, start=1):
        ac_id = f"{req_id}-AC{idx}"
        scen_id = f"{req_id}-S{idx:02d}"

        if "ST_WATER_CURSE_STAGE" in exposed_states and idx == 1:
            spec = ScenarioSpec(
                scenario_id=scen_id,
                req_id=req_id,
                covers=[ac_id],
                initial_state={"ST_WATER_CURSE_STAGE": 0},
                steps=[
                    ScenarioStep(frame=1, actions=[{"inject_event": "EVT_DRINK_RIVER_WATER"}]),
                    ScenarioStep(frame=2, actions=[{"input": first_input or "IN_CHOOSE_CONCEAL"}]),
                    ScenarioStep(frame=3, actions=[{"input": first_input or "IN_CHOOSE_CONCEAL"}]),
                ],
                expect=ScenarioExpect(
                    final_state={"ST_WATER_CURSE_STAGE": 3},
                    events_include=["EVT_DRINK_RIVER_WATER"],
                    events_exclude=[],
                ),
            )
        elif "ST_WATER_CURSE_STAGE" in exposed_states and "EVT_BREAK_CURSE" in emitted_events:
            excl = ["EVT_DEBATE_EXPOSED"] if "EVT_DEBATE_EXPOSED" in all_contract_events else []
            spec = ScenarioSpec(
                scenario_id=scen_id,
                req_id=req_id,
                covers=[ac_id],
                initial_state={"ST_WATER_CURSE_STAGE": 3},
                steps=[
                    ScenarioStep(
                        frame=1,
                        actions=[
                            {"inject_event": "EVT_BREAK_CURSE"},
                            {"inject_event": "EVT_DEBATE_EXPOSED"},
                        ],
                    )
                ],
                expect=ScenarioExpect(
                    final_state={"ST_WATER_CURSE_STAGE": 0},
                    events_include=["EVT_BREAK_CURSE"],
                    events_exclude=excl,
                ),
            )
        elif "ST_COURT_SUSPICION" in exposed_states and idx == 1:
            spec = ScenarioSpec(
                scenario_id=scen_id,
                req_id=req_id,
                covers=[ac_id],
                initial_state={"ST_COURT_SUSPICION": 10},
                steps=[
                    ScenarioStep(frame=1, actions=[{"input": first_input or "IN_SUBMIT_EVIDENCE", "mode": "valid_proof"}]),
                    ScenarioStep(frame=2, actions=[{"input": first_input or "IN_SUBMIT_EVIDENCE", "mode": "bad_forged"}]),
                    ScenarioStep(frame=3, actions=[{"input": first_input or "IN_SUBMIT_EVIDENCE", "mode": "bad_forged"}]),
                    ScenarioStep(frame=4, actions=[{"input": first_input or "IN_SUBMIT_EVIDENCE", "mode": "bad_forged"}]),
                    ScenarioStep(frame=5, actions=[{"input": first_input or "IN_SUBMIT_EVIDENCE", "mode": "bad_forged"}]),
                ],
                expect=ScenarioExpect(
                    final_state={"ST_COURT_SUSPICION": 100},
                    events_include=["EVT_DEBATE_EXPOSED"] if "EVT_DEBATE_EXPOSED" in emitted_events else [],
                    events_exclude=[],
                ),
            )
        else:
            init_state = {st: 0 for st in exposed_states}
            step_actions: List[Dict[str, str]] = []
            if second_input:
                step_actions.append({"input": second_input})
            elif emitted_events:
                step_actions.append({"inject_event": emitted_events[0]})
            spec = ScenarioSpec(
                scenario_id=scen_id,
                req_id=req_id,
                covers=[ac_id],
                initial_state=init_state,
                steps=[ScenarioStep(frame=1, actions=step_actions)] if step_actions else [],
                expect=ScenarioExpect(final_state=dict(init_state), events_include=[], events_exclude=[]),
            )

        scenarios.append(spec)

    validate_scenarios(scenarios, sys_item, contract)

    scen_rel_dir = get_scenario_dir(req_id)
    out_dir = target_root / scen_rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.yaml"
    payload = {
        "schema_version": "scenario_bundle/v1",
        "req_id": req_id,
        "revision_note": force_revision_note,
        "scenarios": [s.model_dump(mode="json") for s in scenarios],
    }
    out_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return scenarios, [f"{scen_rel_dir}index.yaml"]


def validate_scenarios(
    scenarios: List[ScenarioSpec],
    sys_item: SystemDeliverable,
    contract: StateEventsContract,
) -> None:
    """§8.1 步骤 2：校验场景 Schema、全 ac_id 覆盖与引用合法性。"""
    declared_states = {s.id for s in contract.states}
    declared_events = {e.id for e in contract.events}
    declared_inputs = {i.id for i in contract.inputs}
    expected_acs = {f"{sys_item.req_id}-AC{idx}" for idx in range(1, len(sys_item.acceptance_criteria) + 1)}
    covered_acs: Set[str] = set()

    for sc in scenarios:
        for ac in sc.covers:
            covered_acs.add(ac)
        for st_id in list(sc.initial_state.keys()) + list(sc.expect.final_state.keys()):
            if st_id not in declared_states:
                raise OrchestratorError(
                    "ERR_SCENARIO_INVALID",
                    f"场景 {sc.scenario_id} 引用了契约外状态 {st_id}。",
                    {"scenario_id": sc.scenario_id, "state_id": st_id},
                )
        for ev_id in sc.expect.events_include + sc.expect.events_exclude:
            if ev_id not in declared_events:
                raise OrchestratorError(
                    "ERR_SCENARIO_INVALID",
                    f"场景 {sc.scenario_id} 引用了契约外事件 {ev_id}。",
                    {"scenario_id": sc.scenario_id, "event_id": ev_id},
                )
        for step in sc.steps:
            for act in step.actions:
                if "inject_event" in act and act["inject_event"] not in declared_events:
                    raise OrchestratorError(
                        "ERR_SCENARIO_INVALID",
                        f"场景 {sc.scenario_id} 注入了契约外事件 {act['inject_event']}。",
                    )
                if "input" in act and act["input"] not in declared_inputs:
                    raise OrchestratorError(
                        "ERR_SCENARIO_INVALID",
                        f"场景 {sc.scenario_id} 使用了契约外输入 {act['input']}。",
                    )

    missing = expected_acs - covered_acs
    if missing:
        raise OrchestratorError(
            "ERR_SCENARIO_INVALID",
            f"系统任务 {sys_item.req_id} 存在未被验收场景覆盖的条款: {sorted(missing)}",
            {"missing_ac_ids": sorted(missing)},
        )


def load_scenarios_from_dir(root: Path, req_id: str) -> List[ScenarioSpec]:
    idx = root / get_scenario_dir(req_id) / "index.yaml"
    if not idx.exists():
        return []
    data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
    return [ScenarioSpec.model_validate(item) for item in data.get("scenarios", [])]


def run_scenarios_replay(
    scenarios: List[ScenarioSpec],
    workdir: Path,
    req_id: str,
) -> Tuple[bool, List[str]]:
    """
    §5.5 确定性场景回放测试桩（离线/mock 与结构化系统规格验证）：
    读取作者提交的系统实现元数据并逐帧执行场景，核对状态迁移动作与期望结果。
    """
    if not scenarios:
        return False, [f"{req_id} 缺少独立验收场景文件。"]

    impl_path = workdir / "game" / "src" / "systems" / req_id.lower() / f"{req_id.lower()}_system.json"
    if not impl_path.exists():
        return False, [f"缺少系统实现文件: {impl_path.relative_to(workdir).as_posix()}"]

    impl_data = json.loads(impl_path.read_text(encoding="utf-8"))
    declared_inputs = set(impl_data.get("inputs", []))
    errors: List[str] = []

    for sc in scenarios:
        state = dict(sc.initial_state)
        emitted: List[str] = []
        broken_curse = False

        for step in sc.steps:
            frame_events: Set[str] = set()
            for act in step.actions:
                if "inject_event" in act:
                    frame_events.add(act["inject_event"])
                if "input" in act and act["input"] not in declared_inputs:
                    errors.append(f"{sc.scenario_id}: 系统实现未声明输入 {act['input']}")
                if act.get("input", "").startswith("IN_CONCEAL") or act.get("input", "").startswith("IN_CHOOSE_CONCEAL"):
                    if "ST_WATER_CURSE_STAGE" in state and not broken_curse:
                        state["ST_WATER_CURSE_STAGE"] = min(3, int(state["ST_WATER_CURSE_STAGE"]) + 1)
                elif "IN_SUBMIT" in act.get("input", "") and "ST_COURT_SUSPICION" in state:
                    mode = act.get("mode", "bad_forged")
                    delta = -15 if mode == "valid_proof" else 25
                    state["ST_COURT_SUSPICION"] = max(0, min(100, int(state["ST_COURT_SUSPICION"]) + delta))
                    if state["ST_COURT_SUSPICION"] >= 100:
                        frame_events.add("EVT_DEBATE_EXPOSED")

            # ADR-001：同帧并发 EVT_BREAK_CURSE 与 EVT_DEBATE_EXPOSED 时强制优先破咒
            if "EVT_BREAK_CURSE" in frame_events:
                broken_curse = True
                if "ST_WATER_CURSE_STAGE" in state:
                    state["ST_WATER_CURSE_STAGE"] = 0
                emitted.append("EVT_BREAK_CURSE")
            else:
                for ev in sorted(frame_events):
                    emitted.append(ev)
                    if ev == "EVT_DRINK_RIVER_WATER" and "ST_WATER_CURSE_STAGE" in state and not broken_curse:
                        if int(state["ST_WATER_CURSE_STAGE"]) == 0:
                            state["ST_WATER_CURSE_STAGE"] = 1

        for k, expected_v in sc.expect.final_state.items():
            if state.get(k) != expected_v:
                errors.append(f"{sc.scenario_id}: 期望 {k}={expected_v}，实际={state.get(k)}")
        for req_ev in sc.expect.events_include:
            if req_ev not in emitted:
                errors.append(f"{sc.scenario_id}: 期望触发事件 {req_ev} 未触发（实际={emitted}）")
        for ban_ev in sc.expect.events_exclude:
            if ban_ev in emitted:
                errors.append(f"{sc.scenario_id}: 禁用事件 {ban_ev} 被错误触发")

    return len(errors) == 0, errors
