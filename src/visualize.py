# -*- coding: utf-8 -*-
"""
产物渲染：把任务图渲染为人类可读的任务清单（Markdown）
与一个零外部依赖的静态可视化页（SVG 的 DAG + CSS 甘特）。
"""
import html
from datetime import date

TYPE_COLORS = {
    "开发": "#2563eb",
    "测试": "#059669",
    "评审": "#d97706",
    "人工": "#7c3aed",
    "规划": "#64748b",
}


def render_tasks_md(graph):
    """graph: {项目, 图版本, 概要, 任务[]} -> Markdown 文本。"""
    s = graph["概要"]
    lines = []
    lines.append("# 任务清单：%s" % graph["项目"])
    lines.append("")
    lines.append("- 任务图版本：v%s" % graph["图版本"])
    lines.append("- 规格版本：%s" % graph.get("规格版本", ""))
    lines.append("- 项目周期：%s → %s（工作日口径，8 小时/日）" % (s["项目开始日期"], s["项目截止日期"]))
    lines.append("- 任务总数：%d 个；总工时：%d 小时；关键路径：%d 小时"
                 % (len(graph["任务"]), s["总工时"], s["关键路径工时"]))
    lines.append("- 关键路径：%s" % " → ".join(s["关键路径"]))
    lines.append("")
    lines.append("| 编号 | 任务 | 来源 | 执行对象 | 限制时间 | 依赖 | 验收 |")
    lines.append("|---|---|---|---|---|---|---|")
    for t in graph["任务"]:
        lt = t["限制时间"]
        limit = "%dh 工时<br>截止 %s<br>缓冲 %dh%s" % (
            lt["工时"], lt["截止日期"], lt["缓冲小时"],
            "（关键路径）" if lt["是否关键路径"] else "")
        src = "%s %s<br>%s" % (t["来源模块"], t["模块名称"], "、".join(t["需求编号"]))
        exe = "%s（%s）" % (t["执行对象"]["承担者"], t["执行对象"]["角色"])
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            t["编号"], t["标题"], src, exe, limit,
            "、".join(t["依赖"]) or "—", "%s：%s" % (t["验收方式"], t["验收标准"])))
    lines.append("")
    lines.append("> 规则：没有执行对象或没有限制时间的任务不许进入执行编排；"
                 "关键路径任务缓冲为 0，延期直接顺延项目截止日。")
    return "\n".join(lines) + "\n"


# ---------------- HTML 可视化 ----------------

def _layout_levels(tasks):
    """按最长依赖链给任务分层（DAG 横向布局用）。"""
    by_id = {t["编号"]: t for t in tasks}
    level = {}

    def lev(tid):
        if tid in level:
            return level[tid]
        deps = by_id[tid]["依赖"]
        level[tid] = 0 if not deps else max(lev(d) for d in deps) + 1
        return level[tid]

    for t in tasks:
        lev(t["编号"])
    return level


