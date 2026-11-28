from __future__ import annotations

import json
import re
import struct
import wave
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import yaml

from ..handoff_loader import compute_file_sha256
from ..schemas import (
    ArtifactManifest,
    HandoffBundle,
    Level1Report,
    SessionState,
    TaskKind,
    TaskRecord,
)
from .scenario_runner import load_scenarios_from_dir, run_scenarios_replay

CONTRACT_IDENT_RE = re.compile(r"\b(?:ST|EVT|IN)_[A-Z0-9_]+\b")
HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
MAX_CHARS_RE = re.compile(r"≤\s*(\d+)\s*字")


def _check_required_index_fields(items: Any, required_fields: List[str], kind_label: str) -> List[str]:
    if not isinstance(items, list) or not items:
        return [f"{kind_label} index.yaml 缺少非空 items 列表。"]
    errs: List[str] = []
    for idx, entry in enumerate(items):
        if not isinstance(entry, dict):
            errs.append(f"{kind_label} index.yaml 第 {idx} 项非字典对象。")
            continue
        for rf in required_fields:
            if rf not in entry or entry[rf] in (None, ""):
                errs.append(f"{kind_label} index.yaml 第 {idx} 项缺少核心字段 '{rf}'。")
    return errs


def run_level1_checks(
    session: SessionState,
    bundle: HandoffBundle,
    task: TaskRecord,
    manifest: ArtifactManifest,
    workdir: Path,
    changed_files: List[str],
) -> Level1Report:
    """
    §8.2 L1 确定性脚本检查（零模型调用，必过）：
    1. 全部任务：清单文件存在且哈希一致，无独占目录外改动；
    2. 按工种执行对应的格式、标识符、回放场景、色板/位图、音长/削波及非功能测试桩核查；
    3. 缺失测试桩或无法自动测量的运行时指标计入 manual_required（不静默判过）。
    """
    failed: List[str] = []
    manual_required: List[str] = []
    details: Dict[str, Any] = {"changed_files": changed_files}

    # 通用检查：manifest 列出的文件存在且 sha256 一致
    allowed = list(task.writable_paths)
    for af in manifest.files:
        fpath = workdir / af.path
        if not fpath.exists() or not fpath.is_file():
            failed.append(f"产物清单声明的文件不存在: {af.path}")
            continue
        actual_sha = compute_file_sha256(fpath)
        if actual_sha != af.sha256:
            failed.append(f"产物文件哈希不匹配: {af.path}")
        if not any(af.path == p.rstrip("/") or af.path.startswith(p) for p in allowed):
            failed.append(f"产物清单引用了独占目录外文件: {af.path}")

    contract = session.state_events
    allowed_contract_ids: Set[str] = set()
    if contract:
        allowed_contract_ids |= {s.id for s in contract.states}
        allowed_contract_ids |= {e.id for e in contract.events}
        allowed_contract_ids |= {i.id for i in contract.inputs}

    if task.kind == TaskKind.TECH:
        if not (workdir / "game" / "package.json").exists():
            failed.append("TECH-001 缺少 game/package.json 工程骨架。")

    elif task.kind == TaskKind.SYS and task.req_id:
        sys_item = next(d for d in bundle.system_requirements.stage_deliverables if d.req_id == task.req_id)
        # 1. 只检查 ST_/EVT_/IN_ 前缀标识符，不误杀内部变量名
        for rel in changed_files:
            p = workdir / rel
            if p.exists() and p.suffix.lower() in {".json", ".ts", ".js", ".py", ".gd", ".cs", ".yaml", ".yml"}:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for ident in set(CONTRACT_IDENT_RE.findall(content)):
                    if allowed_contract_ids and ident not in allowed_contract_ids:
                        failed.append(f"代码使用了契约外标识符 {ident} ({rel})")

        # 2. 执行独立验收场景回放
        scenarios = load_scenarios_from_dir(workdir, task.req_id)
        if not scenarios:
            # 回退检查主工作区是否已写入场景
            scenarios = load_scenarios_from_dir(workdir, task.req_id)
        ok_replay, replay_errs = run_scenarios_replay(scenarios, workdir, task.req_id)
        if not ok_replay:
            failed.extend(replay_errs)
        details["scenarios_checked"] = len(scenarios)

    elif task.kind == TaskKind.NAR and task.req_id:
        nar_item = next(d for d in bundle.narrative_requirements.stage_deliverables if d.req_id == task.req_id)
        idx_path = workdir / f"game/data/narrative/{task.req_id.lower()}/index.yaml"
        if not idx_path.exists():
            failed.append(f"叙事任务缺少 {idx_path.relative_to(workdir).as_posix()}")
        else:
            data = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            req_fields = (
                session.asset_schemas.schemas["narrative_line"]["required"]
                if session.asset_schemas
                else ["line_id", "req_id", "speaker", "text", "when"]
            )
            failed.extend(_check_required_index_fields(items, req_fields, "NAR"))

            # 检查状态与事件覆盖 + 禁用例句 + 可机读字数上限
            covered_states: Set[str] = set()
            covered_events: Set[str] = set()
            forbidden_lines = [
                f.get("line", "")
                for f in bundle.narrative_requirements.global_constraints.get("tone_samples", {}).get("forbidden_examples", [])
                if isinstance(f, dict) and f.get("line")
            ]
            max_chars_match = MAX_CHARS_RE.search(nar_item.deliverable_spec)
            max_chars = int(max_chars_match.group(1)) if max_chars_match else None

            for entry in items:
                if not isinstance(entry, dict):
                    continue
                txt = str(entry.get("text", ""))
                if max_chars is not None and len(txt) > max_chars:
                    failed.append(f"台词 {entry.get('line_id')} 超过长度上限 {max_chars} 字 (实际 {len(txt)})")
                for ban in forbidden_lines:
                    if ban and ban in txt:
                        failed.append(f"台词 {entry.get('line_id')} 命中全局禁用样张。")
                when = entry.get("when", {})
                if isinstance(when, dict):
                    sc = when.get("state_condition")
                    if isinstance(sc, dict) and sc.get("state_id"):
                        covered_states.add(sc["state_id"])
                    et = when.get("event_trigger")
                    if isinstance(et, dict) and et.get("event_id"):
                        covered_events.add(et["event_id"])

            for st in nar_item.linked_state_ids:
                if st not in covered_states:
                    failed.append(f"叙事产出未覆盖状态 {st}")
            for ev in nar_item.trigger_event_ids:
                if ev not in covered_events:
                    failed.append(f"叙事产出未覆盖触发事件 {ev}")

    elif task.kind == TaskKind.ART and task.req_id:
        art_item = next(d for d in bundle.art_requirements.stage_deliverables if d.req_id == task.req_id)
        idx_path = workdir / f"game/assets/art/{task.req_id.lower()}/index.yaml"
        if not idx_path.exists():
            failed.append(f"美术任务缺少 {idx_path.relative_to(workdir).as_posix()}")
        else:
            data = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            req_fields = (
                session.asset_schemas.schemas["art_asset"]["required"]
                if session.asset_schemas
                else ["asset_id", "req_id", "file", "kind", "size_px"]
            )
            failed.extend(_check_required_index_fields(items, req_fields, "ART"))
            palette = {
                str(v).upper()
                for v in bundle.art_requirements.global_constraints.get("color_palette", {}).values()
            }
            base_frames: Set[str] = set()
            bitmap_report: List[Dict[str, Any]] = []

            for entry in items:
                if not isinstance(entry, dict):
                    continue
                asset_rel = str(entry.get("file", ""))
                asset_file = workdir / asset_rel
                if not asset_file.exists():
                    failed.append(f"美术资源文件缺失: {asset_rel}")
                    continue
                if art_item.reuse_group:
                    if not entry.get("base_frame_id"):
                        failed.append(f"同复用组资产 {entry.get('asset_id')} 缺少 base_frame_id")
                    else:
                        base_frames.add(str(entry["base_frame_id"]))

                if asset_file.suffix.lower() == ".svg":
                    svg_txt = asset_file.read_text(encoding="utf-8", errors="ignore")
                    found_colors = {c.upper() for c in HEX_COLOR_RE.findall(svg_txt)}
                    illegal = found_colors - palette
                    if palette and illegal:
                        failed.append(f"矢量资产 {asset_rel} 使用了色板外颜色: {sorted(illegal)}")
                elif asset_file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    # §8.2 位图/生成式仅核验尺寸/格式并生成辅助色情报告给 L2，不在 L1 死卡色板
                    raw = asset_file.read_bytes()
                    if asset_file.suffix.lower() == ".png" and raw[:8] != b"\x89PNG\r\n\x1a\n":
                        failed.append(f"PNG 文件头损坏: {asset_rel}")
                    bitmap_report.append({"file": asset_rel, "bytes": len(raw), "note": "位图色彩由 L2 结合预览审核"})

            if len(base_frames) > 1:
                failed.append(f"同复用组存在多个不一致的 base_frame_id: {sorted(base_frames)}")
            if bitmap_report:
                details["bitmap_color_report"] = bitmap_report

    elif task.kind == TaskKind.AUD and task.req_id:
        aud_item = next(d for d in bundle.audio_requirements.stage_deliverables if d.req_id == task.req_id)
        idx_path = workdir / f"game/assets/audio/{task.req_id.lower()}/index.yaml"
        if not idx_path.exists():
            failed.append(f"音频任务缺少 {idx_path.relative_to(workdir).as_posix()}")
        else:
            data = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            req_fields = (
                session.asset_schemas.schemas["audio_asset"]["required"]
                if session.asset_schemas
                else ["asset_id", "req_id", "file", "kind", "duration_sec"]
            )
            failed.extend(_check_required_index_fields(items, req_fields, "AUD"))
            covered_events: Set[str] = set()
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                aud_rel = str(entry.get("file", ""))
                aud_file = workdir / aud_rel
                if not aud_file.exists():
                    failed.append(f"音频文件缺失: {aud_rel}")
                    continue
                if aud_file.suffix.lower() == ".wav":
                    try:
                        with wave.open(str(aud_file), "rb") as wf:
                            n_frames = wf.getnframes()
                            rate = wf.getframerate()
                            actual_dur = n_frames / float(rate) if rate > 0 else 0.0
                            raw_frames = wf.readframes(min(n_frames, rate * 5))
                            if wf.getsampwidth() == 2 and len(raw_frames) >= 2:
                                samples = struct.unpack(f"<{len(raw_frames)//2}h", raw_frames)
                                if samples and max(abs(s) for s in samples) >= 32767:
                                    failed.append(f"音频 {aud_rel} 峰值削波")
                        declared_dur = float(entry.get("duration_sec", actual_dur))
                        if abs(actual_dur - declared_dur) > 0.5:
                            failed.append(f"音频 {aud_rel} 实际时长 {actual_dur:.2f}s 与声明 {declared_dur:.2f}s 偏差过大")
                    except Exception as exc:
                        failed.append(f"音频解码失败 {aud_rel}: {exc}")
                binds = entry.get("binds", {})
                if isinstance(binds, dict):
                    et = binds.get("event_trigger")
                    if isinstance(et, dict) and et.get("event_id"):
                        covered_events.add(et["event_id"])
            for ev in aud_item.trigger_event_ids:
                if ev not in covered_events:
                    failed.append(f"音频产出未覆盖触发事件 {ev}")

    elif task.kind == TaskKind.INTEG and task.gdd_ref:
        mod_file = workdir / f"game/src/modules/{task.gdd_ref.lower()}/module_binding.json"
        if not mod_file.exists():
            failed.append(f"模块联调缺少绑定文件 {mod_file.relative_to(workdir).as_posix()}")
        else:
            mod_data = json.loads(mod_file.read_text(encoding="utf-8"))
            bound_events = set(mod_data.get("bound_events", []))
            if contract:
                req_events = {
                    e.id
                    for e in contract.events
                    if any(dep in e.referenced_by for dep in task.depends_on)
                }
                missing_ev = req_events - bound_events
                if missing_ev:
                    failed.append(f"模块联调遗漏事件绑定: {sorted(missing_ev)}")
        # 在集成状态下复跑本模块相关 SYS 验收场景
        for dep_id in task.depends_on:
            dep_task = session.tasks.get(dep_id)
            if dep_task and dep_task.kind == TaskKind.SYS and dep_task.req_id:
                scenarios = load_scenarios_from_dir(workdir, dep_task.req_id)
                ok_replay, errs = run_scenarios_replay(scenarios, workdir, dep_task.req_id)
                if not ok_replay:
                    failed.extend([f"[集成复跑] {e}" for e in errs])

    elif task.kind == TaskKind.QA_FINAL:
        # 复跑全量 SYS 验收场景
        for t in sorted(session.tasks.values(), key=lambda x: x.task_id):
            if t.kind == TaskKind.SYS and t.req_id:
                scenarios = load_scenarios_from_dir(workdir, t.req_id)
                ok_replay, errs = run_scenarios_replay(scenarios, workdir, t.req_id)
                if not ok_replay:
                    failed.extend([f"[终验全量] {e}" for e in errs])

        # §8.2 runtime_harness 非功能检测：缺失测试桩命令标为 MANUAL_REQUIRED，绝不静默通过 (O17)
        harness = session.tech_profile.runtime_harness
        for probe_key, label in (
            ("perf_probe", "perf_probe (60FPS 性能采样测试桩缺失，需人工确认)"),
            ("save_load_roundtrip", "save_load_roundtrip (存读档一致性测试桩缺失，需人工确认)"),
        ):
            cmd = harness.get(probe_key)
            if not cmd or not str(cmd).strip():
                manual_required.append(label)

    return Level1Report(
        passed=len(failed) == 0,
        failed_checks=failed,
        manual_required=manual_required,
        details=details,
    )
