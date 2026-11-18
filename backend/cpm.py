from __future__ import annotations

from collections import deque
from typing import Dict, List, Tuple
from .models import BotCard, GameDevTask, TaskStatus
from .rules import STAGE_DEFINITIONS, WorkflowRuleError, check_3d_blacklist


VAGUE_ACCEPTANCE_PHRASES = {"完成开发", "优化体验", "做好就行", "待完善", "完成功能"}


def validate_task_contract(tasks: List[GameDevTask]) -> None:
    """第 3.2 节入库校验纪律：缺追溯源、缺负责Bot、缺CPM限时、空泛验收标准或循环依赖一律拦截。"""
    ids = {t.task_id for t in tasks}
    for t in tasks:
        if not t.source_clause_ref or not t.source_clause_ref.strip():
            raise WorkflowRuleError(
                "ERR_MISSING_TRACEABILITY",
                f"任务 {t.task_id} 缺少设计规格追溯锚点 source_clause_ref。",
                {"task_id": t.task_id},
            )
        if not t.assigned_bot_id or not t.assigned_bot_id.strip():
            raise WorkflowRuleError(
                "ERR_MISSING_ASSIGNED_BOT",
                f"任务 {t.task_id} 缺少唯一主责 Bot。",
                {"task_id": t.task_id},
            )
        if t.duration_hours <= 0:
            raise WorkflowRuleError(
                "ERR_INVALID_DURATION",
                f"任务 {t.task_id} 工期 duration_hours 必须 > 0。",
                {"task_id": t.task_id},
            )
        if not t.acceptance_criteria or any(
            not c.strip() or c.strip() in VAGUE_ACCEPTANCE_PHRASES for c in t.acceptance_criteria
        ):
            raise WorkflowRuleError(
                "ERR_VAGUE_ACCEPTANCE",
                f"任务 {t.task_id} 验收标准不可判定（禁止空话如'完成开发'/'优化体验'）。",
                {"task_id": t.task_id, "acceptance_criteria": t.acceptance_criteria},
            )
        check_3d_blacklist(title_or_text := f"{t.title} {' '.join(t.acceptance_criteria)}", t.required_tags)
        for dep in t.depends_on:
            if dep not in ids:
                raise WorkflowRuleError(
                    "ERR_MISSING_DEPENDENCY",
                    f"任务 {t.task_id} 依赖了不存在的前置任务 '{dep}'。",
                    {"task_id": t.task_id, "missing_dep": dep},
                )
            if dep == t.task_id:
                raise WorkflowRuleError(
                    "ERR_DAG_CYCLE",
                    f"任务 {t.task_id} 存在自环依赖。",
                    {"task_id": t.task_id},
                )


