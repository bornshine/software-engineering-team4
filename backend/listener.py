from __future__ import annotations

from collections import deque
from typing import Dict, List, Set, Tuple
from .cpm import recalculate_cpm
from .models import (
    BotCard,
    ChangeRequestRecord,
    CollaborationMode,
    EnvSignalRecord,
    GameDevTask,
    SpecDocument,
    TaskStatus,
)
from .planner_memory import utc_now_str
from .rules import check_3d_blacklist, explain_and_select_bot


NOISE_KEYWORDS = (
    "午饭", "吃什么", "天气", "咖啡", "奶茶", "下班", "周末", "哈哈", "闲聊", "摸鱼", "快递", "打卡"
)
BUG_KEYWORDS = (
    "卡顿", "穿模", "闪退", "崩溃", "bug", "报错", "掉帧", "死锁", "错位", "生硬", "遮挡错误"
)
FEATURE_KEYWORDS = (
    "增加", "新增", "要求", "改进", "过渡", "动效", "小地图", "雷达", "视差", "关卡",
    "技能", "手感", "hud", "ui", "背包", "存档", "等轴", "房间", "光照", "法线", "boss", "试玩"
)


def evaluate_environment_signal(
    raw_text: str,
    source_type: str,
    seq_num: int,
) -> EnvSignalRecord:
    """第 9.2 节：环境信号提炼、噪音过滤与量化评分（urgency 1~10 + impact 1~10）。"""
    text = (raw_text or "").strip()
    check_3d_blacklist(text)

    low = text.lower()
    noise_hits = sum(1 for k in NOISE_KEYWORDS if k in low)
    bug_hits = sum(1 for k in BUG_KEYWORDS if k in low)
    feat_hits = sum(1 for k in FEATURE_KEYWORDS if k in low)

    if (noise_hits > 0 and bug_hits == 0 and feat_hits == 0) or (len(text) < 8 and bug_hits == 0 and feat_hits == 0):
        return EnvSignalRecord(
            signal_id=f"SIG-{seq_num:03d}",
            timestamp=utc_now_str(),
            source_type=source_type,
            raw_text=text,
            category="NOISE",
            urgency=1,
            impact=1,
            total_score=2,
            filtered_as_noise=True,
            requires_planner_verdict=False,
            extracted_summary="已识别为非工程相关闲聊/噪音，自动过滤拦截，不扰动当前编排 DAG。",
            status="IGNORED_NOISE",
        )

    if bug_hits > feat_hits:
        category = "BUG"
        urgency = min(10, 6 + bug_hits * 2)
        impact = min(10, 6 + (1 if any(k in low for k in ("等轴", "房间", "核心", "帧", "穿模", "死锁")) else 0) + feat_hits)
    else:
        category = "FEATURE_CHANGE"
        urgency = min(10, 6 + (1 if any(k in low for k in ("试玩", "反馈", "要求", "紧急")) else 0) + min(3, feat_hits))
        impact = min(10, 6 + min(4, feat_hits + bug_hits))

    total_score = urgency + impact
    requires_verdict = total_score >= 12
    extracted = (
        f"[{category}] 提炼核心诉求：「{text[:80]}{'…' if len(text) > 80 else ''}」"
        f"（紧急度={urgency}/10，架构影响度={impact}/10，综合评分={total_score}/20"
        f"{' >= 12，已推送主策拍案' if requires_verdict else ' < 12，归档为观察建议'}）"
    )

    return EnvSignalRecord(
        signal_id=f"SIG-{seq_num:03d}",
        timestamp=utc_now_str(),
        source_type=source_type,
        raw_text=text,
        category=category,
        urgency=urgency,
        impact=impact,
        total_score=total_score,
        filtered_as_noise=False,
        requires_planner_verdict=requires_verdict,
        extracted_summary=extracted,
        status="PENDING" if requires_verdict else "OBSERVED",
    )


def _infer_delta_specs(raw_text: str) -> List[Tuple[str, str, List[str], float]]:
    """根据提炼后的需求信号生成 1~2 个精准的 2D/2.5D 增量变更任务定义。"""
    low = raw_text.lower()
    deltas: List[Tuple[str, str, List[str], float]] = []

    if any(k in low for k in ("小地图", "雷达", "ui", "hud", "界面")):
        deltas.append((
            "增量 UI：小地图雷达与 HUD 指示器贴图",
            "art_2d",
            ["ui_hud_art", "2d_sprite_sheet"],
            4.0,
        ))
    if any(k in low for k in ("视差", "过渡", "动效", "房间", "相机", "等轴", "遮挡")):
        deltas.append((
            "增量逻辑：视差过渡动效与房间切换相机平滑",
            "dev_2d",
            ["camera_parallax_ctrl", "character_state_machine"],
            5.0,
        ))
    if not deltas:
        deltas.append((
            f"增量变更：{raw_text[:20]}",
            "dev_2d",
            ["combat_numeric_logic", "character_state_machine"],
            4.5,
        ))
    return deltas


