# 第一层（讨论层）→ 第二层（编排器）固定输出契约（v1.2 向后兼容）

> [!IMPORTANT]
> **给第二层编排器开发者的 TL;DR**：
> 第一层（讨论层）的最终输出接口已彻底固定并锁定（**v1.2 为纯向后兼容增量升级**，在 v1.0/v1.1 全部必填字段之上仅新增模块 `focus_tier` 焦点配额与 `pacing_flow_audit` 标记，旧解析器零破坏）：
> **`1 份 manifest.json` + `1 份 MASTER_GDD.md（附机器可读 gdd_index.yaml）` + `4 张工种纯需求表（叙事 / 美术 / 音频 / 程序系统）` + `外部长期记忆与不可变 ADR`**。
>
> 编排器**只需消费这份冻结交接包**，与讨论层内部的多支柱抽卡熔炉、骨架与逐系统微压测、双主干树拆解、底层模型厂商和原生 CLI **100% 物理彻底解耦**。

---

## 一、冻结交接包标准目录结构

讨论层完成 Stage 3 确定性对表终审并获得人类导演签字后，会在交接目录原子写入不可变版本快照：

```text
handoff/<project_id>/<spec_version>/
├── manifest.json                              # 交接包总入口：版本、父版本、总哈希、文件清单与签字元数据
├── MASTER_GDD.md                              # 《核心总策划案》（纯 What，供人类与高阶拆解 Agent 阅读）
├── gdd_index.yaml                             # MASTER_GDD.md 的机器可读模块索引（GDD-M01..Mxx）
├── diff_summary.yaml                          # [仅 Delta RFC 升版存在] 变更条目精确 ID 清单，驱动 DAG 增量标脏
├── requirements/                              # ⭐ 核心纯需求表（彻底取消“圣经”，只写 What 不写 How）
│   ├── narrative_requirements.yaml            # 叙事纯需求表（上栏全局约束 + 下栏本阶段交付清单）
│   ├── art_requirements.yaml                  # 美术纯需求表（上栏全局约束 + 下栏本阶段交付清单）
│   ├── audio_requirements.yaml                # 音频纯需求表（上栏全局约束 + 下栏本阶段交付清单）
│   └── system_requirements.yaml               # 程序系统纯需求表（含权威 state_id / event_id 声明，零引擎绑定）
├── references/                                # [可选] 美术纯需求表引用的风格参考样图（0~2 张）
│   └── style_ref_01.png
└── memory/                                    # 厂商无关外部长期记忆切片与审计证据
    ├── canon_registry.yaml                    # 世界真相账本快照（长期防吃书基准）
    ├── adr/
    │   └── ADR-001.yaml                       # 不可变架构/设计裁决日志（防下游迭代开倒车）
    └── ideas_backlog.md                       # 旁路参考灵感（严禁自动转为任务！仅供人类查阅）
```

> [!NOTE]
> 下文所有 Schema 与完整可运行样例，均以中小成本水墨风格化 2D 项目 **`西游记·女儿国（xiyou-nverguo / 《子母河畔·问心局》）`** 为统一示例，完整呈现 `GDD-Mxx` ↔ `SYS/NAR/ART/AUD` ↔ `ST_* / EVT_*` 的全闭合交叉引用关系。

---

## 二、逐文件字段级 Schema 与完整可运行示例

### 1. `manifest.json`（交接包总入口与防篡改哈希索引）

**编排器消费说明**：
* 编排器启动或恢复任务时**首先读取 `manifest.json`**；
* 通过 `canonical_sha256` 判断版本是否变更，结合各文件 `sha256` 与 `diff_summary.yaml` 实现**确定性断点续跑**与 **DAG 增量标脏**；
* `approval_signature.status` 必须为 `"APPROVED"`，否则编排器应拒绝消费。

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :---: | :--- |
| `contract_version` | `string` | ✅ | 契约协议版本，当前为 `"layer1-handoff/v1.2"`（100% 向后兼容 `v1.0/v1.1` 必填字段） |
| `project_id` | `string` | ✅ | 项目唯一标识（kebab-case） |
| `spec_version` | `string` | ✅ | 语义化版本号（如 `"v1.0.0"`，Delta RFC 递增为 `"v1.1.0"`） |
| `parent_version` | `string \| null` | ✅ | 上一冻结版本号；首版为 `null` |
| `canonical_sha256` | `string` | ✅ | 对除 `manifest.json` 外的规范化排序文件哈希再次计算的包级总摘要 |
| `scope_tier` | `enum` | ✅ | `"micro_2d" \| "indie_stylized_2d" \| "indie_light_25d"`（严禁出现 3A 写实） |
| `lead_pillars` | `string[]` | ✅ | 1~2 个领衔支柱，数组顺序即优先级权重 |
| `derived_pillars` | `string[]` | ✅ | 顺流衍生支柱补集 |
| `approval_signature` | `object` | ✅ | 人类导演签字记录（`approved_by`, `approved_at`, `status`） |
| `interceptors_passed` | `object` | ✅ | Stage 3 三道 $0 脚本拦截器与 `Feasibility Critic` 终审通过证明 |
| `files` | `object[]` | ✅ | 包内受管文件清单，含相对路径、`role`、`sha256` 与 `item_count` |
| `diff_summary_ref` | `string \| null` | ✅ | 首版为 `null`；Delta RFC 升版时指向 `"diff_summary.yaml"` |

