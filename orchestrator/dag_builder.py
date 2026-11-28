from __future__ import annotations

from collections import deque
from typing import Dict, List

from .schemas import HandoffBundle, OrchestratorError, TaskGraph, TaskKind, TaskRecord
from .tech_bootstrap import get_scenario_dir, get_task_writable_paths

TECH_TASK_ID = "TECH-001"
FINAL_TASK_ID = "QA-FINAL"


def build_task_graph(bundle: HandoffBundle) -> TaskGraph:
    """
    §6.1~§6.2 确定性建图：
    - 1 个 TECH-001 (DEV_STAGE_1)
    - N 个生产任务，任务 ID 严格沿用 req_id (DEV_STAGE_2)
    - M 个模块联调任务 INTEG-<gdd_id> (DEV_STAGE_3)
    - 1 个 QA-FINAL (DEV_STAGE_4)
    """
    tasks: List[TaskRecord] = []

    tech_task = TaskRecord(
        task_id=TECH_TASK_ID,
        title="技术定型与共享契约骨架",
        kind=TaskKind.TECH,
        dev_stage="DEV_STAGE_1",
        role="ROLE_TECH_LEAD",
        priority="P0",
        depends_on=[],
        writable_paths=get_task_writable_paths(TaskKind.TECH),
    )
    tasks.append(tech_task)

    module_children: Dict[str, List[str]] = {mod.gdd_id: [] for mod in bundle.gdd_index.modules}

    def _add_prod_task(
        *,
        req_id: str,
        title: str,
        kind: TaskKind,
        role: str,
        gdd_ref: str,
        priority: str,
        reuse_group: str | None = None,
    ) -> None:
        scenario_paths = [f"{get_scenario_dir(req_id)}index.yaml"] if kind == TaskKind.SYS else []
        tasks.append(
            TaskRecord(
                task_id=req_id,
                title=title,
                kind=kind,
                dev_stage="DEV_STAGE_2",
                role=role,
                req_id=req_id,
                gdd_ref=gdd_ref,
                priority=priority,
                reuse_group=reuse_group,
                depends_on=[TECH_TASK_ID],
                writable_paths=get_task_writable_paths(kind, req_id=req_id),
                scenario_paths=scenario_paths,
            )
        )
        if gdd_ref in module_children:
            module_children[gdd_ref].append(req_id)

    for s in bundle.system_requirements.stage_deliverables:
        _add_prod_task(
            req_id=s.req_id,
            title=s.title,
            kind=TaskKind.SYS,
            role="ROLE_SYS_DEV",
            gdd_ref=s.linked_gdd_ref,
            priority=s.priority,
        )

    for n in bundle.narrative_requirements.stage_deliverables:
        _add_prod_task(
            req_id=n.req_id,
            title=n.title,
            kind=TaskKind.NAR,
            role="ROLE_NARRATIVE",
            gdd_ref=n.linked_gdd_ref,
            priority=n.priority,
        )

    for a in bundle.art_requirements.stage_deliverables:
        _add_prod_task(
            req_id=a.req_id,
            title=a.title,
            kind=TaskKind.ART,
            role="ROLE_ART_2D",
            gdd_ref=a.linked_gdd_ref,
            priority=a.priority,
            reuse_group=a.reuse_group,
        )

    for au in bundle.audio_requirements.stage_deliverables:
        _add_prod_task(
            req_id=au.req_id,
            title=au.title,
            kind=TaskKind.AUD,
            role="ROLE_AUDIO",
            gdd_ref=au.linked_gdd_ref,
            priority=au.priority,
        )

    integ_ids: List[str] = []
    for mod in bundle.gdd_index.modules:
        integ_id = f"INTEG-{mod.gdd_id}"
        deps = module_children.get(mod.gdd_id, []) or [TECH_TASK_ID]
        tasks.append(
            TaskRecord(
                task_id=integ_id,
                title=f"{mod.title} · 模块联调",
                kind=TaskKind.INTEG,
                dev_stage="DEV_STAGE_3",
                role="ROLE_TECH_LEAD",
                gdd_ref=mod.gdd_id,
                priority=mod.priority,
                depends_on=list(deps),
                writable_paths=get_task_writable_paths(TaskKind.INTEG, gdd_ref=mod.gdd_id),
            )
        )
        integ_ids.append(integ_id)

    tasks.append(
        TaskRecord(
            task_id=FINAL_TASK_ID,
            title="全链路封版终验",
            kind=TaskKind.QA_FINAL,
            dev_stage="DEV_STAGE_4",
            role="ROLE_QA_INTEG",
            priority="P0",
            depends_on=integ_ids or [TECH_TASK_ID],
            writable_paths=get_task_writable_paths(TaskKind.QA_FINAL),
        )
    )

    # Kahn 环检测与规范化边表
    validate_dag_acyclic(tasks)
    edges: List[List[str]] = []
    for t in tasks:
        for dep in t.depends_on:
            edges.append([dep, t.task_id])

    return TaskGraph(
        project_id=bundle.manifest.project_id,
        spec_version=bundle.manifest.spec_version,
        tasks=tasks,
        edges=edges,
    )


def validate_dag_acyclic(tasks: List[TaskRecord]) -> List[str]:
    """Kahn 算法拓扑排序，同时检出缺边与环路（ERR_DAG_CYCLE）。"""
    ids = {t.task_id for t in tasks}
    in_degree: Dict[str, int] = {t.task_id: 0 for t in tasks}
    successors: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in ids:
                raise OrchestratorError(
                    "ERR_DAG_CYCLE",
                    f"任务 {t.task_id} 依赖了不存在的前置节点 {dep}。",
                    {"task_id": t.task_id, "missing_dep": dep},
                )
            if dep == t.task_id:
                raise OrchestratorError(
                    "ERR_DAG_CYCLE",
                    f"任务 {t.task_id} 存在自环依赖。",
                    {"task_id": t.task_id},
                )
            successors[dep].append(t.task_id)
            in_degree[t.task_id] += 1

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
        raise OrchestratorError(
            "ERR_DAG_CYCLE",
            "任务依赖图存在环路，无法完成拓扑排序。",
            {"cycle_nodes": [tid for tid, d in in_degree.items() if d > 0]},
        )
    return order
