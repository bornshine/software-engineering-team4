from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple
from .cpm import recalculate_cpm
from .models import (
    BotCard,
    CollaborationMode,
    GameDevTask,
    SpecClause,
    SpecDocument,
    TaskStatus,
)
from .presets import PRESET_SPECS
from .rules import (
    TASK_TYPE_TO_ROLE,
    VALID_2D_CAPABILITY_TAGS,
    check_3d_blacklist,
    explain_and_select_bot,
)


AMBIGUITY_PATTERNS = [
    r"待定",
    r"\btbd\b",
    r"歧义",
    r"冲突",
    r"待裁决",
    r"二选一",
    r"\bvs\b",
    r"\d+\s*(?:级|fps|s|秒|点|格)\s*或\s*\d+",
]


def _detect_ambiguity(text: str) -> Optional[str]:
    for pat in AMBIGUITY_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return f"检测到规格歧义信号（命中 '{m.group(0)}'）：严禁执行侧静默脑补，已自动升级至主策拍案台等待一锤定音。原文：「{text.strip()}」"
    return None


def _parse_clauses(raw_markdown: str) -> List[SpecClause]:
    clauses: List[SpecClause] = []
    current_section = "§1 核心规格"
    section_idx = 0
    item_idx = 0

    for raw_line in raw_markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# ") and not clauses:
            continue
        if line.startswith("## "):
            section_idx += 1
            item_idx = 0
            current_section = line.lstrip("#").strip()
            continue

        clean = re.sub(r"^[-*•]\s*", "", line)
        clean = re.sub(r"^\d+[.)]\s*", "", clean)
        ref_match = re.match(r"^(§\d+(?:\.\d+)?)\s*[:：]?\s*(.+)$", clean)
        if ref_match:
            cid = ref_match.group(1)
            body = ref_match.group(2).strip()
        else:
            item_idx += 1
            sec_num = max(1, section_idx)
            cid = f"§{sec_num}.{item_idx}"
            body = clean
        if body:
            clauses.append(SpecClause(clause_id=cid, section=current_section, text=body))

    if not clauses:
        clauses.append(SpecClause(clause_id="§1.1", section="§1 总体计划", text=raw_markdown.strip() or "2D 游戏核心原型计划"))
    return clauses


def _infer_stage_id(section: str, text: str, idx: int, total: int) -> str:
    combined = f"{section} {text}".lower()
    for s in ("stage_1", "stage_2", "stage_3", "stage_4", "stage_5"):
        if s in combined:
            return s.upper()
    if any(k in combined for k in ("§1", "立项", "定调", "核心循环", "歧义", "规范", "投影")):
        return "STAGE_1"
    if any(k in combined for k in ("§5", "封版", "全链路", "回归", "压测", "终审")):
        return "STAGE_5"
    if any(k in combined for k in ("§3", "垂直切片", "首关", "首块", "首夜", "合流", "联调")):
        return "STAGE_3"
    if any(k in combined for k in ("§4", "多关", "扩展", "量产", "boss", "背包", "对话", "集市", "商店", "卡组")):
        return "STAGE_4"
    if any(k in combined for k in ("§2", "基础资产", "底层", "图集", "瓦片", "碰撞", "加载器", "状态机")):
        return "STAGE_2"
    ratio = idx / max(1, total)
    if ratio < 0.2:
        return "STAGE_1"
    if ratio < 0.45:
        return "STAGE_2"
    if ratio < 0.65:
        return "STAGE_3"
    if ratio < 0.85:
        return "STAGE_4"
    return "STAGE_5"