def _find_direct_impact_anchors(raw_text: str, tasks: List[GameDevTask]) -> List[str]:
    low = raw_text.lower()
    keywords = [
        k for k in ("视差", "相机", "等轴", "房间", "小地图", "hud", "ui", "状态机", "动画", "瓦片", "光照", "战斗")
        if k in low
    ]
    matched: List[str] = []
    for t in tasks:
        # Stage 1 是立项定调，不回滚重置已完成的历史立项任务；增量重排作用于中后段研发任务
        if t.stage_id == "STAGE_1":
            continue
        blob = f"{t.title} {' '.join(t.required_tags)} {t.source_clause_ref}".lower()
        if any(k in blob for k in keywords):
            matched.append(t.task_id)

    if not matched:
        # 回退定位至 Stage 3 合流或 Stage 4 节点
        for t in tasks:
            if t.stage_id in ("STAGE_3", "STAGE_4"):
                matched.append(t.task_id)
                break
    return matched[:2]


def apply_incremental_hot_replan(
    signal: EnvSignalRecord,
    spec: SpecDocument,
    tasks: List[GameDevTask],
    bots: List[BotCard],
    verdict_id: str,
    cr_seq: int,
) -> Tuple[ChangeRequestRecord, List[GameDevTask]]:
    """
    第 9.2 节增量 DAG 热重排：
    1) 计算反向/下游依赖传递闭包得出脏节点集合（Dirty Tasks）；
    2) 已完成且不在下游重跑范围的历史任务（如 Stage 1、未受影响的 Stage 2）100% 保留 SUCCEEDED 不重跑；
    3) 注入新增量任务并接入 Stage 5 QA 门禁，重新计算全图 CPM。
    """
    check_3d_blacklist(signal.raw_text)

    # 先清除上一轮 dirty_flag
    for t in tasks:
        t.dirty_flag = False

    # 建立下游邻接表
    succ_map: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    task_map: Dict[str, GameDevTask] = {t.task_id: t for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in succ_map:
                succ_map[dep].append(t.task_id)

    anchor_ids = _find_direct_impact_anchors(signal.raw_text, tasks)

    # 传递闭包找出受影响下游脏节点
    dirty_set: Set[str] = set()
    queue = deque(anchor_ids)
    while queue:
        curr = queue.popleft()
        if curr in dirty_set:
            continue
        dirty_set.add(curr)
        for nxt in succ_map.get(curr, []):
            queue.append(nxt)

    # 若某个锚点本身已经 SUCCEEDED（非 Stage 5 回归门），保留其已完成产出作为新增量任务的依赖前驱，
    # 仅标记下游未完成任务与 Stage 5 回归门为脏节点重跑/重验！
    preserved_succeeded: List[str] = []
    reopened_dirty: List[str] = []

    for t in tasks:
        if t.task_id not in dirty_set:
            if t.status == TaskStatus.SUCCEEDED:
                preserved_succeeded.append(t.task_id)
            continue

        if t.stage_id in ("STAGE_1", "STAGE_2") and t.status == TaskStatus.SUCCEEDED:
            # 历史阶段已完成成果 100% 保留不重跑
            preserved_succeeded.append(t.task_id)
        elif t.task_id in anchor_ids and t.status == TaskStatus.SUCCEEDED and t.stage_id != "STAGE_5":
            preserved_succeeded.append(t.task_id)
        else:
            t.dirty_flag = True
            reopened_dirty.append(t.task_id)
            if t.status == TaskStatus.SUCCEEDED:
                # 特别是 Stage 5 验收门若已通过，因新增量需重新回到 PENDING 待回归
                t.status = TaskStatus.PENDING
                t.progress_hours = 0.0
                t.deliverable_summary = None
            elif t.status in (TaskStatus.RUNNING, TaskStatus.WAITING_VERIFY, TaskStatus.FAILED):
                t.status = TaskStatus.READY
                t.progress_hours = 0.0
            t.execution_logs.append(f"[HOT-REPLAN {signal.signal_id}] 位于变更影响闭包内，已标脏并等待增量同步。")

    # 插入新增量任务（挂入 STAGE_3 或 STAGE_4，并汇入 STAGE_5 首条 QA 门禁）
    target_stage = "STAGE_4"
    for a_id in anchor_ids:
        if task_map[a_id].stage_id in ("STAGE_2", "STAGE_3"):
            target_stage = "STAGE_3"
            break

    # 决定新任务前置依赖：优先依赖未完成或刚完成的锚点；若锚点本身要保留，直接接在锚点之后
    delta_specs = _infer_delta_specs(signal.raw_text)
    added_ids: List[str] = []

    # 寻找 Stage 1 收口门或 anchor 作为增量前驱
    s1_tasks = [t.task_id for t in tasks if t.stage_id == "STAGE_1"]
    default_deps = anchor_ids if anchor_ids else ([s1_tasks[-1]] if s1_tasks else [])

    existing_cr_count = sum(1 for t in tasks if t.task_id.startswith("TASK-CR-"))
    for idx, (title, t_type, tags, dur) in enumerate(delta_specs, start=1):
        new_id = f"TASK-CR-{existing_cr_count + idx:02d}"
        bot, reason = explain_and_select_bot(t_type, tags, bots)
        bot.current_load_hours = round(bot.current_load_hours + dur, 2)
        deps_ready = all(task_map[d].status in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED) for d in default_deps if d in task_map)
        new_task = GameDevTask(
            task_id=new_id,
            title=title,
            stage_id=target_stage,
            collaboration_mode=CollaborationMode.JOINT if len(delta_specs) > 1 else CollaborationMode.DISPERSED,
            task_type=t_type,
            required_tags=tags,
            assigned_bot_id=bot.bot_id,
            assignment_reason=reason,
            depends_on=list(default_deps),
            duration_hours=dur,
            acceptance_criteria=[
                f"响应环境变更信号 {signal.signal_id}：{signal.raw_text[:45]}",
                "增量模块 60 FPS 帧耗时 <= 2.0ms 且与主线场景零遮挡冲突",
            ],
            verify_mode="HYBRID",
            source_clause_ref=f"CR-{cr_seq:02d} ({signal.signal_id})",
            status=TaskStatus.READY if deps_ready else TaskStatus.PENDING,
            dirty_flag=True,
            verdict_id=verdict_id,
            execution_logs=[f"[HOT-REPLAN] 由主策拍案 {verdict_id} 增量注入 DAG。"],
        )
        tasks.append(new_task)
        task_map[new_id] = new_task
        added_ids.append(new_id)

    # 将新增量任务接入 STAGE_5 QA 回归门禁，保证闭环验收
    s5_qa_tasks = [t for t in tasks if t.stage_id == "STAGE_5" and t.task_type == "qa_integ"]
    if not s5_qa_tasks:
        s5_qa_tasks = [t for t in tasks if t.stage_id == "STAGE_5"]
    for qa_t in s5_qa_tasks[:1]:
        for aid in added_ids:
            if aid not in qa_t.depends_on:
                qa_t.depends_on.append(aid)
        qa_t.dirty_flag = True
        if qa_t.task_id not in reopened_dirty:
            reopened_dirty.append(qa_t.task_id)
        if qa_t.status in (TaskStatus.SUCCEEDED, TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.WAITING_VERIFY):
            qa_t.status = TaskStatus.PENDING
            qa_t.progress_hours = 0.0

    # 更新规格版本号与变更记录
    ver_num = int(spec.spec_version.lstrip("v").split(".")[0]) if spec.spec_version.startswith("v") else 1
    minor_num = int(spec.spec_version.lstrip("v").split(".")[1]) if "." in spec.spec_version else 0
    old_ver = spec.spec_version
    new_ver = f"v{ver_num}.{minor_num + 1}"
    spec.spec_version = new_ver
    spec.change_log.append(f"{new_ver} ({verdict_id}): {signal.raw_text[:60]} -> 新增 {added_ids}，保留 {len(preserved_succeeded)} 个已完成节点")

    recalculate_cpm(tasks)

    cr = ChangeRequestRecord(
        cr_id=f"CR-{cr_seq:03d}",
        signal_id=signal.signal_id,
        timestamp=utc_now_str(),
        spec_version_before=old_ver,
        spec_version_after=new_ver,
        dirty_task_ids=reopened_dirty + added_ids,
        preserved_succeeded_ids=preserved_succeeded,
        added_task_ids=added_ids,
        summary=f"保留 {len(preserved_succeeded)} 个历史已完成任务不重跑；标脏重算 {len(reopened_dirty)} 个受影响下游任务，新增 {len(added_ids)} 个增量任务。",
        verdict_id=verdict_id,
    )
    return cr, tasks