```json
{
  "contract_version": "layer1-handoff/v1.2",
  "project_id": "xiyou-nverguo",
  "spec_version": "v1.0.0",
  "parent_version": null,
  "canonical_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "scope_tier": "indie_stylized_2d",
  "lead_pillars": ["narrative", "gameplay"],
  "derived_pillars": ["art", "audio"],
  "approval_signature": {
    "status": "APPROVED",
    "approved_by": "human_director",
    "approved_at": "2026-11-27T14:00:00Z",
    "note": "七日朝议问心局基调清晰，心流/信息量体检通过，四工种反向复述一致，准予交付编排层。"
  },
  "interceptors_passed": {
    "linked_gdd_ref_integrity": true,
    "gdd_bidirectional_na_closed": true,
    "system_no_how_blacklist_clean": true,
    "cross_table_state_event_closed": true,
    "no_placeholder_words_clean": true,
    "pacing_and_cognitive_load_audit": true,
    "understanding_echo_aligned": true,
    "feasibility_cold_reader_audit": true
  },
  "files": [
    {
      "path": "MASTER_GDD.md",
      "role": "master_gdd",
      "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "item_count": 2
    },
    {
      "path": "gdd_index.yaml",
      "role": "gdd_index",
      "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
      "item_count": 2
    },
    {
      "path": "requirements/narrative_requirements.yaml",
      "role": "narrative_requirements",
      "sha256": "ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d",
      "item_count": 2
    },
    {
      "path": "requirements/art_requirements.yaml",
      "role": "art_requirements",
      "sha256": "7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451",
      "item_count": 2
    },
    {
      "path": "requirements/audio_requirements.yaml",
      "role": "audio_requirements",
      "sha256": "2c624232cdd221771294dfbb310aca000a0df6ac8b66b696d90ef06fdefb64a3",
      "item_count": 2
    },
    {
      "path": "requirements/system_requirements.yaml",
      "role": "system_requirements",
      "sha256": "19581e27de7ced00ff1ce50b2047e7a567c76b1cbaebabe5ef03f7c3017bb5b7",
      "item_count": 2
    },
    {
      "path": "memory/canon_registry.yaml",
      "role": "canon_registry",
      "sha256": "4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce",
      "item_count": 3
    }
  ],
  "diff_summary_ref": null
}
```

---

### 2. `gdd_index.yaml`（`MASTER_GDD.md` 机器可读模块索引）

`MASTER_GDD.md` 面向阅读者完整陈述核心循环、博弈规则与边界条件；`gdd_index.yaml` 将其结构化为确定性的模块 ID 集合（`GDD-M01`, `GDD-M02`, ...），供编排器建图和三道拦截器核验 `linked_gdd_ref`。

