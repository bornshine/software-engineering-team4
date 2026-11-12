# -*- coding: utf-8 -*-
"""
分解引擎：设计规格 JSON -> 任务图（确定性实现，不依赖任何 LLM）。

流水线：
  1. 解析规格：模块 / 工作项 / 需求编号 / 模块依赖
  2. 按模块拆任务：每个 work_item 生成一个任务
  3. 推导依赖（规则见 derive_dependencies）
  4. 按角色卡分配执行对象（能力标签 + 负责类型 + 负载均衡）
  5. CPM 关键路径计算：正推最早开始/结束，反推最晚开始/结束，
     每个任务的限制时间 = 截止日期（由项目截止日沿关键路径反推）+ 缓冲（总时差）
  6. 校验：无环 / 无悬空依赖 / 可独立验收 / 执行对象与限时必填

时间口径：工时以小时计；日期按工作日折算（1 工作日 = 8 小时，跳过周末）。
"""
import math
from datetime import date, timedelta

HOURS_PER_DAY = 8

# 工作项类型之间的同模块先后关系（类型流水线顺序）
TYPE_ORDER = {"人工": 0, "开发": 1, "测试": 2, "评审": 3}


# ---------------- 工作日工具 ----------------

def _is_workday(d):
    return d.weekday() < 5  # 周一=0 … 周五=4


def add_workdays(d, n):
    """从 d 起向后数 n 个工作日（n=0 返回 d 本身，先把 d 调到工作日）。"""
    while not _is_workday(d):
        d += timedelta(days=1)
    step = 1
    while n > 0:
        d += timedelta(days=step)
        if _is_workday(d):
            n -= 1
    return d


def sub_workdays(d, n):
    """从 d 起向前数 n 个工作日。"""
    while not _is_workday(d):
        d -= timedelta(days=1)
    while n > 0:
        d -= timedelta(days=1)
        if _is_workday(d):
            n -= 1
    return d


