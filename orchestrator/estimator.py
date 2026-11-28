from __future__ import annotations

from typing import Any, Dict, List

from .schemas import TaskKind, TaskRecord

DEFAULT_BASELINE_HOURS: Dict[str, Any] = {
    "TECH": 6.0,
    "SYS": {"P0": 6.0, "P1": 4.0, "P2": 2.0},
    "NAR": {"P0": 4.0, "P1": 3.0, "P2": 2.0},
    "ART": {"P0": 5.0, "P1": 3.0, "P2": 2.0},
    "AUD": {"P0": 3.0, "P1": 2.0, "P2": 1.0},
    "INTEG_per_child": 1.0,
    "QA_FINAL": 4.0,
}


def apply_estimates(tasks: List[TaskRecord], config: Dict[str, Any]) -> None:
    """§6.4 两段式工期估算（默认确定性基线表，支持在基线 [0.5x, 2.0x] 内受限修正）。"""
    est_cfg = config.get("estimation", {})
    base_cfg = est_cfg.get("baseline_hours", DEFAULT_BASELINE_HOURS)
    oversized_limit = float(config.get("policy", {}).get("oversized_task_hours", 16))
    child_count_by_integ: Dict[str, int] = {
        t.task_id: len(t.depends_on) for t in tasks if t.kind == TaskKind.INTEG
    }

    for task in tasks:
        if task.kind == TaskKind.TECH:
            hours = float(base_cfg.get("TECH", 6.0))
        elif task.kind == TaskKind.QA_FINAL:
            hours = float(base_cfg.get("QA_FINAL", 4.0))
        elif task.kind == TaskKind.INTEG:
            per_child = float(base_cfg.get("INTEG_per_child", 1.0))
            hours = round(max(1, child_count_by_integ.get(task.task_id, 1)) * per_child, 2)
        else:
            kind_table = base_cfg.get(task.kind.value, {"P0": 4.0, "P1": 3.0, "P2": 2.0})
            hours = float(kind_table.get(task.priority, kind_table.get("P1", 3.0)))

        task.estimate_hours = hours
        task.oversized = hours > oversized_limit


def clamp_agent_estimate(baseline: float, raw_proposal: float, bounds: List[float] = [0.5, 2.0]) -> float:
    """把 Agent 估算修正值强制钳位在基线的 [low, high] 倍率内。"""
    low = baseline * float(bounds[0])
    high = baseline * float(bounds[1])
    return round(max(low, min(high, raw_proposal)), 2)


def add_rework_delay(task: TaskRecord, config: Dict[str, Any]) -> float:
    """§6.4 每次以 FAILED 结束的尝试追加 rework_ratio * estimate_hours 延期。"""
    ratio = float(config.get("estimation", {}).get("rework_ratio", 0.5))
    added = round(task.estimate_hours * ratio, 2)
    task.delay_hours = round(task.delay_hours + added, 2)
    return added
