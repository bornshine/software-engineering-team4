from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .handoff_loader import compute_canonical_sha256, compute_file_sha256
from .schemas import HandoffBundle, OrchestratorError, SessionState

ALLOWED_CONTRACT_VERSIONS = {
    "layer1-handoff/v1.0",
    "layer1-handoff/v1.1",
    "layer1-handoff/v1.2",
}
ALLOWED_SCOPE_TIERS = {"micro_2d", "indie_stylized_2d", "indie_light_25d"}


@dataclass
class ValidationResult:
    passed: bool
    warnings: List[str] = field(default_factory=list)
    load_mode: str = "NEW"  # NEW | RESUME | UPGRADE


def validate_handoff_bundle(
    bundle: HandoffBundle,
    *,
    auxiliary_mode: str = "compat",
    existing_session: Optional[SessionState] = None,
    force_new_project: bool = False,
) -> ValidationResult:
    """执行接入校验门 A-1 ~ A-11（全部确定性校验，失败即拒收）。"""
    m = bundle.manifest
    root = Path(bundle.source_dir)
    warnings: List[str] = []

    # A-1 契约版本
    if m.contract_version not in ALLOWED_CONTRACT_VERSIONS:
        raise OrchestratorError(
            "ERR_CONTRACT_VERSION_UNSUPPORTED",
            f"不支持的契约版本: {m.contract_version}",
            {"contract_version": m.contract_version},
        )

    # A-2 签字状态
    sig = m.approval_signature
    if sig.status != "APPROVED" or not sig.approved_by.strip() or not sig.approved_at.strip():
        raise OrchestratorError(
            "ERR_HANDOFF_NOT_APPROVED",
            "交接包未获得人类导演 APPROVED 有效签字。",
            {"approval_signature": sig.model_dump()},
        )

    # A-3 上游拦截器（同时兼容校验 v1.0 核心 4 项与 v1.1/v1.2 新增可选项）
    ic = m.interceptors_passed
    required_checks = [
        ic.linked_gdd_ref_integrity,
        ic.system_no_how_blacklist_clean,
        ic.cross_table_state_event_closed,
        ic.feasibility_cold_reader_audit,
    ]
    optional_checks = [
        v
        for v in (
            ic.gdd_bidirectional_na_closed,
            ic.no_placeholder_words_clean,
            ic.pacing_and_cognitive_load_audit,
            ic.understanding_echo_aligned,
        )
        if v is not None
    ]
    if not all(required_checks) or not all(optional_checks):
        raise OrchestratorError(
            "ERR_UPSTREAM_INTERCEPTOR_FAILED",
            "上游 Stage 3 确定性拦截器或终审未全通过。",
            {"interceptors_passed": ic.model_dump()},
        )

    # A-4 文件完整性（逐文件存在且 sha256 一致）
    for entry in m.files:
        rel = entry.path.replace("\\", "/")
        fpath = (root / rel).resolve()
        if not fpath.is_relative_to(root) or not fpath.exists() or not fpath.is_file():
            raise OrchestratorError(
                "ERR_FILE_HASH_MISMATCH",
                f"受管文件缺失或路径越界: {rel}",
                {"path": rel},
            )
        actual_sha = compute_file_sha256(fpath)
        if actual_sha != entry.sha256:
            raise OrchestratorError(
                "ERR_FILE_HASH_MISMATCH",
                f"受管文件 {rel} 哈希校验不通过。",
                {"path": rel, "expected": entry.sha256, "actual": actual_sha},
            )

    # A-5 包级规范化哈希
    actual_canonical = compute_canonical_sha256(m.files)
    if actual_canonical != m.canonical_sha256:
        raise OrchestratorError(
            "ERR_CANONICAL_HASH_MISMATCH",
            "交接包级 canonical_sha256 校验失败（包内容与清单不一致）。",
            {"expected": m.canonical_sha256, "actual": actual_canonical},
        )

    # A-7 体量档位（A-6 Schema 已在 loader 解析时执行）
    if m.scope_tier not in ALLOWED_SCOPE_TIERS:
        raise OrchestratorError(
            "ERR_SCOPE_TIER_FORBIDDEN",
            f"禁止的体量档位 {m.scope_tier}，仅允许 {sorted(ALLOWED_SCOPE_TIERS)}。",
            {"scope_tier": m.scope_tier},
        )

    # A-8 全包交叉引用与唯一性复核
    gdd_ids: Set[str] = {mod.gdd_id for mod in bundle.gdd_index.modules}
    canon_ids: Set[str] = {c.canon_id for c in bundle.canon_registry.entries}
    declared_states: Set[str] = set()
    declared_events: Set[str] = set()
    seen_req_ids: Set[str] = set()

    def _register_req(req_id: str, gdd_ref: str) -> None:
        if req_id in seen_req_ids:
            raise OrchestratorError(
                "ERR_CROSS_REF_BROKEN",
                f"存在重复的需求编号 {req_id}。",
                {"req_id": req_id},
            )
        seen_req_ids.add(req_id)
        if gdd_ref not in gdd_ids:
            raise OrchestratorError(
                "ERR_CROSS_REF_BROKEN",
                f"需求 {req_id} 引用了不存在的模块 {gdd_ref}。",
                {"req_id": req_id, "linked_gdd_ref": gdd_ref},
            )

    for s in bundle.system_requirements.stage_deliverables:
        _register_req(s.req_id, s.linked_gdd_ref)
        for st in s.exposed_state_ids:
            declared_states.add(st.id)
        for ev in s.emitted_event_ids:
            declared_events.add(ev.id)

    for n in bundle.narrative_requirements.stage_deliverables:
        _register_req(n.req_id, n.linked_gdd_ref)
        for st_id in n.linked_state_ids:
            if st_id not in declared_states:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"叙事需求 {n.req_id} 引用了未在系统表声明的状态 {st_id}。",
                    {"req_id": n.req_id, "state_id": st_id},
                )
        for ev_id in n.trigger_event_ids:
            if ev_id not in declared_events:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"叙事需求 {n.req_id} 引用了未在系统表声明的事件 {ev_id}。",
                    {"req_id": n.req_id, "event_id": ev_id},
                )
        for c_id in n.canon_refs:
            if c_id not in canon_ids:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"叙事需求 {n.req_id} 引用了不存在的 Canon 条目 {c_id}。",
                    {"req_id": n.req_id, "canon_id": c_id},
                )

    for a in bundle.art_requirements.stage_deliverables:
        _register_req(a.req_id, a.linked_gdd_ref)
        for st_id in a.linked_state_ids:
            if st_id not in declared_states:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"美术需求 {a.req_id} 引用了未声明状态 {st_id}。",
                    {"req_id": a.req_id, "state_id": st_id},
                )
        for ev_id in a.trigger_event_ids:
            if ev_id not in declared_events:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"美术需求 {a.req_id} 引用了未声明事件 {ev_id}。",
                    {"req_id": a.req_id, "event_id": ev_id},
                )

    for au in bundle.audio_requirements.stage_deliverables:
        _register_req(au.req_id, au.linked_gdd_ref)
        for st_id in au.linked_state_ids:
            if st_id not in declared_states:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"音频需求 {au.req_id} 引用了未声明状态 {st_id}。",
                    {"req_id": au.req_id, "state_id": st_id},
                )
        for ev_id in au.trigger_event_ids:
            if ev_id not in declared_events:
                raise OrchestratorError(
                    "ERR_CROSS_REF_BROKEN",
                    f"音频需求 {au.req_id} 引用了未声明事件 {ev_id}。",
                    {"req_id": au.req_id, "event_id": ev_id},
                )

    # A-10 辅助文件哈希保护检查（ADR 与参考图）
    for aux in bundle.auxiliary_files:
        if not aux.listed_in_manifest:
            if auxiliary_mode == "strict":
                raise OrchestratorError(
                    "ERR_UNHASHED_AUXILIARY_FILE",
                    f"严格模式下拒绝未列入 manifest.files 的辅助文件: {aux.path}",
                    {"path": aux.path, "kind": aux.kind},
                )
            warnings.append(
                f"WARN_UNHASHED_AUXILIARY_FILE: 辅助文件 {aux.path} ({aux.kind}) 未列入 manifest.files，已按兼容模式加载并记录 sha256:{aux.sha256[:12]}。"
            )

    # A-11 ADR 悬空引用告警
    valid_adr_targets = seen_req_ids | gdd_ids
    for adr in bundle.adr_records:
        for ref in adr.impacted_refs:
            if ref not in valid_adr_targets:
                warnings.append(f"WARN_ADR_DANGLING_REF: {adr.adr_id} 引用了未知标识 '{ref}'。")

    # A-9 与 §4.3 会话/版本链判定
    load_mode = "NEW"
    if existing_session is None or force_new_project:
        if m.parent_version and not force_new_project and existing_session is None:
            raise OrchestratorError(
                "ERR_PARENT_VERSION_MISSING",
                f"交接包声明父版本 {m.parent_version}，但本地不存在该父版本运行态。",
                {"parent_version": m.parent_version},
            )
        load_mode = "NEW"
    else:
        if m.spec_version == existing_session.spec_version:
            if m.canonical_sha256 == existing_session.canonical_sha256:
                load_mode = "RESUME"
            else:
                raise OrchestratorError(
                    "ERR_SAME_VERSION_DIFFERENT_CONTENT",
                    f"同版本号 {m.spec_version} 内容哈希冲突，拒绝覆盖加载。",
                    {"spec_version": m.spec_version},
                )
        elif m.parent_version == existing_session.spec_version:
            if bundle.diff_summary is None:
                raise OrchestratorError(
                    "ERR_VERSION_CHAIN_BROKEN",
                    f"升版包 {m.spec_version} 缺少 diff_summary.yaml。",
                    {"spec_version": m.spec_version, "parent_version": m.parent_version},
                )
            if (
                bundle.diff_summary.from_version != existing_session.spec_version
                or bundle.diff_summary.to_version != m.spec_version
            ):
                raise OrchestratorError(
                    "ERR_VERSION_CHAIN_BROKEN",
                    "diff_summary.yaml 的 from_version / to_version 与版本链不一致。",
                    {
                        "expected_from": existing_session.spec_version,
                        "expected_to": m.spec_version,
                        "actual_from": bundle.diff_summary.from_version,
                        "actual_to": bundle.diff_summary.to_version,
                    },
                )
            load_mode = "UPGRADE"
        else:
            raise OrchestratorError(
                "ERR_VERSION_CHAIN_BROKEN",
                f"当前运行版本为 {existing_session.spec_version}，新包 parent_version={m.parent_version} 无法衔接。",
                {"current": existing_session.spec_version, "parent": m.parent_version},
            )

    return ValidationResult(passed=True, warnings=warnings, load_mode=load_mode)
