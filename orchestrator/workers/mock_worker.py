from __future__ import annotations

import io
import json
import math
import re
import struct
import time
import wave
from pathlib import Path
from typing import Any, Dict, List
import yaml

from ..handoff_loader import compute_file_sha256
from ..schemas import ArtifactFile, ArtifactManifest
from .base import WorkerResult


def _build_silent_wav_bytes(duration_sec: float = 1.2, sample_rate: int = 16000) -> bytes:
    """生成合法的无削波单声道 WAV 音频字节，供 L1 音频长度与峰值检验。"""
    n_frames = max(1, int(duration_sec * sample_rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_frames):
            sample = int(8000 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _extract_max_chars(deliverable_spec: str) -> int:
    m = re.search(r"≤\s*(\d+)\s*字", deliverable_spec)
    return int(m.group(1)) if m else 120


class MockWorker:
    """
    §7.4 确定性离线 MockWorker：
    - 秒级在尝试工作区独占目录产出符合 L1 检查规则的真实文件（代码/YAML/SVG/WAV）；
    - 支持注入越界写入、多次失败、场景争议、预算耗尽与合并构建失败，用于单测与看板演练。
    """

    mode = "mock"

    def __init__(self, role: str) -> None:
        self.role = role

    def run(self, ctx: Dict[str, Any], workdir: Path, timeout_sec: int) -> WorkerResult:
        started = time.perf_counter()
        task_id: str = ctx["task_id"]
        kind: str = ctx["kind"]
        attempt: int = int(ctx.get("attempt", 1))
        writable: List[str] = list(ctx.get("writable_paths", []))
        faults: List[str] = list(ctx.get("injected_faults", []))

        # 支持注入单次故障，例如 fail_attempt_1 / write_violation / scenario_dispute
        if "budget_spike" in faults:
            return WorkerResult(
                ok=True,
                manifest=ArtifactManifest(task_id=task_id, attempt=attempt, files=[], summary="spike", api_calls=99999, cost=9999.0),
                api_calls=99999,
                cost=9999.0,
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        if "write_violation" in faults:
            rogue = workdir / "game" / "src" / "rogue_outside.txt"
            rogue.parent.mkdir(parents=True, exist_ok=True)
            rogue.write_text("illegal cross-directory write\n", encoding="utf-8")
            sha = compute_file_sha256(rogue)
            return WorkerResult(
                ok=True,
                manifest=ArtifactManifest(
                    task_id=task_id,
                    attempt=attempt,
                    files=[ArtifactFile(path="game/src/rogue_outside.txt", sha256=sha)],
                    summary="simulated out-of-scope write",
                    api_calls=1,
                    cost=0.01,
                ),
                api_calls=1,
                cost=0.01,
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        if "scenario_dispute" in faults and f"scenario_dispute_resolved_{attempt}" not in faults:
            return WorkerResult(
                ok=True,
                manifest=ArtifactManifest(
                    task_id=task_id,
                    attempt=attempt,
                    files=[],
                    scenario_dispute={
                        "scenario_id": f"{task_id}-S01",
                        "reason": "作者质疑验收场景预期状态未考虑同帧破咒优先 ADR-001。",
                    },
                    summary="提出场景争议",
                    api_calls=1,
                    cost=0.01,
                ),
                api_calls=1,
                cost=0.01,
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        if "worker_crash" in faults:
            return WorkerResult(
                ok=False,
                error_message="Mock 注入 Worker 进程异常退出",
                api_calls=1,
                cost=0.01,
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        produced_files: List[Path] = []
        if kind == "TECH":
            produced_files = self._produce_tech(workdir, ctx)
        elif kind == "SYS":
            produced_files = self._produce_sys(workdir, ctx)
        elif kind == "NAR":
            produced_files = self._produce_nar(workdir, ctx)
        elif kind == "ART":
            produced_files = self._produce_art(workdir, ctx)
        elif kind == "AUD":
            produced_files = self._produce_aud(workdir, ctx)
        elif kind == "INTEG":
            produced_files = self._produce_integ(workdir, ctx)
        elif kind == "QA_FINAL":
            produced_files = []

        # QA_FINAL 的 writable_paths 为空，仅产出摘要，无文件写盘
        artifact_entries: List[ArtifactFile] = []
        for fpath in produced_files:
            rel = fpath.relative_to(workdir).as_posix()
            artifact_entries.append(
                ArtifactFile(
                    path=rel,
                    sha256=compute_file_sha256(fpath),
                    source_route="procedural" if kind in ("ART", "AUD") else None,
                )
            )

        return WorkerResult(
            ok=True,
            manifest=ArtifactManifest(
                task_id=task_id,
                attempt=attempt,
                files=artifact_entries,
                summary=f"[Mock] 已完成 {task_id} 第 {attempt} 次尝试产出（共 {len(artifact_entries)} 个文件）",
                api_calls=1,
                cost=0.02,
            ),
            api_calls=1,
            cost=0.02,
            runtime_sec=round(time.perf_counter() - started, 4),
        )

    def _produce_tech(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        game_dir = workdir / "game"
        pkg = game_dir / "package.json"
        pkg.parent.mkdir(parents=True, exist_ok=True)
        # 故意不包含阻塞无 NPM 环境的重依赖，仅作为工程骨架声明
        pkg.write_text(
            json.dumps(
                {
                    "name": "stylized-2d-game",
                    "version": "1.0.0",
                    "scripts": {
                        "build": "echo build-ok",
                        "test": "echo test-ok",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        entry = game_dir / "src" / "main.ts"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            "// 共享工程入口：仅从 generated/modules_registry.json 读取模块，避免联调并发冲突\n"
            "export const ENGINE_READY = true;\n",
            encoding="utf-8",
        )
        harness = game_dir / "src" / "replay_harness.ts"
        harness.write_text(
            "// 纯数据驱动状态机回放测试桩占位骨架\nexport function runReplayScenario() { return true; }\n",
            encoding="utf-8",
        )
        return [pkg, entry, harness]

    def _produce_sys(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        req = ctx["requirement"]
        req_id: str = req["req_id"]
        slug = req_id.lower()
        src_dir = workdir / "game" / "src" / "systems" / slug
        tst_dir = workdir / "game" / "tests" / "systems" / slug
        src_dir.mkdir(parents=True, exist_ok=True)
        tst_dir.mkdir(parents=True, exist_ok=True)

        # 生成合法的状态机数据描述与规则实现（只包含契约登记的 ST_/EVT_/IN_ 标识符）
        states = [s["id"] for s in ctx.get("state_event_contract", {}).get("states", [])]
        events = [e["id"] for e in ctx.get("state_event_contract", {}).get("events", [])]
        inputs = [i["id"] for i in ctx.get("state_event_contract", {}).get("inputs", [])]

        impl_path = src_dir / f"{slug}_system.json"
        impl_data = {
            "req_id": req_id,
            "title": req["title"],
            "states": states,
            "events": events,
            "inputs": inputs,
            "business_rules": req.get("business_rules", []),
            "edge_cases": req.get("edge_cases", []),
            "adr_followed": [a["adr_id"] for a in ctx.get("adr_entries", [])],
            # 默认支持从需求原文参数驱动行为（包括 v1.1.0 阈值变更）
            "rule_params": {"suspicion_warn_threshold": 50 if "50" in "".join(req.get("business_rules", [])) else 60},
        }
        impl_path.write_text(json.dumps(impl_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        unit_path = tst_dir / f"{slug}_unit.json"
        unit_path.write_text(
            json.dumps({"req_id": req_id, "self_check": "passed"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return [impl_path, unit_path]

    def _produce_nar(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        req = ctx["requirement"]
        req_id: str = req["req_id"]
        slug = req_id.lower()
        out_dir = workdir / "game" / "data" / "narrative" / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        limit = _extract_max_chars(req.get("deliverable_spec", ""))
        items: List[Dict[str, Any]] = []
        seq = 1
        for st in ctx.get("state_event_contract", {}).get("states", []):
            st_id = st["id"]
            if "0..3" in st.get("value_type", ""):
                vals = [1, 2, 3]
            else:
                vals = [10, 50, 85]
            for v in vals:
                txt = f"此间因果印记已至第{v}阶，殿前一言一行皆须谨慎。"[:limit]
                items.append(
                    {
                        "line_id": f"{req_id}-L{seq:02d}",
                        "req_id": req_id,
                        "speaker": "女儿国主",
                        "text": txt,
                        "when": {"state_condition": {"state_id": st_id, "values": [v]}},
                        "order": seq,
                    }
                )
                seq += 1
        for ev in req.get("trigger_event_ids", []):
            items.append(
                {
                    "line_id": f"{req_id}-L{seq:02d}",
                    "req_id": req_id,
                    "speaker": "旁白",
                    "text": f"仪轨既定，应象而行（触发 {ev}）。"[:limit],
                    "when": {"event_trigger": {"event_id": ev}},
                    "order": seq,
                }
            )
            seq += 1

        idx_file = out_dir / "index.yaml"
        idx_file.write_text(yaml.safe_dump({"items": items}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return [idx_file]

    def _produce_art(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        req = ctx["requirement"]
        req_id: str = req["req_id"]
        slug = req_id.lower()
        out_dir = workdir / "game" / "assets" / "art" / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        palette_dict = ctx.get("discipline_global_constraints", {}).get("color_palette", {})
        colors = list(palette_dict.values()) or ["#F3EDE0", "#1F2428", "#B83227", "#2E6F7E"]
        bg = colors[0]
        ink = colors[1] if len(colors) > 1 else colors[0]
        accent = colors[2] if len(colors) > 2 else ink
        curse = colors[3] if len(colors) > 3 else accent

        items: List[Dict[str, Any]] = []
        created: List[Path] = []
        base_frame_id = f"{req.get('reuse_group') or req_id}-BASE"
        for idx in range(1, 3):
            svg_name = f"{slug}_{idx:02d}.svg"
            svg_path = out_dir / svg_name
            opacity = round(0.35 + idx * 0.25, 2)
            svg_text = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'
                f'  <rect width="256" height="256" fill="{bg}" />\n'
                f'  <circle cx="128" cy="128" r="{42 + idx * 14}" fill="{curse}" fill-opacity="{opacity}" stroke="{ink}" stroke-width="4" />\n'
                f'  <circle cx="128" cy="128" r="18" fill="{accent}" fill-opacity="0.85" />\n'
                f"</svg>\n"
            )
            svg_path.write_text(svg_text, encoding="utf-8")
            created.append(svg_path)
            entry: Dict[str, Any] = {
                "asset_id": f"{req_id}-A{idx:02d}",
                "req_id": req_id,
                "file": f"game/assets/art/{slug}/{svg_name}",
                "kind": "vector",
                "size_px": [256, 256],
            }
            if req.get("reuse_group"):
                entry["reuse_group"] = req["reuse_group"]
                entry["base_frame_id"] = base_frame_id
            if req.get("linked_state_ids"):
                entry["binds"] = {"state_id": req["linked_state_ids"][0], "value": idx}
            items.append(entry)

        idx_file = out_dir / "index.yaml"
        idx_file.write_text(yaml.safe_dump({"items": items}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        created.append(idx_file)
        return created

    def _produce_aud(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        req = ctx["requirement"]
        req_id: str = req["req_id"]
        slug = req_id.lower()
        out_dir = workdir / "game" / "assets" / "audio" / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        spec_text = req.get("deliverable_spec", "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*s", spec_text)
        target_dur = float(m.group(1)) if m else 1.2

        created: List[Path] = []
        items: List[Dict[str, Any]] = []
        triggers = req.get("trigger_event_ids", []) or [None]
        for idx, ev in enumerate(triggers, start=1):
            wav_name = f"{slug}_{idx:02d}.wav"
            wav_path = out_dir / wav_name
            wav_path.write_bytes(_build_silent_wav_bytes(duration_sec=target_dur))
            created.append(wav_path)
            entry: Dict[str, Any] = {
                "asset_id": f"{req_id}-S{idx:02d}",
                "req_id": req_id,
                "file": f"game/assets/audio/{slug}/{wav_name}",
                "kind": "sfx",
                "duration_sec": target_dur,
            }
            if ev:
                entry["binds"] = {"event_trigger": {"event_id": ev}}
            items.append(entry)

        idx_file = out_dir / "index.yaml"
        idx_file.write_text(yaml.safe_dump({"items": items}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        created.append(idx_file)
        return created

    def _produce_integ(self, workdir: Path, ctx: Dict[str, Any]) -> List[Path]:
        gdd_mod = ctx.get("gdd_module") or {}
        gdd_id = gdd_mod.get("gdd_id", "GDD-M01")
        slug = gdd_id.lower()
        mod_dir = workdir / "game" / "src" / "modules" / slug
        tst_dir = workdir / "game" / "tests" / "integration" / slug
        mod_dir.mkdir(parents=True, exist_ok=True)
        tst_dir.mkdir(parents=True, exist_ok=True)

        events = [e["id"] for e in ctx.get("state_event_contract", {}).get("events", [])]
        manifest_path = mod_dir / "module_binding.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "gdd_id": gdd_id,
                    "bound_events": events,
                    "children": [c["task_id"] for c in ctx["requirement"].get("child_deliverables", [])],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        integ_test = tst_dir / "integration_check.json"
        integ_test.write_text(
            json.dumps({"gdd_id": gdd_id, "verified_events": events}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return [manifest_path, integ_test]
