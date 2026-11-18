from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from .models import PitfallMemoryItem, PlannerVerdictRecord
from .rules import WorkflowRuleError, validate_anti_dogma


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def create_initial_pitfall_memory() -> List[PitfallMemoryItem]:
    """第 7.3 节：仅主策拥有的轻量踩坑教训记忆库（不含僵化工作流禁令）。"""
    return [
        PitfallMemoryItem(
            memory_id="MEM-PITFALL-001",
            context_scenario="2.5D 等轴测地图与角色精灵图层级遮挡联调",
            past_failure="未在阶段 1 统一 Y 轴排序锚点基准，导致阶段 3 合流时 80% 贴图穿模返工",
            lesson_learned="涉及 2.5D 伪 3D 视角时，需在阶段 1 规格中显式声明精灵 Pivot 锚点处于底部中心及 Y-sorting 排序公式",
            source_event_id="HIST-INCIDENT-25D-09",
            active=True,
        ),
        PitfallMemoryItem(
            memory_id="MEM-PITFALL-002",
            context_scenario="2D 横版动作跳跃手感与判定框垂直切片联调",
            past_failure="Stage 1 未锁定土狼时间（Coyote Time）与输入缓冲窗口，导致 Stage 3 联调手感僵硬返工",
            lesson_learned="动作类项目建议在 Stage 1 尽早明确无敌帧与缓冲时间基线，便于 Stage 2 并行对齐",
            source_event_id="HIST-INCIDENT-2D-04",
            active=True,
        ),
    ]


class PlannerMemoryStore:
    """专属于主策（ROLE_PLANNER）的教训记忆与拍案记录管理器。"""

    def __init__(self) -> None:
        self.memories: List[PitfallMemoryItem] = create_initial_pitfall_memory()
        self.verdicts: List[PlannerVerdictRecord] = []
        self._mem_seq = len(self.memories)
        self._verdict_seq = 0

    def reset(self) -> None:
        self.memories = create_initial_pitfall_memory()
        self.verdicts = []
        self._mem_seq = len(self.memories)
        self._verdict_seq = 0

    def add_memory(
        self,
        context_scenario: str,
        past_failure: str,
        lesson_learned: str,
        source_event_id: str,
    ) -> PitfallMemoryItem:
        if not context_scenario.strip() or not past_failure.strip() or not lesson_learned.strip():
            raise WorkflowRuleError(
                "ERR_INVALID_MEMORY_ITEM",
                "新增教训记忆必须完整填写情境、踩坑原因与可解释教训。",
            )
        # 反束缚校验护栏
        validate_anti_dogma(lesson_learned, past_failure, context_scenario)

        self._mem_seq += 1
        item = PitfallMemoryItem(
            memory_id=f"MEM-PITFALL-{self._mem_seq:03d}",
            context_scenario=context_scenario.strip(),
            past_failure=past_failure.strip(),
            lesson_learned=lesson_learned.strip(),
            source_event_id=source_event_id.strip() or f"EVT-{self._mem_seq:03d}",
            active=True,
        )
        self.memories.append(item)
        return item

    def set_memory_active(self, memory_id: str, active: bool) -> PitfallMemoryItem:
        for item in self.memories:
            if item.memory_id == memory_id:
                item.active = active
                return item
        raise WorkflowRuleError("ERR_MEMORY_NOT_FOUND", f"未找到教训记忆 {memory_id}")

    def find_relevant_memory(self, text: str) -> Optional[PitfallMemoryItem]:
        low = text.lower()
        for item in self.memories:
            if not item.active:
                continue
            if ("2.5d" in low or "等轴" in low or "y-sort" in low) and "2.5d" in item.context_scenario.lower():
                return item
            if ("横版" in low or "动作" in low or "手感" in low or "跳" in low) and "横版" in item.context_scenario:
                return item
        return None

    def record_verdict(
        self,
        trigger_reason: str,
        target_task_ids: List[str],
        decision_conclusion: str,
        rationale: str,
        memory_ref_id: Optional[str] = None,
    ) -> PlannerVerdictRecord:
        if not decision_conclusion.strip():
            raise WorkflowRuleError("ERR_EMPTY_VERDICT", "主策拍案必须给出明确的一锤定音结论。")
        if memory_ref_id:
            valid_ids = {m.memory_id for m in self.memories if m.active}
            if memory_ref_id not in valid_ids:
                raise WorkflowRuleError(
                    "ERR_INVALID_MEMORY_REF",
                    f"引用的历史教训 {memory_ref_id} 不存在或已被撤销。",
                )

        self._verdict_seq += 1
        verdict = PlannerVerdictRecord(
            verdict_id=f"VERDICT-{self._verdict_seq:03d}",
            timestamp=utc_now_str(),
            planner_model_tier="flagship (Tier-1)",
            trigger_reason=trigger_reason,
            target_task_ids=list(target_task_ids),
            decision_conclusion=decision_conclusion.strip(),
            rationale=rationale.strip() or "主策基于项目当前阶段目标与风险收益比作出一锤定音裁决。",
            memory_ref_id=memory_ref_id,
        )
        self.verdicts.append(verdict)
        return verdict
