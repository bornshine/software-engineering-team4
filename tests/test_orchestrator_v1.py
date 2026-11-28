from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from typing import Any, Dict
import yaml

from orchestrator.cpm import compute_cpm
from orchestrator.dag_builder import build_task_graph
from orchestrator.engine import OrchestratorEngine
from orchestrator.handoff_loader import compute_canonical_sha256, compute_file_sha256, load_handoff_bundle
from orchestrator.schemas import (
    DecisionKind,
    ManifestFileEntry,
    OrchestratorError,
    ProjectState,
    TaskKind,
    TaskRecord,
    TaskStatus,
)
from orchestrator.server import OrchestratorHTTPServer
from orchestrator.state_store import force_rmtree
from orchestrator.workers.base import WorkerResult

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_V1 = REPO_ROOT / "fixtures" / "handoff" / "xiyou-nverguo" / "v1.0.0"
FIXTURE_V2 = REPO_ROOT / "fixtures" / "handoff" / "xiyou-nverguo" / "v1.1.0"


def _make_config(tmp_dir: Path, *, spot_check: list[str] | None = None, cost_cap: float = 50.0) -> Dict[str, Any]:
    return {
        "state_root": str(tmp_dir / "state"),
        "workspace_root": str(tmp_dir / "workspace"),
        "ingest": {"auxiliary_files": "compat"},
        "concurrency": {
            "ROLE_TECH_LEAD": 1,
            "ROLE_SYS_DEV": 2,
            "ROLE_NARRATIVE": 1,
            "ROLE_ART_2D": 2,
            "ROLE_AUDIO": 1,
            "ROLE_QA_INTEG": 2,
        },
        "workers": {
            "ROLE_QA_INTEG": {"mode": "api", "vision": True, "timeout_sec": 60},
        },
        "policy": {
            "max_attempts": 3,
            "human_spot_check": [] if spot_check is None else spot_check,
            "oversized_task_hours": 16,
        },
        "budget": {"project_cost_cap": cost_cap, "project_call_cap": 2000, "per_attempt_call_cap": 40},
        "estimation": {"mode": "baseline", "rework_ratio": 0.5},
        "test_mode": {"all_workers_mock": True},
    }


