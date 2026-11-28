from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Set, Tuple

from .handoff_loader import stable_json_sha256
from .schemas import (
    AssetSchemasContract,
    EventContractItem,
    HandoffBundle,
    InputActionDef,
    OrchestratorError,
    StateContractItem,
    StateEventsContract,
    TaskKind,
    TechProfile,
)

STATE_OR_EVENT_RE = re.compile(r"\b(?:ST|EVT)_[A-Z0-9_]+\b")

KNOWN_INPUT_TOKENS = {
    "隐瞒": "CONCEAL",
    "伪装": "DISGUISE",
    "落胎泉": "SPRING_SAMPLE",
    "试样": "SAMPLE",
    "证物": "SUBMIT_EVIDENCE",
    "呈递": "SUBMIT",
    "昼夜": "ADVANCE_PHASE",
    "切换": "SWITCH_PHASE",
    "跳过": "SKIP",
    "重开": "RESTART",
}


def propose_tech_profile(bundle: HandoffBundle) -> TechProfile:
    """§5.1 B-1：结合 scope_tier 与系统表上栏约束生成技术档案提案（待 G1 确认）。"""
    nfr = bundle.system_requirements.global_constraints.get("non_functional_targets", {})
    note_render = "canvas2d" if bundle.manifest.scope_tier != "indie_light_25d" else "pixi_25d"
    return TechProfile(
        platform="web",
        language="typescript",
        render=note_render,
        data_format="yaml",
        directories={
            "systems": "game/src/systems/",
            "narrative": "game/data/narrative/",
            "art": "game/assets/art/",
            "audio": "game/assets/audio/",
            "modules": "game/src/modules/",
            "generated": "game/src/generated/",
        },
        runtime_harness={
            "build": "npm run build",
            "unit_test": "npm test",
            "scenario_replay": "npm run replay -- {scenario_file}",
            "perf_probe": f"npm run perf -- --fps {nfr.get('target_frame_rate_hz', 60)} --seconds 30",
            "save_load_roundtrip": "npm run saveload-check",
            "render_preview": (
                f"npm run preview -- {{asset_file}} --size {nfr.get('min_supported_resolution', '1280x720')}"
            ),
        },
    )


def _derive_input_id(req_id: str, source_text: str, used_ids: Set[str], idx: int) -> str:
    """为系统输入自然语言描述生成稳定、唯一的 IN_* 动作标识符。"""
    matched_parts: List[str] = []
    for zh_kw, en_tok in KNOWN_INPUT_TOKENS.items():
        if zh_kw in source_text and en_tok not in matched_parts:
            matched_parts.append(en_tok)
    if matched_parts:
        candidate = f"IN_{'_'.join(matched_parts[:2])}"
    else:
        ascii_words = re.findall(r"[A-Za-z0-9]+", source_text.upper())
        if ascii_words:
            candidate = f"IN_{'_'.join(ascii_words[:3])}"
        else:
            digest = hashlib.sha256(f"{req_id}:{source_text}".encode("utf-8")).hexdigest()[:6].upper()
            clean_req = re.sub(r"[^A-Z0-9]", "_", req_id.upper())
            candidate = f"IN_{clean_req}_{idx}_{digest}"

    base = candidate
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def build_state_events_contract(
    bundle: HandoffBundle,
    previous_contract: Optional[StateEventsContract] = None,
) -> Tuple[StateEventsContract, List[str]]:
    """
    §5.3 与 §9.2 步骤 2：
    - states / events 完全由代码从系统需求表提取；
    - referenced_by 通过正则扫描 business_rules / edge_cases 生成；
    - inputs 按 source_text 逐字匹配沿用旧 IN_* 标识，新增或改写项登记需要补登列表。
    """
    state_map: Dict[str, StateContractItem] = {}
    event_map: Dict[str, EventContractItem] = {}

    for sys_item in bundle.system_requirements.stage_deliverables:
        for st in sys_item.exposed_state_ids:
            if st.id in state_map:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"状态 {st.id} 在系统表中重复声明。",
                    {"state_id": st.id},
                )
            state_map[st.id] = StateContractItem(
                id=st.id,
                value_type=st.value_type,
                owner_req=sys_item.req_id,
                referenced_by=[sys_item.req_id],
                meaning=st.meaning,
            )
        for ev in sys_item.emitted_event_ids:
            if ev.id in event_map:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"事件 {ev.id} 在系统表中重复声明。",
                    {"event_id": ev.id},
                )
            event_map[ev.id] = EventContractItem(
                id=ev.id,
                owner_req=sys_item.req_id,
                referenced_by=[sys_item.req_id],
                meaning=ev.meaning,
            )

    # 扫描系统业务规则与边界条件补充 referenced_by
    for sys_item in bundle.system_requirements.stage_deliverables:
        corpus = "\n".join([*sys_item.business_rules, *sys_item.edge_cases, *sys_item.acceptance_criteria])
        for ident in STATE_OR_EVENT_RE.findall(corpus):
            if ident in state_map and sys_item.req_id not in state_map[ident].referenced_by:
                state_map[ident].referenced_by.append(sys_item.req_id)
            if ident in event_map and sys_item.req_id not in event_map[ident].referenced_by:
                event_map[ident].referenced_by.append(sys_item.req_id)

    # 也登记叙事/美术/音频消费引用，便于跨表溯源
    for disc_reqs in (
        bundle.narrative_requirements.stage_deliverables,
        bundle.art_requirements.stage_deliverables,
        bundle.audio_requirements.stage_deliverables,
    ):
        for item in disc_reqs:
            for st_id in item.linked_state_ids:
                if st_id in state_map and item.req_id not in state_map[st_id].referenced_by:
                    state_map[st_id].referenced_by.append(item.req_id)
            for ev_id in item.trigger_event_ids:
                if ev_id in event_map and item.req_id not in event_map[ev_id].referenced_by:
                    event_map[ev_id].referenced_by.append(item.req_id)

    prev_by_key: Dict[Tuple[str, str], str] = {}
    if previous_contract is not None:
        for inp in previous_contract.inputs:
            prev_by_key[(inp.req_id, inp.source_text)] = inp.id

    used_input_ids: Set[str] = set()
    inputs: List[InputActionDef] = []
    new_or_changed_inputs: List[str] = []

    for sys_item in bundle.system_requirements.stage_deliverables:
        for idx, text in enumerate(sys_item.inputs, start=1):
            key = (sys_item.req_id, text)
            if key in prev_by_key and prev_by_key[key] not in used_input_ids:
                in_id = prev_by_key[key]
                used_input_ids.add(in_id)
            else:
                in_id = _derive_input_id(sys_item.req_id, text, used_input_ids, idx)
                if previous_contract is not None:
                    new_or_changed_inputs.append(in_id)
            if not re.match(r"^IN_[A-Z0-9_]+$", in_id):
                raise OrchestratorError(
                    "ERR_SCHEMA_INVALID",
                    f"非法输入标识 {in_id}，必须满足 ^IN_[A-Z0-9_]+$。",
                    {"input_id": in_id},
                )
            inputs.append(InputActionDef(id=in_id, req_id=sys_item.req_id, source_text=text))

    sys_manifest_entry = next(
        (e for e in bundle.manifest.files if e.path.replace("\\", "/") == "requirements/system_requirements.yaml"),
        None,
    )
    source_sha = sys_manifest_entry.sha256 if sys_manifest_entry else stable_json_sha256(bundle.system_requirements.model_dump())

    contract = StateEventsContract(
        source="requirements/system_requirements.yaml",
        source_sha256=source_sha,
        states=list(state_map.values()),
        events=list(event_map.values()),
        inputs=inputs,
    )
    digest_payload = {
        "states": [s.model_dump() for s in contract.states],
        "events": [e.model_dump() for e in contract.events],
        "inputs": [i.model_dump() for i in contract.inputs],
    }
    contract.contract_sha256 = stable_json_sha256(digest_payload)
    return contract, new_or_changed_inputs


