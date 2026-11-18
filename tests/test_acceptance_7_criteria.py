from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.cpm import recalculate_cpm
from backend.models import CollaborationMode, GameDevTask, TaskStatus
from backend.orchestrator import WorkflowOrchestrator
from backend.rules import ROLE_CODES, WorkflowRuleError, check_3d_blacklist
from backend.server import create_server


class TestAcceptanceSevenCriteria(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="rjgc_test_"))
        self.orch = WorkflowOrchestrator(self.tmp_dir / ".sandbox_git")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 判据 1：多案例通用性演示（2D 横版银河城 + 2.5D 等轴测种田 + 自定义计划书含歧义）
    def test_criterion_1_multi_case_generality_and_custom_spec(self) -> None:
        state_a = self.orch.load_preset("case_a_metroidvania")
        self.assertGreaterEqual(len(state_a["tasks"]), 10)
        self.assertEqual(state_a["spec"]["dimension_mode"], "2D")
        for t in state_a["tasks"]:
            self.assertIn(t["stage_id"], {"STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4", "STAGE_5"})
            self.assertTrue(t["assigned_bot_id"])
            self.assertTrue(t["source_clause_ref"])
            self.assertGreater(len(t["acceptance_criteria"]), 0)

        state_b = self.orch.load_preset("case_b_farming_25d")
        self.assertEqual(state_b["spec"]["dimension_mode"], "2.5D")
        self.assertGreaterEqual(len(state_b["tasks"]), 10)
        all_tags_b = {tag for t in state_b["tasks"] for tag in t["required_tags"]}
        self.assertTrue({"isometric_25d_asset", "isometric_coord_math", "y_sort_depth_render"} & all_tags_b)

        # Case C 含歧义自动升级主策拍案，禁止静默脑补
        state_c = self.orch.load_preset("case_c_custom_ambiguity")
        waiting_c = [t for t in state_c["tasks"] if t["status"] == TaskStatus.WAITING_DECISION.value]
        self.assertGreaterEqual(len(waiting_c), 1)
        self.assertIn("歧义", waiting_c[0]["ambiguity_note"])

        # 自由输入全新 2D 计划书
        custom_md = """# 《星海矿工》2D 像素挖掘计划书
## §1 核心定调
- §1.1 确定氧气上限 100 秒与 60FPS 像素视差基准。
## §2 资产与底座
- §2.1 矿工精灵表与地下瓦片贴图。
- §2.2 2D 物理碰撞与挖掘状态机。
## §3 首层垂直切片
- §3.1 首层矿洞合流联调与独立验收。
"""
        state_custom = self.orch.load_custom_spec(custom_md, title="《星海矿工》")
        self.assertEqual({t["stage_id"] for t in state_custom["tasks"]}, {"STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4", "STAGE_5"})

    # 判据 2：聚散过程与阶段切面一目了然（5 阶段 + 散开/联合/集中 + 关键路径）
    def test_criterion_2_convergence_modes_and_critical_path(self) -> None:
        state = self.orch.load_preset("case_a_metroidvania")
        stages = state["stages"]
        self.assertEqual(len(stages), 5)
        self.assertEqual([s["dominant_mode"] for s in stages], [
            CollaborationMode.CONCENTRATED.value,
            CollaborationMode.DISPERSED.value,
            CollaborationMode.JOINT.value,
            CollaborationMode.DISPERSED.value,
            CollaborationMode.CONCENTRATED.value,
        ])
        modes_present = {t["collaboration_mode"] for t in state["tasks"]}
        self.assertEqual(modes_present, {"CONCENTRATED", "DISPERSED", "JOINT"})
        # 存在唯一主干关键路径（slack == 0），且并行支线存在 slack > 0
        cp_tasks = [t for t in state["tasks"] if t["is_critical"]]
        non_cp_tasks = [t for t in state["tasks"] if not t["is_critical"]]
        self.assertGreaterEqual(len(cp_tasks), 7)
        self.assertGreaterEqual(len(non_cp_tasks), 4)
        self.assertTrue(all(t["slack"] == 0.0 for t in cp_tasks))
        self.assertTrue(all(t["slack"] > 0.0 for t in non_cp_tasks))
        joint_tasks = [t for t in state["tasks"] if t["collaboration_mode"] == "JOINT"]
        self.assertTrue(any(len(t["depends_on"]) >= 2 for t in joint_tasks))

        # 修复验证：所有预设的关键路径总工时严格等于 CPM 预计总工期，且严格小于全图累计总工时
        for key in ("case_a_metroidvania", "case_b_farming_25d", "case_c_custom_ambiguity"):
            st = self.orch.load_preset(key)
            m = st["metrics"]
            self.assertAlmostEqual(m["cp_total_hours"], m["project_total_hours"], places=2)
            self.assertLess(m["cp_total_hours"], m["total_hours"])

        # 验证编排器内部原理视图遥测字段完备
        internals = state["internals"]
        self.assertEqual(sum(internals["fsm_counts"].values()), len(state["tasks"]))
        self.assertEqual(len(internals["scheduler_queues"]["bot_slots"]), 6)
        self.assertIn("pipeline_stats", internals)

    # 判据 3：双口径进度与延期顺延实时重算
    def test_criterion_3_dual_metrics_and_delay_propagation(self) -> None:
        state0 = self.orch.load_preset("case_a_metroidvania")
        baseline = state0["metrics"]["project_total_hours"]
        cp_task = next(t for t in state0["tasks"] if t["is_critical"])

        state_delayed = self.orch.inject_delay(cp_task["task_id"], 4.0)
        self.assertAlmostEqual(state_delayed["metrics"]["project_total_hours"], baseline + 4.0, places=2)
        self.assertAlmostEqual(state_delayed["metrics"]["delay_delta_hours"], 4.0, places=2)
        self.assertTrue(state_delayed["metrics"]["has_delay_alert"])
        self.assertIn(cp_task["task_id"], state_delayed["metrics"]["critical_delayed_tasks"])

        # 验证双口径分离：支线任务完成或总体进度与关键路径进度分别计算
        self.assertIn("cp_progress_pct", state_delayed["metrics"])
        self.assertIn("total_progress_pct", state_delayed["metrics"])

    # 判据 4：三维分配可解释 + 改派能力拦截 + 3D 黑名单零容忍拦截
    def test_criterion_4_explainable_assignment_and_rejections(self) -> None:
        state = self.orch.load_preset("case_a_metroidvania")
        art_task = next(t for t in state["tasks"] if t["task_type"] == "art_2d")
        self.assertIn("角色匹配", art_task["assignment_reason"])
        self.assertIn("标签 100% 命中", art_task["assignment_reason"])
        self.assertIn("负载均衡路由", art_task["assignment_reason"])

        # 合法改派：art_bot_01 <-> art_bot_02
        other_art = "art_bot_02" if art_task["assigned_bot_id"] == "art_bot_01" else "art_bot_01"
        reassigned = self.orch.reassign_task(art_task["task_id"], other_art)
        updated_art = next(t for t in reassigned["tasks"] if t["task_id"] == art_task["task_id"])
        self.assertEqual(updated_art["assigned_bot_id"], other_art)

        # 非法改派：art_2d 任务改派给 dev_bot_01 -> 当场拦截报错
        with self.assertRaises(WorkflowRuleError) as ctx:
            self.orch.reassign_task(art_task["task_id"], "dev_bot_01")
        self.assertEqual(ctx.exception.code, "ERR_REASSIGN_CAPABILITY_MISMATCH")

        # 3D 黑名单零容忍拦截（标签与计划书均拦截）
        with self.assertRaises(WorkflowRuleError) as ctx3d_tag:
            check_3d_blacklist(tags=["3d_mesh_modeling", "pbr_shader_baking"])
        self.assertEqual(ctx3d_tag.exception.code, "ERR_3D_PIPELINE_FORBIDDEN")

        with self.assertRaises(WorkflowRuleError) as ctx3d_spec:
            self.orch.load_custom_spec("# 违规测试\n- 使用 3d骨骼蒙皮 与 uv展开 制作角色")
        self.assertEqual(ctx3d_spec.exception.code, "ERR_3D_PIPELINE_FORBIDDEN")

    # 判据 5：角色瘦身 4 类 + 主策旗舰模型唯一拍案 + QA 打回 2 次升级 + 作者/评价者分离
    def test_criterion_5_lean_roles_planner_verdict_and_qa_escalation(self) -> None:
        state = self.orch.load_preset("case_c_custom_ambiguity")
        role_codes = {b["role_code"] for b in state["bots"]}
        self.assertEqual(role_codes, set(ROLE_CODES))
        self.assertEqual(len(role_codes), 4)

        # 仅主策为 flagship 且拥有记忆
        for b in state["bots"]:
            if b["role_code"] == "ROLE_PLANNER":
                self.assertEqual(b["model_tier"], "flagship")
                self.assertTrue(b["has_long_term_memory"])
            else:
                self.assertEqual(b["model_tier"], "standard")
                self.assertFalse(b["has_long_term_memory"])

        # 先处理歧义拍案解锁 Stage 1
        waiting = [t for t in state["tasks"] if t["status"] == "WAITING_DECISION"]
        for wt in waiting:
            state = self.orch.submit_planner_verdict(
                wt["task_id"],
                "锁定防御塔上限 5 级且目标帧率 60FPS",
                "消除计划书歧义，放行 Stage 2",
                memory_ref_id="MEM-PITFALL-002",
            )
        self.assertGreaterEqual(len(state["planner_verdicts"]), 1)
        self.assertEqual(state["planner_verdicts"][0]["planner_model_tier"], "flagship (Tier-1)")

        # 推进编排，验证 Stage 2 美术/程序完成后停在 WAITING_VERIFY（不可自评通过）
        for _ in range(10):
            state = self.orch.step_tick(2.0)
            s2_verify = [t for t in state["tasks"] if t["stage_id"] == "STAGE_2" and t["status"] == "WAITING_VERIFY"]
            if s2_verify:
                break

        # 模拟 QA 连续打回某任务 2 次 -> 自动升级至 WAITING_DECISION
        target = next(t for t in state["tasks"] if t["stage_id"] == "STAGE_2" and t["status"] in ("READY", "RUNNING", "WAITING_VERIFY", "SUCCEEDED"))
        state = self.orch.reject_task_qa(target["task_id"], "第1次打回：锚点偏移")
        t_after1 = next(t for t in state["tasks"] if t["task_id"] == target["task_id"])
        self.assertEqual(t_after1["retry_count"], 1)
        self.assertEqual(t_after1["status"], "FAILED")

        state = self.orch.retry_failed_task(target["task_id"])
        state = self.orch.reject_task_qa(target["task_id"], "第2次打回：依然偏差，超限升级主策")
        t_after2 = next(t for t in state["tasks"] if t["task_id"] == target["task_id"])
        self.assertEqual(t_after2["retry_count"], 2)
        self.assertEqual(t_after2["status"], "WAITING_DECISION")

        # 主策拍案裁决并留痕后恢复 READY
        state = self.orch.submit_planner_verdict(
            target["task_id"],
            "按底部中心 Pivot 重新导出并返工",
            "连续2次被打回，主策介入拍板规范",
            memory_ref_id="MEM-PITFALL-001",
            resolve_action="REWORK_WITH_RULING",
        )
        t_resolved = next(t for t in state["tasks"] if t["task_id"] == target["task_id"])
        self.assertEqual(t_resolved["status"], "READY")

    # 判据 6：主策踩坑教训记忆可查、新增、反束缚校验拦截与撤销
    def test_criterion_6_pitfall_memory_and_anti_dogma_guardrail(self) -> None:
        state = self.orch.get_state()
        self.assertGreaterEqual(len(state["planner_memory"]), 2)

        # 反束缚护栏拦截僵化流程禁令
        with self.assertRaises(WorkflowRuleError) as ctx:
            self.orch.add_pitfall_memory(
                "探索玩法实验",
                "之前尝试创新失败",
                "必须固定使用某工作流模板，禁止探索某类玩法",
                "TEST-DOGMA",
            )
        self.assertEqual(ctx.exception.code, "ERR_ANTI_DOGMA_GUARDRAIL")

        # 合法新增 + 撤销
        added = self.orch.add_pitfall_memory(
            "2D 粒子特效过载掉帧",
            "同屏生成 500 个独立碰撞粒子导致低端机掉帧",
            "粒子层优先采用对象池与关闭非必要物理碰撞检测",
            "EVT-PERF-11",
        )
        mid = added["memory"]["memory_id"]
        toggled = self.orch.toggle_pitfall_memory(mid, False)
        self.assertFalse(toggled["memory"]["active"])

    # 判据 7：环境监听、噪音过滤、主策拍案、脏节点增量热重排（保留已完成成果）+ Git 演化树
    def test_criterion_7_env_listener_hot_replan_and_git_tree(self) -> None:
        state = self.orch.load_preset("case_b_farming_25d")
        # 推进直至 Stage 1 完成 & Stage 2 完成一部分
        for _ in range(25):
            waiting = [t for t in state["tasks"] if t["status"] == "WAITING_DECISION"]
            for wt in waiting:
                state = self.orch.submit_planner_verdict(wt["task_id"], "批准阶段门过关", "符合 2.5D 基线")
            state = self.orch.step_tick(2.0)
            s2_done = [t for t in state["tasks"] if t["stage_id"] == "STAGE_2" and t["status"] == "SUCCEEDED"]
            if len(s2_done) >= 2:
                break

        s1_done_before = [t["task_id"] for t in state["tasks"] if t["stage_id"] == "STAGE_1" and t["status"] == "SUCCEEDED"]
        self.assertGreaterEqual(len(s1_done_before), 1)

        # 注入噪音信号应自动过滤
        noise_res = self.orch.inject_signal("大家午饭吃什么外卖？哈哈", "TEAM_DISCUSSION")
        self.assertTrue(noise_res["signal"]["filtered_as_noise"])
        self.assertFalse(noise_res["signal"]["requires_planner_verdict"])

        # 注入高优先级玩家反馈信号
        sig_res = self.orch.inject_signal(
            "试玩反馈：2.5D 等轴测房间切换时画面生硬，要求增加视差过渡动效与小地图雷达",
            "PLAYER_FEEDBACK",
        )
        sig = sig_res["signal"]
        self.assertFalse(sig["filtered_as_noise"])
        self.assertGreaterEqual(sig["total_score"], 12)
        self.assertTrue(sig["requires_planner_verdict"])

        # 主策拍案并触发增量热重排
        replan_res = self.orch.approve_signal_replan(
            sig["signal_id"],
            "批准新增视差过渡动效与小地图雷达增量任务",
            "保留已完成 Stage 1 与基础资产，仅局部热重排受影响下游节点",
            memory_ref_id="MEM-PITFALL-001",
        )
        cr = replan_res["change_request"]
        after_state = replan_res["state"]
        self.assertGreaterEqual(len(cr["added_task_ids"]), 1)
        # 历史已完成 Stage 1 任务 100% 保留 SUCCEEDED
        after_map = {t["task_id"]: t for t in after_state["tasks"]}
        for tid in s1_done_before:
            self.assertEqual(after_map[tid]["status"], "SUCCEEDED")
            self.assertIn(tid, cr["preserved_succeeded_ids"])

        # 验证 Git 沙箱产生多条提交与变更单分支记录
        self.assertGreaterEqual(len(after_state["git"]["commits"]), 3)
        self.assertIn("cr/", "\n".join(after_state["git"]["branches"]))
        self.assertTrue(after_state["git"]["graph_text"])

    # 额外：验证 DAG 循环依赖检测与阶段门回滚
    def test_extra_dag_cycle_and_rollback(self) -> None:
        t1 = GameDevTask(
            task_id="A", title="A", stage_id="STAGE_1", collaboration_mode=CollaborationMode.CONCENTRATED,
            task_type="design", required_tags=["game_spec_breakdown"], assigned_bot_id="planner_master",
            assignment_reason="ok", depends_on=["B"], duration_hours=2.0,
            acceptance_criteria=["可测标准A"], source_clause_ref="§1.1",
        )
        t2 = GameDevTask(
            task_id="B", title="B", stage_id="STAGE_1", collaboration_mode=CollaborationMode.CONCENTRATED,
            task_type="design", required_tags=["game_spec_breakdown"], assigned_bot_id="planner_master",
            assignment_reason="ok", depends_on=["A"], duration_hours=2.0,
            acceptance_criteria=["可测标准B"], source_clause_ref="§1.2",
        )
        with self.assertRaises(WorkflowRuleError) as ctx:
            recalculate_cpm([t1, t2])
        self.assertEqual(ctx.exception.code, "ERR_DAG_CYCLE")

        # 回滚测试
        self.orch.load_preset("case_a_metroidvania")
        self.orch.step_tick(4.0)
        rb_state = self.orch.rollback_to_stage("STAGE_1")
        self.assertEqual(rb_state["orchestrator"]["sim_clock_hours"], 0.0)

    # 额外：全流程无外部 API Key 跑通至 100% 完成 + HTTP Server 端到端冒烟
    def test_extra_full_e2e_run_and_http_api(self) -> None:
        server = create_server(Path(__file__).resolve().parent.parent, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
                self.assertEqual(r.status, 200)
                data = json.loads(r.read().decode("utf-8"))
                self.assertIn("tasks", data)

            # 测试通过 HTTP 触发 3D 拦截返回 400
            req = Request(
                f"http://127.0.0.1:{port}/api/tasks/validate_tags",
                data=json.dumps({"tags": ["3d_mesh_modeling"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as http_err:
                urlopen(req, timeout=5)
            self.assertEqual(http_err.exception.code, 400)
            http_err.exception.close()
        finally:
            server.shutdown()
            server.server_close()

        # 确定性引擎跑完整个 Case A 到 100% SUCCEEDED
        self.orch.load_preset("case_a_metroidvania")
        for _ in range(120):
            st = self.orch.get_state()
            for wt in [t for t in st["tasks"] if t["status"] == "WAITING_DECISION"]:
                self.orch.submit_planner_verdict(wt["task_id"], "拍板通过阶段门", "全链路自动仿真验收")
            st = self.orch.step_tick(2.0)
            if st["metrics"]["cp_progress_pct"] == 100.0 and st["metrics"]["total_progress_pct"] == 100.0:
                break
        final_st = self.orch.get_state()
        self.assertEqual(final_st["metrics"]["cp_progress_pct"], 100.0)
        self.assertEqual(final_st["metrics"]["total_progress_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