```yaml
schema_version: "gdd_index/v1.2"
source_document: "MASTER_GDD.md"
rubric_coverage_map:                     # $0 脚本强制校验考纲 R01~R18 覆盖率 == 100%
  R01: "GDD-M01"
  R07: "GDD-M02"
pacing_summary:                          # 全局心流与信息量体检记录
  first_5min_new_concepts: 2             # 红线 <= 3，超标强制改为阶梯渐进解锁
  anchor_module_count: 1                 # 全章高光记忆位严格限 1~2 个，防止处处抖机灵毁心流
modules:
  - gdd_id: "GDD-M01"
    title: "子母河因果印记与体征隐瞒机制"
    pillar_origin: "narrative"
    priority: "P0"
    focus_tier: "FLOW"                   # 枚举: ANCHOR(高光位,限1~2) | FLOW(心流承重位) | UTILITY(零感基建)
    anchor_heading: "## 2.1 子母河因果印记与体征隐瞒"
    entry_trigger: "渡口剧情误饮子母河水触发 EVT_DRINK_RIVER_WATER"
    core_rules: "3阶段离散因果印记；每次隐瞒升1档，宵禁验真落胎泉清零锁定"
    win_exit: "七日内以真品落胎泉清零印记并保留博弈筹码"
    fail_exit: "印记升至3阶满溢，次日开场强制进入暴露危机 EVT_DEBATE_EXPOSED"
    experience_intent: "克制窒息的体征隐瞒心理拉扯（绝非打怪掉血或低俗猎奇笑料）"
    acceptance_oracle: "任意状态下误饮+2次隐瞒精确抵达3阶且无溢出"
  - gdd_id: "GDD-M02"
    title: "七日朝议质询与朱砂呈词循环"
    pillar_origin: "gameplay"
    priority: "P0"
    focus_tier: "ANCHOR"                 # 本章唯一高光记忆位：允许零膨胀微巧思（如高疑心落印手抖晕墨）
    anchor_heading: "## 2.2 七日朝议质询与朱砂呈词"
    entry_trigger: "每日昼间进入大殿朝议"
    core_rules: "昼间呈递证物盖印增减疑心值(0..100)，夜间宵禁搜证筹措"
    win_exit: "第7日昼间结束且疑心值<100进入终局分支判定"
    fail_exit: "疑心值>=100当帧中止质询触发 EVT_DEBATE_EXPOSED"
    experience_intent: "无声礼教凝视下的双向试探博弈（绝非拔刀追杀或跳吓恐怖片）"
    acceptance_oracle: "疑心值严格钳位[0,100]，满100当帧触发暴露事件"
```

---

### 3. `requirements/system_requirements.yaml`（程序系统纯需求表 · 权威状态/事件源）

> [!CAUTION]
> **编排器建图核心锚点**：`system_requirements.yaml` 是全交接包中 **`state_id`（前缀 `ST_`）与 `event_id`（前缀 `EVT_`）的唯一权威声明源**。同时保证 **100% 纯 What、零引擎/框架/类名绑定**（已通过 Stage 3 实现词黑名单扫描）。

* **上栏 `global_constraints`**：跨全生命周期不变的非功能硬指标（帧率/响应延迟/存档确定性/分辨率适配/平台边界）；
* **下栏 `stage_deliverables`**：本阶段具体系统功能需求卡（含 `linked_gdd_ref`、输入、业务规则、异常边界、`exposed_state_ids`、`emitted_event_ids` 与客观 `acceptance_criteria`）。