def build_asset_schemas_contract() -> AssetSchemasContract:
    """§5.4：由编排器代码固定生成叙事/美术/音频三类核心数据格式契约，防止联调结构冲突。"""
    schemas = {
        "narrative_line": {
            "required": ["line_id", "req_id", "speaker", "text", "when"],
            "when_one_of": {
                "state_condition": {"state_id": "ST_*", "values": ["int"]},
                "event_trigger": {"event_id": "EVT_*"},
            },
            "optional": ["order", "variant", "note"],
        },
        "art_asset": {
            "required": ["asset_id", "req_id", "file", "kind", "size_px"],
            "kind_enum": ["sprite", "vector", "overlay", "portrait", "ui_frame"],
            "optional": ["reuse_group", "base_frame_id", "binds", "variant"],
            "binds": {"state_id": "ST_*", "value": "int"},
        },
        "audio_asset": {
            "required": ["asset_id", "req_id", "file", "kind", "duration_sec"],
            "kind_enum": ["sfx", "bgm_layer", "ambience"],
            "optional": ["loop", "binds", "gain_db"],
            "binds_one_of": {
                "event_trigger": {"event_id": "EVT_*"},
                "state_range": {"state_id": "ST_*", "min": "int", "max": "int"},
            },
        },
    }
    return AssetSchemasContract(schemas=schemas, contract_sha256=stable_json_sha256(schemas))


def get_task_writable_paths(kind: TaskKind, req_id: Optional[str] = None, gdd_ref: Optional[str] = None) -> List[str]:
    """§5.6 独占目录表（按 req_id / gdd_id 小写划分）。"""
    if kind == TaskKind.TECH:
        return ["game/", "contracts/"]
    if kind == TaskKind.SYS and req_id:
        slug = req_id.lower()
        return [f"game/src/systems/{slug}/", f"game/tests/systems/{slug}/"]
    if kind == TaskKind.NAR and req_id:
        return [f"game/data/narrative/{req_id.lower()}/"]
    if kind == TaskKind.ART and req_id:
        return [f"game/assets/art/{req_id.lower()}/"]
    if kind == TaskKind.AUD and req_id:
        return [f"game/assets/audio/{req_id.lower()}/"]
    if kind == TaskKind.INTEG and gdd_ref:
        slug = gdd_ref.lower()
        return [f"game/src/modules/{slug}/", f"game/tests/integration/{slug}/"]
    return []


def get_scenario_dir(req_id: str) -> str:
    return f"game/tests/scenarios/{req_id.lower()}/"
