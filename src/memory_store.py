# -*- coding: utf-8 -*-
"""
硬性记忆：以结构化 JSON 原样存储的事实库，位于 memory/ 目录。

四类存储：
- spec_library.json  设计规格库：规格原文 + 版本 + 内容哈希（SHA-256）
- task_graphs.json   任务图库：任务图的各个版本 + 已删任务的墓碑 + 编号计数器
- constraints.json   约束清单：用户定下的硬约束，只增改要经过程序写操作
- changelog.json     变更记录：每次落库变更一条，含来源（命令/对话轮次）

硬性规则：
- 这些文件只能通过本模块的写方法修改，不允许模型或对话“凭记忆”改写；
- 任务编号由计数器单调发放，永不复用；删除任务时写入墓碑，编号作废留痕；
- 任务图每次写操作生成新版本，旧版本保留在库中可查。
"""
import hashlib
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MEMORY_DIR = os.path.join(BASE_DIR, "memory")

FILES = {
    "spec": "spec_library.json",
    "graphs": "task_graphs.json",
    "constraints": "constraints.json",
    "changelog": "changelog.json",
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _canonical(obj):
    """把对象序列化为稳定字符串（用于算内容哈希）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def content_hash(obj):
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


class HardMemory:
    def __init__(self, memory_dir=DEFAULT_MEMORY_DIR):
        self.dir = memory_dir
        os.makedirs(self.dir, exist_ok=True)
        self._ensure_files()

    # ---------- 基础读写 ----------
    def _path(self, key):
        return os.path.join(self.dir, FILES[key])

    def _read(self, key, default):
        path = self._path(key)
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, key, data):
        path = self._path(key)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # 原子替换，避免写一半损坏事实库

    def _ensure_files(self):
        if not os.path.exists(self._path("spec")):
            self._write("spec", {"规格库": []})
        if not os.path.exists(self._path("graphs")):
            self._write("graphs", {"版本": [], "墓碑": [], "编号计数器": 0})
        if not os.path.exists(self._path("constraints")):
            self._write("constraints", {"约束": []})
        if not os.path.exists(self._path("changelog")):
            self._write("changelog", {"变更记录": []})

    # ---------- 设计规格库 ----------
    def save_spec(self, spec):
        """把一份设计规格存入规格库（相同哈希不重复存）。返回存储条目。"""
        lib = self._read("spec", {"规格库": []})
        h = content_hash(spec)
        for entry in lib["规格库"]:
            if entry["内容哈希"] == h:
                return entry
        entry = {
            "规格版本": spec.get("规格版本", "未标版本"),
            "项目": spec.get("项目", ""),
            "内容哈希": h,
            "存入时间": _now(),
            "规格原文": spec,
        }
        lib["规格库"].append(entry)
        self._write("spec", lib)
        return entry

    # ---------- 约束清单 ----------
    def list_constraints(self):
        return self._read("constraints", {"约束": []})["约束"]

    def add_constraint(self, text, source="初始化"):
        cons = self._read("constraints", {"约束": []})
        cid = "C-%02d" % (len(cons["约束"]) + 1)
        cons["约束"].append({"编号": cid, "内容": text, "来源": source, "写入时间": _now()})
        self._write("constraints", cons)
        return cid

    # ---------- 任务图库 ----------
    def reset_task_graph(self, tasks, meta):
        """
        分解命令专用：以本次分解结果初始化任务图库为版本 1。
        编号计数器设为当前最大任务号，之后只增不减。
        """
        max_no = 0
        for t in tasks:
            try:
                max_no = max(max_no, int(str(t["编号"]).split("-")[1]))
            except Exception:
                pass
        graphs = {
            "版本": [{"版本号": 1, "生成时间": _now(), "元信息": meta, "任务": tasks}],
            "墓碑": [],
            "编号计数器": max_no,
        }
        self._write("graphs", graphs)
        return 1

    def current_graph(self):
        """返回最新版本的任务图条目 {版本号, 元信息, 任务}，没有时返回 None。"""
        graphs = self._read("graphs", {"版本": []})
        if not graphs["版本"]:
            return None
        return graphs["版本"][-1]

    def save_new_graph_version(self, tasks, meta, change_desc, source):
        """
        在旧版本基础上存入一个新版本，并写一条变更记录。
        被删除的任务（旧版本有、新版本没有）自动登记墓碑。
        返回新版本号。
        """
        graphs = self._read("graphs", {"版本": [], "墓碑": [], "编号计数器": 0})
        old = graphs["版本"][-1] if graphs["版本"] else {"任务": []}
        old_ids = {t["编号"] for t in old["任务"]}
        new_ids = {t["编号"] for t in tasks}
        for tid in sorted(old_ids - new_ids):
            graphs["墓碑"].append({"任务编号": tid, "删除时间": _now(), "原因": change_desc})
        new_version = (old.get("版本号", 0) + 1) if graphs["版本"] else 1
        graphs["版本"].append(
            {"版本号": new_version, "生成时间": _now(), "元信息": meta, "任务": tasks}
        )
        self._write("graphs", graphs)
        self.append_changelog("任务图变更", change_desc, source,
                              before_version=old.get("版本号"), after_version=new_version)
        return new_version

    def next_task_id(self):
        """发放下一个任务编号（单调递增，永不复用，含已进墓碑的编号）。"""
        graphs = self._read("graphs", {"版本": [], "墓碑": [], "编号计数器": 0})
        graphs["编号计数器"] += 1
        self._write("graphs", graphs)
        return "T-%02d" % graphs["编号计数器"]

    # ---------- 变更记录 ----------
    def append_changelog(self, kind, desc, source, **extra):
        log = self._read("changelog", {"变更记录": []})
        entry = {"序号": len(log["变更记录"]) + 1, "时间": _now(),
                 "类型": kind, "说明": desc, "来源": source}
        entry.update(extra)
        log["变更记录"].append(entry)
        self._write("changelog", log)
        return entry

    def list_changelog(self):
        return self._read("changelog", {"变更记录": []})["变更记录"]