```yaml
schema_version: "system_requirements/v1.1"
discipline: "system"
milestone_scope: "vertical_slice_act1"
understanding_echo:                      # ≤150字大白话反向复述 + 2反例，1秒校验语义无偏移
  summary: "本作是双轨状态博弈（因果印记0..3与朝堂疑心0..100）驱动的克制宫廷盘问循环，胜负取决于礼法试探与宵禁筹措。"
  anti_examples:
    - "绝不做成实时追逐战斗或视野锥拔刀追杀系统。"
    - "绝不做成无脑刷数值升级或随机掉落装备系统。"
explicit_na_refs: []                     # 本表覆盖全部 GDD 模块；若某模块无系统需求必须显式声明及理由

global_constraints:
  non_functional_targets:
    target_frame_rate_hz: 60
    input_to_feedback_max_ms: 80
    deterministic_save_load: true
    base_aspect_ratio: "16:9"
    min_supported_resolution: "1280x720"
  shared_entity_dictionary:              # Root 共享实体词典，全树子节点严禁重造
    - { entity_id: "ENT_HERO", name: "取经人代表" }
    - { entity_id: "ENT_QUEEN", name: "女儿国主" }
    - { entity_id: "ENT_PRECEPTOR", name: "太师" }
  architecture_boundaries:
    - "所有状态迁移与数值判定必须纯数据驱动且可脱离画面独立回放验证。"
    - "禁止依赖任何联网服务器或外部云端存档服务，纯单机离线运行。"

system_interaction_matrix:               # 主干①收口必交：显式锁死跨系统并发冲突仲裁，消灭接缝打架
  - pair: ["SYS-001", "SYS-002"]
    concurrent_trigger: "同一结算帧内同时满足 EVT_BREAK_CURSE 与 EVT_DEBATE_EXPOSED"
    resolution_rule: "强制优先结算 EVT_BREAK_CURSE，ST_WATER_CURSE_STAGE 归0锁定并取消当帧暴露结算（见 ADR-001）"

stage_deliverables:
  - req_id: "SYS-001"
    tree_path: "SYSTEMS/SYS-001"         # 双主干游戏树血缘路径（SYSTEMS/* 或 WORLD/<大场景>/<小场景>）
    title: "子母河因果印记状态机"
    linked_gdd_ref: "GDD-M01"
    priority: "P0"
    inputs:
      - "玩家在朝议中选择「隐瞒/伪装」对话选项"
      - "玩家在宵禁阶段使用「落胎泉试样」道具"
    business_rules:
      - "印记状态 ST_WATER_CURSE_STAGE 仅取离散整数 0（未染）、1（微澜）、2（显相）、3（满溢）。"
      - "触发 EVT_DRINK_RIVER_WATER 后，ST_WATER_CURSE_STAGE 从 0 立即升至 1。"
      - "每次选择伪装隐瞒且未被当场拆穿时，ST_WATER_CURSE_STAGE 递增 1（上限 3）。"
      - "当 ST_WATER_CURSE_STAGE 达到 3 且进入次日朝议开场前，必须触发终局暴露事件 EVT_DEBATE_EXPOSED。"
      - "在宵禁期成功核验真品落胎泉后触发 EVT_BREAK_CURSE，ST_WATER_CURSE_STAGE 立即归 0 并锁定不可再升。"
    edge_cases:
      - "若 ST_WATER_CURSE_STAGE 已为 3 时再次执行隐瞒动作，数值保持 3 不溢出，且立即转为触发 EVT_DEBATE_EXPOSED。"
      - "若同一结算帧内同时满足 EVT_BREAK_CURSE 与 EVT_DEBATE_EXPOSED，强制优先结算 EVT_BREAK_CURSE。"
    exposed_state_ids:
      - id: "ST_WATER_CURSE_STAGE"
        value_type: "enum_int(0..3)"
        meaning: "子母河因果印记阶段：0未染 / 1微澜 / 2显相 / 3满溢"
    emitted_event_ids:
      - id: "EVT_DRINK_RIVER_WATER"
        meaning: "角色误饮子母河水并初染印记"
      - id: "EVT_BREAK_CURSE"
        meaning: "成功以真品落胎泉破除因果印记"
    acceptance_criteria:
      - "给定初始态 0，连续输入误饮 + 2次隐瞒后 ST_WATER_CURSE_STAGE 精确等于 3。"
      - "同帧并发 EVT_BREAK_CURSE 与 EVT_DEBATE_EXPOSED 时，最终状态为 0 且不进入暴露结局。"

  - req_id: "SYS-002"
    tree_path: "SYSTEMS/SYS-002"
    title: "七日朝议质询与疑心值结算系统"
    linked_gdd_ref: "GDD-M02"
    priority: "P0"
    inputs:
      - "玩家向案台呈递证物卡并盖下朱砂印确认"
      - "昼夜阶段切换指令（第 1 日至第 7 日）"
    business_rules:
      - "朝堂疑心值 ST_COURT_SUSPICION 范围锁定为整数 0..100，初始值为 20。"
      - "呈递与当前质询矛盾的伪证导致 ST_COURT_SUSPICION 增加 25；呈递指向太师破绽的实证减少 15。"
      - "当 ST_COURT_SUSPICION >= 100 时立即中止当日质询并触发 EVT_DEBATE_EXPOSED。"
    edge_cases:
      - "ST_COURT_SUSPICION 增减后必须截断在 [0, 100] 闭区间内。"
      - "当第 7 日昼间质询结束且 ST_COURT_SUSPICION < 100 时，即使处于宵禁过渡点也不再触发常规递增，直接进入终局分支判定。"
    exposed_state_ids:
      - id: "ST_COURT_SUSPICION"
        value_type: "int(0..100)"
        meaning: "朝堂对取经人一行身份的实时疑心值"
    emitted_event_ids:
      - id: "EVT_DEBATE_EXPOSED"
        meaning: "身份暴露或疑心值满溢触发的朝堂危机事件"
    acceptance_criteria:
      - "呈递实证使疑心值低于 0 时精确钳位为 0；达到或超过 100 时当帧触发 EVT_DEBATE_EXPOSED。"
      - "存读档还原任意一日质询现场时，ST_COURT_SUSPICION 与已呈递证物集合 100% 一致。"
```

---

### 4. `requirements/narrative_requirements.yaml`（叙事纯需求表）