def _infer_task_type_and_tags(text: str, stage_id: str) -> Tuple[str, List[str], float]:
    low = text.lower()
    # QA / 验收 / 回归
    if any(k in low for k in ("qa", "验收", "回归", "压测", "profiling", "帧率", "内存", "校验")):
        tags = []
        if any(k in low for k in ("切片", "首关", "首波", "首块", "合流")):
            tags.append("vertical_slice_integ")
        if any(k in low for k in ("帧率", "fps", "内存", "压测")):
            tags.append("fps_memory_profiling")
        if any(k in low for k in ("回归", "全流程", "跨季节")):
            tags.append("regression_testing")
        if not tags or "验收" in low or "校验" in low:
            tags.append("acceptance_verification")
        return "qa_integ", list(dict.fromkeys(tags))[:2], 6.0

    # 主策 / 定调 / 封版 / 歧义
    if any(k in low for k in ("主策", "拍板", "拍案", "终审", "封版", "立项", "核心循环", "歧义", "规范", "数值基线")):
        tags = ["game_spec_breakdown"]
        if any(k in low for k in ("数值", "歧义", "平衡", "冲突", "上限")):
            tags.append("numeric_balancing")
        if any(k in low for k in ("拍板", "拍案", "终审", "封版")):
            tags.append("verdict_arbitration")
        if stage_id in ("STAGE_1", "STAGE_5"):
            tags.append("scope_control")
        return "design", list(dict.fromkeys(tags))[:2], 5.0

    # Stage 3 合流联调默认由程序或集成牵头
    if stage_id == "STAGE_3" and any(k in low for k in ("合流", "联调", "组装")):
        tags = ["character_state_machine", "camera_parallax_ctrl"]
        if any(k in low for k in ("等轴", "y-sort", "遮挡", "2.5d")):
            tags = ["y_sort_depth_render", "isometric_coord_math"]
        elif any(k in low for k in ("卡牌", "伤害", "法线")):
            tags = ["combat_numeric_logic", "data_table_loader"]
        return "dev_2d", tags, 8.0

    # 2D/2.5D 美术资产
    art_score = sum(
        1
        for k in (
            "精灵", "sprite", "图集", "动画", "序列帧", "spine", "骨骼", "瓦片",
            "tilemap", "视差", "背景", "贴图", "ui", "hud", "法线", "等轴", "建筑", "美术"
        )
        if k in low
    )
    dev_score = sum(
        1
        for k in (
            "物理", "碰撞", "状态机", "坐标", "y-sort", "渲染", "相机", "战斗", "数值",
            "背包", "对话", "交易", "加载器", "数据表", "ai", "行为树", "逻辑", "控制", "索敌", "刷怪", "程序"
        )
        if k in low
    )

    if art_score > dev_score:
        tags: List[str] = []
        if any(k in low for k in ("精灵", "sprite", "图集", "角色")):
            tags.append("2d_sprite_sheet")
        if any(k in low for k in ("序列帧", "帧动画", "动画")):
            tags.append("frame_animation")
        if "spine" in low or "骨骼" in low:
            tags.append("spine_2d_rigging")
        if any(k in low for k in ("瓦片", "tilemap", "地图", "关卡")):
            tags.append("tilemap_design")
        if any(k in low for k in ("等轴", "2.5d", "建筑", "作物")):
            tags.append("isometric_25d_asset")
        if any(k in low for k in ("视差", "背景")):
            tags.append("parallax_background")
        if any(k in low for k in ("ui", "hud")):
            tags.append("ui_hud_art")
        if any(k in low for k in ("法线", "光照", "光效")):
            tags.append("2d_normal_lighting")
        if not tags:
            tags = ["2d_sprite_sheet", "tilemap_design"]
        return "art_2d", list(dict.fromkeys(tags))[:2], 8.0

    # 2D/2.5D 程序
    tags = []
    if any(k in low for k in ("碰撞", "物理", "aabb", "索敌")):
        tags.append("2d_physics_collision")
    if any(k in low for k in ("状态机", "ai", "行为树", "刷怪")):
        tags.append("character_state_machine")
    if any(k in low for k in ("等轴", "坐标", "网格")):
        tags.append("isometric_coord_math")
    if any(k in low for k in ("y-sort", "遮挡", "深度")):
        tags.append("y_sort_depth_render")
    if any(k in low for k in ("相机", "视差", "昼夜")):
        tags.append("camera_parallax_ctrl")
    if any(k in low for k in ("战斗", "伤害", "卡牌", "数值")):
        tags.append("combat_numeric_logic")
    if any(k in low for k in ("背包", "对话", "交易", "npc", "遗物", "事件")):
        tags.append("inventory_dialogue_sys")
    if any(k in low for k in ("加载器", "数据表", "配表", "json", "csv")):
        tags.append("data_table_loader")
    if not tags:
        tags = ["2d_physics_collision", "character_state_machine"]
    return "dev_2d", list(dict.fromkeys(tags))[:2], 8.0


