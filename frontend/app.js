const MODE_LABELS = {
  DISPERSED: "散开并行",
  JOINT: "联合对齐",
  CONCENTRATED: "集中收口",
};

const STATUS_LABELS = {
  PENDING: "未就绪",
  READY: "就绪待调度",
  RUNNING: "执行中",
  WAITING_DECISION: "待主策拍案",
  WAITING_VERIFY: "待独立QA验收",
  SUCCEEDED: "已完成",
  FAILED: "失败/打回",
  BLOCKED: "阻塞",
  SKIPPED: "已跳过",
};

const ROLE_ORDER = {
  ROLE_PLANNER: 1,
  ROLE_ART_2D: 2,
  ROLE_DEV_2D: 3,
  ROLE_QA_INTEG: 4,
};

let appState = null;
let selectedTaskId = null;
let hoveredTaskId = null;
let hoveredEdgeKey = null;
let edgeMode = "all"; // "all" | "focus" | "critical"
let simTimer = null;
let verdictTarget = null; // { kind: "task", taskId } | { kind: "signal", signalId }

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4800);
}

async function apiPost(url, payload = {}) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) {
    const code = data.error_code ? `[${data.error_code}] ` : "";
    throw new Error(`${code}${data.message || "请求失败"}`);
  }
  return data;
}

async function fetchState() {
  const resp = await fetch("/api/state");
  const data = await resp.json();
  applyState(data);
}

function applyState(state) {
  appState = state;
  if (selectedTaskId && !state.tasks.some((t) => t.task_id === selectedTaskId)) {
    selectedTaskId = null;
  }
  if (!selectedTaskId && state.tasks.length > 0) {
    const waiting = state.tasks.find((t) => t.status === "WAITING_DECISION");
    selectedTaskId = waiting ? waiting.task_id : state.tasks[0].task_id;
  }
  syncAutoLoop();
  renderAll();
}

function syncAutoLoop() {
  const running = Boolean(appState?.orchestrator?.is_running);
  if (running && !simTimer) {
    simTimer = setInterval(async () => {
      try {
        const next = await apiPost("/api/orchestrator/tick", { hours_per_tick: 2.0 });
        applyState(next);
      } catch (err) {
        showToast(err.message, "error");
        clearInterval(simTimer);
        simTimer = null;
      }
    }, 950);
  } else if (!running && simTimer) {
    clearInterval(simTimer);
    simTimer = null;
  }
}

function renderAll() {
  if (!appState) return;
  renderTopbar();
  renderMetrics();
  renderSwimlaneGraph();
  renderSelectedTask();
  renderPlannerTab();
  renderListenerTab();
  renderGitTab();
  const internalsModal = document.getElementById("internals-modal");
  if (internalsModal && !internalsModal.classList.contains("hidden")) {
    renderInternalsModal();
  }
}

function renderTopbar() {
  const { spec, presets, orchestrator } = appState;
  document.getElementById("spec-title-label").textContent = spec ? spec.title : "-";
  document.getElementById("spec-version-pill").textContent = spec ? spec.spec_version : "v1.0";
  document.getElementById("spec-dim-pill").textContent = spec ? `${spec.dimension_mode} 管线` : "2D";

  const presetSel = document.getElementById("preset-select");
  if (presetSel.options.length === 0) {
    presetSel.innerHTML = presets
      .map((p) => `<option value="${esc(p.key)}">${esc(p.title)}</option>`)
      .join("");
  }
  if (spec) {
    const match = presets.find((p) => spec.title.includes(p.title.slice(0, 6)));
    if (match) presetSel.value = match.key;
  }

  const runBtn = document.getElementById("btn-toggle-run");
  if (orchestrator.is_running) {
    runBtn.textContent = "⏸ 暂停编排";
    runBtn.className = "btn btn-warn";
  } else {
    runBtn.textContent = "▶ 启动编排";
    runBtn.className = "btn btn-primary";
  }

  const rbSel = document.getElementById("rollback-select");
  const snaps = orchestrator.available_snapshots || [];
  rbSel.innerHTML = snaps
    .map((s) => `<option value="${esc(s.stage_id)}">${esc(s.label)} (T+${s.sim_clock_hours}h)</option>`)
    .join("");
}

function renderMetrics() {
  const { metrics, orchestrator, tasks } = appState;
  document.getElementById("cp-progress-text").textContent = `${metrics.cp_progress_pct}%`;
  document.getElementById("cp-progress-bar").style.width = `${metrics.cp_progress_pct}%`;
  document.getElementById("cp-hours-detail").textContent =
    `关键路径已完成 ${metrics.cp_completed_hours} / ${metrics.cp_total_hours} h (${metrics.critical_path_task_ids.length} 节点)`;

  document.getElementById("total-progress-text").textContent = `${metrics.total_progress_pct}%`;
  document.getElementById("total-progress-bar").style.width = `${metrics.total_progress_pct}%`;
  document.getElementById("total-hours-detail").textContent =
    `全图累计已完成 ${metrics.total_completed_hours} / ${metrics.total_hours} h`;

  document.getElementById("project-duration-text").textContent = `${metrics.project_total_hours} h`;
  document.getElementById("baseline-duration-text").textContent = `无延期基线：${metrics.baseline_total_hours} h`;
  document.getElementById("sim-clock-text").textContent =
    `T+${orchestrator.sim_clock_hours.toFixed(1)}h (Tick ${orchestrator.tick_count})`;

  const delayBanner = document.getElementById("delay-alert-banner");
  if (metrics.has_delay_alert) {
    delayBanner.classList.remove("hidden");
    delayBanner.textContent = `⚠️ 关键路径延期告警：总工期已实时顺延 +${metrics.delay_delta_hours}h（受影响 ${metrics.critical_delayed_tasks.join(", ")}）`;
  } else {
    delayBanner.classList.add("hidden");
  }

  const pendingDecisions = tasks.filter((t) => t.status === "WAITING_DECISION");
  const pendingSignals = appState.signals.filter((s) => s.requires_planner_verdict && s.status === "PENDING");
  const totalPending = pendingDecisions.length + pendingSignals.length;
  const vCard = document.getElementById("verdict-queue-card");
  const vBtn = document.getElementById("btn-quick-verdict");
  document.getElementById("pending-verdicts-count").textContent = `${totalPending} 项待拍案`;
  if (totalPending > 0) {
    vCard.classList.add("has-pending");
    vBtn.classList.remove("hidden");
    const firstMsg = pendingDecisions[0]
      ? `任务 [${pendingDecisions[0].task_id}] ${pendingDecisions[0].title}`
      : `信号 [${pendingSignals[0].signal_id}] 待变更裁决`;
    document.getElementById("pending-verdicts-preview").textContent = firstMsg;
  } else {
    vCard.classList.remove("has-pending");
    vBtn.classList.add("hidden");
    document.getElementById("pending-verdicts-preview").textContent = "当前无阻塞拍案项";
  }
}