```yaml
schema_version: "narrative_requirements/v1.1"
discipline: "narrative"
milestone_scope: "vertical_slice_act1"
understanding_echo:
  summary: "以克制古雅的宫廷礼法话术承载双向试探与清醒抉择，突出国主借势破局的冷静张力。"
  anti_examples:
    - "绝不写成低俗猎奇的婚恋闹剧。"
    - "绝不写成冗长说教式的无交互纯电子小说。"
explicit_na_refs: []

global_constraints:
  core_theme: "体面礼法之下的双向试探与清醒抉择"
  world_laws:
    - "女儿国国主并非恋爱脑反派，而是借外来变数撬动太师旧礼法的冷静掌局者。"
    - "严禁将女儿国降格为低俗猎奇笑料，全文本保持克制古雅的试探张力。"
  tone_samples:
    good_examples:
      - speaker: "女儿国主"
        line: "子母河水映的从来不是身孕，是过境之人不敢落笔的真话。"
    forbidden_examples:
      - line: "哈哈你个大男人怎么怀孕啦，快留下来当我的压寨夫君吧！"
        reason: "违背克制博弈基调，滑向脸谱化低俗套路。"

stage_deliverables:
  - req_id: "NAR-001"
    tree_path: "WORLD/A_river_ferry/A1_drink_water"
    title: "初饮子母河水与三阶段异变心理独白组"
    linked_gdd_ref: "GDD-M01"
    priority: "P0"
    linked_state_ids: ["ST_WATER_CURSE_STAGE"]
    trigger_event_ids: ["EVT_DRINK_RIVER_WATER", "EVT_BREAK_CURSE"]
    canon_refs: ["CANON-LOC-01", "CANON-RULE-01"]
    deliverable_spec: "提供印记阶段 1/2/3 各 2 组短独白（每组 ≤60 字）及破咒后的 1 段收束对话（≤120 字），严格体现从侥幸隐瞒到直面抉择的语气递进。"
    acceptance_criteria:
      - "所有台词均符合全局克制古雅语调，无任何禁用样张风格词汇。"
      - "覆盖 ST_WATER_CURSE_STAGE=1/2/3 与两个触发事件，无空文本分支。"

  - req_id: "NAR-002"
    tree_path: "WORLD/B_royal_court/B1_morning_debate"
    title: "太师质询与疑心满溢暴露对峙剧本"
    linked_gdd_ref: "GDD-M02"
    priority: "P0"
    linked_state_ids: ["ST_COURT_SUSPICION"]
    trigger_event_ids: ["EVT_DEBATE_EXPOSED"]
    canon_refs: ["CANON-CHAR-01", "CANON-CHAR-02"]
    deliverable_spec: "编写 3 组高低疑心区间（0-39 / 40-79 / 80-99）的太师压迫追问分支，以及 EVT_DEBATE_EXPOSED 触发时的朝堂摊牌对峙演出文本。"
    acceptance_criteria:
      - "三个疑心区间语气梯度清晰可辨，且国主台词始终保持借势试探立场，不与 CANON-CHAR-01 吃书。"
```

---

### 5. `requirements/art_requirements.yaml`（美术纯需求表）