def _build_acceptance_criteria(title: str, task_type: str, clause_text: str) -> Tuple[List[str], str]:
    if task_type == "design":
        return (
            [
                f"输出《{title}》定版规格参数表（无待定/冲突项），经主策拍案确认",
                "全部数值与 2D/2.5D 渲染基准可在下游任务直接引用校验",
            ],
            "HUMAN",
        )
    if task_type == "art_2d":
        return (
            [
                f"交付资源符合 2D/2.5D 导出规范（PNG 图集尺寸为 2 的幂次，Pivot 锚点校验 0 偏差）",
                f"覆盖原文条款要求：{clause_text[:48]}（经独立 QA 资源检视通过）",
            ],
            "HYBRID",
        )
    if task_type == "dev_2d":
        return (
            [
                f"对应模块单元测试覆盖率 >= 85%，核心逻辑帧耗时 <= 4.0ms（60 FPS 预算内）",
                f"严格兑现条款行为契约：{clause_text[:48]}",
            ],
            "AUTO" if "加载器" in title or "数学" in title or "数据表" in title else "HYBRID",
        )
    return (
        [
            "执行独立 QA 核验清单：0 个 P0/P1 阻塞缺陷，目标场景稳定 >= 60 FPS",
            "生成可追溯验收报告与 Git 校验基线",
        ],
        "HUMAN" if "终审" in title else "AUTO",
    )


def _summarize_title(text: str) -> str:
    head = re.split(r"[：:]", text, maxsplit=1)[0].strip()
    if 4 <= len(head) <= 28:
        return head
    clean = re.sub(r"[（(].*?[)）]", "", text).strip()
    return (clean[:26] + "…") if len(clean) > 27 else clean


