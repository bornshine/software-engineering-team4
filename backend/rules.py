from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple
from .models import BotCard, CollaborationMode, GameDevTask, StageDefinition


class WorkflowRuleError(Exception):
    """Domain validation error carrying an explicit machine-readable error code."""

    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict:
        return {
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


# 第 6.1 节：预设 5 大标准阶段（关卡）容器
STAGE_DEFINITIONS: List[StageDefinition] = [
    StageDefinition(
        stage_id="STAGE_1",
        order=1,
        name="Stage 1 · 核心循环与立项规格定调",
        dominant_mode=CollaborationMode.CONCENTRATED,
        exit_criteria="主策拍板核心玩法循环、2D/2.5D 视差/投影规范与基础数值表",
        description="立项定调与歧义消除收口门，确保下游散开前基准一致。",
    ),
    StageDefinition(
        stage_id="STAGE_2",
        order=2,
        name="Stage 2 · 基础资产与底层框架开发",
        dominant_mode=CollaborationMode.DISPERSED,
        exit_criteria="精灵图集/瓦片地图与 2D 物理碰撞/相机/输入框架分别自检通过",
        description="美术与程序 Bot 按泳道散开并行推进各自基础资产与核心底座。",
    ),
    StageDefinition(
        stage_id="STAGE_3",
        order=3,
        name="Stage 3 · 首关垂直切片合流联调",
        dominant_mode=CollaborationMode.JOINT,
        exit_criteria="美术资产、状态机、UI HUD 与层级遮挡在首关合流并通过独立 QA 验收",
        description="跨角色泳道产出合流联调，暴露接口与遮挡问题并由 QA 独立把关。",
    ),
    StageDefinition(
        stage_id="STAGE_4",
        order=4,
        name="Stage 4 · 多关卡内容与系统扩展量产",
        dominant_mode=CollaborationMode.DISPERSED,
        exit_criteria="扩展关卡地图、敌人 AI / 经营系统与支线道具全部产出并自检完成",
        description="基于首关垂直切片模板，多实例 Bot 并行量产多关卡与系统扩展。",
    ),
    StageDefinition(
        stage_id="STAGE_5",
        order=5,
        name="Stage 5 · 全链路验收、数值调优与封版",
        dominant_mode=CollaborationMode.CONCENTRATED,
        exit_criteria="独立 QA 全链路回归达标 + 主策终审拍案封版归档",
        description="全图支线收束至独立 QA 与主策集中门禁，完成帧率内存核验与封版。",
    ),
]


# 第 7.1 节：4 类核心角色严格边界
ROLE_CODES = ("ROLE_PLANNER", "ROLE_ART_2D", "ROLE_DEV_2D", "ROLE_QA_INTEG")

TASK_TYPE_TO_ROLE: Dict[str, str] = {
    "design": "ROLE_PLANNER",
    "art_2d": "ROLE_ART_2D",
    "dev_2d": "ROLE_DEV_2D",
    "qa_integ": "ROLE_QA_INTEG",
}

ROLE_DISPLAY_NAMES: Dict[str, str] = {
    "ROLE_PLANNER": "主策 / PM Agent（拍案人）",
    "ROLE_ART_2D": "2D/2.5D 视觉与资产 Bot",
    "ROLE_DEV_2D": "2D/2.5D 玩法与逻辑程序 Bot",
    "ROLE_QA_INTEG": "独立验收与关卡集成 Bot",
}

# 第 8 节：标准 2D/2.5D 能力标签白名单
VALID_2D_CAPABILITY_TAGS: Dict[str, List[str]] = {
    "ROLE_PLANNER": [
        "game_spec_breakdown",
        "numeric_balancing",
        "verdict_arbitration",
        "scope_control",
    ],
    "ROLE_ART_2D": [
        "2d_sprite_sheet",
        "frame_animation",
        "spine_2d_rigging",
        "tilemap_design",
        "isometric_25d_asset",
        "parallax_background",
        "ui_hud_art",
        "2d_normal_lighting",
    ],
    "ROLE_DEV_2D": [
        "2d_physics_collision",
        "character_state_machine",
        "isometric_coord_math",
        "y_sort_depth_render",
        "camera_parallax_ctrl",
        "combat_numeric_logic",
        "inventory_dialogue_sys",
        "data_table_loader",
    ],
    "ROLE_QA_INTEG": [
        "vertical_slice_integ",
        "acceptance_verification",
        "fps_memory_profiling",
        "regression_testing",
    ],
}

ALL_VALID_2D_TAGS = {
    tag for tags in VALID_2D_CAPABILITY_TAGS.values() for tag in tags
}

# 第 8 节：3D 零容忍黑名单拦截词表
FORBIDDEN_3D_BLACKLIST: List[str] = [
    "3d_mesh_modeling",
    "3d_skeleton_rigging",
    "3d_mesh_rigging",
    "uv_unwrapping",
    "pbr_shader_baking",
    "3d_raytracing",
    "polygonal_topology",
    "3d建模",
    "3d骨骼蒙皮",
    "uv展开",
    "pbr材质烘培",
    "pbr材质烘焙",
    "3d网格拓扑",
]

# 反束缚校验护栏（第 7.3 节）
DOGMA_FORBIDDEN_PHRASES: List[str] = [
    "必须固定使用某工作流模板",
    "固定使用某工作流",
    "禁止探索某类玩法",
    "禁止探索",
    "一律不准修改",
    "永远禁止",
    "绝对不准变更",
    "强制固定流程",
    "不得偏离固定模板",
]


def create_default_bots() -> List[BotCard]:
    """创建严格收敛后的 4 类角色共 6 个默认 Bot 实例。"""
    return [
        BotCard(
            bot_id="planner_master",
            role_code="ROLE_PLANNER",
            display_name="主策 · Planner Master",
            model_tier="flagship",
            model_name="Tier-1 Flagship (claude-3-7-sonnet / gpt-4o / deepseek-r1)",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_PLANNER"]),
            current_load_hours=0.0,
            has_long_term_memory=True,
        ),
        BotCard(
            bot_id="art_bot_01",
            role_code="ROLE_ART_2D",
            display_name="2D/2.5D 美术 · Art-01",
            model_tier="standard",
            model_name="Tier-2 Fast Standard",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_ART_2D"]),
            current_load_hours=0.0,
            has_long_term_memory=False,
        ),
        BotCard(
            bot_id="art_bot_02",
            role_code="ROLE_ART_2D",
            display_name="2D/2.5D 美术 · Art-02",
            model_tier="standard",
            model_name="Tier-2 Fast Standard",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_ART_2D"]),
            current_load_hours=0.0,
            has_long_term_memory=False,
        ),
        BotCard(
            bot_id="dev_bot_01",
            role_code="ROLE_DEV_2D",
            display_name="2D/2.5D 程序 · Dev-01",
            model_tier="standard",
            model_name="Tier-2 Fast Standard",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_DEV_2D"]),
            current_load_hours=0.0,
            has_long_term_memory=False,
        ),
        BotCard(
            bot_id="dev_bot_02",
            role_code="ROLE_DEV_2D",
            display_name="2D/2.5D 程序 · Dev-02",
            model_tier="standard",
            model_name="Tier-2 Fast Standard",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_DEV_2D"]),
            current_load_hours=0.0,
            has_long_term_memory=False,
        ),
        BotCard(
            bot_id="qa_bot_01",
            role_code="ROLE_QA_INTEG",
            display_name="独立 QA 集成 · QA-01",
            model_tier="standard",
            model_name="Tier-2 Fast Standard",
            capabilities=list(VALID_2D_CAPABILITY_TAGS["ROLE_QA_INTEG"]),
            current_load_hours=0.0,
            has_long_term_memory=False,
        ),
    ]


def check_3d_blacklist(text: str = "", tags: Optional[Iterable[str]] = None) -> None:
    """检查输入文本与能力标签是否命中 3D 零容忍黑名单。"""
    hits: List[str] = []
    lowered_text = (text or "").lower()
    for term in FORBIDDEN_3D_BLACKLIST:
        if term.lower() in lowered_text:
            hits.append(term)

    for tag in tags or []:
        tag_low = tag.strip().lower()
        for term in FORBIDDEN_3D_BLACKLIST:
            if term.lower() == tag_low or term.lower() in tag_low:
                if term not in hits:
                    hits.append(tag)

    if hits:
        raise WorkflowRuleError(
            code="ERR_3D_PIPELINE_FORBIDDEN",
            message=(
                f"命中 3D 零容忍黑名单 {hits}！本工作流仅面向 2D/2.5D 伪 3D 渲染管线，"
                "请转化为 2D 序列帧/Spine 骨骼/2.5D 等轴测瓦片/Y-sorting 等效工序。"
            ),
            details={"forbidden_hits": hits},
        )


def validate_tags_against_whitelist(tags: Iterable[str]) -> None:
    """校验标签是否在 2D/2.5D 标准词表内，且不触犯 3D 黑名单。"""
    tag_list = list(tags)
    check_3d_blacklist(tags=tag_list)
    unknown = [t for t in tag_list if t not in ALL_VALID_2D_TAGS]
    if unknown:
        raise WorkflowRuleError(
            code="ERR_UNKNOWN_CAPABILITY_TAG",
            message=f"存在未列入 2D/2.5D 标准白名单的能力标签：{unknown}",
            details={"unknown_tags": unknown},
        )


def validate_anti_dogma(lesson_learned: str, past_failure: str = "", context_scenario: str = "") -> None:
    """第 7.3 节反束缚校验护栏：禁止向主策记忆灌入僵化流程模板禁令。"""
    combined = f"{context_scenario} {past_failure} {lesson_learned}"
    hits = [phrase for phrase in DOGMA_FORBIDDEN_PHRASES if phrase in combined]
    if hits:
        raise WorkflowRuleError(
            code="ERR_ANTI_DOGMA_GUARDRAIL",
            message=(
                f"反束缚护栏拦截：教训文本包含僵化流程禁令 {hits}。"
                "主策教训记忆只能记录可追溯的踩坑原因与避坑启发，严禁限制创意与工作流探索空间。"
            ),
            details={"blocked_phrases": hits},
        )


def explain_and_select_bot(
    task_type: str,
    required_tags: List[str],
    bots: List[BotCard],
    preferred_bot_id: Optional[str] = None,
) -> Tuple[BotCard, str]:
    """
    R2 三维可解释分配：
    1) 角色类型匹配
    2) 能力标签 100% 命中 (required_tags ⊆ bot.capabilities)
    3) 负载均衡与最早空闲路由 (Least-Loaded Routing)
    """
    validate_tags_against_whitelist(required_tags)

    expected_role = TASK_TYPE_TO_ROLE.get(task_type)
    if not expected_role:
        raise WorkflowRuleError(
            code="ERR_INVALID_TASK_TYPE",
            message=f"未知任务类型 '{task_type}'，仅支持 {list(TASK_TYPE_TO_ROLE.keys())}",
            details={"task_type": task_type},
        )

    role_bots = [b for b in bots if b.role_code == expected_role]
    eligible = [b for b in role_bots if set(required_tags).issubset(set(b.capabilities))]

    if not eligible:
        missing_summary = {
            b.bot_id: sorted(list(set(required_tags) - set(b.capabilities)))
            for b in role_bots
        }
        raise WorkflowRuleError(
            code="ERR_NO_ELIGIBLE_BOT",
            message=(
                f"无人可接单：角色 {expected_role} 下没有 Bot 满足全部能力标签 {required_tags}，"
                f"缺失明细：{missing_summary}"
            ),
            details={"expected_role": expected_role, "required_tags": required_tags, "missing": missing_summary},
        )

    # 若指定 preferred_bot_id 且合格则使用，否则按当前负荷最小优先
    if preferred_bot_id:
        for b in eligible:
            if b.bot_id == preferred_bot_id:
                chosen = b
                break
        else:
            chosen = min(eligible, key=lambda b: (b.current_load_hours, b.bot_id))
    else:
        chosen = min(eligible, key=lambda b: (b.current_load_hours, b.bot_id))

    load_snapshot = ", ".join(f"{b.bot_id}={b.current_load_hours:.1f}h" for b in eligible)
    reason = (
        f"① 角色匹配：task_type='{task_type}' → {expected_role}（{ROLE_DISPLAY_NAMES[expected_role]}）；"
        f"② 标签 100% 命中：required_tags={required_tags} ⊆ {chosen.bot_id}.capabilities；"
        f"③ 负载均衡路由：同角色候选当前水位 [{load_snapshot}]，选中最早空闲实例 {chosen.bot_id}。"
    )
    return chosen, reason


def validate_reassignment(task: GameDevTask, target_bot: BotCard, all_bots: List[BotCard]) -> str:
    """运行期人工改派资格复核：不匹配则当场拦截报错。"""
    check_3d_blacklist(tags=task.required_tags)
    expected_role = TASK_TYPE_TO_ROLE.get(task.task_type)
    missing_tags = sorted(list(set(task.required_tags) - set(target_bot.capabilities)))

    if target_bot.role_code != expected_role or missing_tags:
        reasons = []
        if target_bot.role_code != expected_role:
            reasons.append(
                f"角色不匹配（任务要求 {expected_role}，目标 {target_bot.bot_id} 属于 {target_bot.role_code}）"
            )
        if missing_tags:
            reasons.append(f"缺失所需能力标签 {missing_tags}")
        raise WorkflowRuleError(
            code="ERR_REASSIGN_CAPABILITY_MISMATCH",
            message=f"改派拦截：{target_bot.bot_id} 不具备接管 [{task.task_id}] 的资格 — " + "；".join(reasons),
            details={
                "task_id": task.task_id,
                "target_bot_id": target_bot.bot_id,
                "expected_role": expected_role,
                "actual_role": target_bot.role_code,
                "missing_tags": missing_tags,
            },
        )

    role_peers = [b for b in all_bots if b.role_code == expected_role]
    load_snapshot = ", ".join(f"{b.bot_id}={b.current_load_hours:.1f}h" for b in role_peers)
    return (
        f"① 角色复核通过：{target_bot.role_code} == {expected_role}；"
        f"② 标签 100% 命中：{task.required_tags} ⊆ {target_bot.bot_id}.capabilities；"
        f"③ 人工运行期改派接管（同角色水位 [{load_snapshot}]，已迁移上下文与日志）。"
    )