function renderSwimlaneGraph() {
  const { stages, bots, tasks, metrics } = appState;
  const grid = document.getElementById("swimlane-grid");
  const stageStatsMap = Object.fromEntries(metrics.stage_stats.map((s) => [s.stage_id, s]));
  const botStatsMap = Object.fromEntries(metrics.bot_stats.map((b) => [b.bot_id, b]));

  const sortedBots = [...bots].sort(
    (a, b) => (ROLE_ORDER[a.role_code] || 9) - (ROLE_ORDER[b.role_code] || 9) || a.bot_id.localeCompare(b.bot_id)
  );

  let html = `<div class="grid-corner"><strong>纵轴：4 类角色泳道</strong><span>横轴：5 大游戏研发阶段</span></div>`;

  for (const st of stages) {
    const stat = stageStatsMap[st.stage_id] || { completed_tasks: 0, total_tasks: 0, progress_pct: 0 };
    html += `
      <div class="stage-header-cell">
        <div class="stage-title">${esc(st.name)}</div>
        <div class="stage-meta">
          <span class="mode-badge mode-${esc(st.dominant_mode)}">${esc(MODE_LABELS[st.dominant_mode] || st.dominant_mode)}</span>
          <span>${stat.completed_tasks}/${stat.total_tasks} (${stat.progress_pct}%)</span>
        </div>
        <div class="stage-exit" title="${esc(st.exit_criteria)}">准出：${esc(st.exit_criteria)}</div>
      </div>
    `;
  }

  for (const bot of sortedBots) {
    const bStat = botStatsMap[bot.bot_id] || { completed_count: 0, assigned_count: 0 };
    const tierBadge = bot.model_tier === "flagship" ? "Tier-1 旗舰" : "Tier-2 标准";
    const memBadge = bot.has_long_term_memory ? "🧠 教训记忆" : "无长期记忆";
    html += `
      <div class="lane-header-cell lane-role-${esc(bot.role_code)}">
        <div class="lane-bot-name">${esc(bot.display_name)}</div>
        <div class="lane-bot-meta">
          <span>${esc(bot.bot_id)}</span>
          <span>· ${esc(tierBadge)}</span>
          <span>· ${esc(memBadge)}</span>
        </div>
        <div class="lane-bot-meta">
          <span>负荷 ${bot.current_load_hours.toFixed(1)}h</span>
          <span>· 完成 ${bStat.completed_count}/${bStat.assigned_count}</span>
        </div>
      </div>
    `;

    for (const st of stages) {
      const cellTasks = tasks.filter((t) => t.stage_id === st.stage_id && t.assigned_bot_id === bot.bot_id);
      const cardsHtml = cellTasks
        .map((t) => {
          const effDur = t.duration_hours + t.delay_hours;
          const pct = Math.min(100, Math.round(((t.progress_hours || 0) / Math.max(0.1, effDur)) * 100));
          const selCls = t.task_id === selectedTaskId ? "selected" : "";
          const cpCls = t.is_critical ? "is-critical" : "";
          const modeCls = `mode-${t.collaboration_mode}`;
          const stCls = `status-${t.status}`;
          return `
            <div class="task-node ${selCls} ${cpCls} ${modeCls} ${stCls}" data-task-id="${esc(t.task_id)}">
              <div class="node-top">
                <span class="node-id">${esc(t.task_id)}</span>
                <span>${esc(STATUS_LABELS[t.status] || t.status)} · ${effDur.toFixed(1)}h</span>
              </div>
              <div class="node-title">${esc(t.title)}</div>
              <div class="node-badges">
                ${t.is_critical ? `<span class="badge badge-cp">关键路径</span>` : ""}
                ${t.collaboration_mode === "JOINT" ? `<span class="badge badge-joint">⇄ 联合合流</span>` : ""}
                ${t.collaboration_mode === "CONCENTRATED" ? `<span class="badge badge-gate">◆ 收口门</span>` : ""}
                ${t.delay_hours > 0 ? `<span class="badge badge-delay">+${t.delay_hours}h延期</span>` : ""}
                ${t.retry_count > 0 ? `<span class="badge badge-retry">打回×${t.retry_count}</span>` : ""}
                ${t.dirty_flag ? `<span class="badge badge-dirty">DIRTY 热重排</span>` : ""}
              </div>
              <div class="node-status-bar"><div class="node-status-fill" style="width:${t.status === "SUCCEEDED" ? 100 : pct}%"></div></div>
            </div>
          `;
        })
        .join("");

      html += `<div class="lane-cell">${cardsHtml}</div>`;
    }
  }

  grid.innerHTML = html;

  grid.querySelectorAll(".task-node").forEach((el) => {
    const tid = el.getAttribute("data-task-id");
    el.addEventListener("click", () => {
      selectedTaskId = tid;
      document.querySelector('[data-tab="tab-task"]').click();
      renderSwimlaneGraph();
      renderSelectedTask();
    });
    el.addEventListener("mouseenter", () => {
      hoveredTaskId = tid;
      requestAnimationFrame(drawDagEdges);
    });
    el.addEventListener("mouseleave", () => {
      if (hoveredTaskId === tid) {
        hoveredTaskId = null;
        requestAnimationFrame(drawDagEdges);
      }
    });
  });

  requestAnimationFrame(drawDagEdges);
}

