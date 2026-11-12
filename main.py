# -*- coding: utf-8 -*-
"""
任务分解 Agent 系统 · 入口

用法（在仓库根目录运行）：
  python3 main.py decompose --spec examples/spec.json --deadline 2026-12-25
  python3 main.py chat
  python3 main.py show

decompose 是初始化动作：把规格存入硬性记忆的规格库，并以分解结果
重置任务图库为 v1，产出 outputs/task_graph.json、outputs/tasks.md、
outputs/task_graph.html。之后的修改请走 chat 对话（提案—确认—落库）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.decomposer import decompose
from src.memory_store import HardMemory
from src.roles import assign, load_role_cards
from src.visualize import render_html, render_tasks_md

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")


def cmd_decompose(args):
    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    memory = HardMemory()
    entry = memory.save_spec(spec)
    print("设计规格已存入硬性记忆 · 规格库（版本 %s，内容哈希 %s…）"
          % (entry["规格版本"], entry["内容哈希"][:12]))

    cards = load_role_cards()
    tasks, summary = decompose(spec, cards, args.deadline, assign)
    meta = {"项目": spec.get("项目", ""), "规格版本": spec.get("规格版本", ""), "概要": summary}
    version = memory.reset_task_graph(tasks, meta)
    if not memory.list_constraints():
        memory.add_constraint("项目截止日期为 %s，关键路径任务缓冲为 0，不顺延总工期" % args.deadline, "decompose 初始化")
        memory.add_constraint("没有执行对象或没有限制时间的任务不许进入执行编排", "decompose 初始化")
        memory.add_constraint("任务编号稳定不复用，删除留墓碑", "decompose 初始化")
    memory.append_changelog("首次分解", "由规格 %s 分解出 %d 个任务，任务图 v%d"
                            % (spec.get("规格版本", ""), len(tasks), version), "decompose 命令")

    graph = {"项目": spec.get("项目", ""), "规格版本": spec.get("规格版本", ""),
             "图版本": version, "概要": summary, "任务": tasks}
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(os.path.join(OUTPUTS_DIR, "task_graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUTS_DIR, "tasks.md"), "w", encoding="utf-8") as f:
        f.write(render_tasks_md(graph))
    with open(os.path.join(OUTPUTS_DIR, "task_graph.html"), "w", encoding="utf-8") as f:
        f.write(render_html(graph))

    print("分解完成：%d 个任务，总工时 %d 小时" % (len(tasks), summary["总工时"]))
    print("项目周期：%s → %s（工作日口径）" % (summary["项目开始日期"], summary["项目截止日期"]))
    print("关键路径（%d 小时）：%s" % (summary["关键路径工时"], " → ".join(summary["关键路径"])))
    print("产物：outputs/task_graph.json、outputs/tasks.md、outputs/task_graph.html")
    return 0


def cmd_show(args):
    memory = HardMemory()
    graph = memory.current_graph()
    if graph is None:
        print("尚无任务图，请先运行 decompose。")
        return 1
    s = graph["元信息"]["概要"]
    print("任务图 v%d｜%s｜任务 %d 个｜总工时 %d 小时｜周期 %s → %s"
          % (graph["版本号"], graph["元信息"].get("项目", ""),
             len(graph["任务"]), s["总工时"], s["项目开始日期"], s["项目截止日期"]))
    print("关键路径：%s" % " → ".join(s["关键路径"]))
    entries = memory.list_changelog()
    print("变更记录共 %d 条，最近一条：%s" % (
        len(entries), entries[-1]["说明"] if entries else "无"))
    return 0


def cmd_chat(args):
    from src.chat import ChatSession
    memory = HardMemory()
    session = ChatSession(memory)
    session.repl()
    return 0


def main():
    parser = argparse.ArgumentParser(description="任务分解 Agent 系统")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_dec = sub.add_parser("decompose", help="把设计规格分解为任务图（初始化）")
    p_dec.add_argument("--spec", required=True, help="设计规格 JSON 路径")
    p_dec.add_argument("--deadline", required=True, help="项目截止日期 YYYY-MM-DD")
    p_dec.set_defaults(func=cmd_decompose)
    sub.add_parser("chat", help="多轮对话模式").set_defaults(func=cmd_chat)
    sub.add_parser("show", help="查看当前任务图概要").set_defaults(func=cmd_show)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