def date_of_offset(start, hours_offset):
    """项目开始日 + 工时偏移 -> 日期（按整工作日折算，多余小时进位到当天）。"""
    days = int(hours_offset // HOURS_PER_DAY)
    return add_workdays(start, days)


# ---------------- 1-2. 解析与拆分 ----------------

def build_raw_tasks(spec):
    """
    把规格的模块/工作项展开为原始任务（尚未分配、未排期）。
    任务编号按模块顺序、工作项顺序依次发放 T-01、T-02、…（单次分解内稳定）。
    """
    tasks = []
    counter = 0
    for module in spec["模块"]:
        for item in module.get("work_items", []):
            counter += 1
            tasks.append({
                "编号": "T-%02d" % counter,
                "标题": item["标题"],
                "来源模块": module["id"],
                "模块名称": module["名称"],
                "需求编号": list(module.get("需求编号", [])),
                "类型": item["类型"],
                "能力要求": item["能力"],
                "工时": item["工时"],
                "验收方式": item.get("验收方式", ""),
                "验收标准": item.get("验收标准", ""),
                "依赖": [],
                "_item_key": item.get("key", ""),
            })
    return tasks


# ---------------- 3. 依赖推导 ----------------

def derive_dependencies(spec, tasks):
    """
    依赖推导规则（确定性）：
    R1 同模块内按类型流水线：人工 -> 开发 -> 测试 -> 评审，
       后一类任务依赖同模块所有前一类任务（如测试依赖本模块全部开发任务）。
    R2 跨模块：若模块 A depends_on 模块 B，则 A 的「开发」任务依赖 B 的「开发」任务
       （接口就绪才能动手）；B 没有开发任务时，依赖 B 的最后一个流水线任务。
    """
    by_module = {}
    for t in tasks:
        by_module.setdefault(t["来源模块"], []).append(t)

    def ids(module_id, type_name=None):
        lst = by_module.get(module_id, [])
        if type_name is not None:
            lst = [t for t in lst if t["类型"] == type_name]
        return [t["编号"] for t in lst]

    for t in tasks:
        deps = set()
        my_order = TYPE_ORDER[t["类型"]]
        # R1：同模块在先类型
        for other in by_module[t["来源模块"]]:
            if TYPE_ORDER[other["类型"]] < my_order:
                deps.add(other["编号"])
        t["依赖"] = sorted(deps)

    module_deps = {m["id"]: m.get("depends_on", []) for m in spec["模块"]}
    for t in tasks:
        if t["类型"] != "开发":
            continue
        deps = set(t["依赖"])
        for dep_module in module_deps.get(t["来源模块"], []):
            upstream = ids(dep_module, "开发") or ids(dep_module)
            deps.update(upstream)
        t["依赖"] = sorted(deps)
    return tasks


# ---------------- 4. 分配执行对象 ----------------

def assign_executors(tasks, cards, assign_fn):
    """逐个任务按角色卡分配执行对象，并累计工时做负载均衡。"""
    from collections import defaultdict
    load = defaultdict(int)
    for t in tasks:
        result = assign_fn(cards, t["能力要求"], t["类型"], load)
        if result is None:
            raise ValueError(
                "任务 %s（%s）找不到可承接的执行对象：能力「%s」/类型「%s」"
                "没有任何角色卡匹配，请检查 config/role_cards.json"
                % (t["编号"], t["标题"], t["能力要求"], t["类型"]))
        t["执行对象"] = result
        load[result["承担者"]] += t["工时"]
    return tasks


# ---------------- 5. CPM 排期与限制时间 ----------------

def topo_sort(tasks):
    """Kahn 拓扑排序；有环时抛错并指出剩余节点。"""
    by_id = {t["编号"]: t for t in tasks}
    indeg = {t["编号"]: 0 for t in tasks}
    adj = {t["编号"]: [] for t in tasks}
    for t in tasks:
        for d in t["依赖"]:
            if d not in by_id:
                raise ValueError("任务 %s 依赖了不存在的任务 %s（悬空依赖）" % (t["编号"], d))
            indeg[t["编号"]] += 1
            adj[d].append(t["编号"])
    queue = sorted([tid for tid, v in indeg.items() if v == 0])
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    if len(order) != len(tasks):
        remaining = sorted(set(by_id) - set(order))
        raise ValueError("任务图存在循环依赖，涉及任务：%s" % "、".join(remaining))
    return order, adj


def compute_schedule(tasks, deadline_str):
    """
    CPM 计算并回填每个任务的限制时间字段。就地修改 tasks，返回概要 dict。
    - 正推：ES = max(前置 EF)，EF = ES + 工时
    - 项目总时长 = max(EF)；项目开始日 = 截止日往前推总时长（工作日折算）
    - 反推：LF = min(后继 LS)，LS = LF - 工时；缓冲（总时差）= LS - ES
    - 限制时间.截止日期 = 开始日 + EF 折算日期；关键路径任务缓冲为 0
    """
    deadline = date.fromisoformat(deadline_str)
    deadline = sub_workdays(deadline, 0)  # 若截止日落在周末，回退到周五
    order, adj = topo_sort(tasks)
    by_id = {t["编号"]: t for t in tasks}

    es, ef = {}, {}
    for tid in order:
        t = by_id[tid]
        es[tid] = max([ef[d] for d in t["依赖"]], default=0)
        ef[tid] = es[tid] + t["工时"]
    project_hours = max(ef.values()) if ef else 0

    total_days = int(math.ceil(project_hours / HOURS_PER_DAY)) if project_hours else 0
    project_start = sub_workdays(deadline, max(total_days - 1, 0))

    ls, lf = {}, {}
    for tid in reversed(order):
        t = by_id[tid]
        lf[tid] = min([ls[s] for s in adj[tid]], default=project_hours)
        ls[tid] = lf[tid] - t["工时"]

    critical = []
    for t in tasks:
        tid = t["编号"]
        buffer_h = ls[tid] - es[tid]
        t["限制时间"] = {
            "工时": t["工时"],
            "开始日期": str(date_of_offset(project_start, es[tid])),
            "截止日期": str(date_of_offset(project_start, max(ef[tid] - 1, 0))),
            "缓冲小时": buffer_h,
            "是否关键路径": buffer_h == 0,
        }
        t["_es"] = es[tid]
        if buffer_h == 0:
            critical.append(tid)
    # 关键路径按 ES 排序输出
    critical.sort(key=lambda tid: es[tid])
    summary = {
        "项目开始日期": str(project_start),
        "项目截止日期": str(deadline),
        "总工时": sum(t["工时"] for t in tasks),
        "关键路径工时": project_hours,
        "关键路径": critical,
    }
    return summary


# ---------------- 6. 校验 ----------------

def validate_tasks(tasks):
    """落库前的硬性校验，任何一项不过都抛错（校验失败 = 不产出任务图）。"""
    errors = []
    ids = [t["编号"] for t in tasks]
    if len(ids) != len(set(ids)):
        errors.append("任务编号有重复")
    for t in tasks:
        if not t.get("执行对象") or not t["执行对象"].get("承担者"):
            errors.append("任务 %s 缺少执行对象" % t["编号"])
        lt = t.get("限制时间")
        if not lt or not lt.get("截止日期") or lt.get("工时") is None:
            errors.append("任务 %s 缺少限制时间（工时/截止日期）" % t["编号"])
        if not t.get("验收标准"):
            errors.append("任务 %s 缺少验收标准，无法独立验收" % t["编号"])
        if not t.get("需求编号"):
            errors.append("任务 %s 缺少需求编号，无法追溯" % t["编号"])
    topo_sort(tasks)  # 顺带做无环 + 无悬空依赖校验（内部会抛错）
    if errors:
        raise ValueError("任务图校验未通过：\n- " + "\n- ".join(errors))
    return True


# ---------------- 主流程 ----------------

def decompose(spec, cards, deadline_str, assign_fn):
    """完整分解：返回 (tasks, summary)。内部字段（下划线开头）在落库前剔除。"""
    tasks = build_raw_tasks(spec)
    tasks = derive_dependencies(spec, tasks)
    tasks = assign_executors(tasks, cards, assign_fn)
    summary = compute_schedule(tasks, deadline_str)
    validate_tasks(tasks)
    for t in tasks:
        t.pop("_item_key", None)
        t.pop("_es", None)
    return tasks, summary