def _rehash_manifest(handoff_dir: Path) -> None:
    mpath = handoff_dir / "manifest.json"
    mdata = json.loads(mpath.read_text(encoding="utf-8"))
    entries = []
    for item in mdata["files"]:
        f = handoff_dir / item["path"]
        item["sha256"] = compute_file_sha256(f)
        entries.append(ManifestFileEntry.model_validate(item))
    mdata["canonical_sha256"] = compute_canonical_sha256(entries)
    mpath.write_text(json.dumps(mdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class TestOrchestratorV1(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="rjgc_orch_test_"))

    def tearDown(self) -> None:
        force_rmtree(self._tmp)

    def _new_engine(self, *, spot_check: list[str] | None = None, cost_cap: float = 50.0) -> OrchestratorEngine:
        return OrchestratorEngine(
            _make_config(self._tmp, spot_check=spot_check, cost_cap=cost_cap),
            base_dir=REPO_ROOT,
            force_mock=True,
        )

    def _complete_all_tasks_and_confirm_g1(self, eng: OrchestratorEngine, hdir: Path) -> None:
        sess, _ = eng.load_project(hdir)
        self.assertEqual(sess.project_state, ProjectState.AWAITING_TECH_CONFIRM)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_until_settled(sess.project_id)

    # O1: 接入校验拒收不产生任何运行态
    def test_o1_ingest_rejects_invalid_handoffs_without_state(self) -> None:
        cases = []
        # 1. 未签字
        d1 = self._tmp / "bad_unsign"
        shutil.copytree(FIXTURE_V1, d1)
        m1 = json.loads((d1 / "manifest.json").read_text(encoding="utf-8"))
        m1["approval_signature"]["status"] = "PENDING"
        (d1 / "manifest.json").write_text(json.dumps(m1), encoding="utf-8")
        cases.append((d1, "ERR_HANDOFF_NOT_APPROVED"))

        # 2. 拦截器未全过
        d2 = self._tmp / "bad_ic"
        shutil.copytree(FIXTURE_V1, d2)
        m2 = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
        m2["interceptors_passed"]["cross_table_state_event_closed"] = False
        (d2 / "manifest.json").write_text(json.dumps(m2), encoding="utf-8")
        cases.append((d2, "ERR_UPSTREAM_INTERCEPTOR_FAILED"))

        # 3. 文件哈希不符
        d3 = self._tmp / "bad_fhash"
        shutil.copytree(FIXTURE_V1, d3)
        (d3 / "MASTER_GDD.md").write_text("# tampered\n", encoding="utf-8")
        cases.append((d3, "ERR_FILE_HASH_MISMATCH"))

        # 4. 包级哈希不符
        d4 = self._tmp / "bad_chash"
        shutil.copytree(FIXTURE_V1, d4)
        m4 = json.loads((d4 / "manifest.json").read_text(encoding="utf-8"))
        m4["canonical_sha256"] = "0" * 64
        (d4 / "manifest.json").write_text(json.dumps(m4), encoding="utf-8")
        cases.append((d4, "ERR_CANONICAL_HASH_MISMATCH"))

        # 5. 交叉引用断裂
        d5 = self._tmp / "bad_xref"
        shutil.copytree(FIXTURE_V1, d5)
        nar = yaml.safe_load((d5 / "requirements/narrative_requirements.yaml").read_text(encoding="utf-8"))
        nar["stage_deliverables"][0]["linked_state_ids"].append("ST_NON_EXISTENT")
        (d5 / "requirements/narrative_requirements.yaml").write_text(yaml.safe_dump(nar, allow_unicode=True), encoding="utf-8")
        _rehash_manifest(d5)
        cases.append((d5, "ERR_CROSS_REF_BROKEN"))

        eng = self._new_engine()
        for idx, (bad_dir, expected_code) in enumerate(cases):
            with self.assertRaises(OrchestratorError) as ctx:
                eng.load_project(bad_dir)
            self.assertEqual(ctx.exception.code, expected_code, f"Case {idx} mismatch")
            self.assertFalse((self._tmp / "state" / "xiyou-nverguo").exists())

    # O2 & O3: 辅助文件兼容/严格模式 & ideas_backlog.md 物理隔离
    def test_o2_o3_auxiliary_adr_compat_strict_and_backlog_isolation(self) -> None:
        eng = self._new_engine()
        with self.assertRaises(OrchestratorError) as ctx:
            eng.load_project(FIXTURE_V1, auxiliary_mode="strict")
        self.assertEqual(ctx.exception.code, "ERR_UNHASHED_AUXILIARY_FILE")

        sess, mode = eng.load_project(FIXTURE_V1, auxiliary_mode="compat")
        self.assertEqual(mode, "NEW")
        self.assertTrue(any("WARN_UNHASHED_AUXILIARY_FILE" in w for w in sess.warnings))
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_until_settled(sess.project_id)

        # 检查 SYS-001 上下文包含 ADR-001
        det = eng.get_task_detail(sess.project_id, "SYS-001")
        self.assertIsNotNone(det["latest_context"])
        ctx_obj = json.loads(det["latest_context"])
        self.assertTrue(any(a["adr_id"] == "ADR-001" for a in ctx_obj["adr_entries"]))

        # O3: 扫描所有已生成 task_context.json，严禁出现 ideas_backlog.md 内容
        ctx_root = self._tmp / "state" / sess.project_id / "contexts"
        for cf in ctx_root.rglob("task_context.json"):
            txt = cf.read_text(encoding="utf-8")
            self.assertNotIn("市井说书人旁观视角彩蛋", txt)
            self.assertNotIn("ideas_backlog", txt)

    # O4 & O5: 确定性建图 (12节点18边) 与共享契约 state_events.json 一致性
    def test_o4_o5_deterministic_dag_and_shared_contract(self) -> None:
        b = load_handoff_bundle(FIXTURE_V1, auxiliary_mode="compat")
        g1 = build_task_graph(b)
        g2 = build_task_graph(b)
        self.assertEqual(len(g1.tasks), 12)
        self.assertEqual(len(g1.edges), 18)
        self.assertEqual(g1.model_dump(mode="json"), g2.model_dump(mode="json"))

        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        contract_file = self._tmp / "workspace" / sess.project_id / "contracts" / "state_events.json"
        self.assertTrue(contract_file.exists())
        c_data = json.loads(contract_file.read_text(encoding="utf-8"))
        self.assertEqual({s["id"] for s in c_data["states"]}, {"ST_WATER_CURSE_STAGE", "ST_COURT_SUSPICION"})
        self.assertEqual(
            {e["id"] for e in c_data["events"]},
            {"EVT_DRINK_RIVER_WATER", "EVT_BREAK_CURSE", "EVT_DEBATE_EXPOSED"},
        )
        # 每条系统 input 都有唯一 IN_* 映射
        total_sys_inputs = sum(len(d.inputs) for d in b.system_requirements.stage_deliverables)
        self.assertEqual(len(c_data["inputs"]), total_sys_inputs)
        self.assertTrue(all(i["id"].startswith("IN_") for i in c_data["inputs"]))

    # O6: 并列双关键路径 cp_length_hours == max(EF)
    def test_o6_dual_parallel_critical_paths_denominator(self) -> None:
        t0 = TaskRecord(task_id="T0", title="Root", kind=TaskKind.TECH, dev_stage="DEV_STAGE_1", role="ROLE_TECH_LEAD", estimate_hours=2.0)
        ta = TaskRecord(task_id="SYS-A", title="PathA", kind=TaskKind.SYS, dev_stage="DEV_STAGE_2", role="ROLE_SYS_DEV", depends_on=["T0"], estimate_hours=10.0)
        tb = TaskRecord(task_id="NAR-B", title="PathB", kind=TaskKind.NAR, dev_stage="DEV_STAGE_2", role="ROLE_NARRATIVE", depends_on=["T0"], estimate_hours=10.0)
        tc = TaskRecord(task_id="AUD-C", title="Side", kind=TaskKind.AUD, dev_stage="DEV_STAGE_2", role="ROLE_AUDIO", depends_on=["T0"], estimate_hours=3.0)
        tf = TaskRecord(task_id="QA-FINAL", title="End", kind=TaskKind.QA_FINAL, dev_stage="DEV_STAGE_4", role="ROLE_QA_INTEG", depends_on=["SYS-A", "NAR-B", "AUD-C"], estimate_hours=4.0)

        summary = compute_cpm([t0, ta, tb, tc, tf], ["gameplay", "narrative"])
        # 两条并行 10h 关键路径：max EF = 2 + 10 + 4 = 16，而非 2+10+10+4=26
        self.assertEqual(summary.cp_length_hours, 16.0)
        self.assertEqual(summary.total_all_hours, 29.0)
        self.assertTrue(ta.is_critical and tb.is_critical)
        # 仅主关键路径节点之和 == cp_length_hours
        main_sum = sum(t.estimate_hours for t in [t0, ta, tb, tc, tf] if t.on_main_critical_path)
        self.assertEqual(main_sum, 16.0)

    # O7 & O11: 门禁阻塞、跳过模式、G4 签字与退回闭包
    def test_o7_o11_gates_skip_waiver_and_g4_reject(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        # 未过 G1 时不可派单
        self.assertEqual(eng.run_wave(sess.project_id), [])

        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        # 先跑 TECH-001
        eng.run_wave(sess.project_id)
        # 把 AUD-002 设为连续失败触发 G2，再验证 skip_and_block 与 skip_with_waiver
        eng.inject_demo_fault(sess.project_id, "AUD-002", ["fail_always"])
        eng.run_until_settled(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["AUD-002"].state, TaskStatus.WAITING_DECISION)

        # 先尝试 skip_and_block -> INTEG-GDD-M02 与 QA-FINAL 进入 BLOCKED
        eng.apply_gate_decision(sess.project_id, "G2", "skip_and_block", target="AUD-002")
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["INTEG-GDD-M02"].state, TaskStatus.BLOCKED)
        self.assertEqual(s.tasks["QA-FINAL"].state, TaskStatus.BLOCKED)

        # 撤销跳过，再设为 skip_with_waiver -> QA-FINAL 解锁直达 AWAITING_RELEASE
        eng.apply_gate_decision(sess.project_id, "G2", "undo_skip", target="AUD-002")
        eng.inject_demo_fault(sess.project_id, "AUD-002", [])
        # 手工再进一次失败 -> 直接调 skip_with_waiver 前先把 AUD-002 放进 WAITING_DECISION
        eng.inject_demo_fault(sess.project_id, "AUD-002", ["fail_always"])
        eng.run_until_settled(sess.project_id)
        eng.apply_gate_decision(sess.project_id, "G2", "skip_with_waiver", target="AUD-002")
        s = eng.run_until_settled(sess.project_id)
        self.assertEqual(s.project_state, ProjectState.AWAITING_RELEASE)
        self.assertIn("AUD-002", s.cpm.waived_tasks)

        # G4 退回 SYS-001 -> SYS-001, INTEG-GDD-M01, QA-FINAL 回 PENDING，项目回 RUNNING
        eng.apply_gate_decision(sess.project_id, "G4", "reject_tasks", payload={"task_ids": ["SYS-001"]})
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.project_state, ProjectState.RUNNING)
        self.assertEqual(s.tasks["SYS-001"].state, TaskStatus.PENDING)
        self.assertEqual(s.tasks["INTEG-GDD-M01"].state, TaskStatus.PENDING)
        self.assertEqual(s.tasks["QA-FINAL"].state, TaskStatus.PENDING)

        # 清空故障后重跑到待封版并最终签字
        eng.run_until_settled(sess.project_id)
        eng.apply_gate_decision(sess.project_id, "G4", "sign_release")
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.project_state, ProjectState.RELEASED)

    # O8 & O9: 并发工作区隔离越界拦截、L1 失败不进 L2、作者不可写场景
    def test_o8_o9_worktree_isolation_write_violation_and_l1_gate(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_wave(sess.project_id)  # TECH-001

        # SYS-001 与 SYS-002 并发：让 SYS-001 越界写入，SYS-002 正常完成
        eng.inject_demo_fault(sess.project_id, "SYS-001", ["write_violation"])
        eng.run_wave(sess.project_id)

        s = eng.get_session(sess.project_id)
        main_ws = self._tmp / "workspace" / sess.project_id
        self.assertFalse((main_ws / "game/src/rogue_outside.txt").exists())
        self.assertEqual(s.tasks["SYS-002"].state, TaskStatus.SUCCEEDED)
        self.assertEqual(s.tasks["SYS-001"].attempts_failed, 1)
        self.assertEqual(s.tasks["SYS-001"].delay_hours, 3.0)

        # 验证作者写入场景目录一样被判越界拦截，且 WRITE_VIOLATION 未进 L2
        class RogueScenarioWriter:
            role = "ROLE_SYS_DEV"
            mode = "mock"
            def run(self, ctx, workdir, timeout_sec):
                sc_file = workdir / "game/tests/scenarios/sys-001/index.yaml"
                sc_file.write_text("tampered: true\n", encoding="utf-8")
                from orchestrator.schemas import ArtifactManifest
                return WorkerResult(ok=True, manifest=ArtifactManifest(task_id=ctx["task_id"], attempt=ctx["attempt"], files=[]), api_calls=1, cost=0.01)

        eng.inject_demo_fault(sess.project_id, "SYS-001", [])
        eng.worker_overrides["SYS-001"] = RogueScenarioWriter()
        eng.run_wave(sess.project_id)
        events = eng.store.read_events(sess.project_id)
        l2_for_sys1 = [e for e in events if e["event_type"] == "VERIFY_L2_DONE" and e.get("task_id") == "SYS-001"]
        self.assertEqual(len(l2_for_sys1), 0)
        viol_for_sys1 = [e for e in events if e["event_type"] == "WRITE_VIOLATION" and e.get("task_id") == "SYS-001"]
        self.assertEqual(len(viol_for_sys1), 2)

    # O10: 失败 3 次进 G2，取消与场景重写不计失败次数
    def test_o10_retry_exhausted_and_non_penalized_dispute_cancel(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_wave(sess.project_id)  # TECH-001

        # 先注入场景争议并重写 -> attempts_failed 必须保持 0
        eng.inject_demo_fault(sess.project_id, "SYS-001", ["scenario_dispute"])
        eng.run_wave(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["SYS-001"].state, TaskStatus.WAITING_DECISION)
        self.assertEqual(s.tasks["SYS-001"].decision_kind, DecisionKind.SCENARIO_DISPUTE)
        self.assertEqual(s.tasks["SYS-001"].attempts_failed, 0)

        eng.apply_gate_decision(sess.project_id, "G2", "rewrite_scenario", target="SYS-001")
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["SYS-001"].state, TaskStatus.READY)
        self.assertEqual(s.tasks["SYS-001"].attempts_failed, 0)

        # 改注入 fail_always，第 1/2/3 次失败后进入 RETRY_EXHAUSTED
        eng.inject_demo_fault(sess.project_id, "SYS-001", ["fail_always"])
        eng.run_until_settled(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["SYS-001"].attempts_failed, 3)
        self.assertEqual(s.tasks["SYS-001"].state, TaskStatus.WAITING_DECISION)
        self.assertEqual(s.tasks["SYS-001"].decision_kind, DecisionKind.RETRY_EXHAUSTED)

    # O12: 需求缺陷引用校验（伪造降级 vs 合法进 G3 并导出 CR）
    def test_o12_requirement_defect_quote_guard_and_cr_export(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_wave(sess.project_id)

        # 伪造 quote -> 被系统强制降级为 IMPLEMENTATION -> attempts_failed+1 并回 READY
        eng.inject_demo_fault(sess.project_id, "NAR-001", ["req_defect_bad_quote"])
        eng.run_wave(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["NAR-001"].state, TaskStatus.READY)
        self.assertEqual(s.tasks["NAR-001"].attempts_failed, 1)

        # 真实原文 quote -> 进入 G3(REQUIREMENT_DEFECT) 并导出 change_request.yaml
        eng.inject_demo_fault(sess.project_id, "NAR-001", ["req_defect_valid"])
        eng.run_wave(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["NAR-001"].state, TaskStatus.WAITING_DECISION)
        self.assertEqual(s.tasks["NAR-001"].decision_kind, DecisionKind.REQUIREMENT_DEFECT)

        eng.apply_gate_decision(
            sess.project_id,
            "G3",
            "submit_cr",
            target="NAR-001",
            payload={
                "trigger_source": "playtest_feedback",
                "impacted_req_ids": ["NAR-001"],
                "problem_statement": "字数约束过严",
                "requested_delta": "独白上限由60字放宽至80字",
            },
        )
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.tasks["NAR-001"].state, TaskStatus.BLOCKED)
        self.assertEqual(len(s.change_requests), 1)
        cr_file = self._tmp / "state" / sess.project_id / "change_requests" / f"{s.change_requests[0].request_id}.yaml"
        self.assertTrue(cr_file.exists())

    # O13: 崩溃恢复：RUNNING 回 READY（不计失败），SUCCEEDED 不重跑，清理残留工作区
    def test_o13_crash_recovery_resets_running_preserves_succeeded(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_wave(sess.project_id)  # TECH-001 SUCCEEDED

        # 模拟 SYS-001 在 RUNNING 时进程被强杀且遗留 attempts/
        s = eng.get_session(sess.project_id)
        s.tasks["SYS-001"].state = TaskStatus.RUNNING
        orphan = self._tmp / "state" / sess.project_id / "attempts" / "SYS-001" / "1"
        orphan.mkdir(parents=True, exist_ok=True)
        (orphan / "partial.txt").write_text("leftover", encoding="utf-8")
        eng.store.save_session(s)

        eng2 = self._new_engine()
        resumed, mode = eng2.load_project(FIXTURE_V1)
        self.assertEqual(mode, "RESUME")
        self.assertEqual(resumed.tasks["TECH-001"].state, TaskStatus.SUCCEEDED)
        self.assertEqual(resumed.tasks["SYS-001"].state, TaskStatus.READY)
        self.assertEqual(resumed.tasks["SYS-001"].attempts_failed, 0)
        self.assertFalse(orphan.exists())

    # O14: 在途运行期升版 v1.1.0 -> 先排空再 7 复用 + 5 重跑，复用产物哈希不变
    def test_o14_delta_upgrade_while_running_drains_and_reuses_7(self) -> None:
        eng = self._new_engine()
        self._complete_all_tasks_and_confirm_g1(eng, FIXTURE_V1)
        s1 = eng.get_session("xiyou-nverguo")
        reused_targets = ["TECH-001", "SYS-001", "NAR-001", "ART-001", "ART-002", "AUD-001", "INTEG-GDD-M01"]
        old_hashes = {tid: [a.sha256 for a in s1.tasks[tid].artifacts] for tid in reused_targets}

        # 人工模拟其中一个任务恰好处于 RUNNING 在途态时触发升版
        s1.tasks["QA-FINAL"].state = TaskStatus.RUNNING
        eng.store.save_session(s1)

        s2, mode = eng.load_project(FIXTURE_V2)
        self.assertEqual(mode, "UPGRADE")
        delta = s2.delta_history[-1]
        self.assertEqual(sorted(delta.reused_ids), sorted(reused_targets))
        self.assertEqual(
            sorted(delta.dirty_ids),
            sorted(["SYS-002", "NAR-002", "AUD-002", "INTEG-GDD-M02", "QA-FINAL"]),
        )
        for tid in reused_targets:
            self.assertEqual(s2.tasks[tid].state, TaskStatus.SUCCEEDED)
            self.assertEqual([a.sha256 for a in s2.tasks[tid].artifacts], old_hashes[tid])
            self.assertEqual(s2.tasks[tid].produced_in_version, "v1.0.0")

        # 重跑那 5 个脏节点至全量通过
        s2_end = eng.run_until_settled(s2.project_id)
        self.assertEqual(s2_end.project_state, ProjectState.AWAITING_RELEASE)

    # O15: 升版新增影响 SYS-001 的 ADR，即使在 unchanged_ids 也判脏并记一致性告警
    def test_o15_new_adr_dirties_unchanged_task_with_warning(self) -> None:
        eng = self._new_engine()
        self._complete_all_tasks_and_confirm_g1(eng, FIXTURE_V1)

        v2_adr = self._tmp / "v1.1_adr"
        shutil.copytree(FIXTURE_V2, v2_adr)
        (v2_adr / "memory/adr/ADR-002.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": "adr/v1",
                    "adr_id": "ADR-002",
                    "created_at": "2026-11-28T01:00:00Z",
                    "status": "ACCEPTED",
                    "trigger": "test",
                    "context": "new rule for SYS-001",
                    "decision": "extra safeguard",
                    "rationale": "integrity",
                    "impacted_refs": ["SYS-001"],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        s2, mode = eng.load_project(v2_adr)
        self.assertEqual(mode, "UPGRADE")
        delta = s2.delta_history[-1]
        self.assertIn("SYS-001", delta.dirty_ids)
        self.assertIn("INTEG-GDD-M01", delta.dirty_ids)
        self.assertTrue(any("SYS-001" in w and "CONSISTENCY_WARNING" in w for w in delta.warnings))

    # O16: 预算耗尽暂停项目且溢出产物不合入主工作区
    def test_o16_budget_exhausted_pauses_without_merging(self) -> None:
        eng = self._new_engine(cost_cap=1.0)
        sess, _ = eng.load_project(FIXTURE_V1)
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.inject_demo_fault(sess.project_id, "TECH-001", ["budget_spike"])
        eng.run_wave(sess.project_id)
        s = eng.get_session(sess.project_id)
        self.assertEqual(s.project_state, ProjectState.PAUSED)
        self.assertNotEqual(s.tasks["TECH-001"].state, TaskStatus.SUCCEEDED)

    # O17: 缺失 perf_probe 标为 MANUAL_REQUIRED 而非静默通过
    def test_o17_missing_probe_flags_manual_required(self) -> None:
        eng = self._new_engine()
        sess, _ = eng.load_project(FIXTURE_V1)
        profile = sess.tech_profile.model_dump()
        profile["runtime_harness"]["perf_probe"] = None
        eng.apply_gate_decision(sess.project_id, "G1", "confirm", payload={"tech_profile": profile})
        s = eng.run_until_settled(sess.project_id)
        self.assertEqual(s.project_state, ProjectState.AWAITING_RELEASE)
        self.assertTrue(any("perf_probe" in m for m in s.manual_required_items))

    # O18 + HTTP/SSE E2E: 全链路带人工抽检 + REST API 验证
    def test_o18_full_e2e_spot_check_and_rest_server(self) -> None:
        eng = self._new_engine(spot_check=["AUD"])
        frontend_dir = REPO_ROOT / "frontend"
        srv = OrchestratorHTTPServer(("127.0.0.1", 0), eng, frontend_dir)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()

        try:
            def _req(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, Any]:
                data = None if payload is None else json.dumps(payload).encode("utf-8")
                hdrs = {"Content-Type": "application/json"} if payload is not None else {}
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=hdrs, method=method)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw = resp.read().decode("utf-8")
                    ct = resp.headers.get("Content-Type", "")
                    return resp.status, (json.loads(raw) if "json" in ct else raw)

            st, _ = _req("/")
            self.assertEqual(st, 200)
            st, load_res = _req("/api/projects/load", "POST", {"handoff_dir": str(FIXTURE_V1)})
            self.assertEqual(st, 200)
            pid = load_res["session"]["project_id"]

            _req(f"/api/projects/{pid}/gates/G1/decision", "POST", {"option": "confirm"})
            s = eng.run_until_settled(pid)
            # AUD-001 & AUD-002 停在 SPOT_CHECK
            self.assertEqual(s.tasks["AUD-001"].decision_kind, DecisionKind.SPOT_CHECK)
            self.assertEqual(s.tasks["AUD-002"].decision_kind, DecisionKind.SPOT_CHECK)

            _req(f"/api/projects/{pid}/gates/G2/decision", "POST", {"option": "approve", "target": "AUD-001"})
            _req(f"/api/projects/{pid}/gates/G2/decision", "POST", {"option": "approve", "target": "AUD-002"})
            s = eng.run_until_settled(pid)
            self.assertEqual(s.project_state, ProjectState.AWAITING_RELEASE)

            _req(f"/api/projects/{pid}/gates/G4/decision", "POST", {"option": "sign_release"})
            st, gres = _req(f"/api/projects/{pid}/graph")
            self.assertEqual(st, 200)
            self.assertEqual(gres["project_state"], "RELEASED")
            self.assertEqual(gres["cpm"]["progress_cp"], 100.0)

            st, tres = _req(f"/api/projects/{pid}/trace/SYS-001")
            self.assertEqual(st, 200)
            self.assertEqual(tres["gdd_module"]["gdd_id"], "GDD-M01")
            self.assertIn("ADR-001", tres["adr_refs"])
        finally:
            srv.shutdown()
            srv.server_close()

    # v1.2 契约向后兼容测试
    def test_v12_contract_compatibility(self) -> None:
        v12_dir = self._tmp / "handoff_v12"
        shutil.copytree(FIXTURE_V1, v12_dir)

        gdd = yaml.safe_load((v12_dir / "gdd_index.yaml").read_text(encoding="utf-8"))
        gdd["schema_version"] = "gdd_index/v1.2"
        gdd["rubric_coverage_map"] = {"R01": "GDD-M01", "R07": "GDD-M02"}
        gdd["pacing_summary"] = {"first_5min_new_concepts": 2, "anchor_module_count": 1}
        for idx, mod in enumerate(gdd["modules"]):
            mod.pop("summary", None)
            mod["focus_tier"] = "FLOW" if idx == 0 else "ANCHOR"
            mod["entry_trigger"] = "渡口误饮 / 朝堂开启"
            mod["core_rules"] = "规则详见条款"
            mod["win_exit"] = "通关出口"
            mod["fail_exit"] = "失败出口"
            mod["experience_intent"] = "克制博弈"
            mod["acceptance_oracle"] = "断言全过"
        (v12_dir / "gdd_index.yaml").write_text(yaml.safe_dump(gdd, allow_unicode=True, sort_keys=False), encoding="utf-8")

        sys_y = yaml.safe_load((v12_dir / "requirements/system_requirements.yaml").read_text(encoding="utf-8"))
        sys_y["schema_version"] = "system_requirements/v1.1"
        sys_y["understanding_echo"] = {"summary": "双轨博弈系统", "anti_examples": ["绝不做打怪升级"]}
        sys_y["explicit_na_refs"] = []
        sys_y["global_constraints"]["shared_entity_dictionary"] = [{"entity_id": "ENT_HERO", "name": "取经人代表"}]
        sys_y["system_interaction_matrix"] = [
            {"pair": ["SYS-001", "SYS-002"], "concurrent_trigger": "同帧", "resolution_rule": "破咒优先"}
        ]
        for s in sys_y["stage_deliverables"]:
            s["tree_path"] = f"SYSTEMS/{s['req_id']}"
        (v12_dir / "requirements/system_requirements.yaml").write_text(
            yaml.safe_dump(sys_y, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        for fname, ver, tp in (
            ("requirements/narrative_requirements.yaml", "narrative_requirements/v1.1", "WORLD/A"),
            ("requirements/art_requirements.yaml", "art_requirements/v1.1", "SYSTEMS/SYS-001"),
            ("requirements/audio_requirements.yaml", "audio_requirements/v1.1", "WORLD/B"),
        ):
            doc = yaml.safe_load((v12_dir / fname).read_text(encoding="utf-8"))
            doc["schema_version"] = ver
            doc["understanding_echo"] = {"summary": "复述一致", "anti_examples": ["反例1"]}
            doc["explicit_na_refs"] = []
            for item in doc["stage_deliverables"]:
                item["tree_path"] = tp
            (v12_dir / fname).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

        mdata = json.loads((v12_dir / "manifest.json").read_text(encoding="utf-8"))
        mdata["contract_version"] = "layer1-handoff/v1.2"
        mdata["interceptors_passed"].update(
            {
                "gdd_bidirectional_na_closed": True,
                "no_placeholder_words_clean": True,
                "pacing_and_cognitive_load_audit": True,
                "understanding_echo_aligned": True,
            }
        )
        (v12_dir / "manifest.json").write_text(json.dumps(mdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _rehash_manifest(v12_dir)

        eng = self._new_engine()
        sess, mode = eng.load_project(v12_dir)
        self.assertEqual(mode, "NEW")
        self.assertEqual(len(sess.tasks), 12)
        self.assertEqual(len(sess.edges), 18)

        # 验证 SYS-001 上下文透传了 understanding_echo 与 system_interaction_matrix
        eng.apply_gate_decision(sess.project_id, "G1", "confirm")
        eng.run_wave(sess.project_id)
        eng.run_wave(sess.project_id)
        det = eng.get_task_detail(sess.project_id, "SYS-001")
        ctx_obj = json.loads(det["latest_context"])
        self.assertEqual(ctx_obj["understanding_echo"]["summary"], "双轨博弈系统")
        self.assertEqual(len(ctx_obj["system_interaction_matrix"]), 1)

        # 若新增 v1.2 拦截器为 False，则必须拒收
        v12_bad = self._tmp / "handoff_v12_bad"
        shutil.copytree(v12_dir, v12_bad)
        bad_m = json.loads((v12_bad / "manifest.json").read_text(encoding="utf-8"))
        bad_m["interceptors_passed"]["pacing_and_cognitive_load_audit"] = False
        (v12_bad / "manifest.json").write_text(json.dumps(bad_m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _rehash_manifest(v12_bad)
        eng_bad = self._new_engine()
        with self.assertRaises(OrchestratorError) as err:
            eng_bad.load_project(v12_bad, force_new_project=True)
        self.assertEqual(err.exception.code, "ERR_UPSTREAM_INTERCEPTOR_FAILED")


if __name__ == "__main__":
    unittest.main()
