# 2D / 2.5D 游戏工程多 Agent 全链路动态编排与执行可视化平台

> 当前可运行代码版本：**v3.0**（`app.py` / `backend/` / `frontend/`，9/9 验收测试全绿）｜最新已定稿总体架构蓝图：**v4.3**（LLM-First 默认真 API 环境，按 M1~M4 规划落地）。

---

## 范围与非目标（Scope & Non-Goals）

- **适用范围**：面向 **2D / 2.5D 游戏大类**（横版动作 / 类银河恶魔城、俯视角经营模拟、肉鸽卡牌等通用 2D/2.5D 游戏研发场景）的软件工程全链路多 Agent 协同工作流，覆盖「立项讨论 → 方案评审 → 需求/设计冻结 → 任务分解 → CPM 排期与动态执行 → 可视化监控 → 反馈热重排」闭环。
- **非目标（Non-Goals）**：
  - 不支持 3D 渲染管线、3D 建模/骨骼动画/Shader 资产生产（全链路白名单 + 零容忍黑名单拦截 `ERR_3D_PIPELINE_FORBIDDEN`）；
  - 不覆盖非游戏类跨行业软件工程场景（如社交软件、电商系统或通用 OA）；
  - 不承担商业游戏引擎（Unity / Godot / Unreal）工程的真实二进制编译打包与运行时宿主托管；
  - 不涉及多租户企业级账号体系与分布式权限中心（定位为单机/小组级工程协同与仿真平台）。

---

## 设计文档与架构演进（Docs Index）

| 文档 | 版本 / 状态 | 说明 |
| :--- | :--- | :--- |
| [总体架构设计-九阶段双编排器全链路架构-v4.3.md](docs/总体架构设计-九阶段双编排器全链路架构-v4.3.md) | **v4.3 架构定稿蓝图（规划待落地）** | 汇总“默认真 LLM API”决策、D1~D7 组内方案融合、P0×8 / P1×18 评审修正、AG2 讨论内核、`PHASE_1~9` / `DEV_STAGE_1~5` 双轨与 M1~M4 落地路线图 |
| [设计评审意见-总体架构设计-v4.3.md](docs/设计评审意见-总体架构设计-v4.3.md) | v4.3 评审意见清单（待消缺） | 对照 v4.2 与 v3.0 契约审出的 P0×7 / P1×18 / P2×8 修改建议（进入 M1 编码前参考） |
| [详细设计方案-九阶段双编排器全链路架构-v4.0.md](docs/详细设计方案-九阶段双编排器全链路架构-v4.0.md) | v4.2 详细设计归档（原样保留备查） | 经两轮架构自审的 v4.2 全链路细粒度规约草案 |
| [设计评审意见-九阶段双编排器全链路架构-v4.2.md](docs/设计评审意见-九阶段双编排器全链路架构-v4.2.md) | v4.2 评审意见档案 | 对照 v3.0 代码契约逐节审出的 P0×8 / P1×18 / P2×10 评审清单 |
| [需求说明-项目管理任务可视化与多Agent流改造.md](docs/需求说明-项目管理任务可视化与多Agent流改造.md) | v3.0 需求定稿（已实现） | 下游 2D/2.5D 动态编排与可视化平台的 7 条验收判据与契约基准 |
| [group4-process-design.pdf](docs/group4-process-design.pdf) | 作业 2 基线设计 | 第四组全流程工程设计基线文档 |
| [multi-agent-discussion-workflow-design-v1.2.pdf](docs/multi-agent-discussion-workflow-design-v1.2.pdf) | 作业 1 基线设计 | 上游多 Agent 讨论工作流设计基线 v1.2 |
| [USAGE.md](docs/USAGE.md) | v1.0 历史基线指南 | 第一阶段 `main.py` / `src/` CLI 静态分解与硬性记忆使用说明 |

---

## v4.3 下一阶段统一架构规划概览（待按 M1~M4 实施）

> 诚实边界说明：以下 6 项为核心团队已拍板的 **v4.3 总体架构规划**，详见 [v4.3 总体架构设计文档](docs/总体架构设计-九阶段双编排器全链路架构-v4.3.md)；截至当前提交，主干运行代码仍为 **v3.0**（下游编排仿真与可视化平台）。

1. **双轨阶段分明（`PHASE_1~9` vs `DEV_STAGE_1~5`）**：宏观全链路按 `PHASE_1~9`（独立 9-Chip 导航，严格确认门零绕过）推进；下游研发沿用领域包定义的 `DEV_STAGE_1~5`。
2. **LLM-First 三通道独立开关**：默认配置为 `UPSTREAM_MODE=llm`、`DECOMP_MODE=agent`、`EXEC_MODE=llm`；并发盲发/盲评通过按固定角色字典序串行回收保障结果顺序与哈希稳定；离线测试/CI 保留 `fixture` 与 `rule` 确定性回放通道。
3. **领域包与动态角色注册表外置化（`domain_packs/games_2d.json`）**：默认保持 4 类精简执行角色，白黑名单、阶段拓扑、角色卡与全链路阈值全部外置配置化。
4. **D1 PM Agent 双通道分解 + D3 自由策划案适配**：阶段 7 默认由 PM Agent（Tier-1）生成任务草案，规则通道作为确定性兜底与对比基线，共用 `V-1~V-7` 校验门（违规 2 次自动回落 `rule` 并留痕），执行分配与 CPM 排期始终由确定性代码拍板；上游支持通过 `spec_adapter` 兼容任意自由格式游戏策划案。
5. **主策外部共享服务 + 单文件 SSOT 存储**：主策 `planner_master` 作为双编排器之外的横切决策服务；会话全量状态统一收口到单文件原子写 `.storage/sessions/<session_id>/session_state.json` + 追加流 `events.jsonl`，`.sandbox_git/` 专注派生分支审计留痕。
6. **9 态任务 FSM、CPM 单最长路径修正与可控三回退回路**：对齐 9 态枚举、以 `max(EF)` 单最长路径作为 CP 分母、落地 S-1~S-4 安全门（含合法规格语境白名单）、通过 `SpecUpgradeReconciler` 在大回退升版时 100% 保留未变更 `SUCCEEDED` 任务。

