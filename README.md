# 2D / 2.5D 游戏工程多 Agent 动态编排与执行可视化平台 (v3.0)

> 基于第四组《多体讨论工作流设计文档 v1.2》《流程设计（作业2）v1.0》及《需求说明-项目管理任务可视化与多Agent流改造（v3.0 终极定稿版）》完成改造升级。

## v3.0 核心特性（动态编排仿真与可视化平台）

- **严格 4 类精简角色**：`ROLE_PLANNER`（主策 · Tier-1 旗舰模型 + 唯一拥有踩坑教训记忆）、`ROLE_ART_2D`、`ROLE_DEV_2D`、`ROLE_QA_INTEG`（独立验收，保障作者与评价者严格分离）。
- **2D / 2.5D 白名单与 3D 零容忍黑名单**：彻底剔除 3D 管线，命中 `FORBIDDEN_3D_BLACKLIST` 当场拦截报错 `ERR_3D_PIPELINE_FORBIDDEN`。
- **五阶段横轴 × 四角色泳道合流图**：清晰呈现 `CONCENTRATED`（集中收口）→ `DISPERSED`（散开并行）→ `JOINT`（联合合流）→ `DISPERSED` → `CONCENTRATED` 拓扑与金色关键路径（`slack == 0`），支持正交总线分流走线、悬停高亮与视图过滤。
- **防自欺双口径进度仪表盘 & CPM 实时重算**：主口径关键路径完成比 vs 辅口径全图工时吞吐比；关键路径总工时严格等于 CPM 预计总工期；支持延期顺延实时重算与告警。
- **动态编排仿真器 & 编排器内部原理图 (Orchestrator Internals)**：支持暂停/恢复、单步 Tick、主策拍案裁决弹窗、QA 打回重试（2 次自动升级主策拍案）、运行期改派资格拦截、阶段门快照回滚，以及五层流水线/8 态 FSM/实时调度队列/职责边界原理视图。
- **环境监听 & 增量 DAG 热重排 & 沙箱 Git 演化树**：玩家反馈量化评分、噪音过滤、脏节点传递闭包增量重排（100% 保留已完成历史任务）及真实 `.sandbox_git` 分支提交留痕。
- **零外部 API Key 可跑通**：内置确定性仿真引擎，无需 LLM API Key 即可 100% 跑通第 11 节全部 7 条验收判据。

### 快速启动 v3.0 可视化平台

```bash
pip install -r requirements.txt   # 仅依赖 pydantic>=2.10.0
python app.py --host 127.0.0.1 --port 8000
```
打开浏览器访问 `http://127.0.0.1:8000` 即可使用。

### 运行 v3.0 全量验收测试（7 条判据 + E2E）

```bash
python -m unittest discover -s tests -v
```

---

## v1.0 上游基线（CLI 静态分解与多轮对话）

仓库保留了第一阶段 `main.py` / `src/` CLI 静态分解与硬性记忆基线（详细见 [docs/USAGE.md](docs/USAGE.md)）：

```bash
python3 main.py decompose --spec examples/spec.json --deadline 2026-12-25
python3 main.py chat
python3 main.py show
bash tests/run_demo.sh
```