```yaml
schema_version: "art_requirements/v1.1"
discipline: "art"
milestone_scope: "vertical_slice_act1"
understanding_echo:
  summary: "熟宣底色+焦墨留白+朱砂危机聚焦的2D工笔舞台视觉，靠神态差分与水墨纹样传达无声压迫。"
  anti_examples:
    - "绝不做写实3D渲染或高饱和荧光二次元光效。"
    - "绝不做鬼屋流血跳吓式的恐怖片视觉。"
explicit_na_refs: []

global_constraints:
  visual_direction: "中小体量水墨工笔 2D 风格化（宣纸纹理底 + 简洁剪影分层 + 朱砂功能色聚焦）"
  camera_framing: "固定 2D 平面舞台剧透视，前景案台与中景立绘强图底分离"
  color_palette:
    primary_bg: "#F3EDE0"        # 熟宣纸米底
    ink_structural: "#1F2428"    # 焦墨结构主色
    accent_signal: "#B83227"     # 朱砂功能强调色（仅用于印章/危机高亮）
    curse_tint: "#2E6F7E"        # 河水石青异变色
  visual_anti_rules:
    - "严禁写实 PBR 质感、3D 写实骨骼模型与高饱和霓虹光污染。"
    - "严禁复杂逐帧长片过场动画，立绘情绪切换采用差分表情+轻度呼吸位移动效。"
  style_reference_images:        # 可选，0~2 张
    - path: "references/style_ref_01.png"
      usage: "仅锚定宣纸笔触、朱砂留白比例与朝堂人物比例基准"

stage_deliverables:
  - req_id: "ART-001"
    tree_path: "SYSTEMS/SYS-001"
    title: "因果印记四档水墨纹样与案台状态反馈套件"
    linked_gdd_ref: "GDD-M01"
    priority: "P0"
    linked_state_ids: ["ST_WATER_CURSE_STAGE"]
    reuse_group: "UI_INK_SEAL_SET"
    deliverable_spec: "提供对应 ST_WATER_CURSE_STAGE 0/1/2/3 四档的水墨水纹叠加徽记与边缘染墨滤镜规格（2D 矢量/精灵图，共享同一底框复用）。"
    acceptance_criteria:
      - "四档视觉差异在 1280x720 缩略尺度下 1 秒内肉眼可区分，且仅用规定石青/焦墨色板。"
      - "不遮挡核心对话字幕区与呈证交互热区。"

  - req_id: "ART-002"
    tree_path: "WORLD/B_royal_court/B1_morning_debate"
    title: "太师与国主朝议立绘差分及疑心高危视觉警示"
    linked_gdd_ref: "GDD-M02"
    priority: "P0"
    linked_state_ids: ["ST_COURT_SUSPICION"]
    reuse_group: "CHAR_PORTRAIT_DIFF"
    deliverable_spec: "两位核心角色各 1 套基础工笔立绘 + 3 档神态差分（平静/试探/峻厉），配合高疑心区间（>=80）案台朱砂裂纹警示框。"
    acceptance_criteria:
      - "人物轮廓与背景明度差清晰，满足图底分离铁律；严格复用基础体块，不重画全身动态。"
```

---

### 6. `requirements/audio_requirements.yaml`（音频纯需求表）

```yaml
schema_version: "audio_requirements/v1.1"
discipline: "audio"
milestone_scope: "vertical_slice_act1"
understanding_echo:
  summary: "极简古琴、箫与石磬水滴构成的克制留白声景，用低频水滴与骤停弦音烘托礼法窒息感。"
  anti_examples:
    - "绝不使用热血交响铜管或高速BOSS战密集鼓点。"
    - "绝不使用现代电子合成器或恐怖片刺耳尖叫。"
explicit_na_refs: []

global_constraints:
  sonic_identity: "极简古琴、箫与木鱼/石磬点缀；克制留白，绝不堆砌交响史诗铜管"
  loudness_hierarchy:
    - "第一层（最清晰）：呈词盖印、暴露警报等交互反馈 SFX"
    - "第二层：环境底噪（微弱流水/殿堂风声）与极简古琴 BGM"
  audio_anti_rules:
    - "严禁全程密集打击乐或现代电子合成器音色。"
    - "严禁任何无触发事件的纯装饰长音频资产。"

stage_deliverables:
  - req_id: "AUD-001"
    tree_path: "SYSTEMS/SYS-001"
    title: "子母河异变与破咒音效套件"
    linked_gdd_ref: "GDD-M01"
    priority: "P0"
    linked_state_ids: ["ST_WATER_CURSE_STAGE"]
    trigger_event_ids: ["EVT_DRINK_RIVER_WATER", "EVT_BREAK_CURSE"]
    deliverable_spec: "提供初饮水声异响 SFX（1.2s）、印记每升一档的低频水滴余韵 SFX（复用变调 3 档）以及破咒清越石磬 SFX（2.0s）。"
    acceptance_criteria:
      - "EVT_DRINK_RIVER_WATER 与 EVT_BREAK_CURSE 触发反馈情绪反差鲜明，峰值不削波。"

  - req_id: "AUD-002"
    tree_path: "WORLD/B_royal_court/B1_morning_debate"
    title: "朝堂疑心梯度配乐层与暴露惊堂音效"
    linked_gdd_ref: "GDD-M02"
    priority: "P0"
    linked_state_ids: ["ST_COURT_SUSPICION"]
    trigger_event_ids: ["EVT_DEBATE_EXPOSED"]
    deliverable_spec: "提供 2 轨无缝循环古琴/箫 BGM（常态平静轨 + 疑心>=60 叠入紧绷弦音轨）及 EVT_DEBATE_EXPOSED 骤停重击 SFX。"
    acceptance_criteria:
      - "常态轨与紧绷轨同 BPM 可平滑淡入淡出，EVT_DEBATE_EXPOSED 触发时能在 150ms 内压低 BGM 突出惊堂警示。"
```

---

### 7. `memory/canon_registry.yaml` & `memory/adr/ADR-001.yaml` & `memory/ideas_backlog.md`