function buildRoundedOrthoPath(points, radius = 9) {
  if (points.length < 2) return "";
  // 合并共线或极近的连续点
  const pts = [points[0]];
  for (let i = 1; i < points.length; i++) {
    const prev = pts[pts.length - 1];
    const curr = points[i];
    if (Math.hypot(curr.x - prev.x, curr.y - prev.y) > 1.5) {
      pts.push(curr);
    }
  }
  if (pts.length < 2) return "";
  if (pts.length === 2) {
    return `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)} L ${pts[1].x.toFixed(1)} ${pts[1].y.toFixed(1)}`;
  }

  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p0 = pts[i - 1];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const v1x = p1.x - p0.x;
    const v1y = p1.y - p0.y;
    const v2x = p2.x - p1.x;
    const v2y = p2.y - p1.y;
    const len1 = Math.hypot(v1x, v1y);
    const len2 = Math.hypot(v2x, v2y);
    const r = Math.min(radius, len1 * 0.45, len2 * 0.45);
    if (r < 1.5) {
      d += ` L ${p1.x.toFixed(1)} ${p1.y.toFixed(1)}`;
      continue;
    }
    const ax = p1.x - (v1x / len1) * r;
    const ay = p1.y - (v1y / len1) * r;
    const bx = p1.x + (v2x / len2) * r;
    const by = p1.y + (v2y / len2) * r;
    d += ` L ${ax.toFixed(1)} ${ay.toFixed(1)} Q ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} ${bx.toFixed(1)} ${by.toFixed(1)}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
  return d;
}

function drawDagEdges() {
  const canvas = document.getElementById("graph-canvas");
  const svg = document.getElementById("dag-edges-svg");
  if (!canvas || !svg || !appState) return;

  const rect = canvas.getBoundingClientRect();
  svg.setAttribute("width", String(canvas.scrollWidth));
  svg.setAttribute("height", String(canvas.scrollHeight));
  svg.setAttribute("viewBox", `0 0 ${canvas.scrollWidth} ${canvas.scrollHeight}`);

  const stageIdxMap = Object.fromEntries(appState.stages.map((s) => [s.stage_id, s.order]));
  const nodePositions = {};
  canvas.querySelectorAll(".task-node").forEach((el) => {
    const tid = el.getAttribute("data-task-id");
    const r = el.getBoundingClientRect();
    nodePositions[tid] = {
      left: r.left - rect.left + canvas.scrollLeft,
      right: r.right - rect.left + canvas.scrollLeft,
      top: r.top - rect.top + canvas.scrollTop,
      bottom: r.bottom - rect.top + canvas.scrollTop,
      width: r.width,
      height: r.height,
      midX: r.left - rect.left + canvas.scrollLeft + r.width / 2,
      midY: r.top - rect.top + canvas.scrollTop + r.height / 2,
    };
  });

  const taskMap = Object.fromEntries(appState.tasks.map((t) => [t.task_id, t]));
  const edges = [];
  for (const t of appState.tasks) {
    const toPos = nodePositions[t.task_id];
    if (!toPos) continue;
    for (const depId of t.depends_on) {
      const fromPos = nodePositions[depId];
      const depTask = taskMap[depId];
      if (!fromPos || !depTask) continue;
      const isCriticalEdge = t.is_critical && depTask.is_critical && Math.abs(t.es - depTask.ef) < 1e-3;
      const isJointEdge = t.collaboration_mode === "JOINT" && !isCriticalEdge;
      edges.push({
        key: `${depId}->${t.task_id}`,
        fromId: depId,
        toId: t.task_id,
        fromStage: stageIdxMap[depTask.stage_id] || 1,
        toStage: stageIdxMap[t.stage_id] || 1,
        fromPos,
        toPos,
        isCriticalEdge,
        isJointEdge,
      });
    }
  }

  // 1) 端口分流：按目标/来源垂直位置分配均匀出/入端口，避免终点重合
  const outGroups = {};
  const inGroups = {};
  for (const e of edges) {
    (outGroups[e.fromId] ||= []).push(e);
    (inGroups[e.toId] ||= []).push(e);
  }
  for (const list of Object.values(outGroups)) {
    list.sort((a, b) => a.toPos.midY - b.toPos.midY || a.toId.localeCompare(b.toId));
    list.forEach((e, idx) => {
      const span = Math.min(36, e.fromPos.height * 0.56);
      const startY = e.fromPos.midY - span / 2;
      e.y1 = list.length === 1 ? e.fromPos.midY : startY + (span * idx) / (list.length - 1);
    });
  }
  for (const list of Object.values(inGroups)) {
    list.sort((a, b) => a.fromPos.midY - b.fromPos.midY || a.fromId.localeCompare(b.fromId));
    list.forEach((e, idx) => {
      const span = Math.min(36, e.toPos.height * 0.56);
      const startY = e.toPos.midY - span / 2;
      e.y2 = list.length === 1 ? e.toPos.midY : startY + (span * idx) / (list.length - 1);
    });
  }

  // 2) 为每个相邻阶段走廊 (stage k -> k+1) 计算零交叉的正交总线轨道 busX
  const corridorGroups = {};
  for (const e of edges) {
    if (e.toStage > e.fromStage) {
      const cKey = `${e.fromStage}->${e.fromStage + 1}`;
      (corridorGroups[cKey] ||= []).push(e);
    }
  }
  for (const list of Object.values(corridorGroups)) {
    const corrLeft = Math.max(...list.map((e) => e.fromPos.right)) + 12;
    const corrRight = Math.min(...list.map((e) => e.toPos.left)) - 14;
    const span = Math.max(24, corrRight - corrLeft);
    // 向下走线按 y1 升序从右往左分配轨道，向上走线按 y1 降序分配，最大化避免垂直与水平线段相交
    const downEdges = list.filter((e) => e.y1 <= e.y2).sort((a, b) => a.y1 - b.y1 || b.y2 - a.y2);
    const upEdges = list.filter((e) => e.y1 > e.y2).sort((a, b) => b.y1 - a.y1 || a.y2 - b.y2);
    const orderedCorr = [...downEdges.reverse(), ...upEdges];
    orderedCorr.forEach((e, i) => {
      const ratio = orderedCorr.length === 1 ? 0.5 : i / (orderedCorr.length - 1);
      e.busX = corrLeft + span * (0.12 + 0.76 * ratio);
    });
  }

  const focusId = hoveredTaskId || selectedTaskId;
  let paths = `
    <defs>
      <marker id="arrow-normal" markerWidth="6" markerHeight="6" refX="5.5" refY="3" orient="auto">
        <polygon points="0 0, 6 3, 0 6" fill="#64748b" />
      </marker>
      <marker id="arrow-gold" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
        <polygon points="0 0, 7 3.5, 0 7" fill="#f59e0b" />
      </marker>
      <marker id="arrow-cyan" markerWidth="6" markerHeight="6" refX="5.5" refY="3" orient="auto">
        <polygon points="0 0, 6 3, 0 6" fill="#06b6d4" />
      </marker>
      <marker id="arrow-focus" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
        <polygon points="0 0, 7 3.5, 0 7" fill="#38bdf8" />
      </marker>
    </defs>
  `;

  const ordered = [...edges].sort((a, b) => {
    const score = (e) => (e.key === hoveredEdgeKey ? 4 : e.isCriticalEdge ? 3 : e.isJointEdge ? 2 : 1);
    return score(a) - score(b);
  });

  ordered.forEach((e, idx) => {
    const isConnectedToFocus = focusId && (e.fromId === focusId || e.toId === focusId);
    const isEdgeHover = hoveredEdgeKey === e.key;
    if (edgeMode === "critical" && !e.isCriticalEdge && !e.isJointEdge && !isConnectedToFocus && !isEdgeHover) {
      return;
    }

    let d = "";
    const sameColumn = Math.abs(e.fromPos.left - e.toPos.left) < 40;
    if (sameColumn) {
      const sameCellStack =
        Math.abs(e.fromPos.midX - e.toPos.midX) < 30 &&
        e.toPos.top > e.fromPos.bottom - 5 &&
        e.toPos.top - e.fromPos.bottom < 32;
      if (sameCellStack) {
        const x = e.fromPos.midX;
        d = `M ${x.toFixed(1)} ${e.fromPos.bottom.toFixed(1)} L ${x.toFixed(1)} ${(e.toPos.top - 2).toFixed(1)}`;
      } else {
        // 同阶段跨泳道（如 Stage 3 合流 -> QA，或 Stage 5 QA -> 主策）：走右侧阶段走廊绕行进入左侧或右侧
        const bowX = Math.max(e.fromPos.right, e.toPos.right) + 22 + (idx % 3) * 8;
        d = buildRoundedOrthoPath(
          [
            { x: e.fromPos.right, y: e.y1 },
            { x: bowX, y: e.y1 },
            { x: bowX, y: e.y2 },
            { x: e.toPos.right + 2, y: e.y2 },
          ],
          8
        );
      }
    } else if (e.toStage - e.fromStage > 1) {
      // 跨越多阶段的远距边（如增量变更 CR）：走泳道间隙水平通道，不横穿中间阶段卡片
      const bus1 = e.busX || e.fromPos.right + 26;
      const gutterY = e.toPos.top - 10 - (idx % 3) * 4;
      const enterX = e.toPos.left - 24 - (idx % 3) * 6;
      d = buildRoundedOrthoPath(
        [
          { x: e.fromPos.right, y: e.y1 },
          { x: bus1, y: e.y1 },
          { x: bus1, y: gutterY },
          { x: enterX, y: gutterY },
          { x: enterX, y: e.y2 },
          { x: e.toPos.left - 2, y: e.y2 },
        ],
        8
      );
    } else {
      // 标准相邻阶段：正交总线分流走线 (H -> V -> H)
      const bx = e.busX || (e.fromPos.right + e.toPos.left) / 2;
      if (Math.abs(e.y1 - e.y2) < 3) {
        d = `M ${e.fromPos.right.toFixed(1)} ${e.y1.toFixed(1)} L ${(e.toPos.left - 2).toFixed(1)} ${e.y2.toFixed(1)}`;
      } else {
        d = buildRoundedOrthoPath(
          [
            { x: e.fromPos.right, y: e.y1 },
            { x: bx, y: e.y1 },
            { x: bx, y: e.y2 },
            { x: e.toPos.left - 2, y: e.y2 },
          ],
          9
        );
      }
    }

    let stroke = "#64748b";
    let width = 1.4;
    let opacity = 0.5;
    let marker = "url(#arrow-normal)";
    let dash = "";

    if (e.isJointEdge) {
      stroke = "#06b6d4";
      width = 1.9;
      opacity = 0.85;
      marker = "url(#arrow-cyan)";
      dash = `stroke-dasharray="6,3"`;
    }
    if (e.isCriticalEdge) {
      stroke = "#f59e0b";
      width = 2.8;
      opacity = 0.96;
      marker = "url(#arrow-gold)";
      dash = "";
    }

    if (hoveredEdgeKey) {
      if (isEdgeHover) {
        opacity = 1.0;
        width = 3.2;
        if (!e.isCriticalEdge && !e.isJointEdge) {
          stroke = "#38bdf8";
          marker = "url(#arrow-focus)";
        }
      } else {
        opacity = e.isCriticalEdge ? 0.25 : 0.10;
      }
    } else if (focusId) {
      if (isConnectedToFocus) {
        opacity = 1.0;
        width = Math.max(width, 2.5);
        if (!e.isCriticalEdge && !e.isJointEdge) {
          stroke = "#38bdf8";
          marker = "url(#arrow-focus)";
        }
      } else if (edgeMode === "focus" || hoveredTaskId) {
        opacity = e.isCriticalEdge ? 0.30 : 0.10;
      }
    }

    const kindText = e.isCriticalEdge ? "关键路径" : e.isJointEdge ? "联合合流" : "前置依赖";
    paths += `
      <g class="dag-edge-group" data-edge-key="${esc(e.key)}" data-to-id="${esc(e.toId)}">
        <path d="${d}" fill="none" stroke="transparent" stroke-width="11" style="pointer-events:stroke;cursor:pointer;">
          <title>${esc(e.fromId)} → ${esc(e.toId)} (${kindText})</title>
        </path>
        <path d="${d}" fill="none" stroke="${stroke}" stroke-width="${width}" ${dash} marker-end="${marker}" opacity="${opacity}" style="pointer-events:none;" />
      </g>
    `;
  });

  svg.innerHTML = paths;

  svg.querySelectorAll(".dag-edge-group").forEach((g) => {
    const key = g.getAttribute("data-edge-key");
    const toId = g.getAttribute("data-to-id");
    g.addEventListener("mouseenter", () => {
      hoveredEdgeKey = key;
      requestAnimationFrame(drawDagEdges);
    });
    g.addEventListener("mouseleave", () => {
      if (hoveredEdgeKey === key) {
        hoveredEdgeKey = null;
        requestAnimationFrame(drawDagEdges);
      }
    });
    g.addEventListener("click", () => {
      selectedTaskId = toId;
      document.querySelector('[data-tab="tab-task"]').click();
      renderSwimlaneGraph();
      renderSelectedTask();
    });
  });
}

function renderSelectedTask() {
  const emptyEl = document.getElementById("task-detail-empty");
  const bodyEl = document.getElementById("task-detail-body");
  const task = appState.tasks.find((t) => t.task_id === selectedTaskId);
  if (!task) {
    emptyEl.classList.remove("hidden");
    bodyEl.classList.add("hidden");
    return;
  }
  emptyEl.classList.add("hidden");
  bodyEl.classList.remove("hidden");

  const botOptions = appState.bots
    .map(
      (b) =>
        `<option value="${esc(b.bot_id)}" ${b.bot_id === task.assigned_bot_id ? "selected" : ""}>${esc(b.bot_id)} (${esc(b.role_code)})</option>`
    )
    .join("");

  const effDur = task.duration_hours + task.delay_hours;
  const collabs = task.collaborator_bot_ids?.length ? task.collaborator_bot_ids.join(", ") : "无";

  bodyEl.innerHTML = `
    <div class="section-box">
      <div class="section-title-row">
        <h3>[${esc(task.task_id)}] ${esc(task.title)}</h3>
        <span class="pill pill-info">${esc(STATUS_LABELS[task.status] || task.status)}</span>
      </div>
      <div class="pill-wrap">
        <span class="pill pill-dim">${esc(task.stage_id)}</span>
        <span class="pill pill-lean">${esc(MODE_LABELS[task.collaboration_mode] || task.collaboration_mode)}</span>
        <span class="pill pill-clock">类型: ${esc(task.task_type)}</span>
        ${task.is_critical ? `<span class="badge badge-cp">关键路径 Slack=0</span>` : `<span class="pill pill-clock">浮动 Slack=${task.slack}h</span>`}
      </div>
      <div style="font-size:11.5px;color:#cbd5e1;margin-top:4px;">
        <div><strong>主责 Bot：</strong>${esc(task.assigned_bot_id)} ｜ <strong>协同者：</strong>${esc(collabs)}</div>
        <div><strong>所需 2D/2.5D 标签：</strong>${task.required_tags.map((tag) => `<code>${esc(tag)}</code>`).join(" · ")}</div>
        <div><strong>原文双向追溯锚点：</strong>${esc(task.source_clause_ref)}</div>
        ${task.git_commit_hash ? `<div><strong>Git 留痕 Commit：</strong><code>${esc(task.git_commit_hash)}</code></div>` : ""}
        ${task.ambiguity_note ? `<div class="info-banner" style="margin-top:6px;">${esc(task.ambiguity_note)}</div>` : ""}
      </div>
    </div>

    <div class="section-box">
      <h3>三维可解释分配依据卡片（R2）</h3>
      <div class="explain-card">${esc(task.assignment_reason)}</div>
    </div>

    <div class="section-box">
      <h3>CPM 关键路径与工期指标（R4）</h3>
      <div class="cpm-grid">
        <div class="cpm-item"><span>预计工时 (+延期)</span><strong>${task.duration_hours}h (+${task.delay_hours}h = ${effDur}h)</strong></div>
        <div class="cpm-item"><span>ES / EF</span><strong>${task.es}h / ${task.ef}h</strong></div>
        <div class="cpm-item"><span>LS / LF</span><strong>${task.ls}h / ${task.lf}h</strong></div>
        <div class="cpm-item"><span>浮动 Slack</span><strong>${task.slack}h</strong></div>
        <div class="cpm-item"><span>重试次数</span><strong>${task.retry_count} 次</strong></div>
        <div class="cpm-item"><span>验收模式</span><strong>${esc(task.verify_mode)}</strong></div>
      </div>
    </div>

    <div class="section-box">
      <h3>独立可判定验收标准</h3>
      <ul class="criteria-list">
        ${task.acceptance_criteria.map((c) => `<li>${esc(c)}</li>`).join("")}
      </ul>
      ${task.deliverable_summary ? `<div style="margin-top:6px;font-size:11.5px;color:#86efac;"><strong>交付产出：</strong>${esc(task.deliverable_summary)}</div>` : ""}
    </div>

    <div class="section-box">
      <h3>运行期人工交互干预（R2 / R4 / R7）</h3>
      <div class="action-row">
        <select id="reassign-bot-select">${botOptions}</select>
        <button id="btn-reassign-task" class="btn btn-primary btn-sm">改派 Bot（触发资格复核）</button>
      </div>
      <div class="action-row">
        <button id="btn-delay-2h" class="btn btn-warn btn-sm">⏱ 注入延期 +2h</button>
        <button id="btn-delay-4h" class="btn btn-danger btn-sm">⏱ 注入延期 +4h（测试顺延）</button>
      </div>
      <div class="action-row">
        <button id="btn-qa-reject" class="btn btn-danger btn-sm">❌ QA 打回重试 (当前 ${task.retry_count} 次)</button>
        ${task.status === "FAILED" ? `<button id="btn-retry-task" class="btn btn-primary btn-sm">↻ 恢复重试</button>` : ""}
        ${task.status === "WAITING_VERIFY" ? `<button id="btn-qa-pass" class="btn btn-success btn-sm">✔ 独立 QA 核验通过</button>` : ""}
        ${task.status === "WAITING_DECISION" ? `<button id="btn-open-task-verdict" class="btn btn-purple btn-sm">⚖️ 主策拍案裁决</button>` : ""}
      </div>
    </div>

    <div class="section-box">
      <h3>任务执行与流转日志</h3>
      <div class="log-box">
        ${(task.execution_logs && task.execution_logs.length) ? task.execution_logs.map((l) => `<div>• ${esc(l)}</div>`).join("") : "<div>暂无运行日志</div>"}
      </div>
    </div>
  `;

  document.getElementById("btn-reassign-task").addEventListener("click", async () => {
    const targetBotId = document.getElementById("reassign-bot-select").value;
    try {
      const next = await apiPost("/api/tasks/reassign", { task_id: task.task_id, target_bot_id: targetBotId });
      applyState(next);
      showToast(`[${task.task_id}] 已改派给 ${targetBotId}`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  const handleDelay = async (hours) => {
    try {
      const next = await apiPost("/api/tasks/delay", { task_id: task.task_id, delay_hours: hours });
      applyState(next);
      showToast(`已对 [${task.task_id}] 注入 +${hours}h 延期，CPM 已重算`, "info");
    } catch (err) {
      showToast(err.message, "error");
    }
  };
  document.getElementById("btn-delay-2h").addEventListener("click", () => handleDelay(2));
  document.getElementById("btn-delay-4h").addEventListener("click", () => handleDelay(4));

  document.getElementById("btn-qa-reject").addEventListener("click", async () => {
    try {
      const next = await apiPost("/api/tasks/reject", {
        task_id: task.task_id,
        reason: "独立 QA 发现碰撞盒/锚点或数值边界与规格偏差，打回重做",
      });
      applyState(next);
      showToast(`已注入 QA 打回（${task.task_id}）`, "info");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  const retryBtn = document.getElementById("btn-retry-task");
  if (retryBtn) {
    retryBtn.addEventListener("click", async () => {
      try {
        const next = await apiPost("/api/tasks/retry", { task_id: task.task_id });
        applyState(next);
        showToast(`[${task.task_id}] 已重新入队待调度`, "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }

  const passBtn = document.getElementById("btn-qa-pass");
  if (passBtn) {
    passBtn.addEventListener("click", async () => {
      try {
        const next = await apiPost("/api/tasks/verify", { task_id: task.task_id, passed: true });
        applyState(next);
        showToast(`[${task.task_id}] 独立 QA 核验通过`, "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }

  const vBtn = document.getElementById("btn-open-task-verdict");
  if (vBtn) {
    vBtn.addEventListener("click", () => openVerdictModal({ kind: "task", taskId: task.task_id }));
  }
}

function renderPlannerTab() {
  const waitingTasks = appState.tasks.filter((t) => t.status === "WAITING_DECISION");
  const pendingEl = document.getElementById("planner-pending-list");
  if (waitingTasks.length === 0) {
    pendingEl.innerHTML = `<div style="color:var(--text-muted);font-size:11.5px;">暂无处于 WAITING_DECISION 的待拍案任务节点。</div>`;
  } else {
    pendingEl.innerHTML = waitingTasks
      .map(
        (t) => `
        <div class="item-card" style="border-color:rgba(147,51,234,0.6);margin-bottom:6px;">
          <div class="item-card-head">
            <span>[${esc(t.task_id)}] ${esc(t.title)}</span>
            <button class="btn btn-purple btn-sm btn-open-v" data-tid="${esc(t.task_id)}">拍案裁决</button>
          </div>
          <div style="color:#e9d5ff;font-size:11px;">${esc(t.ambiguity_note || (t.retry_count >= 2 ? `连续被 QA 打回 ${t.retry_count} 次升级` : `阶段门禁 ${t.stage_id} 收口确认`))}</div>
        </div>
      `
      )
      .join("");
    pendingEl.querySelectorAll(".btn-open-v").forEach((b) => {
      b.addEventListener("click", () => openVerdictModal({ kind: "task", taskId: b.getAttribute("data-tid") }));
    });
  }

  const memEl = document.getElementById("memory-list");
  memEl.innerHTML = appState.planner_memory
    .map(
      (m) => `
      <div class="item-card ${m.active ? "" : "revoked"}">
        <div class="item-card-head">
          <span>${esc(m.memory_id)} · ${esc(m.context_scenario)}</span>
          <button class="btn ${m.active ? "btn-secondary" : "btn-primary"} btn-sm btn-toggle-mem" data-mid="${esc(m.memory_id)}" data-active="${!m.active}">
            ${m.active ? "撤销教训" : "恢复生效"}
          </button>
        </div>
        <div><strong>踩过的坑：</strong>${esc(m.past_failure)}</div>
        <div style="color:#fcd34d;margin-top:2px;"><strong>教训：</strong>${esc(m.lesson_learned)}</div>
        <div style="color:var(--text-muted);font-size:10.5px;margin-top:2px;">溯源事件：${esc(m.source_event_id)} · 状态：${m.active ? "生效中" : "已撤销"}</div>
      </div>
    `
    )
    .join("");

  memEl.querySelectorAll(".btn-toggle-mem").forEach((b) => {
    b.addEventListener("click", async () => {
      const mid = b.getAttribute("data-mid");
      const active = b.getAttribute("data-active") === "true";
      try {
        const res = await apiPost("/api/memory/toggle", { memory_id: mid, active });
        applyState(res.state);
        showToast(`${mid} 已${active ? "恢复生效" : "撤销"}`, "info");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });

  const vHistEl = document.getElementById("verdict-history-list");
  if (appState.planner_verdicts.length === 0) {
    vHistEl.innerHTML = `<div style="color:var(--text-muted);font-size:11.5px;">暂无拍案记录。</div>`;
  } else {
    vHistEl.innerHTML = [...appState.planner_verdicts]
      .reverse()
      .map(
        (v) => `
        <div class="item-card">
          <div class="item-card-head">
            <span>${esc(v.verdict_id)} (${esc(v.planner_model_tier)})</span>
            <span class="pill pill-info">${esc(v.target_task_ids.join(", "))}</span>
          </div>
          <div><strong>触发：</strong>${esc(v.trigger_reason)}</div>
          <div style="color:#a7f3d0;"><strong>拍案结论：</strong>${esc(v.decision_conclusion)}</div>
          <div><strong>依据：</strong>${esc(v.rationale)}${v.memory_ref_id ? ` [引用教训 ${esc(v.memory_ref_id)}]` : ""}</div>
          <div style="color:var(--text-muted);font-size:10.5px;">${esc(v.timestamp)}</div>
        </div>
      `
      )
      .join("");
  }
}

function renderListenerTab() {
  const sigEl = document.getElementById("signals-list");
  if (appState.signals.length === 0) {
    sigEl.innerHTML = `<div style="color:var(--text-muted);font-size:11.5px;">尚未注入外部环境信号。</div>`;
  } else {
    sigEl.innerHTML = appState.signals
      .map(
        (s) => `
        <div class="item-card">
          <div class="item-card-head">
            <span>${esc(s.signal_id)} · ${esc(s.category)}</span>
            <span class="pill ${s.filtered_as_noise ? "pill-clock" : s.requires_planner_verdict ? "pill-dim" : "pill-info"}">
              评分 ${s.total_score}/20 (${s.filtered_as_noise ? "噪音过滤" : s.status})
            </span>
          </div>
          <div>${esc(s.raw_text)}</div>
          <div style="color:var(--text-muted);font-size:11px;margin-top:3px;">${esc(s.extracted_summary)}</div>
          ${s.requires_planner_verdict && s.status === "PENDING" ? `<button class="btn btn-purple btn-sm btn-sig-approve" style="margin-top:6px;" data-sid="${esc(s.signal_id)}">⚖️ 主策拍案并触发增量热重排</button>` : ""}
        </div>
      `
      )
      .join("");

    sigEl.querySelectorAll(".btn-sig-approve").forEach((b) => {
      b.addEventListener("click", () => openVerdictModal({ kind: "signal", signalId: b.getAttribute("data-sid") }));
    });
  }

  const crEl = document.getElementById("cr-list");
  if (appState.change_requests.length === 0) {
    crEl.innerHTML = `<div style="color:var(--text-muted);font-size:11.5px;">暂无增量变更热重排记录。</div>`;
  } else {
    crEl.innerHTML = appState.change_requests
      .map(
        (cr) => `
        <div class="item-card" style="border-color:rgba(244,63,94,0.45);">
          <div class="item-card-head">
            <span>${esc(cr.cr_id)} (${esc(cr.spec_version_before)} → ${esc(cr.spec_version_after)})</span>
            <code>${esc(cr.git_commit_hash || "-")}</code>
          </div>
          <div>${esc(cr.summary)}</div>
          <div style="font-size:11px;color:#86efac;margin-top:3px;"><strong>100% 保留已完成：</strong>${esc(cr.preserved_succeeded_ids.join(", ") || "无")}</div>
          <div style="font-size:11px;color:#fda4af;"><strong>增量新增任务：</strong>${esc(cr.added_task_ids.join(", "))}</div>
        </div>
      `
      )
      .join("");
  }
}

function renderGitTab() {
  const { git, events } = appState;
  document.getElementById("git-branch-count").textContent = `${git.branches.length} 分支 · ${git.commits.length} 提交`;
  document.getElementById("git-branches-pills").innerHTML = git.branches
    .map((b) => `<span class="pill ${b === "main" ? "pill-lean" : "pill-info"}">${esc(b)}</span>`)
    .join("");
  document.getElementById("git-graph-pre").textContent = git.graph_text || "暂无 Git 提交记录";

  document.getElementById("events-list").innerHTML = events
    .slice(0, 30)
    .map(
      (ev) => `
      <div class="item-card">
        <div class="item-card-head">
          <span>[T+${ev.sim_hour}h] ${esc(ev.title)}</span>
          <span class="pill pill-clock">${esc(ev.kind)}</span>
        </div>
        ${ev.detail ? `<div style="color:var(--text-muted);font-size:11px;">${esc(ev.detail)}</div>` : ""}
      </div>
    `
    )
    .join("");
}

function openVerdictModal(target) {
  verdictTarget = target;
  const modal = document.getElementById("verdict-modal");
  const info = document.getElementById("verdict-target-info");
  const conclInput = document.getElementById("verdict-conclusion");
  const ratInput = document.getElementById("verdict-rationale");
  const resolveRow = document.getElementById("verdict-resolve-mode-row");

  const memSelect = document.getElementById("verdict-memory-select");
  const activeMems = appState.planner_memory.filter((m) => m.active);
  memSelect.innerHTML =
    `<option value="">-- 不引用历史教训 --</option>` +
    activeMems.map((m) => `<option value="${esc(m.memory_id)}">${esc(m.memory_id)}: ${esc(m.context_scenario)}</option>`).join("");

  if (target.kind === "task") {
    const task = appState.tasks.find((t) => t.task_id === target.taskId);
    info.textContent = `目标任务：[${task.task_id}] ${task.title} ｜ 触发原因：${task.ambiguity_note || (task.retry_count >= 2 ? `连续打回 ${task.retry_count} 次` : `${task.stage_id} 阶段收口门禁`)}`;
    if (task.ambiguity_note) {
      conclInput.value = "拍板锁定唯一参数：防御塔最大 5 级，目标帧率 60FPS，消除歧义后放行下游。";
      ratInput.value = "结合 2D 渲染性能预算与核心战斗深度，锁定 60FPS 与 5 级成长梯度。";
      resolveRow.classList.add("hidden");
    } else if (task.retry_count >= 2) {
      conclInput.value = "重新明确精灵 Pivot 锚点与碰撞判定容差 <= 2px，要求按定版参数返工。";
      ratInput.value = "连续被独立 QA 打回两次，主策介入统一接口规格与验收口径。";
      resolveRow.classList.remove("hidden");
    } else {
      conclInput.value = `确认 ${task.stage_id} 阶段收口准出达标，批准进入下一阶段。`;
      ratInput.value = "核查规格追溯与验收报告齐全，符合阶段准出条件。";
      resolveRow.classList.add("hidden");
    }
  } else {
    const sig = appState.signals.find((s) => s.signal_id === target.signalId);
    info.textContent = `环境变更信号 [${sig.signal_id}] (评分 ${sig.total_score}/20)：${sig.raw_text}`;
    conclInput.value = "批准纳入增量变更单：保留历史已完成成果，仅对受影响脏节点增量热重排。";
    ratInput.value = "试玩反馈直指核心体验痛点，增量接入视差动效与小地图雷达且可控在预算内。";
    resolveRow.classList.add("hidden");
  }

  modal.classList.remove("hidden");
}

function wireEvents() {
  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.getAttribute("data-tab")).classList.add("active");
    });
  });

  // Modal closes
  document.querySelectorAll("[data-close]").forEach((el) => {
    el.addEventListener("click", () => {
      document.getElementById(el.getAttribute("data-close")).classList.add("hidden");
    });
  });

  // Preset switch
  document.getElementById("preset-select").addEventListener("change", async (e) => {
    try {
      const next = await apiPost("/api/presets/load", { case_key: e.target.value });
      selectedTaskId = null;
      applyState(next);
      showToast("已切换预设案例并重新构建 5 阶段 DAG 与 Git 基线", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Run / Pause
  document.getElementById("btn-toggle-run").addEventListener("click", async () => {
    try {
      const action = appState.orchestrator.is_running ? "pause" : "start";
      const next = await apiPost("/api/orchestrator/control", { action });
      applyState(next);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Single tick
  document.getElementById("btn-step-tick").addEventListener("click", async () => {
    try {
      const next = await apiPost("/api/orchestrator/tick", { hours_per_tick: 2.0 });
      applyState(next);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Rollback
  document.getElementById("btn-rollback").addEventListener("click", async () => {
    const stageId = document.getElementById("rollback-select").value;
    if (!stageId) return;
    try {
      const next = await apiPost("/api/orchestrator/control", { action: "rollback", stage_id: stageId });
      applyState(next);
      showToast(`已回滚至 ${stageId} 阶段门快照`, "info");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Quick verdict button
  document.getElementById("btn-quick-verdict").addEventListener("click", () => {
    const pendingTask = appState.tasks.find((t) => t.status === "WAITING_DECISION");
    if (pendingTask) {
      openVerdictModal({ kind: "task", taskId: pendingTask.task_id });
      return;
    }
    const pendingSig = appState.signals.find((s) => s.requires_planner_verdict && s.status === "PENDING");
    if (pendingSig) {
      openVerdictModal({ kind: "signal", signalId: pendingSig.signal_id });
    }
  });

  // Submit verdict
  document.getElementById("btn-submit-verdict").addEventListener("click", async () => {
    if (!verdictTarget) return;
    const conclusion = document.getElementById("verdict-conclusion").value.trim();
    const rationale = document.getElementById("verdict-rationale").value.trim();
    const memoryRefId = document.getElementById("verdict-memory-select").value || null;
    const resolveAction = document.getElementById("verdict-resolve-action").value;
    try {
      if (verdictTarget.kind === "task") {
        const next = await apiPost("/api/tasks/verdict", {
          task_id: verdictTarget.taskId,
          decision_conclusion: conclusion,
          rationale,
          memory_ref_id: memoryRefId,
          resolve_action: resolveAction,
        });
        applyState(next);
        showToast(`主策拍案落库成功（${verdictTarget.taskId}）`, "success");
      } else {
        const res = await apiPost("/api/signals/approve", {
          signal_id: verdictTarget.signalId,
          decision_conclusion: conclusion,
          rationale,
          memory_ref_id: memoryRefId,
        });
        applyState(res.state);
        showToast(`变更单 ${res.change_request.cr_id} 增量热重排完成！`, "success");
      }
      document.getElementById("verdict-modal").classList.add("hidden");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Add Pitfall Memory & Anti-Dogma test
  document.getElementById("add-memory-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await apiPost("/api/memory/add", {
        context_scenario: document.getElementById("mem-scenario").value,
        past_failure: document.getElementById("mem-failure").value,
        lesson_learned: document.getElementById("mem-lesson").value,
        source_event_id: `UI-MEM-${Date.now().toString().slice(-4)}`,
      });
      applyState(res.state);
      e.target.reset();
      showToast(`已新增主策教训 ${res.memory.memory_id}`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-test-dogma").addEventListener("click", async () => {
    try {
      await apiPost("/api/memory/add", {
        context_scenario: "工作流探索约束测试",
        past_failure: "测试僵化流程输入",
        lesson_learned: "必须固定使用某工作流模板，禁止探索某类玩法",
        source_event_id: "DOGMA-TEST",
      });
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Signal quick presets & submit
  document.getElementById("btn-fill-sig-valid").addEventListener("click", () => {
    document.getElementById("signal-source").value = "PLAYER_FEEDBACK";
    document.getElementById("signal-text").value =
      "试玩反馈：2.5D 等轴测房间切换时画面生硬，要求增加视差过渡动效与小地图雷达";
  });
  document.getElementById("btn-fill-sig-noise").addEventListener("click", () => {
    document.getElementById("signal-source").value = "TEAM_DISCUSSION";
    document.getElementById("signal-text").value = "大家中午吃什么外卖？今天天气真不错哈哈";
  });
  document.getElementById("btn-fill-sig-3d").addEventListener("click", () => {
    document.getElementById("signal-source").value = "TEAM_DISCUSSION";
    document.getElementById("signal-text").value = "建议把角色改成 3d骨骼蒙皮 和 pbr材质烘培 渲染管线";
  });

  document.getElementById("signal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw_text = document.getElementById("signal-text").value;
    const source_type = document.getElementById("signal-source").value;
    try {
      const res = await apiPost("/api/signals/inject", { raw_text, source_type });
      applyState(res.state);
      const sig = res.signal;
      if (sig.filtered_as_noise) {
        showToast(`信号 ${sig.signal_id} 判定为噪音已过滤（评分 ${sig.total_score}/20）`, "info");
      } else {
        showToast(`信号 ${sig.signal_id} 评分 ${sig.total_score}/20，已推送主策拍案`, "success");
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Custom Spec Modal
  document.getElementById("btn-open-spec-modal").addEventListener("click", () => {
    document.getElementById("custom-spec-title").value = appState.spec?.title || "";
    document.getElementById("custom-spec-markdown").value = appState.spec?.raw_markdown || "";
    document.getElementById("spec-modal").classList.remove("hidden");
  });

  document.getElementById("btn-fill-custom-2d").addEventListener("click", () => {
    document.getElementById("custom-spec-title").value = "《星界牌组》2D 像素肉鸽地牢（自定义）";
    document.getElementById("custom-spec-markdown").value = `# 《星界牌组》2D 像素肉鸽地牢计划书

## §1 核心规则与立项定调 (STAGE_1)
- §1.1 核心循环：2D 格子走位 + 回合卡牌构筑，初始手牌上限 4 张或 5 张待定。
- §1.2 表现基准：16x16 像素精灵图集 + 2D 法线贴图地牢火把照明。

## §2 基础资产与核心底座 (STAGE_2)
- §2.1 绘制主角与怪物 2D Sprite Sheet 序列帧动画与地牢 Tilemap。
- §2.2 实现 2D 网格碰撞判定与卡牌战斗数值加载器。

## §3 首层垂直切片合流联调 (STAGE_3)
- §3.1 首层地牢合流联调：整合角色移动、卡牌 HUD、2D 法线光效与受击反馈。
- §3.2 独立 QA 核验首层 60FPS 与出牌结算无死锁。

## §4 多层扩展量产 (STAGE_4)
- §4.1 扩充 3 个主题地牢瓦片集与 Boss Spine 2D 骨骼动画。
- §4.2 完成背包遗物与商人对话事件系统。

## §5 回归验收与封版 (STAGE_5)
- §5.1 全流程回归测试与性能报告。
- §5.2 主策终审封版拍案。`;
  });

  document.getElementById("btn-fill-custom-3d").addEventListener("click", () => {
    document.getElementById("custom-spec-title").value = "违规 3D 渲染管线测试计划书";
    document.getElementById("custom-spec-markdown").value = `# 违规 3D 计划书测试
- §1.1 使用 3d建模 与 pbr材质烘培 制作次时代高精度角色并绑定 3d骨骼蒙皮。`;
  });

  document.getElementById("btn-test-3d-tag").addEventListener("click", async () => {
    try {
      await apiPost("/api/tasks/validate_tags", { tags: ["3d_mesh_modeling", "3d_skeleton_rigging"] });
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-submit-custom-spec").addEventListener("click", async () => {
    const title = document.getElementById("custom-spec-title").value.trim();
    const raw_markdown = document.getElementById("custom-spec-markdown").value;
    try {
      const next = await apiPost("/api/specs/custom", { title, raw_markdown });
      selectedTaskId = null;
      applyState(next);
      document.getElementById("spec-modal").classList.add("hidden");
      showToast("自定义计划书拆解成功！已重置 DAG 与 Git 基线", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  window.addEventListener("resize", () => requestAnimationFrame(drawDagEdges));

  // 连线视图模式切换
  document.querySelectorAll(".edge-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".edge-mode-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      edgeMode = btn.getAttribute("data-edge-mode") || "all";
      requestAnimationFrame(drawDagEdges);
    });
  });

  // 编排器内部原理图弹窗与弹窗内实时联动控制
  document.getElementById("btn-open-internals").addEventListener("click", () => {
    renderInternalsModal();
    document.getElementById("internals-modal").classList.remove("hidden");
  });

  document.getElementById("btn-internals-step").addEventListener("click", async () => {
    try {
      const next = await apiPost("/api/orchestrator/tick", { hours_per_tick: 2.0 });
      applyState(next);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-internals-run").addEventListener("click", async () => {
    try {
      const action = appState.orchestrator.is_running ? "pause" : "start";
      const next = await apiPost("/api/orchestrator/control", { action });
      applyState(next);
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function renderInternalsModal() {
  if (!appState || !appState.internals) return;
  const { orchestrator, internals } = appState;
  const ps = internals.pipeline_stats;
  const fsm = internals.fsm_counts;
  const queues = internals.scheduler_queues;

  document.getElementById("internals-live-clock").textContent =
    `T+${orchestrator.sim_clock_hours.toFixed(1)}h · Tick ${orchestrator.tick_count} (${orchestrator.is_running ? "运行中" : "已暂停"})`;
  const runBtn = document.getElementById("btn-internals-run");
  runBtn.textContent = orchestrator.is_running ? "⏸ 暂停联动" : "▶ 启动联动";
  runBtn.className = orchestrator.is_running ? "btn btn-warn btn-sm" : "btn btn-primary btn-sm";

  // (a) 五层工作流水线架构图
  const pipelineSteps = [
    {
      title: "1. 规格解析与 2D/3D 黑白名单校验器",
      desc: "提取双向追溯条款、检测数值歧义升级、拦截 3D 禁用词",
      active: ps.ambiguity_count > 0,
      kpis: [
        `解析条款 ${ps.clauses_count}`,
        `歧义升级 ${ps.ambiguity_count}`,
        `3D拦截词 ${ps.blacklist_rule_count}`,
      ],
    },
    {
      title: "2. Kahn 拓扑无环校验 & CPM 正逆推计算器",
      desc: "无环检验 + 正向 ES/EF、逆向 LS/LF 与 Slack==0 关键路径判定",
      active: appState.metrics.has_delay_alert,
      kpis: [
        `节点 ${ps.dag_nodes_count} / 边 ${ps.dag_edges_count}`,
        `关键路径 ${ps.cp_nodes_count} 节点`,
        `总工期 ${ps.project_total_hours}h`,
      ],
    },
    {
      title: "3. 三维能力匹配与最小负载路由器",
      desc: "Task→Bot 角色匹配、标签 100% 子集命中、Least-Loaded 路由",
      active: false,
      kpis: [
        `已路由任务 ${ps.routed_tasks_count}`,
        `Bot 池 ${ps.bots_count} 实例`,
        `最高水位 ${ps.max_bot_load_hours}h`,
      ],
    },
    {
      title: "4. Tick 事件循环与并发 Worker 调度池",
      desc: "Ready Queue → Running 并发槽位 → 独立 QA 验收门禁",
      active: orchestrator.is_running || ps.running_count > 0 || ps.waiting_verify_count > 0,
      kpis: [
        `Tick #${ps.tick_count}`,
        `Ready ${ps.ready_count}`,
        `Running ${ps.running_count}`,
        `待QA ${ps.waiting_verify_count}`,
      ],
    },
    {
      title: "5. 异常升级拍案 & 脏节点传递闭包热重排器",
      desc: "主策 Tier-1 一锤定音 + 反向依赖闭包局部热重排 + Git 留痕",
      active: ps.waiting_decision_count > 0 || ps.cr_count > 0,
      kpis: [
        `待拍案 ${ps.waiting_decision_count}`,
        `已拍案 ${ps.verdicts_count}`,
        `热重排 ${ps.cr_count}`,
        `Git ${ps.git_commits_count}`,
      ],
    },
  ];

  document.getElementById("internals-pipeline").innerHTML = pipelineSteps
    .map(
      (st, idx) => `
      <div class="pipeline-step ${st.active ? "active-step" : ""}">
        <div class="pipeline-step-title">${esc(st.title)}</div>
        <div class="pipeline-step-desc">${esc(st.desc)}</div>
        <div class="pipeline-kpis">
          ${st.kpis.map((k) => `<span class="pipeline-kpi">${esc(k)}</span>`).join("")}
        </div>
      </div>
      ${idx < pipelineSteps.length - 1 ? `<div class="pipeline-arrow">➜</div>` : ""}
    `
    )
    .join("");

  // (b) 8 态有限状态机 SVG 流转图（带实时计数徽章）
  const states = [
    { id: "PENDING", label: "PENDING", sub: "未就绪(等依赖)", x: 24, y: 120, color: "#475569" },
    { id: "READY", label: "READY", sub: "入就绪队列", x: 215, y: 120, color: "#0284c7" },
    { id: "RUNNING", label: "RUNNING", sub: "Bot 槽位执行中", x: 420, y: 120, color: "#d97706" },
    { id: "WAITING_DECISION", label: "WAITING_DECISION", sub: "主策 Tier-1 拍案", x: 410, y: 18, color: "#9333ea" },
    { id: "WAITING_VERIFY", label: "WAITING_VERIFY", sub: "独立 QA 验收门", x: 645, y: 120, color: "#0d9488" },
    { id: "SUCCEEDED", label: "SUCCEEDED", sub: "落库并提交 Git", x: 875, y: 120, color: "#16a34a" },
    { id: "FAILED", label: "FAILED / 重试", sub: "QA打回(<2次重试)", x: 645, y: 225, color: "#e11d48" },
    { id: "SKIPPED", label: "SKIPPED", sub: "人工跳过", x: 24, y: 225, color: "#64748b" },
  ];

  const boxW = 148;
  const boxH = 54;
  const nodesSvg = states
    .map((s) => {
      const cnt = fsm[s.id] || 0;
      const glow = cnt > 0 ? `stroke-width="2.6"` : `stroke-width="1.4" opacity="0.72"`;
      const badgeBg = cnt > 0 ? s.color : "#1e293b";
      return `
        <g transform="translate(${s.x}, ${s.y})">
          <rect width="${boxW}" height="${boxH}" rx="8" fill="#131c2e" stroke="${s.color}" ${glow} />
          <text x="10" y="21" fill="#f8fafc" font-size="11" font-weight="700">${esc(s.label)}</text>
          <text x="10" y="39" fill="#94a3b8" font-size="10">${esc(s.sub)}</text>
          <rect x="${boxW - 34}" y="-9" width="30" height="20" rx="10" fill="${badgeBg}" stroke="#0f172a" stroke-width="1.5" />
          <text x="${boxW - 19}" y="5" text-anchor="middle" fill="#ffffff" font-size="11" font-weight="700">${cnt}</text>
        </g>
      `;
    })
    .join("");

  const fsmSvg = `
    <svg viewBox="0 0 1050 295" width="100%" height="280" style="min-width:920px;display:block;">
      <defs>
        <marker id="fsm-arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <polygon points="0 0, 7 3.5, 0 7" fill="#94a3b8" />
        </marker>
        <marker id="fsm-arr-purple" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <polygon points="0 0, 7 3.5, 0 7" fill="#c084fc" />
        </marker>
        <marker id="fsm-arr-red" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <polygon points="0 0, 7 3.5, 0 7" fill="#fb7185" />
        </marker>
      </defs>

      <!-- PENDING -> READY -->
      <path d="M 172 147 L 213 147" stroke="#94a3b8" stroke-width="1.8" fill="none" marker-end="url(#fsm-arr)" />
      <text x="192" y="139" text-anchor="middle" fill="#7dd3fc" font-size="9.5">前置全绿</text>

      <!-- READY -> RUNNING -->
      <path d="M 363 147 L 418 147" stroke="#94a3b8" stroke-width="1.8" fill="none" marker-end="url(#fsm-arr)" />
      <text x="390" y="139" text-anchor="middle" fill="#fcd34d" font-size="9.5">Bot空闲</text>

      <!-- RUNNING -> WAITING_VERIFY -->
      <path d="M 568 147 L 643 147" stroke="#94a3b8" stroke-width="1.8" fill="none" marker-end="url(#fsm-arr)" />
      <text x="605" y="138" text-anchor="middle" fill="#5eead4" font-size="9.5">交独立QA</text>

      <!-- WAITING_VERIFY -> SUCCEEDED -->
      <path d="M 793 147 L 873 147" stroke="#4ade80" stroke-width="2" fill="none" marker-end="url(#fsm-arr)" />
      <text x="833" y="138" text-anchor="middle" fill="#86efac" font-size="9.5">验收通过</text>

      <!-- RUNNING / READY -> WAITING_DECISION -->
      <path d="M 494 120 L 494 74" stroke="#c084fc" stroke-width="1.8" fill="none" marker-end="url(#fsm-arr-purple)" />
      <text x="540" y="99" fill="#d8b4fe" font-size="9.5">歧义 / 收口门</text>

      <!-- WAITING_DECISION -> READY (返工) & SUCCEEDED (拍案过关) -->
      <path d="M 410 45 C 310 45, 290 75, 290 118" stroke="#c084fc" stroke-width="1.5" stroke-dasharray="4,3" fill="none" marker-end="url(#fsm-arr-purple)" />
      <text x="315" y="65" fill="#d8b4fe" font-size="9.5">裁决后重排READY</text>

      <path d="M 558 45 C 760 45, 949 55, 949 118" stroke="#c084fc" stroke-width="1.5" stroke-dasharray="4,3" fill="none" marker-end="url(#fsm-arr-purple)" />
      <text x="760" y="38" fill="#d8b4fe" font-size="9.5">主策拍案门禁直接过关 SUCCEEDED</text>

      <!-- WAITING_VERIFY -> FAILED -->
      <path d="M 719 174 L 719 223" stroke="#fb7185" stroke-width="1.8" fill="none" marker-end="url(#fsm-arr-red)" />
      <text x="752" y="203" fill="#fda4af" font-size="9.5">QA打回</text>

      <!-- FAILED -> READY (重试) -->
      <path d="M 645 252 C 420 265, 290 250, 290 176" stroke="#fb7185" stroke-width="1.6" stroke-dasharray="4,3" fill="none" marker-end="url(#fsm-arr-red)" />
      <text x="455" y="274" text-anchor="middle" fill="#fda4af" font-size="9.5">打回 &lt; 2 次：重置进度回到 READY 重试</text>

      <!-- FAILED -> WAITING_DECISION (>=2次升级) -->
      <path d="M 793 252 C 855 252, 855 72, 560 56" stroke="#c084fc" stroke-width="1.5" stroke-dasharray="4,3" fill="none" marker-end="url(#fsm-arr-purple)" />
      <text x="862" y="195" fill="#e9d5ff" font-size="9.5">打回≥2次</text>
      <text x="862" y="207" fill="#e9d5ff" font-size="9.5">自动升级主策</text>

      <!-- PENDING -> SKIPPED -->
      <path d="M 98 174 L 98 223" stroke="#64748b" stroke-width="1.3" stroke-dasharray="3,3" fill="none" marker-end="url(#fsm-arr)" />
      <text x="128" y="203" fill="#94a3b8" font-size="9.5">人工跳过</text>

      ${nodesSvg}
    </svg>
  `;
  document.getElementById("internals-fsm-wrap").innerHTML = fsmSvg;

  // (c) 调度器内部实时队列监控
  const pendingHtml = queues.pending_pool.length
    ? queues.pending_pool
        .map(
          (p) => `
          <div class="queue-item">
            <div><strong>${esc(p.task_id)}</strong> · ${esc(p.title)}</div>
            <div style="color:var(--text-muted);font-size:10.5px;">分配: ${esc(p.assigned_bot_id)} · 等待前置: ${esc(p.blocked_by.join(", ") || "-")}</div>
          </div>
        `
        )
        .join("")
    : `<div style="color:var(--text-muted);font-size:11px;">等待依赖池为空</div>`;

  const readyHtml = queues.ready_queue.length
    ? queues.ready_queue
        .map(
          (r, i) => `
          <div class="queue-item">
            <div>#${i + 1} <strong>${esc(r.task_id)}</strong> ${r.is_critical ? '<span class="badge badge-cp">CP优先</span>' : ""}</div>
            <div style="color:#7dd3fc;font-size:10.5px;">${esc(r.title)} → 目标槽位 ${esc(r.assigned_bot_id)} (ES=${r.es}h)</div>
          </div>
        `
        )
        .join("")
    : `<div style="color:var(--text-muted);font-size:11px;">就绪待派发队列为空</div>`;

  const slotsHtml = queues.bot_slots
    .map(
      (b) => `
      <div class="queue-item ${b.slot_status === "BUSY" ? "busy" : ""}">
        <div style="display:flex;justify-content:space-between;">
          <strong>${esc(b.bot_id)}</strong>
          <span class="pill ${b.slot_status === "BUSY" ? "pill-dim" : "pill-lean"}">${b.slot_status === "BUSY" ? "BUSY 执行中" : "IDLE 空闲"}</span>
        </div>
        ${
          b.slot_status === "BUSY"
            ? `<div style="color:#fcd34d;font-size:10.5px;">当前任务: ${esc(b.running_task_id)} (${b.progress_hours}/${b.effective_duration}h)</div>`
            : `<div style="color:var(--text-muted);font-size:10.5px;">已排期总水位: ${b.current_load_hours}h</div>`
        }
      </div>
    `
    )
    .join("");

  const gateHtml = queues.gate_queue.length
    ? queues.gate_queue
        .map(
          (g) => `
          <div class="queue-item" style="border-color:${g.status === "WAITING_DECISION" ? "#9333ea" : g.status === "WAITING_VERIFY" ? "#0d9488" : "#e11d48"};">
            <div><strong>${esc(g.task_id)}</strong> · <span class="pill pill-info">${esc(STATUS_LABELS[g.status] || g.status)}</span></div>
            <div style="color:#cbd5e1;font-size:10.5px;margin-top:2px;">${esc(g.reason)}</div>
          </div>
        `
        )
        .join("")
    : `<div style="color:var(--text-muted);font-size:11px;">当前无待验收/待拍案门禁阻塞</div>`;

  document.getElementById("internals-queues").innerHTML = `
    <div class="queue-col">
      <div class="queue-col-head"><span>⏳ 等待依赖池 (Pending)</span><span>${queues.pending_pool.length}</span></div>
      ${pendingHtml}
    </div>
    <div class="queue-col">
      <div class="queue-col-head"><span>🚀 就绪待派发队列 (Ready Queue)</span><span>${queues.ready_queue.length}</span></div>
      ${readyHtml}
    </div>
    <div class="queue-col">
      <div class="queue-col-head"><span>🤖 Bot 并发执行槽位 (Slots)</span><span>${queues.bot_slots.filter((x) => x.slot_status === "BUSY").length}/${queues.bot_slots.length}</span></div>
      ${slotsHtml}
    </div>
    <div class="queue-col">
      <div class="queue-col-head"><span>🛡️ 待验收/待拍案门禁 (Gates)</span><span>${queues.gate_queue.length}</span></div>
      ${gateHtml}
    </div>
  `;
}

wireEvents();
fetchState().catch((err) => showToast(err.message, "error"));
