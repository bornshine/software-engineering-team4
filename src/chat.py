# -*- coding: utf-8 -*-
"""
多轮对话：简单的会话模型 —— 保留本次会话的历史与上下文
（上一次提到的任务、待确认的变更提案），不做复杂的分层记忆。
所有事实都从硬性记忆（memory_store）精确读取；所有修改都先生成
提案（diff），用户输入「确认」后才通过硬性记忆的写操作落库，
任务图版本 +1 并写入变更记录。

支持的说法（固定语义，见 docs/USAGE.md）：
  列表                      查看任务列表
  详情 T-02 / 详情          查看详情（无编号时指代上一次提到的任务）
  改派 T-01 给 DevAgent-B   改派（先按角色卡复核能力，不合规直接拒绝）
  改限时 T-03 工时 32       改预估工时（自动重算全部限制时间）
  改限时 T-03 截止 2026-12-20  改该任务截止日期（人工调整，不重排其余任务）
  接口变更 M3               输出影响分析（沿 DAG 找下游受影响任务），确认后打「待复核」标记
  确认 / 取消               落库待确认提案 / 丢弃提案
  变更记录                  查看硬性记忆中的变更记录
  帮助 / 退出
"""
import copy
import re
import sys

from src.decomposer import compute_schedule
from src.roles import check_assignment, find_holder, load_role_cards


def fmt_task(t):
    lt = t["限制时间"]
    lines = []
    lines.append("%s %s" % (t["编号"], t["标题"]))
    lines.append("  来源：%s %s（%s）｜类型：%s｜能力要求：%s" % (
        t["来源模块"], t["模块名称"], "、".join(t["需求编号"]), t["类型"], t["能力要求"]))
    lines.append("  执行对象：%s（%s）" % (t["执行对象"]["承担者"], t["执行对象"]["角色"]))
    lines.append("  限制时间：%d 小时｜%s → %s｜缓冲 %d 小时%s" % (
        lt["工时"], lt["开始日期"], lt["截止日期"], lt["缓冲小时"],
        "｜关键路径" if lt["是否关键路径"] else ""))
    lines.append("  依赖：%s" % ("、".join(t["依赖"]) or "无"))
    lines.append("  验收：%s —— %s" % (t["验收方式"], t["验收标准"]))
    if t.get("标记"):
        lines.append("  标记：" + t["标记"])
    return "\n".join(lines)


def diff_tasks(old_tasks, new_tasks):
    """比较两版任务，产出人类可读的 diff 行列表。"""
    old = {t["编号"]: t for t in old_tasks}
    new = {t["编号"]: t for t in new_tasks}
    lines = []
    for tid in sorted(set(old) | set(new)):
        if tid not in old:
            lines.append("+ 新增 %s %s" % (tid, new[tid]["标题"]))
            continue
        if tid not in new:
            lines.append("- 删除 %s %s（编号进墓碑，不复用）" % (tid, old[tid]["标题"]))
            continue
        o, n = old[tid], new[tid]
        if o["执行对象"]["承担者"] != n["执行对象"]["承担者"]:
            lines.append("~ %s 执行对象：%s → %s" % (tid, o["执行对象"]["承担者"], n["执行对象"]["承担者"]))
        if o["工时"] != n["工时"]:
            lines.append("~ %s 工时：%dh → %dh" % (tid, o["工时"], n["工时"]))
        if o["限制时间"]["截止日期"] != n["限制时间"]["截止日期"]:
            lines.append("~ %s 截止日期：%s → %s" % (tid, o["限制时间"]["截止日期"], n["限制时间"]["截止日期"]))
        if o["限制时间"]["缓冲小时"] != n["限制时间"]["缓冲小时"]:
            lines.append("~ %s 缓冲：%dh → %dh" % (tid, o["限制时间"]["缓冲小时"], n["限制时间"]["缓冲小时"]))
        if o.get("标记") != n.get("标记"):
            lines.append("~ %s 标记：%s → %s" % (tid, o.get("标记", "无"), n.get("标记", "无")))
    return lines