def render_html(graph):
    tasks = graph["任务"]
    s = graph["概要"]
    by_id = {t["编号"]: t for t in tasks}
    levels = _layout_levels(tasks)
    max_level = max(levels.values()) if levels else 0

    # ---- DAG（SVG）----
    col_w, row_h, node_w, node_h = 210, 74, 168, 46
    rows = {}
    pos = {}
    counters = {}
    for t in sorted(tasks, key=lambda x: (levels[x["编号"]], x["编号"])):
        lv = levels[t["编号"]]
        r = counters.get(lv, 0)
        counters[lv] = r + 1
        pos[t["编号"]] = (30 + lv * col_w, 26 + r * row_h)
        rows[lv] = max(rows.get(lv, 0), r + 1)
    width = 30 + (max_level + 1) * col_w
    height = 26 + max(rows.values()) * row_h + 10
    critical = set(s["关键路径"])
    edges, nodes = [], []
    for t in tasks:
        x, y = pos[t["编号"]]
        for d in t["依赖"]:
            x1, y1 = pos[d]
            crit = d in critical and t["编号"] in critical
            edges.append(
                '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="%s" marker-end="url(#arr)"/>'
                % (x1 + node_w, y1 + node_h // 2, x, y + node_h // 2,
                   "#dc2626" if crit else "#94a3b8", "2.2" if crit else "1.2"))
        color = TYPE_COLORS.get(t["类型"], "#334155")
        stroke = "#dc2626" if t["编号"] in critical else color
        nodes.append(
            '<g><rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s22" stroke="%s" stroke-width="1.6"/>'
            '<text x="%d" y="%d" font-size="12" fill="#0f172a"><tspan font-weight="700">%s</tspan> %s</text>'
            '<text x="%d" y="%d" font-size="10.5" fill="#475569">%s · %dh · 截止 %s</text></g>'
            % (x, y, node_w, node_h, color, stroke,
               x + 9, y + 19, t["编号"], html.escape(t["模块名称"]),
               x + 9, y + 37, html.escape(t["执行对象"]["承担者"]),
               t["工时"], t["限制时间"]["截止日期"]))
    dag_svg = (
        '<svg width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">'
        '<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L7,3 L0,6 z" fill="#64748b"/></marker></defs>%s%s</svg>'
        % (width, height, "".join(edges), "".join(nodes)))

    # ---- 甘特（CSS 条）----
    start = date.fromisoformat(s["项目开始日期"])
    total_days = max(
        (date.fromisoformat(t["限制时间"]["截止日期"]) - start).days for t in tasks) + 1
    bars = []
    for t in tasks:
        lt = t["限制时间"]
        off = (date.fromisoformat(lt["开始日期"]) - start).days
        end = (date.fromisoformat(lt["截止日期"]) - start).days
        dur = max(end - off, 1)
        left = off / total_days * 100
        wdt = dur / total_days * 100
        color = TYPE_COLORS.get(t["类型"], "#334155")
        crit = " outline:2px solid #dc2626;" if lt["是否关键路径"] else ""
        bars.append(
            '<div class="grow"><div class="glabel">%s %s</div>'
            '<div class="gtrack"><div class="gbar" style="left:%.1f%%;width:%.1f%%;background:%s;%s" '
            'title="%s：%s → %s，缓冲 %dh"></div></div>'
            '<div class="gmeta">%s · %dh · 缓冲 %dh</div></div>'
            % (t["编号"], html.escape(t["模块名称"]), left, wdt, color, crit,
               html.escape(t["标题"]), lt["开始日期"], lt["截止日期"], lt["缓冲小时"],
               html.escape(t["执行对象"]["承担者"]), t["工时"], lt["缓冲小时"]))

    # ---- 任务表 ----
    rows_html = []
    for t in tasks:
        lt = t["限制时间"]
        rows_html.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s（%s）</td>"
            "<td>%dh / 截止 %s / 缓冲 %dh%s</td><td>%s</td><td>%s</td></tr>"
            % (t["编号"], html.escape(t["标题"]),
               "%s %s" % (t["来源模块"], html.escape(t["模块名称"])),
               html.escape(t["执行对象"]["承担者"]), html.escape(t["执行对象"]["角色"]),
               lt["工时"], lt["截止日期"], lt["缓冲小时"],
               " · 关键路径" if lt["是否关键路径"] else "",
               "、".join(t["依赖"]) or "—", t["验收方式"]))

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>任务图可视化 · %(title)s</title>
<style>
body{font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc}
h1{font-size:20px} h2{font-size:16px;margin-top:28px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;overflow-x:auto}
table{border-collapse:collapse;width:100%%;font-size:13px}
td,th{border:1px solid #e2e8f0;padding:6px 8px;text-align:left}
th{background:#f1f5f9}
.grow{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:12px}
.glabel{width:110px;text-align:right;color:#334155}
.gtrack{position:relative;flex:1;height:16px;background:#eef2f7;border-radius:4px}
.gbar{position:absolute;top:2px;height:12px;border-radius:3px}
.gmeta{width:210px;color:#64748b}
.legend span{margin-right:14px;font-size:12px}
.dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
</style></head><body>
<h1>任务图可视化 · %(title)s（任务图 v%(ver)s）</h1>
<p>周期 %(start)s → %(end)s ｜ 任务 %(n)d 个 ｜ 总工时 %(hours)d 小时 ｜ 关键路径 %(cp)s（红框/红线，缓冲 0）</p>
<p class="legend"><span><i class="dot" style="background:#2563eb"></i>开发</span><span><i class="dot" style="background:#059669"></i>测试</span><span><i class="dot" style="background:#d97706"></i>评审</span><span><i class="dot" style="background:#7c3aed"></i>人工</span></p>
<h2>依赖图（DAG）</h2><div class="card">%(dag)s</div>
<h2>甘特（按自然日近似排布，精确口径以任务表的工作日限制时间为准）</h2><div class="card">%(gantt)s</div>
<h2>任务清单</h2><div class="card"><table>
<tr><th>编号</th><th>任务</th><th>来源</th><th>执行对象</th><th>限制时间</th><th>依赖</th><th>验收</th></tr>
%(rows)s</table></div>
</body></html>""" % {
        "title": html.escape(graph["项目"]), "ver": graph["图版本"],
        "start": s["项目开始日期"], "end": s["项目截止日期"],
        "n": len(tasks), "hours": s["总工时"],
        "cp": " → ".join(s["关键路径"]),
        "dag": dag_svg, "gantt": "".join(bars), "rows": "".join(rows_html),
    }