**`memory/canon_registry.yaml`**（长期世界真相账本）：

```yaml
schema_version: "canon_registry/v1"
project_id: "xiyou-nverguo"
entries:
  - canon_id: "CANON-CHAR-01"
    category: "character"
    name: "女儿国主"
    immutable_facts:
      - "深知外来取经人身份异常，但选择以朝堂礼法博弈试探而非直接羁押。"
  - canon_id: "CANON-CHAR-02"
    category: "character"
    name: "太师"
    immutable_facts:
      - "旧礼法秩序维护者，对一切外来变量持高度审慎与排斥态度。"
  - canon_id: "CANON-LOC-01"
    category: "location"
    name: "子母河"
    immutable_facts:
      - "河水在本作中兼具生理异变与心证显相双重象征，唯有真品落胎泉可逆转。"
  - canon_id: "CANON-RULE-01"
    category: "world_rule"
    name: "因果印记不可隐藏原则"
    immutable_facts:
      - "因果印记阶段升至 3 阶满溢时必然触发朝堂显相，不存在永久白嫖隐瞒解法。"
```

**`memory/adr/ADR-001.yaml`**（不可变裁决日志，只增不改）：

```yaml
schema_version: "adr/v1"
adr_id: "ADR-001"
created_at: "2026-11-27T13:30:00Z"
status: "ACCEPTED"
trigger: "stage2_round2_deadlock"
context: "压测第2轮对「第7日满溢与破咒同帧结算」的优先级存在争议：偏严苛派主张直接暴露，偏叙事爽感派主张破咒优先。"
decision: "同帧并发 EVT_BREAK_CURSE 与 EVT_DEBATE_EXPOSED 时，强制优先结算 EVT_BREAK_CURSE。"
rationale: "依据 lead_pillars[0]=narrative 核心抉择主权，玩家冒宵禁高风险取得真品落胎泉的孤注一掷动作应获确定性正向回报。"
impacted_refs: ["GDD-M01", "SYS-001"]
```

**`memory/ideas_backlog.md`**（只读旁路灵感与高光提案，编排器**绝不**自动将其转为可执行任务）：

```markdown
# 旁路灵感与高光提案（Ideas Backlog & Golden Sparks · 严禁自动排期）
> 普通灵感仅作未来 DLC 备忘；置顶的 [GOLDEN_SPARK] 为填肉过程中冒出的超体量高光提案（附体量代价），仅在人类导演破格采纳并正式并入总策划案后才生效。

## [GOLDEN_SPARK] 置顶高光提案（需人类导演显式破格拍板）
- [Stage 2 / SYS-002] 偏殿药房增加「知情老宫女的秘密交易」分支（代价：+1 次要 NPC 立绘差分与 1 条分支结局）。

## 普通旁路备忘
- [Stage 2 / Round 1] 未来 DLC 可考虑追加一个市井说书人旁观视角彩蛋，串联前朝旧闻。
```

---

### 8. 跨表依赖闭合示意（编排器可直接自动构建工种 DAG）

