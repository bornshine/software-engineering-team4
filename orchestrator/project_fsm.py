from __future__ import annotations

from typing import Dict, Set

from .schemas import OrchestratorError, ProjectState

VALID_PROJECT_TRANSITIONS: Dict[ProjectState, Set[ProjectState]] = {
    ProjectState.LOADED: {ProjectState.AWAITING_TECH_CONFIRM},
    ProjectState.AWAITING_TECH_CONFIRM: {ProjectState.RUNNING, ProjectState.APPLYING_DELTA},
    ProjectState.RUNNING: {
        ProjectState.PAUSED,
        ProjectState.AWAITING_RELEASE,
        ProjectState.APPLYING_DELTA,
    },
    ProjectState.PAUSED: {ProjectState.RUNNING, ProjectState.APPLYING_DELTA},
    ProjectState.AWAITING_RELEASE: {
        ProjectState.RELEASED,
        ProjectState.RUNNING,
        ProjectState.APPLYING_DELTA,
    },
    ProjectState.RELEASED: {ProjectState.APPLYING_DELTA},
    ProjectState.APPLYING_DELTA: {
        ProjectState.AWAITING_TECH_CONFIRM,
        ProjectState.RUNNING,
    },
}


def transition_project_state(current: ProjectState, target: ProjectState) -> ProjectState:
    """§3.2 项目级状态机校验与迁移。"""
    if target == current:
        return current
    allowed = VALID_PROJECT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise OrchestratorError(
            "ERR_INVALID_PROJECT_TRANSITION",
            f"项目状态禁止从 {current.value} 迁移到 {target.value}。",
            {"from": current.value, "to": target.value},
        )
    return target