---

## v3.0 已实现可运行平台（当前主干：`app.py` / `backend/` / `frontend/`）

### 核心特性（动态编排仿真与可视化平台）

- **严格 4 类精简角色**：`ROLE_PLANNER`（主策 · Tier-1 旗舰模型 + 唯一拥有踩坑教训记忆）、`ROLE_ART_2D`、`ROLE_DEV_2D`、`ROLE_QA_INTEG`（独立验收，保障作者与评价者严格分离）。
- **2D / 2.5D 白名单与 3D 零容忍黑名单**：彻底剔除 3D 管线，命中 `FORBIDDEN_3D_BLACKLIST` 当场拦截报错 `ERR_3D_PIPELINE_FORBIDDEN`。
- **五阶段横轴 × 四角色泳道合流图**：清晰呈现 `CONCENTRATED`（集中收口）→ `DISPERSED`（散开并行）→ `JOINT`（联合合流）→ `DISPERSED` → `CONCENTRATED` 拓扑与金色关键路径（`slack == 0`），支持正交总线分流走线、悬停高亮与视图过滤。
- **防自欺双口径进度仪表盘 & CPM 实时重算**：主口径关键路径完成比 vs 辅口径全图工时吞吐比；关键路径总工时等于 CPM 预计总工期；支持延期顺延实时重算与告警。
- **动态编排仿真器 & 编排器内部原理图 (Orchestrator Internals)**：支持暂停/恢复、单步 Tick、主策拍案裁决弹窗、QA 打回重试（2 次自动升级主策拍案）、运行期改派资格拦截、阶段门快照回滚，以及五层流水线/状态机/实时调度队列/职责边界原理视图。
- **环境监听 & 增量 DAG 热重排 & 沙箱 Git 演化树**：玩家反馈量化评分、噪音过滤、脏节点传递闭包增量重排（100% 保留已完成历史任务）及真实 `.sandbox_git` 分支提交留痕。
- **零外部 API Key 可跑通 v3.0 演示**：内置确定性仿真引擎，无需 LLM API Key 即可跑通第 11 节全部 7 条验收判据。

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

## 2D 银河城可玩垂直切片示例：《丝烬幽窟》（`hollow_grapple/`）

仓库额外附带一套 2D 横版动作银河城可玩垂直切片案例 **《丝烬幽窟》（SILKHOLLOW : THREAD OF ABYSS）**（对应平台 2D 横版动作 / 钩锁开发域的纯前端实装样例）：

- **设计策划案**：[GDD_游戏策划案.md](hollow_grapple/GDD_游戏策划案.md)（v1.0，涵盖世界观、5 层视差氛围、双模渊丝钩锁与角色手感参数、5 大互联分区、4 类常规敌怪及双阶段 Boss「残丝监守者 · 维洛斯」）。
- **运行入口**：[hollow_grapple/index.html](hollow_grapple/index.html)（零第三方依赖 HTML5 Canvas 60Hz + Web Audio 程序化音效合成，支持浏览器直接打开或静态 HTTP 服务运行）。

```bash
# 可选：通过本地静态服务启动试玩
python -m http.server 8080 --directory hollow_grapple
```

---

## 当前仓库目录说明

```text
RJGC-agent/
├── app.py               # v3.0 Web 服务启动入口 (http://127.0.0.1:8000)
├── backend/             # v3.0 核心引擎 (models/rules/cpm/presets/decomposer/planner_memory/listener/git_sandbox/orchestrator/server)
├── frontend/            # v3.0 可视化控制面板 (index.html / styles.css / app.js)
├── hollow_grapple/      # 2D 银河城《丝烬幽窟》GDD 策划案与零依赖纯前端可玩垂直切片 (index.html / styles.css / js/)
├── tests/               # v3.0 验收测试 (test_acceptance_7_criteria.py) 与历史演示脚本 (run_demo.sh)
├── docs/                # 基线设计 PDF、v3.0 需求说明、v4.2 详细设计归档与评审意见、v4.3 总体架构蓝图与评审清单
├── main.py              # v1.0 历史 CLI 静态分解与对话入口（保留基线）
├── src/                 # v1.0 历史基线实现模块
├── config/              # v1.0 历史角色卡配置
├── examples/            # v1.0 示例输入规格 (spec.json)
└── memory/              # v1.0 历史记忆 JSON 基线目录
```

---

## v1.0 上游基线（CLI 静态分解与多轮对话，历史归档）

仓库保留了第一阶段 `main.py` / `src/` CLI 静态分解与硬性记忆基线（详细见 [docs/USAGE.md](docs/USAGE.md)）：

```bash
python3 main.py decompose --spec examples/spec.json --deadline 2026-12-25
python3 main.py chat
python3 main.py show
bash tests/run_demo.sh
```