class ChatSession:
    def __init__(self, memory):
        self.memory = memory
        self.cards = load_role_cards()
        graph = memory.current_graph()
        if graph is None:
            raise RuntimeError("硬性记忆里还没有任务图，请先运行 decompose 命令。")
        self.meta = graph["元信息"]
        self.tasks = copy.deepcopy(graph["任务"])
        self.history = []           # 简单多轮对话：本次会话历史
        self.last_task_id = None    # 上下文：最近提到的任务，供指代
        self.pending = None         # 待确认提案 {说明, 任务, 元信息}

    # ---------- 工具 ----------
    def _task(self, tid):
        for t in self.tasks:
            if t["编号"] == tid:
                return t
        return None

    def _resolve_task_id(self, text):
        m = re.search(r"T-\d+", text or "")
        if m:
            self.last_task_id = m.group(0)
            return self.last_task_id
        return self.last_task_id

    def _propose(self, desc, new_tasks, new_meta=None):
        lines = diff_tasks(self.tasks, new_tasks)
        if not lines:
            return "这个修改和当前任务图没有差异，未生成提案。"
        self.pending = {"说明": desc, "任务": new_tasks, "元信息": new_meta or self.meta}
        out = ["【变更提案】" + desc, "将产生以下变化（尚未落库）："]
        out += ["  " + l for l in lines]
        out.append("输入「确认」落库（任务图版本 +1，写入变更记录），或「取消」放弃。")
        return "\n".join(out)

    # ---------- 各命令 ----------
    def cmd_list(self):
        lines = ["当前任务图共 %d 个任务：" % len(self.tasks)]
        for t in self.tasks:
            lt = t["限制时间"]
            lines.append("  %s [%s] %s ｜ %s ｜ %dh 截止 %s%s" % (
                t["编号"], t["类型"], t["标题"], t["执行对象"]["承担者"],
                lt["工时"], lt["截止日期"], "｜★关键路径" if lt["是否关键路径"] else ""))
        return "\n".join(lines)

    def cmd_detail(self, text):
        tid = self._resolve_task_id(text)
        if not tid or not self._task(tid):
            return "没找到这个任务。你可以先说「列表」，或带编号说「详情 T-02」。"
        return fmt_task(self._task(tid))

    def cmd_reassign(self, text):
        m = re.search(r"改派\s*(T-\d+)?\s*(?:给|到)\s*(\S+)", text)
        if not m:
            return "格式：改派 T-01 给 DevAgent-B（执行对象写承担者名或角色名）。"
        tid = m.group(1) or self.last_task_id
        holder = m.group(2)
        if not tid or not self._task(tid):
            return "没定位到任务，请带上编号，如「改派 T-01 给 DevAgent-B」。"
        self.last_task_id = tid
        t = self._task(tid)
        ok, reason = check_assignment(self.cards, t["能力要求"], t["类型"], holder)
        if not ok:
            return "改派被拒绝：" + reason
        card, real_holder = find_holder(self.cards, holder)
        if real_holder is None:
            # 按角色名改派时，落到该角色卡的第一位承担者
            for c in self.cards:
                if c["角色名"] == holder and c.get("承担者"):
                    card, real_holder = c, c["承担者"][0]
                    break
        new_tasks = copy.deepcopy(self.tasks)
        nt = [x for x in new_tasks if x["编号"] == tid][0]
        nt["执行对象"] = {"角色": card["角色名"], "承担者": real_holder, "角色类型": card["角色类型"]}
        return self._propose("改派 %s 给 %s（角色卡复核通过）" % (tid, real_holder), new_tasks)

    def cmd_change_time(self, text):
        m = re.search(r"改限时\s*(T-\d+)?\s*(?:工时\s*(\d+)|截止\s*(\d{4}-\d{2}-\d{2}))", text)
        if not m:
            return "格式：改限时 T-03 工时 32，或 改限时 T-03 截止 2026-12-20。"
        tid = m.group(1) or self.last_task_id
        if not tid or not self._task(tid):
            return "没定位到任务，请带上编号。"
        self.last_task_id = tid
        new_tasks = copy.deepcopy(self.tasks)
        nt = [x for x in new_tasks if x["编号"] == tid][0]
        deadline = self.meta["概要"]["项目截止日期"]
        if m.group(2):
            nt["工时"] = int(m.group(2))
            summary = compute_schedule(new_tasks, deadline)
            new_meta = copy.deepcopy(self.meta)
            new_meta["概要"] = summary
            return self._propose("改限时 %s 工时改为 %dh（已按关键路径重算全部限制时间）" % (tid, nt["工时"]), new_tasks, new_meta)
        old_deadline = self._task(tid)["限制时间"]["截止日期"]
        nt["限制时间"]["截止日期"] = m.group(3)
        nt["标记"] = "截止日期经对话人工调整为 %s（原排期 %s）" % (m.group(3), old_deadline)
        return self._propose("改限时 %s 截止日期改为 %s（人工调整，不重排其余任务）" % (tid, m.group(3)), new_tasks)

    def cmd_interface_change(self, text):
        m = re.search(r"接口变更\s*(\S+)", text)
        if not m:
            return "格式：接口变更 M3（写模块编号或模块名称）。"
        key = m.group(1)
        module_tasks = [t for t in self.tasks if t["来源模块"] == key or t["模块名称"] == key]
        if not module_tasks:
            return "没找到模块「%s」，可用模块编号如 M1~M5 或模块名称。" % key
        dependents = {}
        for t in self.tasks:
            for d in t["依赖"]:
                dependents.setdefault(d, []).append(t["编号"])
        own = {t["编号"] for t in module_tasks}
        affected, stack = set(), list(own)
        while stack:
            cur = stack.pop()
            for nxt in dependents.get(cur, []):
                if nxt not in affected:
                    affected.add(nxt)
                    stack.append(nxt)
        down = sorted(affected - own)
        lines = ["【影响分析】模块 %s 接口变更：" % key,
                 "  本模块任务（需按新接口调整）：%s" % "、".join(sorted(own)),
                 "  下游受影响任务（依赖链传递）：%s" % ("、".join(down) if down else "无")]
        new_tasks = copy.deepcopy(self.tasks)
        for t in new_tasks:
            if t["编号"] in own | set(down):
                t["标记"] = "接口变更待复核（模块 %s）" % key
        lines.append(self._propose("接口变更 %s：给 %d 个任务打「待复核」标记" % (key, len(own) + len(down)), new_tasks))
        return "\n".join(lines)

    def cmd_confirm(self):
        if not self.pending:
            return "当前没有待确认的提案。"
        p, self.pending = self.pending, None
        version = self.memory.save_new_graph_version(p["任务"], p["元信息"], p["说明"], source="多轮对话（经用户确认）")
        self.tasks = p["任务"]
        self.meta = p["元信息"]
        return "已落库：任务图更新为 v%d，变更记录已写入硬性记忆。变更：%s" % (version, p["说明"])

    def cmd_changelog(self):
        entries = self.memory.list_changelog()
        if not entries:
            return "变更记录为空。"
        lines = ["硬性记忆 · 变更记录（最近 10 条）："]
        for e in entries[-10:]:
            lines.append("  #%d [%s] %s：%s（来源：%s）" % (e["序号"], e["时间"], e["类型"], e["说明"], e["来源"]))
        return "\n".join(lines)

    # ---------- 主循环 ----------
    def handle(self, text):
        text = (text or "").strip()
        if not text:
            return ""
        self.history.append({"role": "user", "text": text})
        if text in ("退出", "exit", "quit"):
            reply = "再见。本次会话共 %d 轮，未确认的提案不会落库。" % len(self.history)
            self.history.append({"role": "agent", "text": reply})
            print("Agent：" + reply)
            sys.exit(0)
        elif text in ("帮助", "help"):
            reply = ("可用说法：列表｜详情 T-02（或只说「详情」指代上一个）｜改派 T-01 给 DevAgent-B｜"
                     "改限时 T-03 工时 32｜改限时 T-03 截止 2026-12-20｜接口变更 M3｜确认｜取消｜变更记录｜退出")
        elif text.startswith("列表") or text.startswith("查看任务"):
            reply = self.cmd_list()
        elif text.startswith("详情"):
            reply = self.cmd_detail(text)
        elif text.startswith("改派"):
            reply = self.cmd_reassign(text)
        elif text.startswith("改限时"):
            reply = self.cmd_change_time(text)
        elif text.startswith("接口变更"):
            reply = self.cmd_interface_change(text)
        elif text == "确认":
            reply = self.cmd_confirm()
        elif text == "取消":
            self.pending = None
            reply = "已取消待确认提案，任务图未做任何修改。"
        elif text.startswith("变更记录"):
            reply = self.cmd_changelog()
        elif re.search(r"T-\d+", text):
            reply = self.cmd_detail(text)
        else:
            reply = "我没理解这句。说「帮助」可以看我能处理哪些说法。"
        self.history.append({"role": "agent", "text": reply})
        return reply

    def repl(self):
        print("任务分解 Agent · 多轮对话（说「帮助」看可用说法，「退出」结束）")
        graph = self.memory.current_graph()
        print("已从硬性记忆读入任务图 v%d，共 %d 个任务。" % (graph["版本号"], len(self.tasks)))
        while True:
            try:
                text = input("你：")
            except EOFError:
                print("\n（输入结束，会话关闭；未确认的提案不落库）")
                break
            reply = self.handle(text)
            if reply:
                print("Agent：" + reply)
