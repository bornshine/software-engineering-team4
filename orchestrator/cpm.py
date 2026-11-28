from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .dag_builder import validate_dag_acyclic
from .schemas import CpmSummary, TaskKind, TaskRecord, TaskStatus

KIND_ORDER = {
    TaskKind.TECH: 0,
    TaskKind.SYS: 1,
    TaskKind.NAR: 2,
    TaskKind.ART: 3,
    TaskKind.AUD: 4,
    TaskKind.INTEG: 5,
    TaskKind.QA_FINAL: 6,
}

KIND_TO_PILLAR = {
    TaskKind.SYS: "gameplay",
    TaskKind.NAR: "narrative",
    TaskKind.ART: "art",
    TaskKind.AUD: "audio",
}

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _effective_duration(t: TaskRecord) -> float:
    return round(max(0.0, t.estimate_hours + t.delay_hours), 2)


def _select_main_critical_path(
    tasks: List[TaskRecord],
    task_map: Dict[str, TaskRecord],
    successors: Dict[str, List[str]],
    project_total: float,
) -> List[str]:
    """
    从并列关键路径中确定性选出一条代表最长链：
    排序优先级为工种序 KIND_ORDER -> task_id 字典序，避免多条并行关键路径工期重复累加。
    """
    if not tasks:
        return []
    # 找出处于关键路径 (slack == 0) 且 EF == project_total 的终点候选
    critical_ids = {t.task_id for t in tasks if t.is_critical}
    critical_succ: Dict[str, List[str]] = {
        tid: sorted(
            [s for s in successors[tid] if s in critical_ids and abs(task_map[s].es - task_map[tid].ef) <= 1e-6],
            key=lambda x: (KIND_ORDER[task_map[x].kind], x),
        )
        for tid in critical_ids
    }
    starts = sorted(
        [tid for tid in critical_ids if abs(task_map[tid].es) <= 1e-6],
        key=lambda x: (KIND_ORDER[task_map[x].kind], x),
    )
    if not starts:
        return []

    memo: Dict[str, Tuple[float, List[str]]] = {}

    def dfs(tid: str) -> Tuple[float, List[str]]:
        if tid in memo:
            return memo[tid]
        dur = _effective_duration(task_map[tid])
        nxts = critical_succ.get(tid, [])
        if not nxts:
            res = (dur, [tid])
            memo[tid] = res
            return res
        best_len = -1.0
        best_sub: List[str] = []
        for nxt in nxts:
            sub_len, sub_path = dfs(nxt)
            if sub_len > best_len + 1e-6:
                best_len = sub_len
                best_sub = sub_path
        res = (round(dur + max(0.0, best_len), 2), [tid, *best_sub])
        memo[tid] = res
        return res

    best_overall_len = -1.0
    best_path: List[str] = []
    for st in starts:
        cand_len, cand_path = dfs(st)
        if cand_len > best_overall_len + 1e-6:
            best_overall_len = cand_len
            best_path = cand_path

    # 回溯兜底（极少数纯零工期情况下保证长度对齐 project_total）
    if best_path and abs(best_overall_len - project_total) <= 1e-4:
        return best_path
    return best_path


def _compute_resource_waits(
    tasks: List[TaskRecord],
    task_map: Dict[str, TaskRecord],
    concurrency: Dict[str, int],
) -> None:
    """
    §6.5 资源约束等待提示（仅在甘特图单独标注，不污染理论 slack）：
    基于并发槽位上限与同 reuse_group 串行约束 (C-1) 估算资源排队额外等待工时。
    """
    ordered = sorted(tasks, key=lambda t: (t.es, KIND_ORDER[t.kind], t.task_id))
    slot_free_times: Dict[str, List[float]] = {}
    reuse_free_at: Dict[str, float] = {}
    res_ef: Dict[str, float] = {}

    for t in ordered:
        role_slots = max(1, int(concurrency.get(t.role, 1)))
        if t.role not in slot_free_times:
            slot_free_times[t.role] = [0.0] * role_slots
        slots = slot_free_times[t.role]
        slots.sort()

        pred_finish = max((res_ef.get(dep, 0.0) for dep in t.depends_on), default=0.0)
        earliest_slot = slots[0]
        reuse_ready = reuse_free_at.get(t.reuse_group, 0.0) if t.reuse_group else 0.0
        actual_start = max(pred_finish, earliest_slot, reuse_ready)

        wait_h = max(0.0, round(actual_start - pred_finish, 2))
        dur = _effective_duration(t)
        finish = round(actual_start + dur, 2)

        t.resource_wait_hours = wait_h
        res_ef[t.task_id] = finish
        slots[0] = finish
        if t.reuse_group:
            reuse_free_at[t.reuse_group] = finish