def decompose_spec_markdown(
    raw_markdown: str,
    bots: List[BotCard],
    spec_id: Optional[str] = None,
    title: Optional[str] = None,
    genre: str = "2D / 2.5D 定制游戏",
    dimension_mode: str = "2D",
    spec_version: str = "v1.0",
) -> Tuple[SpecDocument, List[GameDevTask]]:
    """
    R1 + R2 + R6 确定性设计规格拆解器：
    1) 先过 3D 零容忍黑名单；
    2) 解析计划书条款生成双向追溯锚点；
    3) 补全 5 阶段聚散拓扑（Stage 1 集中定调 -> Stage 2 散开并行 -> Stage 3 联合合流 -> Stage 4 散开量产 -> Stage 5 集中封版）；
    4) 执行三维可解释 Bot 分配 + CPM 关键路径计算。
    """
    check_3d_blacklist(raw_markdown)

    if not raw_markdown or not raw_markdown.strip():
        raise ValueError("设计规格/项目计划书内容不能为空")

    # 推断标题与维度模式
    lines = [l.strip() for l in raw_markdown.splitlines() if l.strip()]
    inferred_title = title or (lines[0].lstrip("#").strip() if lines and lines[0].startswith("#") else "自定义 2D/2.5D 游戏项目计划书")
    if "2.5d" in raw_markdown.lower() or "等轴测" in raw_markdown:
        dimension_mode = "2.5D"

    sha = hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()
    clauses = _parse_clauses(raw_markdown)

    spec = SpecDocument(
        spec_id=spec_id or f"SPEC-{sha[:8].upper()}",
        title=inferred_title,
        genre=genre,
        dimension_mode=dimension_mode,
        spec_version=spec_version,
        content_sha256=sha,
        change_log=[f"{spec_version}: 初始化导入并完成结构化拆解（SHA256={sha[:10]}）"],
        raw_markdown=raw_markdown,
        clauses=clauses,
    )

    # 重置 Bot 当前负荷以便重新排期
    for b in bots:
        b.current_load_hours = 0.0

    # 按阶段分组生成原始候选任务
    stage_buckets: Dict[str, List[Tuple[SpecClause, str, List[str], float, Optional[str]]]] = {
        f"STAGE_{i}": [] for i in range(1, 6)
    }
    for idx, cl in enumerate(clauses):
        st_id = _infer_stage_id(cl.section, cl.text, idx, len(clauses))
        t_type, req_tags, dur = _infer_task_type_and_tags(cl.text, st_id)
        amb = _detect_ambiguity(cl.text)
        stage_buckets[st_id].append((cl, t_type, req_tags, dur, amb))

    # 保证 5 个阶段完整闭环（若用户自定义计划书偏简短，则自动补全缺失阶段，保持完整 SE 工作流）
    first_ref = clauses[0].clause_id
    last_ref = clauses[-1].clause_id
    if not stage_buckets["STAGE_1"]:
        stage_buckets["STAGE_1"].append(
            (SpecClause(clause_id=first_ref, section="§1 核心定调", text="确认 2D/2.5D 核心循环与数值基线"), "design", ["game_spec_breakdown", "scope_control"], 4.0, None)
        )
    if not any(t[1] == "design" for t in stage_buckets["STAGE_1"]):
        # 若 Stage 1 没有主策门禁，将 Stage 1 收束为主策规划
        cl0, _, _, dur0, amb0 = stage_buckets["STAGE_1"][0]
        stage_buckets["STAGE_1"].insert(
            0, (cl0, "design", ["game_spec_breakdown", "verdict_arbitration"], 4.0, amb0)
        )

    if not stage_buckets["STAGE_2"]:
        stage_buckets["STAGE_2"].extend([
            (SpecClause(clause_id=first_ref, section="§2 基础资产", text="绘制主角与基础场景 2D Sprite Sheet 与瓦片"), "art_2d", ["2d_sprite_sheet", "tilemap_design"], 8.0, None),
            (SpecClause(clause_id=first_ref, section="§2 底层框架", text="搭建 2D 物理碰撞与核心状态机框架"), "dev_2d", ["2d_physics_collision", "character_state_machine"], 8.0, None),
        ])
    else:
        has_art = any(x[1] == "art_2d" for x in stage_buckets["STAGE_2"])
        has_dev = any(x[1] == "dev_2d" for x in stage_buckets["STAGE_2"])
        if not has_art:
            stage_buckets["STAGE_2"].append((SpecClause(clause_id=first_ref, section="§2 美术补全", text="制作基础 2D 精灵图集与瓦片资源"), "art_2d", ["2d_sprite_sheet", "tilemap_design"], 6.0, None))
        if not has_dev:
            stage_buckets["STAGE_2"].append((SpecClause(clause_id=first_ref, section="§2 程序补全", text="实现 2D 碰撞与角色控制状态机"), "dev_2d", ["2d_physics_collision", "character_state_machine"], 6.0, None))

    if not stage_buckets["STAGE_3"]:
        stage_buckets["STAGE_3"].append(
            (SpecClause(clause_id=first_ref, section="§3 垂直切片", text="首关垂直切片跨角色合流联调"), "dev_2d", ["character_state_machine", "camera_parallax_ctrl"], 8.0, None)
        )
    if not any(x[1] == "qa_integ" for x in stage_buckets["STAGE_3"]):
        stage_buckets["STAGE_3"].append(
            (SpecClause(clause_id=first_ref, section="§3 垂直切片验收", text="首关垂直切片独立 QA 验收门"), "qa_integ", ["vertical_slice_integ", "acceptance_verification"], 5.0, None)
        )

    if not stage_buckets["STAGE_4"]:
        stage_buckets["STAGE_4"].extend([
            (SpecClause(clause_id=last_ref, section="§4 内容量产", text="扩展关卡瓦片与敌人动画资产量产"), "art_2d", ["tilemap_design", "frame_animation"], 8.0, None),
            (SpecClause(clause_id=last_ref, section="§4 系统扩展", text="实现道具背包、NPC 对话与进阶数值系统"), "dev_2d", ["inventory_dialogue_sys", "combat_numeric_logic"], 8.0, None),
        ])

    if not stage_buckets["STAGE_5"]:
        stage_buckets["STAGE_5"].extend([
            (SpecClause(clause_id=last_ref, section="§5 全链路压测", text="全流程回归测试与 60FPS 性能基线核验"), "qa_integ", ["regression_testing", "fps_memory_profiling"], 6.0, None),
            (SpecClause(clause_id=last_ref, section="§5 终审封版", text="主策终审封版拍案归档"), "design", ["verdict_arbitration", "scope_control"], 3.0, None),
        ])
    elif not any(x[1] == "design" for x in stage_buckets["STAGE_5"]):
        stage_buckets["STAGE_5"].append(
            (SpecClause(clause_id=last_ref, section="§5 终审封版", text="主策终审封版拍案归档"), "design", ["verdict_arbitration", "scope_control"], 3.0, None)
        )

    # 构造带清晰聚散拓扑的 GameDevTask DAG
    tasks: List[GameDevTask] = []
    stage_task_ids: Dict[str, List[str]] = {f"STAGE_{i}": [] for i in range(1, 6)}
    stage_gate_id: Dict[str, str] = {}

    for s_idx in range(1, 6):
        stage_id = f"STAGE_{s_idx}"
        items = stage_buckets[stage_id]
        prev_gate = stage_gate_id.get(f"STAGE_{s_idx - 1}")

        # 确定 Stage 内的节点顺序和依赖
        if stage_id == "STAGE_1":
            # Stage 1: 顺序或收敛到最后一个主策定调 Gate
            prev_in_stage: Optional[str] = None
            for t_i, (cl, t_type, tags, dur, amb) in enumerate(items, start=1):
                tid = f"TASK-S1-{t_i:02d}"
                is_last = t_i == len(items)
                # 最后一个主策节点作为 Stage 1 收口门禁
                mode = CollaborationMode.CONCENTRATED if (is_last or t_type == "design") else CollaborationMode.DISPERSED
                deps = [prev_in_stage] if prev_in_stage else []
                title_str = _summarize_title(cl.text)
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + dur, 2)
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                # 若存在歧义，首条直接置为 WAITING_DECISION；否则由编排器推进到门禁时触发拍案
                init_status = TaskStatus.WAITING_DECISION if amb else (TaskStatus.READY if not deps else TaskStatus.PENDING)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=mode,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        assignment_reason=reason,
                        depends_on=deps,
                        duration_hours=dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=init_status,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
                prev_in_stage = tid
            stage_gate_id[stage_id] = stage_task_ids[stage_id][-1]

        elif stage_id in ("STAGE_2", "STAGE_4"):
            # 散开并行阶段：所有任务直接依赖上一阶段 Gate，彼此无横向阻塞
            # 为并行分支赋予差异化标准工时（如 8h, 6h, 5h, 4h 或 8h, 5h），确保仅最长主干为关键路径 (slack==0)
            deps = [prev_gate] if prev_gate else []
            if len(items) == 2:
                dur_schedule = [8.0, 5.0]
            else:
                dur_schedule = [8.0, 6.0, 5.0, 4.0, 3.5, 3.0]
            for t_i, (cl, t_type, tags, dur, amb) in enumerate(items, start=1):
                eff_dur = dur_schedule[t_i - 1] if t_i - 1 < len(dur_schedule) else max(2.5, round(8.0 - (t_i - 1) * 1.2, 1))
                tid = f"TASK-S{s_idx}-{t_i:02d}"
                title_str = _summarize_title(cl.text)
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + eff_dur, 2)
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=CollaborationMode.DISPERSED,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        assignment_reason=reason,
                        depends_on=list(deps),
                        duration_hours=eff_dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=TaskStatus.PENDING,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
            # Stage 2/4 末尾自然向下一阶段收敛；以列表最后一个作为参考，但下一阶段会汇聚本阶段所有叶节点
            stage_gate_id[stage_id] = stage_task_ids[stage_id][-1]

        elif stage_id == "STAGE_3":
            # 联合合流阶段：前置依赖 Stage 2 的全部任务（跨角色合流 In-degree >= 2），随后收束到 QA Gate
            upstream_s2 = list(stage_task_ids["STAGE_2"])
            joint_items = [x for x in items if x[1] != "qa_integ"]
            qa_items = [x for x in items if x[1] == "qa_integ"]
            if not joint_items:
                joint_items = [items[0]]

            joint_ids: List[str] = []
            # 寻找参与联调的美术与程序协作者
            art_bots_used = sorted({t.assigned_bot_id for t in tasks if t.stage_id == "STAGE_2" and t.task_type == "art_2d"})
            dev_bots_used = sorted({t.assigned_bot_id for t in tasks if t.stage_id == "STAGE_2" and t.task_type == "dev_2d"})

            t_counter = 1
            for j_idx, (cl, t_type, tags, dur, amb) in enumerate(joint_items):
                eff_dur = max(3.0, round(dur - j_idx * 2.0, 1))
                tid = f"TASK-S3-{t_counter:02d}"
                t_counter += 1
                title_str = _summarize_title(cl.text)
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + eff_dur, 2)
                collabs = [b for b in (art_bots_used + dev_bots_used) if b != bot.bot_id]
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=CollaborationMode.JOINT,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        collaborator_bot_ids=collabs,
                        assignment_reason=reason,
                        depends_on=list(upstream_s2),
                        duration_hours=eff_dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=TaskStatus.PENDING,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
                joint_ids.append(tid)

            for q_idx, (cl, t_type, tags, dur, amb) in enumerate(qa_items):
                eff_dur = max(3.0, round(dur - q_idx * 1.5, 1))
                tid = f"TASK-S3-{t_counter:02d}"
                t_counter += 1
                title_str = _summarize_title(cl.text)
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + eff_dur, 2)
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=CollaborationMode.CONCENTRATED,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        collaborator_bot_ids=joint_ids,
                        assignment_reason=reason,
                        depends_on=list(joint_ids),
                        duration_hours=eff_dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=TaskStatus.PENDING,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
            stage_gate_id[stage_id] = stage_task_ids[stage_id][-1]

        elif stage_id == "STAGE_5":
            # 集中收口阶段：QA 汇集 Stage 4 所有任务，随后主策终审封版 Gate
            upstream_s4 = list(stage_task_ids["STAGE_4"])
            qa_items = [x for x in items if x[1] != "design"]
            design_items = [x for x in items if x[1] == "design"]
            if not qa_items:
                qa_items = [(SpecClause(clause_id=last_ref, section="§5 回归", text="全链路 QA 回归与性能验证"), "qa_integ", ["regression_testing", "fps_memory_profiling"], 6.0, None)]
            if not design_items:
                design_items = [(SpecClause(clause_id=last_ref, section="§5 封版", text="主策终审封版拍案归档"), "design", ["verdict_arbitration", "scope_control"], 3.0, None)]

            t_counter = 1
            qa_ids: List[str] = []
            for cl, t_type, tags, dur, amb in qa_items:
                tid = f"TASK-S5-{t_counter:02d}"
                t_counter += 1
                title_str = _summarize_title(cl.text)
                # Stage 5 非主策收口默认归口 QA 集成（若误标为 dev/art 则保留原类型但依然汇聚 S4）
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + dur, 2)
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=CollaborationMode.CONCENTRATED,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        assignment_reason=reason,
                        depends_on=list(upstream_s4),
                        duration_hours=dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=TaskStatus.PENDING,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
                qa_ids.append(tid)

            for cl, t_type, tags, dur, amb in design_items:
                tid = f"TASK-S5-{t_counter:02d}"
                t_counter += 1
                title_str = _summarize_title(cl.text)
                bot, reason = explain_and_select_bot(t_type, tags, bots)
                bot.current_load_hours = round(bot.current_load_hours + dur, 2)
                criteria, v_mode = _build_acceptance_criteria(title_str, t_type, cl.text)
                tasks.append(
                    GameDevTask(
                        task_id=tid,
                        title=title_str,
                        stage_id=stage_id,
                        collaboration_mode=CollaborationMode.CONCENTRATED,
                        task_type=t_type,
                        required_tags=tags,
                        assigned_bot_id=bot.bot_id,
                        assignment_reason=reason,
                        depends_on=list(qa_ids),
                        duration_hours=dur,
                        acceptance_criteria=criteria,
                        verify_mode=v_mode,
                        source_clause_ref=f"{cl.clause_id} ({cl.section})",
                        status=TaskStatus.PENDING,
                        ambiguity_note=amb,
                    )
                )
                stage_task_ids[stage_id].append(tid)
            stage_gate_id[stage_id] = stage_task_ids[stage_id][-1]

    recalculate_cpm(tasks)
    return spec, tasks


def get_preset_case(case_key: str, bots: List[BotCard]) -> Tuple[SpecDocument, List[GameDevTask]]:
    preset = PRESET_SPECS.get(case_key)
    if not preset:
        raise ValueError(f"未知预设案例 '{case_key}'，可选：{list(PRESET_SPECS.keys())}")
    return decompose_spec_markdown(
        raw_markdown=preset["raw_markdown"],
        bots=bots,
        spec_id=preset["spec_id"],
        title=preset["title"],
        genre=preset["genre"],
        dimension_mode=preset["dimension_mode"],
        spec_version="v1.0",
    )
