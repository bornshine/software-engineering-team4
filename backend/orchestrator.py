from __future__ import annotations

import copy
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional
from .cpm import compute_dashboard_metrics, recalculate_cpm
from .decomposer import decompose_spec_markdown, get_preset_case
from .git_sandbox import GitSandbox
from .listener import apply_incremental_hot_replan, evaluate_environment_signal
from .models import (
    BotCard,
    ChangeRequestRecord,
    CollaborationMode,
    EnvSignalRecord,
    GameDevTask,
    PitfallMemoryItem,
    PlannerVerdictRecord,
    SpecDocument,
    StageSnapshot,
    TaskStatus,
)
from .planner_memory import PlannerMemoryStore, utc_now_str
from .presets import PRESET_SPECS
from .rules import (
    FORBIDDEN_3D_BLACKLIST,
    STAGE_DEFINITIONS,
    WorkflowRuleError,
    check_3d_blacklist,
    create_default_bots,
    validate_reassignment,
)


class WorkflowOrchestrator:
    """2D/2.5D 游戏开发动态编排仿真核心引擎。"""

    def __init__(self, sandbox_dir: Path):
        self.lock = RLock()
        self.bots: List[BotCard] = create_default_bots()
        self.memory_store = PlannerMemoryStore()
        self.git_sandbox = GitSandbox(sandbox_dir)
        self.spec: Optional[SpecDocument] = None
        self.tasks: List[GameDevTask] = []
        self.project_total_hours: float = 0.0
        self.baseline_total_hours: float = 0.0
        self.sim_clock_hours: float = 0.0
        self.tick_count: int = 0
        self.is_running: bool = False
        self.signals: List[EnvSignalRecord] = []
        self.change_requests: List[ChangeRequestRecord] = []
        self.snapshots: Dict[str, StageSnapshot] = {}
        self.events: List[Dict] = []
        self._snapshot_seq = 0
        # 默认加载案例 A
        self.load_preset("case_a_metroidvania")

    def _log_event(self, kind: str, title: str, detail: str = "") -> None:
        self.events.insert(
            0,
            {
                "timestamp": utc_now_str(),
                "sim_hour": round(self.sim_clock_hours, 1),
                "kind": kind,
                "title": title,
                "detail": detail,
            },
        )
        self.events = self.events[:120]

    def _recalc_loads_and_cpm(self) -> None:
        load_map: Dict[str, float] = {b.bot_id: 0.0 for b in self.bots}
        for t in self.tasks:
            if t.status != TaskStatus.SKIPPED and t.assigned_bot_id in load_map:
                load_map[t.assigned_bot_id] += (t.duration_hours + t.delay_hours)
        for b in self.bots:
            b.current_load_hours = round(load_map[b.bot_id], 2)
        self.tasks, self.project_total_hours, self.baseline_total_hours = recalculate_cpm(self.tasks)

    def _capture_snapshot(self, stage_id: str, label: str) -> None:
        self._snapshot_seq += 1
        snap = StageSnapshot(
            snapshot_id=f"SNAP-{self._snapshot_seq:03d}",
            stage_id=stage_id,
            label=label,
            timestamp=utc_now_str(),
            sim_clock_hours=self.sim_clock_hours,
            tasks_data=[t.model_dump(mode="json") for t in self.tasks],
            bot_loads={b.bot_id: b.current_load_hours for b in self.bots},
        )
        self.snapshots[stage_id] = snap

    def _init_project_state(self, spec: SpecDocument, tasks: List[GameDevTask]) -> None:
        self.spec = spec
        self.tasks = tasks
        self.sim_clock_hours = 0.0
        self.tick_count = 0
        self.is_running = False
        self.signals = []
        self.change_requests = []
        self.snapshots = {}
        self.events = []
        self.memory_store.verdicts = []
        self.memory_store._verdict_seq = 0

        git_rec = self.git_sandbox.init_repo(
            spec.spec_id, spec.title, spec.raw_markdown, spec.content_sha256
        )
        self.spec.git_commit_hash = git_rec.commit_hash
        self._recalc_loads_and_cpm()
        self._capture_snapshot("STAGE_1", "Stage 1 起点 · 立项规格基线")
        self._log_event("INIT", f"已装载规格：{spec.title}", f"拆解生成 {len(tasks)} 个 DAG 任务，Git 基线 {git_rec.commit_hash}")

        for t in self.tasks:
            if t.status == TaskStatus.WAITING_DECISION:
                self._log_event(
                    "DECISION_NEEDED",
                    f"[{t.task_id}] 触发歧义升级等待主策拍案",
                    t.ambiguity_note or "计划书条款存在歧义",
                )

    def load_preset(self, case_key: str) -> Dict:
        with self.lock:
            self.bots = create_default_bots()
            spec, tasks = get_preset_case(case_key, self.bots)
            self._init_project_state(spec, tasks)
            return self.get_state()

    def load_custom_spec(
        self,
        raw_markdown: str,
        title: Optional[str] = None,
        genre: str = "2D / 2.5D 定制游戏",
    ) -> Dict:
        with self.lock:
            fresh_bots = create_default_bots()
            spec, tasks = decompose_spec_markdown(
                raw_markdown=raw_markdown,
                bots=fresh_bots,
                title=title,
                genre=genre,
            )
            self.bots = fresh_bots
            self._init_project_state(spec, tasks)
            return self.get_state()

    def _unlock_ready_tasks(self) -> None:
        task_map = {t.task_id: t for t in self.tasks}
        stage_first_unlocked: set[str] = set()
        for t in self.tasks:
            if t.status == TaskStatus.PENDING:
                if all(task_map[d].status in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED) for d in t.depends_on if d in task_map):
                    t.status = TaskStatus.READY
                    stage_first_unlocked.add(t.stage_id)
        for st_id in stage_first_unlocked:
            if st_id not in self.snapshots:
                self._capture_snapshot(st_id, f"{st_id} 启动前门禁快照")

    def _complete_task_succeeded(self, task: GameDevTask, summary: str) -> None:
        task.status = TaskStatus.SUCCEEDED
        task.progress_hours = task.duration_hours + task.delay_hours
        task.deliverable_summary = summary
        task.dirty_flag = False
        branch = f"feature/{task.stage_id}-{task.task_id}"
        artifact_path = f"deliverables/{task.stage_id}/{task.task_id}.md"
        artifact_body = (
            f"# {task.task_id}: {task.title}\n"
            f"- Assigned Bot: {task.assigned_bot_id}\n"
            f"- Source Clause: {task.source_clause_ref}\n"
            f"- Summary: {summary}\n"
        )
        rec = self.git_sandbox.commit_event(
            branch=branch,
            message=f"feat({task.stage_id}): complete {task.task_id} {task.title} [{task.assigned_bot_id}]",
            event_type="TASK_DONE",
            related_ids=[task.task_id, task.assigned_bot_id],
            artifact_rel_path=artifact_path,
            artifact_content=artifact_body,
        )
        task.git_commit_hash = rec.commit_hash
        task.execution_logs.append(f"[T+{self.sim_clock_hours:.1f}h] 验收通过并留痕 Git {rec.commit_hash}")
        self._log_event("SUCCEEDED", f"[{task.task_id}] 已完成 ({task.assigned_bot_id})", summary)

    def step_tick(self, hours_per_tick: float = 2.0) -> Dict:
        with self.lock:
            self.tick_count += 1
            self.sim_clock_hours = round(self.sim_clock_hours + hours_per_tick, 2)

            # 1. 解锁满足前置依赖的 PENDING 任务
            self._unlock_ready_tasks()

            # 2. 独立 QA 核验处于 WAITING_VERIFY 的任务（作者与评价者严格分离）
            qa_busy = any(t.assigned_bot_id == "qa_bot_01" and t.status == TaskStatus.RUNNING for t in self.tasks)
            if not qa_busy:
                waiting_verify = [t for t in self.tasks if t.status == TaskStatus.WAITING_VERIFY]
                if waiting_verify:
                    target = waiting_verify[0]
                    self._complete_task_succeeded(
                        target,
                        f"已由独立 QA (qa_bot_01) 依据 {len(target.acceptance_criteria)} 条验收标准核验通过（{target.verify_mode}）。",
                    )

            # 3. 推进 RUNNING 任务进度
            for t in self.tasks:
                if t.status != TaskStatus.RUNNING:
                    continue
                t.progress_hours = round(t.progress_hours + hours_per_tick, 2)
                eff_dur = t.duration_hours + t.delay_hours
                if t.progress_hours >= eff_dur:
                    # 判定进入主策拍案门、独立 QA 核验门，或直接完成
                    needs_planner_gate = (
                        (t.ambiguity_note and not t.verdict_id)
                        or (t.task_type == "design" and t.collaboration_mode == CollaborationMode.CONCENTRATED and not t.verdict_id)
                    )
                    if needs_planner_gate:
                        t.status = TaskStatus.WAITING_DECISION
                        t.execution_logs.append(f"[T+{self.sim_clock_hours:.1f}h] 抵达主策拍案确认门，等待 Tier-1 主策裁决。")
                        self._log_event("DECISION_NEEDED", f"[{t.task_id}] 到达阶段收口门禁", "等待主策使用旗舰模型一锤定音拍案。")
                    elif t.task_type in ("art_2d", "dev_2d"):
                        t.status = TaskStatus.WAITING_VERIFY
                        t.execution_logs.append(f"[T+{self.sim_clock_hours:.1f}h] 交付物自检完成，已提交独立 QA (qa_bot_01) 核验。")
                        self._log_event("WAITING_VERIFY", f"[{t.task_id}] 待独立 QA 验收", f"执行 Bot {t.assigned_bot_id} 无权自评通过。")
                    else:
                        # qa_integ 任务或已拍案的 design 任务完成
                        self._complete_task_succeeded(
                            t,
                            f"{t.assigned_bot_id} 完成独立回归/集成任务并通过阶段核验。",
                        )

            # 4. 为空闲 Bot 调度 READY 任务（单 Bot 实例默认串行槽位）
            busy_bots = {t.assigned_bot_id for t in self.tasks if t.status == TaskStatus.RUNNING}
            ready_queue = sorted(
                [t for t in self.tasks if t.status == TaskStatus.READY],
                key=lambda x: (0 if x.is_critical else 1, x.es, x.task_id),
            )
            for t in ready_queue:
                if t.assigned_bot_id in busy_bots:
                    continue
                if t.ambiguity_note and not t.verdict_id:
                    t.status = TaskStatus.WAITING_DECISION
                    self._log_event("DECISION_NEEDED", f"[{t.task_id}] 存在规格歧义", t.ambiguity_note)
                    continue
                t.status = TaskStatus.RUNNING
                busy_bots.add(t.assigned_bot_id)
                t.execution_logs.append(f"[T+{self.sim_clock_hours:.1f}h] {t.assigned_bot_id} 开始执行任务。")

            # 5. 再次检查是否有新解锁的 READY 任务
            self._unlock_ready_tasks()

            # 6. 若全部完成则自动停止运行态
            if all(t.status in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED) for t in self.tasks):
                self.is_running = False
                self._log_event("FINISHED", "全流程 5 阶段任务已 100% 收口完成！", f"累计仿真工时 {self.sim_clock_hours:.1f}h")

            return self.get_state()

    def set_running(self, running: bool) -> Dict:
        with self.lock:
            self.is_running = running
            self._log_event("CONTROL", "恢复全局编排" if running else "暂停全局编排")
            return self.get_state()

    def submit_planner_verdict(
        self,
        task_id: str,
        decision_conclusion: str,
        rationale: str,
        memory_ref_id: Optional[str] = None,
        resolve_action: str = "APPROVE_COMPLETE",
    ) -> Dict:
        with self.lock:
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            if task.status != TaskStatus.WAITING_DECISION:
                raise WorkflowRuleError(
                    "ERR_NOT_WAITING_DECISION",
                    f"任务 {task_id} 当前状态为 {task.status.value}，无需主策拍案。",
                )

            trigger = task.ambiguity_note or (
                f"连续被 QA 打回 {task.retry_count} 次升级裁决"
                if task.retry_count >= 2
                else f"阶段收口确认门 ({task.stage_id})"
            )
            verdict = self.memory_store.record_verdict(
                trigger_reason=trigger,
                target_task_ids=[task.task_id],
                decision_conclusion=decision_conclusion,
                rationale=rationale,
                memory_ref_id=memory_ref_id or None,
            )
            task.verdict_id = verdict.verdict_id
            task.ambiguity_note = None
            task.execution_logs.append(
                f"[主策拍案 {verdict.verdict_id} | Tier-1] {decision_conclusion}"
                + (f"（引用教训 {verdict.memory_ref_id}）" if verdict.memory_ref_id else "")
            )

            # 记录到沙箱 Git
            rec = self.git_sandbox.commit_event(
                branch=f"verdict/{verdict.verdict_id}",
                message=f"verdict({task.task_id}): {decision_conclusion[:50]}",
                event_type="VERDICT",
                related_ids=[verdict.verdict_id, task.task_id],
                artifact_rel_path=f"verdicts/{verdict.verdict_id}.json",
                artifact_content=verdict.model_dump_json(indent=2),
            )

            if task.task_type == "design" or resolve_action == "APPROVE_COMPLETE":
                task.status = TaskStatus.SUCCEEDED
                task.progress_hours = task.duration_hours + task.delay_hours
                task.git_commit_hash = rec.commit_hash
                task.deliverable_summary = f"主策拍案终裁：{decision_conclusion}"
            else:
                # 例如 QA 打回 >=2 次升级后，带主策新裁决重新进入 READY 返工
                task.retry_count = 0
                task.progress_hours = 0.0
                task.status = TaskStatus.READY

            self._unlock_ready_tasks()
            self._log_event("VERDICT", f"[{verdict.verdict_id}] 主策已拍案 {task.task_id}", decision_conclusion)
            return self.get_state()

    def reject_task_qa(self, task_id: str, reason: str = "独立 QA 核验不通过：存在验收标准偏差") -> Dict:
        with self.lock:
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            if task.status in (TaskStatus.PENDING, TaskStatus.SKIPPED):
                raise WorkflowRuleError(
                    "ERR_CANNOT_REJECT_PENDING",
                    f"任务 {task_id} 尚未开始（{task.status.value}），无法注入 QA 打回。",
                )

            task.retry_count += 1
            task.progress_hours = 0.0
            task.deliverable_summary = None
            task.execution_logs.append(f"[QA 打回 #{task.retry_count}] {reason}")

            if task.retry_count >= 2:
                task.status = TaskStatus.WAITING_DECISION
                task.verdict_id = None
                self._log_event(
                    "ESCALATED",
                    f"[{task.task_id}] 连续打回 {task.retry_count} 次，自动升级主策拍案！",
                    reason,
                )
            else:
                task.status = TaskStatus.FAILED
                self._log_event(
                    "QA_REJECTED",
                    f"[{task.task_id}] 被独立 QA 打回重做（第 {task.retry_count} 次）",
                    reason,
                )
            return self.get_state()

    def retry_failed_task(self, task_id: str) -> Dict:
        with self.lock:
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            if task.status != TaskStatus.FAILED:
                raise WorkflowRuleError("ERR_NOT_FAILED", f"任务 {task_id} 当前不是 FAILED 状态。")
            task.status = TaskStatus.READY
            task.progress_hours = 0.0
            task.execution_logs.append(f"[T+{self.sim_clock_hours:.1f}h] 触发故障恢复重试（第 {task.retry_count} 次打回后重排）。")
            self._log_event("RETRY", f"[{task.task_id}] 已重新入队待执行", f"当前重试计数 retry_count={task.retry_count}")
            return self.get_state()

    def verify_task_qa(self, task_id: str, passed: bool, note: str = "") -> Dict:
        if not passed:
            return self.reject_task_qa(task_id, note or "人工触发独立 QA 打回")
        with self.lock:
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            if task.status != TaskStatus.WAITING_VERIFY:
                raise WorkflowRuleError("ERR_NOT_WAITING_VERIFY", f"任务 {task_id} 当前不在 WAITING_VERIFY 状态。")
            self._complete_task_succeeded(task, note or "独立 QA 人工确认验收通过。")
            self._unlock_ready_tasks()
            return self.get_state()

    def reassign_task(self, task_id: str, target_bot_id: str) -> Dict:
        with self.lock:
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            target_bot = next((b for b in self.bots if b.bot_id == target_bot_id), None)
            if not target_bot:
                raise WorkflowRuleError("ERR_BOT_NOT_FOUND", f"未找到目标 Bot 实例 {target_bot_id}")

            new_reason = validate_reassignment(task, target_bot, self.bots)
            old_bot = task.assigned_bot_id
            task.assigned_bot_id = target_bot.bot_id
            task.assignment_reason = new_reason
            task.execution_logs.append(
                f"[运行期改派] 由 {old_bot} 改派至 {target_bot.bot_id}，已完整迁移上下文与历史交付日志。"
            )
            self._recalc_loads_and_cpm()
            self._log_event("REASSIGN", f"[{task.task_id}] 改派成功：{old_bot} → {target_bot.bot_id}", new_reason)
            return self.get_state()

    def inject_delay(self, task_id: str, delay_hours: float) -> Dict:
        with self.lock:
            if delay_hours <= 0:
                raise WorkflowRuleError("ERR_INVALID_DELAY", "延期工时必须大于 0。")
            task = next((t for t in self.tasks if t.task_id == task_id), None)
            if not task:
                raise WorkflowRuleError("ERR_TASK_NOT_FOUND", f"未找到任务 {task_id}")
            before_total = self.project_total_hours
            task.delay_hours = round(task.delay_hours + delay_hours, 2)
            task.execution_logs.append(f"[延期注入] 增加延期 +{delay_hours:.1f}h（累计延期 {task.delay_hours:.1f}h）。")
            self._recalc_loads_and_cpm()
            delta = round(self.project_total_hours - before_total, 2)
            self._log_event(
                "DELAY_ALERT" if delta > 0 else "DELAY_ABSORBED",
                f"[{task.task_id}] 延期 +{delay_hours:.1f}h -> 全图工期顺延 +{delta:.1f}h",
                "命中关键路径（slack=0），全图预计完工时间实时顺延！" if delta > 0 else f"由浮动时间 slack={task.slack:.1f}h 吸收，未影响总工期。",
            )
            return self.get_state()

    def rollback_to_stage(self, stage_id: str) -> Dict:
        with self.lock:
            snap = self.snapshots.get(stage_id)
            if not snap:
                raise WorkflowRuleError("ERR_SNAPSHOT_NOT_FOUND", f"暂无 {stage_id} 阶段门快照可回滚。")
            self.tasks = [GameDevTask(**item) for item in snap.tasks_data]
            self.sim_clock_hours = snap.sim_clock_hours
            self.is_running = False
            self._recalc_loads_and_cpm()
            self.git_sandbox.commit_event(
                branch="main",
                message=f"revert(stage): rollback workflow state to {stage_id} ({snap.snapshot_id})",
                event_type="ROLLBACK",
                related_ids=[stage_id, snap.snapshot_id],
            )
            self._log_event("ROLLBACK", f"已回滚至 {stage_id} 快照 ({snap.snapshot_id})", f"时间轴恢复至 {snap.sim_clock_hours:.1f}h")
            return self.get_state()

    def inject_signal(self, raw_text: str, source_type: str = "PLAYER_FEEDBACK") -> Dict:
        with self.lock:
            check_3d_blacklist(raw_text)
            sig = evaluate_environment_signal(raw_text, source_type, len(self.signals) + 1)
            self.signals.insert(0, sig)
            if sig.filtered_as_noise:
                self._log_event("SIGNAL_NOISE", f"[{sig.signal_id}] 噪音信号已自动过滤", sig.extracted_summary)
            elif sig.requires_planner_verdict:
                self._log_event("SIGNAL_HIGH", f"[{sig.signal_id}] 高优先级变更信号待主策拍案", sig.extracted_summary)
            else:
                self._log_event("SIGNAL_LOW", f"[{sig.signal_id}] 低优先级信号已记录", sig.extracted_summary)
            return {"signal": sig.model_dump(mode="json"), "state": self.get_state()}

    def approve_signal_replan(
        self,
        signal_id: str,
        decision_conclusion: str,
        rationale: str,
        memory_ref_id: Optional[str] = None,
    ) -> Dict:
        with self.lock:
            sig = next((s for s in self.signals if s.signal_id == signal_id), None)
            if not sig:
                raise WorkflowRuleError("ERR_SIGNAL_NOT_FOUND", f"未找到环境信号 {signal_id}")
            if sig.filtered_as_noise:
                raise WorkflowRuleError("ERR_NOISE_CANNOT_REPLAN", "噪音信号不允许触发需求变更。")
            if sig.status == "APPROVED":
                raise WorkflowRuleError("ERR_SIGNAL_ALREADY_APPROVED", f"信号 {signal_id} 已拍案重排。")

            verdict = self.memory_store.record_verdict(
                trigger_reason=f"环境监听高优先级变更信号 {sig.signal_id} (score={sig.total_score}/20)",
                target_task_ids=[],
                decision_conclusion=decision_conclusion,
                rationale=rationale,
                memory_ref_id=memory_ref_id or None,
            )
            cr, updated_tasks = apply_incremental_hot_replan(
                signal=sig,
                spec=self.spec,
                tasks=self.tasks,
                bots=self.bots,
                verdict_id=verdict.verdict_id,
                cr_seq=len(self.change_requests) + 1,
            )
            self.tasks = updated_tasks
            verdict.target_task_ids = list(cr.dirty_task_ids)
            sig.status = "APPROVED"

            rec = self.git_sandbox.commit_event(
                branch=f"cr/{cr.cr_id}",
                message=f"feat(replan): {cr.cr_id} {sig.signal_id} -> add {cr.added_task_ids}",
                event_type="HOT_REPLAN",
                related_ids=[cr.cr_id, sig.signal_id, verdict.verdict_id] + cr.added_task_ids,
                artifact_rel_path=f"change_requests/{cr.cr_id}.json",
                artifact_content=cr.model_dump_json(indent=2),
            )
            cr.git_commit_hash = rec.commit_hash
            self.change_requests.insert(0, cr)
            self._recalc_loads_and_cpm()
            self._log_event(
                "HOT_REPLAN",
                f"[{cr.cr_id}] 增量热重排完成（Git {rec.commit_hash}）",
                cr.summary,
            )
            return {"change_request": cr.model_dump(mode="json"), "verdict": verdict.model_dump(mode="json"), "state": self.get_state()}

    def add_pitfall_memory(
        self,
        context_scenario: str,
        past_failure: str,
        lesson_learned: str,
        source_event_id: str,
    ) -> Dict:
        with self.lock:
            item = self.memory_store.add_memory(context_scenario, past_failure, lesson_learned, source_event_id)
            self._log_event("MEMORY_ADD", f"[{item.memory_id}] 主策新增踩坑教训记忆", item.lesson_learned)
            return {"memory": item.model_dump(mode="json"), "state": self.get_state()}

    def toggle_pitfall_memory(self, memory_id: str, active: bool) -> Dict:
        with self.lock:
            item = self.memory_store.set_memory_active(memory_id, active)
            self._log_event(
                "MEMORY_TOGGLE",
                f"[{item.memory_id}] {'启用' if active else '已撤销'}主策教训记忆",
                item.lesson_learned,
            )
            return {"memory": item.model_dump(mode="json"), "state": self.get_state()}

    def validate_arbitrary_task_tags(self, tags: List[str]) -> Dict:
        """供前端/验收测试验证 3D 黑名单与标签白名单校验接口。"""
        check_3d_blacklist(tags=tags)
        return {"valid": True, "tags": tags}

    def _build_internals_snapshot(self, metrics: Dict) -> Dict:
        task_map = {t.task_id: t for t in self.tasks}
        fsm_counts = {
            "PENDING": 0,
            "READY": 0,
            "RUNNING": 0,
            "WAITING_DECISION": 0,
            "WAITING_VERIFY": 0,
            "SUCCEEDED": 0,
            "FAILED": 0,
            "SKIPPED": 0,
        }
        for t in self.tasks:
            key = "FAILED" if t.status == TaskStatus.BLOCKED else t.status.value
            fsm_counts[key] = fsm_counts.get(key, 0) + 1

        pending_pool = []
        for t in self.tasks:
            if t.status == TaskStatus.PENDING:
                blockers = [
                    d for d in t.depends_on
                    if d in task_map and task_map[d].status not in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED)
                ]
                pending_pool.append({
                    "task_id": t.task_id,
                    "title": t.title,
                    "stage_id": t.stage_id,
                    "assigned_bot_id": t.assigned_bot_id,
                    "blocked_by": blockers,
                })

        ready_queue = [
            {
                "task_id": t.task_id,
                "title": t.title,
                "stage_id": t.stage_id,
                "assigned_bot_id": t.assigned_bot_id,
                "is_critical": t.is_critical,
                "es": t.es,
                "duration_hours": t.duration_hours + t.delay_hours,
            }
            for t in sorted(
                [x for x in self.tasks if x.status == TaskStatus.READY],
                key=lambda x: (0 if x.is_critical else 1, x.es, x.task_id),
            )
        ]

        bot_slots = []
        for b in self.bots:
            running_t = next(
                (t for t in self.tasks if t.assigned_bot_id == b.bot_id and t.status == TaskStatus.RUNNING),
                None,
            )
            bot_slots.append({
                "bot_id": b.bot_id,
                "role_code": b.role_code,
                "display_name": b.display_name,
                "model_tier": b.model_tier,
                "current_load_hours": round(b.current_load_hours, 2),
                "slot_status": "BUSY" if running_t else "IDLE",
                "running_task_id": running_t.task_id if running_t else None,
                "running_title": running_t.title if running_t else None,
                "progress_hours": round(running_t.progress_hours, 1) if running_t else 0.0,
                "effective_duration": round(running_t.duration_hours + running_t.delay_hours, 1) if running_t else 0.0,
            })

        gate_queue = [
            {
                "task_id": t.task_id,
                "title": t.title,
                "status": t.status.value,
                "assigned_bot_id": t.assigned_bot_id,
                "retry_count": t.retry_count,
                "reason": t.ambiguity_note or (
                    f"打回 {t.retry_count} 次升级主策拍案" if t.status == TaskStatus.WAITING_DECISION and t.retry_count >= 2
                    else "等待独立 QA (qa_bot_01) 验收" if t.status == TaskStatus.WAITING_VERIFY
                    else "阶段门待主策拍案确认" if t.status == TaskStatus.WAITING_DECISION
                    else "QA 打回待恢复重试"
                ),
            }
            for t in self.tasks
            if t.status in (TaskStatus.WAITING_DECISION, TaskStatus.WAITING_VERIFY, TaskStatus.FAILED, TaskStatus.BLOCKED)
        ]

        edge_count = sum(len(t.depends_on) for t in self.tasks)
        ambiguity_count = sum(1 for t in self.tasks if t.ambiguity_note)
        return {
            "pipeline_stats": {
                "clauses_count": len(self.spec.clauses) if self.spec else 0,
                "ambiguity_count": ambiguity_count,
                "blacklist_rule_count": len(FORBIDDEN_3D_BLACKLIST),
                "dag_nodes_count": len(self.tasks),
                "dag_edges_count": edge_count,
                "cp_nodes_count": len(metrics["critical_path_task_ids"]),
                "project_total_hours": metrics["project_total_hours"],
                "routed_tasks_count": len(self.tasks),
                "bots_count": len(self.bots),
                "max_bot_load_hours": max((b.current_load_hours for b in self.bots), default=0.0),
                "tick_count": self.tick_count,
                "ready_count": fsm_counts["READY"],
                "running_count": fsm_counts["RUNNING"],
                "waiting_verify_count": fsm_counts["WAITING_VERIFY"],
                "waiting_decision_count": fsm_counts["WAITING_DECISION"],
                "verdicts_count": len(self.memory_store.verdicts),
                "cr_count": len(self.change_requests),
                "git_commits_count": len(self.git_sandbox.commits),
            },
            "fsm_counts": fsm_counts,
            "scheduler_queues": {
                "pending_pool": pending_pool,
                "ready_queue": ready_queue,
                "bot_slots": bot_slots,
                "gate_queue": gate_queue,
            },
        }

    def get_state(self) -> Dict:
        with self.lock:
            metrics = compute_dashboard_metrics(
                self.tasks, self.bots, self.project_total_hours, self.baseline_total_hours
            )
            return {
                "presets": [
                    {"key": k, "title": v["title"], "genre": v["genre"], "dimension_mode": v["dimension_mode"]}
                    for k, v in PRESET_SPECS.items()
                ],
                "stages": [s.model_dump(mode="json") for s in STAGE_DEFINITIONS],
                "spec": self.spec.model_dump(mode="json") if self.spec else None,
                "bots": [b.model_dump(mode="json") for b in self.bots],
                "tasks": [t.model_dump(mode="json") for t in self.tasks],
                "metrics": metrics,
                "orchestrator": {
                    "is_running": self.is_running,
                    "sim_clock_hours": self.sim_clock_hours,
                    "tick_count": self.tick_count,
                    "available_snapshots": [
                        {"stage_id": k, "snapshot_id": v.snapshot_id, "label": v.label, "sim_clock_hours": v.sim_clock_hours}
                        for k, v in self.snapshots.items()
                    ],
                },
                "internals": self._build_internals_snapshot(metrics),
                "planner_memory": [m.model_dump(mode="json") for m in self.memory_store.memories],
                "planner_verdicts": [v.model_dump(mode="json") for v in self.memory_store.verdicts],
                "signals": [s.model_dump(mode="json") for s in self.signals],
                "change_requests": [c.model_dump(mode="json") for c in self.change_requests],
                "git": {
                    "branches": self.git_sandbox.get_branches(),
                    "commits": [c.model_dump(mode="json") for c in self.git_sandbox.commits],
                    "graph_text": self.git_sandbox.get_graph_text(),
                },
                "events": self.events,
            }