| 模块 (`gdd_index`) | 系统权威源 (`system`) | 声明的 `state_id` / `event_id` | 叙事消费 (`narrative`) | 美术消费 (`art`) | 音频消费 (`audio`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`GDD-M01`** | `SYS-001` | `ST_WATER_CURSE_STAGE`<br>`EVT_DRINK_RIVER_WATER`<br>`EVT_BREAK_CURSE` | `NAR-001` | `ART-001` | `AUD-001` |
| **`GDD-M02`** | `SYS-002` | `ST_COURT_SUSPICION`<br>`EVT_DEBATE_EXPOSED` | `NAR-002` | `ART-002` | `AUD-002` |

> **编排器收益**：无需用 LLM 盲猜模块间怎么连线——直接解析四张 YAML 中的 `linked_gdd_ref`、`exposed_state_ids`/`emitted_event_ids` 与 `linked_state_ids`/`trigger_event_ids`，即可**100% 确定性地推导出跨工种任务依赖边与集成联调验收节点**！

---

## 三、第一层向编排器提供的 7 条确定性契约保证

只要 `manifest.json` 校验通过且 `approval_signature.status == "APPROVED"`，第二层编排器即可 **100% 信任**以下 7 条由代码硬卡口与语义复述保证的前提（无需在编排层重复防御性兜底）：

1. **Schema 100% 严格合规 + 零偷懒占位词**：全部 JSON/YAML 交付文件已通过严格 Schema 校验（`additionalProperties: false`），且已通过禁用词扫描（零 `TBD / 同上 / 略 / 待定`）；
2. **零 3D 写实重资产越界**：`scope_tier` 严格限定在中小体量风格化 2D / 轻 2.5D 档位，`art_requirements.yaml` 与 `MASTER_GDD.md` 不包含任何 3A 写实管线或开放世界重资产需求；
3. **零 How 实现污染**：`system_requirements.yaml` 已通过 Stage 3 实现词黑名单扫描，不包含任何引擎名、类名、节点树或代码实现指令，编排器可自由路由给任意下游技术栈/引擎执行器；
4. **`linked_gdd_ref` + `explicit_na_refs` 双向全覆盖闭合**：四张纯需求表每一条需求均有效溯源至 `gdd_index.yaml`，且各表均满足 `covered_gdd_ids ∪ explicit_na_ids == ALL_GDD_MODULE_IDS`（零孤儿需求、零静默漏项、零 Stage 3 偷加新玩法）；
5. **跨工种 `state_id / event_id` 全量对账闭合 + 树形血缘 `tree_path`**：叙事/美术/音频表引用的每一个 `ST_*` / `EVT_*` 均已在 `system_requirements.yaml` 中权威声明，且 `system_interaction_matrix` 已锁死跨系统并发仲裁优先级；
6. **全局风格锁 + 四工种 `understanding_echo` 语义对齐**：四张表均在统一冻结的 `Root` 全局风格宪法下经双主干树拆解，且四工种大白话反向复述已与 `MASTER_GDD` 体验意图交叉核验一致；
7. **人类导演签字冻结 + 确定性哈希锁**：包级 `canonical_sha256` 与逐文件 `sha256` 完整可验证，天然支持编排器幂等消费、缓存命中与断点续跑。

---

## 四、升版与回流协议（Delta RFC Handoff）

当第二层编排器在**下游可玩切片试玩反馈、首帧视觉风格验收、工期裁剪或新章节立项**中发现需要调整需求时，**严禁在下游私改契约文件**，而是按以下闭环协议回流第一层：

### 1. 编排器提交 `change_request.yaml`

```yaml
schema_version: "change_request/v1"
request_id: "CR-20261127-01"
project_id: "xiyou-nverguo"
base_spec_version: "v1.0.0"
trigger_source: "playtest_feedback"     # 枚举: playtest_feedback | visual_first_frame | scope_cut | new_chapter
impacted_req_ids: ["SYS-002", "AUD-002"]
problem_statement: "试玩显示朝堂疑心值达到 60 时压迫感提示偏晚，玩家误以为仍处于安全区。"
requested_delta: "将高疑心警示与紧绷音乐轨切入阈值从 60 下调至 50，并同步微调太师中段台词节奏。"
```

### 2. 第一层回传升版交接包与 `diff_summary.yaml`

第一层运行定向 Delta RFC，签发新版本交接包（如 `handoff/xiyou-nverguo/v1.1.0/`，`parent_version: "v1.0.0"`），并自动产出机器可读的 **`diff_summary.yaml`**：

```yaml
schema_version: "diff_summary/v1"
project_id: "xiyou-nverguo"
from_version: "v1.0.0"
to_version: "v1.1.0"
change_request_id: "CR-20261127-01"
delta_tier: "TIER_A_LOCAL_TUNING"       # TIER_A_LOCAL_TUNING | TIER_B_CHAPTER_EXTEND | TIER_C_CORE_PIVOT
global_constraints_changed: false
changes:
  added_ids: []
  modified_ids:
    - { req_id: "SYS-002", discipline: "system",    reason: "高疑心警示阈值由60调整为50" }
    - { req_id: "AUD-002", discipline: "audio",     reason: "紧绷弦音轨淡入阈值同步下调至50" }
    - { req_id: "NAR-002", discipline: "narrative", reason: "中段追问疑心区间微调为40-49/50-79" }
  deprecated_ids: []
  unchanged_ids: ["SYS-001", "NAR-001", "ART-001", "ART-002", "AUD-001"]
```

### 3. 编排器增量热重排规则（Dirty Propagation）
* 编排器读取 `diff_summary.yaml`：
  * 对 `modified_ids` 与 `added_ids`（及其直接依赖的联调验收节点）执行**增量传递闭包标脏重跑**；
  * 对 `unchanged_ids`（本例中 `SYS-001 / NAR-001 / ART-001 / ART-002 / AUD-001`）对应且已 `SUCCEEDED` 的下游产出物 **100% 原样保留复用**，彻底避免牵一发动全身的浪费重排！