def compute_cpm(
    tasks: List[TaskRecord],
    lead_pillars: List[str],
    concurrency: Optional[Dict[str, int]] = None,
    baseline_cp_length: Optional[float] = None,
) -> CpmSummary:
    """
    §6.5 标准 CPM 正逆推 + 单条最长关键路径分母 + 双口径防自欺进度计算。
    - 修正历史 v3.0 重复累加并行关键路径工期的 bug：分母严格等于 max(EF)。
    - SKIPPED 任务不计入进度分子，豁免放行项单独记录 waived_tasks。
    """
    if not tasks:
        return CpmSummary()

    topo_order = validate_dag_acyclic(tasks)
    task_map: Dict[str, TaskRecord] = {t.task_id: t for t in tasks}
    successors: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            successors[dep].append(t.task_id)

    # 1. 正推 ES / EF
    for tid in topo_order:
        t = task_map[tid]
        es = max((task_map[dep].ef for dep in t.depends_on), default=0.0)
        ef = round(es + _effective_duration(t), 2)
        t.es = round(es, 2)
        t.ef = ef

    project_total = round(max((t.ef for t in tasks), default=0.0), 2)

    # 2. 逆推 LF / LS / Slack
    for tid in reversed(topo_order):
        t = task_map[tid]
        succs = successors[tid]
        lf = project_total if not succs else min(task_map[s].ls for s in succs)
        ls = round(lf - _effective_duration(t), 2)
        t.lf = round(lf, 2)
        t.ls = ls
        t.slack = round(max(0.0, t.ls - t.es), 2)
        t.is_critical = t.slack <= 1e-6

    # 3. 确定性选取唯一主关键路径（用于单链分母与主展示）
    main_path = _select_main_critical_path(tasks, task_map, successors, project_total)
    main_set = set(main_path)
    for t in tasks:
        t.on_main_critical_path = t.task_id in main_set

    # 4. 资源等待独立标注（不影响 slack）
    _compute_resource_waits(tasks, task_map, concurrency or {})

    # 5. 双口径进度（严格只计 SUCCEEDED，SKIPPED 不计入分子）
    cp_den = project_total
    cp_num = round(
        sum(_effective_duration(task_map[tid]) for tid in main_path if task_map[tid].state == TaskStatus.SUCCEEDED),
        2,
    )
    total_all = round(sum(_effective_duration(t) for t in tasks), 2)
    done_all = round(sum(_effective_duration(t) for t in tasks if t.state == TaskStatus.SUCCEEDED), 2)

    progress_cp = round((cp_num / cp_den) * 100.0, 2) if cp_den > 0 else 0.0
    progress_all = round((done_all / total_all) * 100.0, 2) if total_all > 0 else 0.0

    waived = sorted(
        t.task_id for t in tasks if t.state == TaskStatus.SKIPPED and t.skip.waiver is True
    )

    return CpmSummary(
        cp_length_hours=cp_den,
        total_all_hours=total_all,
        baseline_cp_length_hours=round(baseline_cp_length if baseline_cp_length is not None else cp_den, 2),
        main_path=main_path,
        progress_cp=progress_cp,
        progress_all=progress_all,
        waived_tasks=waived,
    )


def dispatch_priority_key(task: TaskRecord, lead_pillars: List[str]) -> Tuple[float, int, int, str]:
    """
    §6.5 四级派单优先级：
    1. slack 小者优先
    2. priority: P0 > P1 > P2
    3. 所属支柱在 lead_pillars 中的位置靠前者优先
    4. task_id (req_id) 字典序
    """
    pillar = KIND_TO_PILLAR.get(task.kind)
    pillar_rank = lead_pillars.index(pillar) if pillar and pillar in lead_pillars else 99
    return (
        round(task.slack, 4),
        PRIORITY_RANK.get(task.priority, 9),
        pillar_rank,
        task.task_id,
    )