def topological_sort(tasks: List[GameDevTask]) -> List[str]:
    """Kahn 算法拓扑排序，同时检测 DAG 循环依赖。"""
    task_map = {t.task_id: t for t in tasks}
    in_degree: Dict[str, int] = {t.task_id: len(t.depends_on) for t in tasks}
    successors: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            successors[dep].append(t.task_id)

    queue = deque(sorted([tid for tid, deg in in_degree.items() if deg == 0]))
    order: List[str] = []
    while queue:
        curr = queue.popleft()
        order.append(curr)
        for nxt in sorted(successors[curr]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(tasks):
        cycle_nodes = [tid for tid, deg in in_degree.items() if deg > 0]
        raise WorkflowRuleError(
            "ERR_DAG_CYCLE",
            f"DAG 存在循环依赖，无法完成拓扑排序！涉及节点：{cycle_nodes}",
            {"cycle_nodes": cycle_nodes},
        )
    return order


def recalculate_cpm(tasks: List[GameDevTask]) -> Tuple[List[GameDevTask], float, float]:
    """
    第 6.2 节 CPM 精确正推与逆推算法：
    - 正推：ES_i = max(EF_pred), EF_i = ES_i + duration_i + delay_i
    - 逆推：LF_i = min(LS_succ) (终点为 T_total), LS_i = LF_i - (duration_i + delay_i)
    - 浮动：Slack_i = LS_i - ES_i; Slack_i == 0 => is_critical = True
    返回：(更新后的任务列表, 当前总预计工期 T_total, 无延期基线总工期 T_baseline)
    """
    if not tasks:
        return tasks, 0.0, 0.0

    validate_task_contract(tasks)
    topo_order = topological_sort(tasks)
    task_map: Dict[str, GameDevTask] = {t.task_id: t for t in tasks}
    successors: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            successors[dep].append(t.task_id)

    # 1. 基线（不含运行期 delay_hours）总工期计算，用于精确衡量顺延 Δt
    base_ef: Dict[str, float] = {}
    for tid in topo_order:
        t = task_map[tid]
        b_es = max((base_ef[p] for p in t.depends_on), default=0.0)
        base_ef[tid] = round(b_es + t.duration_hours, 4)
    baseline_total = max(base_ef.values(), default=0.0)

    # 2. 正推 (Forward Pass, 计入 delay_hours)
    for tid in topo_order:
        t = task_map[tid]
        t.es = round(max((task_map[p].ef for p in t.depends_on), default=0.0), 4)
        eff_dur = t.duration_hours + t.delay_hours
        t.ef = round(t.es + eff_dur, 4)

    project_total = round(max((t.ef for t in tasks), default=0.0), 4)

    # 3. 逆推 (Backward Pass)
    for tid in reversed(topo_order):
        t = task_map[tid]
        succs = successors[tid]
        if not succs:
            t.lf = project_total
        else:
            t.lf = round(min(task_map[s].ls for s in succs), 4)
        eff_dur = t.duration_hours + t.delay_hours
        t.ls = round(t.lf - eff_dur, 4)
        raw_slack = round(t.ls - t.es, 4)
        t.slack = 0.0 if abs(raw_slack) < 1e-4 else raw_slack
        t.is_critical = t.slack == 0.0

    return tasks, project_total, baseline_total


def compute_dashboard_metrics(
    tasks: List[GameDevTask],
    bots: List[BotCard],
    project_total_hours: float,
    baseline_total_hours: float,
) -> Dict:
    """计算第 6.2 节防自欺双口径进度仪表盘 + 分阶段 + 分 Bot 统计。"""
    cp_tasks = [t for t in tasks if t.is_critical]
    cp_total_hours = round(sum(t.duration_hours + t.delay_hours for t in cp_tasks), 2)
    cp_completed_hours = round(
        sum(t.duration_hours + t.delay_hours for t in cp_tasks if t.status == TaskStatus.SUCCEEDED),
        2,
    )
    cp_progress_pct = round((cp_completed_hours / cp_total_hours * 100.0) if cp_total_hours > 0 else 0.0, 1)

    total_hours = round(sum(t.duration_hours + t.delay_hours for t in tasks), 2)
    total_completed_hours = round(
        sum(t.duration_hours + t.delay_hours for t in tasks if t.status == TaskStatus.SUCCEEDED),
        2,
    )
    total_progress_pct = round((total_completed_hours / total_hours * 100.0) if total_hours > 0 else 0.0, 1)

    delay_delta_hours = round(max(0.0, project_total_hours - baseline_total_hours), 2)
    critical_delayed_tasks = [t.task_id for t in cp_tasks if t.delay_hours > 0]

    # 按 5 阶段聚合
    stage_stats = []
    for st in STAGE_DEFINITIONS:
        st_tasks = [t for t in tasks if t.stage_id == st.stage_id]
        st_done = sum(1 for t in st_tasks if t.status == TaskStatus.SUCCEEDED)
        st_blocked = [
            t.task_id
            for t in st_tasks
            if t.status in (TaskStatus.WAITING_DECISION, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.WAITING_VERIFY)
        ]
        stage_stats.append(
            {
                "stage_id": st.stage_id,
                "name": st.name,
                "dominant_mode": st.dominant_mode.value,
                "total_tasks": len(st_tasks),
                "completed_tasks": st_done,
                "progress_pct": round((st_done / len(st_tasks) * 100.0) if st_tasks else 0.0, 1),
                "attention_task_ids": st_blocked,
            }
        )

    # 按 Bot 聚合
    bot_stats = []
    for bot in bots:
        b_tasks = [t for t in tasks if t.assigned_bot_id == bot.bot_id]
        b_done = sum(1 for t in b_tasks if t.status == TaskStatus.SUCCEEDED)
        b_running = [t.task_id for t in b_tasks if t.status == TaskStatus.RUNNING]
        b_waiting = [
            t.task_id
            for t in b_tasks
            if t.status in (TaskStatus.WAITING_DECISION, TaskStatus.WAITING_VERIFY, TaskStatus.FAILED, TaskStatus.BLOCKED)
        ]
        bot_stats.append(
            {
                "bot_id": bot.bot_id,
                "role_code": bot.role_code,
                "display_name": bot.display_name,
                "model_tier": bot.model_tier,
                "has_long_term_memory": bot.has_long_term_memory,
                "assigned_count": len(b_tasks),
                "completed_count": b_done,
                "current_load_hours": round(bot.current_load_hours, 2),
                "running_task_ids": b_running,
                "blocked_or_waiting_ids": b_waiting,
            }
        )

    return {
        "cp_progress_pct": cp_progress_pct,
        "cp_completed_hours": cp_completed_hours,
        "cp_total_hours": cp_total_hours,
        "total_progress_pct": total_progress_pct,
        "total_completed_hours": total_completed_hours,
        "total_hours": total_hours,
        "baseline_total_hours": round(baseline_total_hours, 2),
        "project_total_hours": round(project_total_hours, 2),
        "delay_delta_hours": delay_delta_hours,
        "has_delay_alert": delay_delta_hours > 0,
        "critical_delayed_tasks": critical_delayed_tasks,
        "critical_path_task_ids": [t.task_id for t in cp_tasks],
        "stage_stats": stage_stats,
        "bot_stats": bot_stats,
    }
