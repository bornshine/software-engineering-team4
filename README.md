# 任务分解 Agent 系统

《多体讨论工作流设计文档 v1.2》第 7 章「开发任务分解」的细化实现：设计规格出来之后，
由一个**任务分解 Agent** 把设计规格拆成一个一个的 task，每个任务**必须标明执行对象
与限制时间**；修改通过简单的多轮对话完成，事实由**硬性记忆**（结构化存储）承载，
执行对象的能力边界由**角色卡**定义。

设计口径：**流程确定性、内容概率性**——拆分、依赖推导、分配、估时、关键路径与校验
全部是确定性代码（纯 Python 标准库，零第三方依赖，不联网、不需要任何 API 密钥）。

## 快速开始

在本仓库根目录运行（Python 3.8+）：

```bash
# 1) 把示例设计规格（多体讨论工作流系统自身）分解为任务图
python3 main.py decompose --spec examples/spec.json --deadline 2026-12-25

# 2) 看产物
#    outputs/task_graph.json  任务图（机器可读）
#    outputs/tasks.md         任务清单（人类可读）
#    outputs/task_graph.html  静态可视化（DAG + 甘特，浏览器直接打开）

# 3) 多轮对话：查看、改派、改限时、接口变更影响分析（先提案、确认才落库）
python3 main.py chat

# 4) 查看当前任务图概要与变更记录条数
python3 main.py show

# 一键实测（分解 + 一轮对话变更），输出存 outputs/demo_run.log
bash tests/run_demo.sh
```

## 目录结构

```text
.
├── main.py               入口：decompose / chat / show 三条命令
├── config/
│   └── role_cards.json   角色卡（5 张：分解Agent、开发、测试、评审、真人）
├── examples/
│   └── spec.json         示例设计规格（多体讨论工作流系统自身）
├── memory/               硬性记忆（结构化 JSON，程序运行时生成/更新）
│   ├── spec_library.json  设计规格库（原文 + 版本 + 内容哈希）
│   ├── task_graphs.json   任务图库（各版本 + 墓碑 + 编号计数器）
│   ├── constraints.json   约束清单
│   └── changelog.json     变更记录
├── src/
│   ├── decomposer.py     分解引擎：拆分/依赖推导/CPM 关键路径/校验
│   ├── roles.py          角色卡加载与执行对象匹配、改派复核
│   ├── memory_store.py   硬性记忆读写（原子写、版本、墓碑、哈希）
│   ├── chat.py           多轮对话（会话历史 + 指代 + 提案-确认）
│   └── visualize.py      任务清单 Markdown 与静态可视化 HTML 渲染
├── outputs/              分解产物与实测日志
├── docs/USAGE.md         详细使用文档
└── tests/run_demo.sh     实测脚本
```

## 核心规则（硬性，程序强制）

- 没有**执行对象**或没有**限制时间**的任务，校验不通过，不产出任务图；
- 执行对象只能按**角色卡**的能力标签与负责类型分配，改派也要复核，不合规直接拒绝；
- 限制时间由项目截止日沿**关键路径反推**：关键路径任务缓冲为 0，延期直接影响总工期；
- 任务图必须无环、无悬空依赖、每个任务可独立验收且能回溯到需求编号；
- 对话里的任何修改先出 **diff 提案**，用户确认后才落库：任务图版本 +1、写变更记录；
- 任务编号稳定不复用，删除留**墓碑**。

详细说明见 [docs/USAGE.md](docs/USAGE.md)。
