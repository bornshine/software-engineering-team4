const STAGES = [
  { id: "DEV_STAGE_1", title: "阶段 1 · 技术定型", sub: "集中收口" },
  { id: "DEV_STAGE_2", title: "阶段 2 · 四工种生产", sub: "散开并行" },
  { id: "DEV_STAGE_3", title: "阶段 3 · 模块联调", sub: "联合合流" },
  { id: "DEV_STAGE_4", title: "阶段 4 · 封版终验", sub: "集中封版" },
];

const ROLES = [
  { id: "ROLE_TECH_LEAD", label: "技术主导", sub: "TECH / INTEG" },
  { id: "ROLE_SYS_DEV", label: "程序系统", sub: "SYS-*" },
  { id: "ROLE_NARRATIVE", label: "叙事设计", sub: "NAR-*" },
  { id: "ROLE_ART_2D", label: "2D 美术", sub: "ART-*" },
  { id: "ROLE_AUDIO", label: "音频设计", sub: "AUD-*" },
  { id: "ROLE_QA_INTEG", label: "独立 QA", sub: "场景 / L2 / 终验" },
];

const PROJECT_STATES = [
  "LOADED",
  "AWAITING_TECH_CONFIRM",
  "RUNNING",
  "PAUSED",
  "AWAITING_RELEASE",
  "RELEASED",
  "APPLYING_DELTA",
];

let projectsMeta = [];
let fixturesMeta = [];
let currentProjectId = null;
let sessionData = null;
let concurrencyMap = {};
let isMockMode = true;
let selectedTaskId = null;
let selectedTaskDetail = null;
let edgeMode = "all"; // all | focus | critical
let eventSource = null;
let sseEvents = [];

function esc(val) {
  return String(val ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg, kind = "ok") {
  const box = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

async function apiGet(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(`[${data.error_code || resp.status}] ${data.message || "请求失败"}`);
  }
  return data;
}

async function apiPost(url, payload = {}) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(`[${data.error_code || resp.status}] ${data.message || "请求失败"}`);
  }
  return data;
}

async function bootstrap() {
  bindStaticEvents();
  await refreshProjectsList();
  if (projectsMeta.length > 0 && !currentProjectId) {
    currentProjectId = projectsMeta[0].project_id;
  }
  if (currentProjectId) {
    await refreshSession();
    connectSSE(currentProjectId);
  }
}

async function refreshProjectsList() {
  const res = await apiGet("/api/projects");
  projectsMeta = res.projects || [];
  fixturesMeta = res.fixtures || [];
  concurrencyMap = res.concurrency || {};
  isMockMode = Boolean(res.mock_mode);

  const pSel = document.getElementById("project-select");
  pSel.innerHTML = projectsMeta
    .map((p) => `<option value="${esc(p.project_id)}">${esc(p.project_id)} (${esc(p.spec_version)})</option>`)
    .join("");
  if (currentProjectId) pSel.value = currentProjectId;

  const fSel = document.getElementById("fixture-select");
  fSel.innerHTML = fixturesMeta
    .map((f) => `<option value="${esc(f.path)}">${esc(f.label)}</option>`)
    .join("");
  if (fixturesMeta.length > 1) {
    fSel.value = fixturesMeta[fixturesMeta.length - 1].path;
  }
}

async function refreshSession() {
  if (!currentProjectId) return;
  const res = await apiGet(`/api/projects/${encodeURIComponent(currentProjectId)}/session`);
  sessionData = res.session;
  concurrencyMap = res.concurrency || concurrencyMap;
  isMockMode = Boolean(res.mock_mode);
  sseEvents = res.events_tail || [];

  const taskIds = Object.keys(sessionData.tasks || {});
  if (!selectedTaskId || !sessionData.tasks[selectedTaskId]) {
    const waiting = taskIds.find((tid) => sessionData.tasks[tid].state === "WAITING_DECISION");
    selectedTaskId = waiting || taskIds[0] || null;
  }
  if (selectedTaskId) {
    try {
      selectedTaskDetail = await apiGet(
        `/api/projects/${encodeURIComponent(currentProjectId)}/tasks/${encodeURIComponent(selectedTaskId)}`
      );
    } catch {
      selectedTaskDetail = null;
    }
  }
  renderAll();
}

function connectSSE(projectId) {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  const lastSeq = sseEvents.length ? sseEvents[sseEvents.length - 1].seq : 0;
  eventSource = new EventSource(
    `/api/projects/${encodeURIComponent(projectId)}/events/stream?since_seq=${lastSeq}`
  );
  const onAnyEvent = (ev) => {
    try {
      const obj = JSON.parse(ev.data);
      sseEvents.push(obj);
      if (sseEvents.length > 80) sseEvents.shift();
      refreshSession();
    } catch {
      /* ignore keepalive */
    }
  };
  [
    "HANDOFF_ACCEPTED",
    "PROJECT_STATE_CHANGED",
    "TASK_STATE_CHANGED",
    "WORKER_STARTED",
    "WORKER_FINISHED",
    "WRITE_VIOLATION",
    "VERIFY_L1_DONE",
    "VERIFY_L2_DONE",
    "MERGE_APPLIED",
    "HUMAN_DECISION",
    "CHANGE_REQUEST_EXPORTED",
    "DELTA_APPLIED",
    "BUDGET_EXHAUSTED",
    "RELEASE_SIGNED",
  ].forEach((name) => eventSource.addEventListener(name, onAnyEvent));
}

function renderAll() {
  if (!sessionData) return;
  renderHeader();
  renderKpis();
  renderDag();
  renderGantt();
  renderDeltaView();
  renderInternalsView();
  renderSideGates();
  renderTaskDetail();
}

function renderHeader() {
  const s = sessionData;
  document.getElementById("mode-pill").textContent = isMockMode ? "MOCK 离线仿真" : "API+CLI 生产";
  document.getElementById("hdr-project-id").textContent = s.project_id;
  document.getElementById("hdr-spec-version").textContent = s.spec_version;
  document.getElementById("hdr-parent-version").textContent = s.parent_version || "无(首版)";
  document.getElementById("hdr-scope-tier").textContent = s.scope_tier;
  document.getElementById("hdr-lead-pillars").textContent = (s.lead_pillars || []).join(" > ");
  const hashEl = document.getElementById("hdr-hash-pill");
  hashEl.title = `canonical_sha256: ${s.canonical_sha256}`;
  hashEl.textContent = `SHA:${(s.canonical_sha256 || "").slice(0, 8)} 已校验`;
  document.getElementById("hdr-project-state").textContent = s.project_state;

  const wBtn = document.getElementById("btn-warnings");
  const warns = s.warnings || [];
  if (warns.length > 0) {
    wBtn.classList.remove("hidden");
    document.getElementById("hdr-warnings-count").textContent = String(warns.length);
  } else {
    wBtn.classList.add("hidden");
  }
  document.getElementById("warnings-drawer").innerHTML = warns.map((w) => `<div>• ${esc(w)}</div>`).join("");
}

function renderKpis() {
  const cpm = sessionData.cpm || {};
  const b = sessionData.budget || {};
  const tasks = Object.values(sessionData.tasks || {});
  const waitingTasks = tasks.filter((t) => t.state === "WAITING_DECISION");
  const pendingProjectGates =
    sessionData.project_state === "AWAITING_TECH_CONFIRM" || sessionData.project_state === "AWAITING_RELEASE" ? 1 : 0;
  const totalGates = waitingTasks.length + pendingProjectGates;

  document.getElementById("kpi-cp-pct").textContent = `${cpm.progress_cp ?? 0}%`;
  document.getElementById("kpi-cp-bar").style.width = `${Math.min(100, cpm.progress_cp ?? 0)}%`;
  document.getElementById("kpi-cp-detail").textContent = `预计总工期：${cpm.cp_length_hours ?? 0}h | 基线：${cpm.baseline_cp_length_hours ?? 0}h`;

  document.getElementById("kpi-all-pct").textContent = `${cpm.progress_all ?? 0}%`;
  document.getElementById("kpi-all-bar").style.width = `${Math.min(100, cpm.progress_all ?? 0)}%`;
  document.getElementById("kpi-all-detail").textContent = `全图总工时：${cpm.total_all_hours ?? 0}h | 豁免跳过：${(cpm.waived_tasks || []).length} 项`;

  const costPct = b.cost_cap > 0 ? Math.min(100, (b.cost_used / b.cost_cap) * 100) : 0;
  document.getElementById("kpi-budget-cost").textContent = `$${Number(b.cost_used || 0).toFixed(2)} / $${Number(b.cost_cap || 0).toFixed(2)}`;
  document.getElementById("kpi-budget-bar").style.width = `${costPct}%`;
  document.getElementById("kpi-budget-calls").textContent = `调用次数：${b.calls_used || 0} / ${b.calls_cap || 0}`;

  document.getElementById("kpi-gate-count").textContent = `${totalGates} 项待处理`;
  document.getElementById("side-gate-badge").textContent = String(totalGates);
  document.getElementById("btn-quick-g1").classList.toggle("hidden", sessionData.project_state !== "AWAITING_TECH_CONFIRM");
  document.getElementById("btn-quick-g4").classList.toggle("hidden", sessionData.project_state !== "AWAITING_RELEASE");
}

function renderDag() {
  const wrap = document.getElementById("dag-canvas-wrap");
  const tasks = Object.values(sessionData.tasks || {});
  const edges = sessionData.edges || [];
  const mainSet = new Set((sessionData.cpm && sessionData.cpm.main_path) || []);

  let html = `<div class="dag-board" id="dag-board"><svg class="dag-svg" id="dag-svg"></svg><div class="dag-grid">`;
  html += `<div class="stage-hdr">工种泳道<small>角色职责</small></div>`;
  for (const st of STAGES) {
    html += `<div class="stage-hdr">${esc(st.title)}<small>${esc(st.sub)}</small></div>`;
  }

  for (const role of ROLES) {
    html += `<div class="lane-hdr">${esc(role.label)}<small>${esc(role.id)} (${esc(role.sub)})</small></div>`;
    for (const st of STAGES) {
      const cellTasks = tasks
        .filter((t) => t.role === role.id && t.dev_stage === st.id)
        .sort((a, b) => a.task_id.localeCompare(b.task_id));
      html += `<div class="lane-cell">`;
      for (const t of cellTasks) {
        const isSel = t.task_id === selectedTaskId;
        const isCp = mainSet.has(t.task_id);
        const cls = ["task-node", isSel ? "selected" : "", isCp ? "critical" : ""].join(" ");
        const deltaHtml = t.delta_tag ? `<span class="tag-delta tag-${esc(t.delta_tag)}">${esc(t.delta_tag)}</span>` : "";
        const skipHtml = t.state === "SKIPPED" ? `<span>${t.skip?.waiver ? "豁免" : "阻断"}</span>` : "";
        html += `
          <div class="${cls}" data-task-id="${esc(t.task_id)}">
            <div class="node-top">
              <span class="node-id">${esc(t.task_id)}</span>
              <span class="node-pill st-${esc(t.state)}">${esc(t.state)}</span>
            </div>
            <div class="node-title" title="${esc(t.title)}">${esc(t.title)}</div>
            <div class="node-foot">
              <span>${esc(t.priority)} · ${t.estimate_hours}${t.delay_hours > 0 ? `+${t.delay_hours}` : ""}h</span>
              ${deltaHtml}${skipHtml}
            </div>
          </div>`;
      }
      html += `</div>`;
    }
  }
  html += `</div></div>`;
  wrap.innerHTML = html;

  wrap.querySelectorAll(".task-node").forEach((el) => {
    el.addEventListener("click", () => selectTask(el.getAttribute("data-task-id")));
  });

  requestAnimationFrame(() => drawDagEdges(edges, mainSet));
}

function drawDagEdges(edges, mainSet) {
  const board = document.getElementById("dag-board");
  const svg = document.getElementById("dag-svg");
  if (!board || !svg) return;

  const bRect = board.getBoundingClientRect();
  svg.setAttribute("width", String(board.scrollWidth));
  svg.setAttribute("height", String(board.scrollHeight));

  const nodeCoords = {};
  board.querySelectorAll(".task-node").forEach((el) => {
    const r = el.getBoundingClientRect();
    nodeCoords[el.getAttribute("data-task-id")] = {
      left: r.left - bRect.left,
      right: r.right - bRect.left,
      top: r.top - bRect.top,
      height: r.height,
    };
  });

  const filtered = edges.filter(([u, v]) => {
    if (edgeMode === "focus" && selectedTaskId) return u === selectedTaskId || v === selectedTaskId;
    if (edgeMode === "critical") return mainSet.has(u) && mainSet.has(v);
    return true;
  });

  const outCount = {};
  const outIdx = {};
  const inCount = {};
  const inIdx = {};
  for (const [u, v] of filtered) {
    outCount[u] = (outCount[u] || 0) + 1;
    inCount[v] = (inCount[v] || 0) + 1;
  }

  let pathsHtml = "";
  filtered.forEach(([u, v], idx) => {
    const a = nodeCoords[u];
    const b = nodeCoords[v];
    if (!a || !b) return;

    const oi = outIdx[u] || 0;
    outIdx[u] = oi + 1;
    const ii = inIdx[v] || 0;
    inIdx[v] = ii + 1;

    const sy = a.top + ((oi + 1) / (outCount[u] + 1)) * a.height;
    const ty = b.top + ((ii + 1) / (inCount[v] + 1)) * b.height;
    const sx = a.right;
    const tx = b.left;
    const laneOffset = ((idx % 5) - 2) * 8;
    const midX = sx + Math.max(20, (tx - sx) * 0.5) + laneOffset;
    const d = `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
    const isCp = mainSet.has(u) && mainSet.has(v);

    pathsHtml += `
      <g class="dag-edge-group">
        <title>${esc(u)} → ${esc(v)}</title>
        <path class="dag-edge-hit" d="${d}"></path>
        <path class="dag-edge-line ${isCp ? "is-critical" : ""}" d="${d}"></path>
      </g>`;
  });
  svg.innerHTML = pathsHtml;
}

function renderGantt() {
  const box = document.getElementById("gantt-container");
  const tasks = Object.values(sessionData.tasks || {}).sort((a, b) => a.es - b.es || a.task_id.localeCompare(b.task_id));
  const maxSpan = Math.max(1, sessionData.cpm?.cp_length_hours || 1, ...tasks.map((t) => t.ef + t.slack + t.resource_wait_hours));

  let html = "";
  for (const t of tasks) {
    const leftPct = (t.es / maxSpan) * 100;
    const basePct = (t.estimate_hours / maxSpan) * 100;
    const delayPct = (t.delay_hours / maxSpan) * 100;
    const slackLeftPct = (t.ef / maxSpan) * 100;
    const slackPct = (t.slack / maxSpan) * 100;
    const waitLeftPct = Math.max(0, leftPct - (t.resource_wait_hours / maxSpan) * 100);
    const waitPct = (t.resource_wait_hours / maxSpan) * 100;
    const barColor = t.on_main_critical_path ? "#f59e0b" : "#0284c7";

    html += `
      <div class="gantt-row" data-task-id="${esc(t.task_id)}">
        <div><strong>${esc(t.task_id)}</strong> <span class="badge st-${esc(t.state)}" style="color:#fff">${esc(t.state)}</span></div>
        <div class="gantt-track">
          ${t.resource_wait_hours > 0 ? `<div class="gantt-wait" style="left:${waitLeftPct}%;width:${waitPct}%" title="资源等待 ${t.resource_wait_hours}h"></div>` : ""}
          <div class="gantt-bar" style="left:${leftPct}%;width:${basePct}%;background:${barColor}"></div>
          ${t.delay_hours > 0 ? `<div class="gantt-bar" style="left:${leftPct + basePct}%;width:${delayPct}%;background:#e11d48"></div>` : ""}
          ${t.slack > 0 ? `<div class="gantt-slack" style="left:${slackLeftPct}%;width:${slackPct}%"></div>` : ""}
        </div>
        <div style="font-size:11px;color:var(--text-muted)">[${t.es}..${t.ef}h] S=${t.slack}h${t.resource_wait_hours > 0 ? ` W=${t.resource_wait_hours}h` : ""}</div>
      </div>`;
  }
  box.innerHTML = html || `<div class="empty-tip">暂无任务数据。</div>`;
  box.querySelectorAll(".gantt-row").forEach((el) => {
    el.addEventListener("click", () => selectTask(el.getAttribute("data-task-id")));
  });
}

function renderDeltaView() {
  const box = document.getElementById("delta-container");
  const hist = sessionData.delta_history || [];
  const crs = sessionData.change_requests || [];
  const tombs = sessionData.tombstones || [];

  let html = `<div class="card-grid">`;
  if (hist.length > 0) {
    const latest = hist[hist.length - 1];
    html += `
      <div class="info-card">
        <h4>最近升版：${esc(latest.from_version)} → ${esc(latest.to_version)} (${esc(latest.delta_tier)})</h4>
        <div>原样复用：<strong>${latest.reused_ids.length}</strong> 个节点（保留原 SHA-256）</div>
        <div>标脏重跑：<strong>${latest.dirty_ids.length}</strong> 个节点</div>
        <div>新增：<strong>${latest.added_ids.length}</strong> | 废弃墓碑：<strong>${latest.deprecated_ids.length}</strong></div>
        <div style="margin-top:6px;color:var(--emerald)">节省计划工时：<strong>${latest.saved_estimate_hours} h</strong></div>
      </div>`;
  } else {
    html += `
      <div class="info-card">
        <h4>尚未执行 Delta RFC 升版</h4>
        <div style="color:var(--text-muted)">可在顶部选择 <code>xiyou-nverguo (v1.1.0)</code> 点击「加载 / 升版」，直接实测 7 个复用 / 5 个重跑的增量热重排。</div>
      </div>`;
  }
  html += `
    <div class="info-card">
      <h4>change_request.yaml 回流单 (${crs.length})</h4>
      ${crs.map((c) => `<div>• <code>${esc(c.request_id)}</code> [${esc(c.trigger_source)}] → ${esc(c.impacted_req_ids.join(","))}</div>`).join("") || `<div style="color:var(--text-muted)">暂无回流变更单</div>`}
    </div>
    <div class="info-card">
      <h4>废弃墓碑表 (${tombs.length})</h4>
      ${tombs.map((tb) => `<div>• <code>${esc(tb.req_id)}</code> (deprecated in ${esc(tb.deprecated_in)})</div>`).join("") || `<div style="color:var(--text-muted)">暂无废弃需求</div>`}
    </div>
  </div>`;

  const tasks = Object.values(sessionData.tasks || {});
  html += `<table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>增量标签</th><th>产出版本</th><th>提交</th></tr></thead><tbody>`;
  for (const t of tasks) {
    html += `<tr><td><strong>${esc(t.task_id)}</strong> ${esc(t.title)}</td><td>${esc(t.state)}</td><td>${esc(t.delta_tag || "-")}</td><td>${esc(t.produced_in_version || "-")}</td><td><code>${esc(t.last_commit || "-")}</code></td></tr>`;
  }
  html += `</tbody></table>`;
  box.innerHTML = html;
}

function renderInternalsView() {
  const box = document.getElementById("internals-container");
  const tasks = Object.values(sessionData.tasks || {});
  const runningByRole = {};
  for (const t of tasks) {
    if (t.state === "RUNNING") runningByRole[t.role] = (runningByRole[t.role] || 0) + 1;
  }

  let html = `<div class="info-card" style="margin-bottom:10px">
    <h4>项目级状态机 (§3.2)</h4>
    <div class="fsm-strip">`;
  for (const st of PROJECT_STATES) {
    html += `<div class="fsm-node ${sessionData.project_state === st ? "active" : ""}">${esc(st)}</div>`;
  }
  html += `</div></div>`;

  html += `<div class="card-grid">`;
  html += `<div class="info-card"><h4>工种并发槽占用</h4>`;
  for (const r of ROLES) {
    const cap = concurrencyMap[r.id] || 1;
    const used = runningByRole[r.id] || 0;
    html += `<div style="display:flex;justify-content:space-between;margin:3px 0"><span>${esc(r.label)}</span><strong>${used} / ${cap}</strong></div>`;
  }
  html += `</div>`;

  const commits = [...(sessionData.git_commits || [])].reverse().slice(0, 12);
  html += `<div class="info-card"><h4>沙箱 Git 审计提交 (${sessionData.git_sync_pending ? "待同步" : "已同步"})</h4>`;
  html += commits.map((c) => `<div style="margin:3px 0"><code>${esc(c.commit_hash)}</code> ${esc(c.message)}</div>`).join("") || "暂无提交";
  html += `</div></div>`;

  const recentEvents = [...sseEvents].reverse().slice(0, 25);
  html += `<div class="info-card"><h4>实时 SSE 审计事件流 (最新 ${recentEvents.length} 条)</h4>
    <table class="data-table"><thead><tr><th>Seq</th><th>事件类型</th><th>任务</th><th>时间</th></tr></thead><tbody>`;
  for (const ev of recentEvents) {
    html += `<tr><td>#${ev.seq}</td><td><code>${esc(ev.event_type)}</code></td><td>${esc(ev.task_id || "-")}</td><td>${esc(ev.occurred_at)}</td></tr>`;
  }
  html += `</tbody></table></div>`;
  box.innerHTML = html;
}

function renderSideGates() {
  const box = document.getElementById("gates-todo-box");
  let html = "";

  if (sessionData.project_state === "AWAITING_TECH_CONFIRM") {
    const tp = sessionData.tech_profile || {};
    html += `
      <div class="gate-card">
        <h4>G1 · 技术定型确认 (项目级)</h4>
        <div class="form-row"><label>平台/语言/渲染</label>
          <input id="g1-platform" value="${esc(tp.platform || "web")}" />
          <input id="g1-lang" value="${esc(tp.language || "typescript")}" />
          <input id="g1-render" value="${esc(tp.render || "canvas2d")}" />
        </div>
        <div class="btn-row">
          <button class="btn btn-purple" onclick="submitG1()">确认技术档案并启动调度</button>
        </div>
      </div>`;
  }

  if (sessionData.project_state === "AWAITING_RELEASE") {
    const manuals = sessionData.manual_required_items || [];
    const waived = sessionData.cpm?.waived_tasks || [];
    const warns = sessionData.warnings || [];
    html += `
      <div class="gate-card">
        <h4>G4 · 终验封版签字 (项目级)</h4>
        <div>MANUAL_REQUIRED：${manuals.length ? manuals.map(esc).join("；") : "无"}</div>
        <div>豁免跳过项：${waived.length ? waived.map(esc).join(", ") : "无"}</div>
        <div>未处理告警：${warns.length} 条</div>
        <div class="form-row"><label>退回指定任务 ID（逗号分隔，仅退回时填写）</label><input id="g4-reject-ids" placeholder="如 SYS-002" /></div>
        <div class="btn-row">
          <button class="btn btn-emerald" onclick="submitG4('sign_release')">🔏 签字封版并打标签</button>
          <button class="btn btn-warn" onclick="submitG4('reject_tasks')">退回指定任务</button>
        </div>
      </div>`;
  }

  const waiting = Object.values(sessionData.tasks || {}).filter((t) => t.state === "WAITING_DECISION");
  for (const t of waiting) {
    html += `<div class="gate-card">
      <h4>${t.decision_kind === "REQUIREMENT_DEFECT" ? "G3 · 需求缺陷变更提单" : "G2 · 任务异常裁决"} · ${esc(t.task_id)}</h4>
      <div>触发原因：<strong>${esc(t.decision_kind)}</strong></div>
      <div class="form-row"><label>裁决/指导意见</label><input id="gate-note-${esc(t.task_id)}" placeholder="填写指导意见或豁免原因" /></div>
      <div class="btn-row">`;

    if (t.decision_kind === "REQUIREMENT_DEFECT") {
      html += `
        <button class="btn btn-purple btn-sm" onclick="submitG3('${esc(t.task_id)}','submit_cr')">导出 change_request.yaml</button>
        <button class="btn btn-secondary btn-sm" onclick="submitG3('${esc(t.task_id)}','reject_defect')">驳回(按实现重做)</button>`;
    } else if (t.decision_kind === "SPOT_CHECK") {
      html += `
        <button class="btn btn-emerald btn-sm" onclick="submitG2('${esc(t.task_id)}','approve')">通过人工抽检</button>
        <button class="btn btn-danger btn-sm" onclick="submitG2('${esc(t.task_id)}','reject')">否决并重做</button>`;
    } else if (t.decision_kind === "SCENARIO_DISPUTE") {
      html += `
        <button class="btn btn-primary btn-sm" onclick="submitG2('${esc(t.task_id)}','rewrite_scenario')">场景有误：重写场景</button>
        <button class="btn btn-warn btn-sm" onclick="submitG2('${esc(t.task_id)}','reject_dispute')">场景无误：作者重做</button>`;
    } else {
      html += `
        <button class="btn btn-primary btn-sm" onclick="submitG2('${esc(t.task_id)}','retry_with_guidance')">补充指导重做</button>
        <button class="btn btn-warn btn-sm" onclick="submitG2('${esc(t.task_id)}','skip_with_waiver')">跳过(豁免放行)</button>
        <button class="btn btn-danger btn-sm" onclick="submitG2('${esc(t.task_id)}','skip_and_block')">跳过(阻断下游)</button>`;
    }
    html += `</div></div>`;
  }

  const skipped = Object.values(sessionData.tasks || {}).filter((t) => t.state === "SKIPPED");
  for (const t of skipped) {
    html += `<div class="gate-card">
      <h4>已跳过 · ${esc(t.task_id)} (${t.skip?.waiver ? "豁免放行" : "阻断下游"})</h4>
      <button class="btn btn-secondary btn-sm" onclick="submitG2('${esc(t.task_id)}','undo_skip')">撤销跳过</button>
    </div>`;
  }

  if (!html) {
    html = `<div style="color:var(--text-muted)">当前无待确认的人工门禁。</div>`;
  }
  box.innerHTML = html;
}

function renderTaskDetail() {
  const box = document.getElementById("task-detail-box");
  if (!selectedTaskId || !sessionData.tasks[selectedTaskId]) {
    box.innerHTML = `<div style="color:var(--text-muted)">点击任意任务节点查看详情与全链血缘。</div>`;
    return;
  }
  const t = sessionData.tasks[selectedTaskId];
  const det = selectedTaskDetail || {};
  const tr = det.trace || {};

  let html = `
    <div class="detail-section">
      <h4>${esc(t.task_id)} · ${esc(t.title)}</h4>
      <div>状态：<span class="badge st-${esc(t.state)}" style="color:#fff">${esc(t.state)}</span> ${t.decision_kind ? `(${esc(t.decision_kind)})` : ""}</div>
      <div style="margin-top:4px;color:var(--text-muted)">工种：${esc(t.role)} | 阶段：${esc(t.dev_stage)} | 失败次数：${t.attempts_failed} | 轮次 Epoch：${t.attempt_epoch}</div>
      <div style="margin-top:4px;color:var(--text-muted)">CPM：[ES ${t.es} .. EF ${t.ef}] · Slack=${t.slack}h · 延期=${t.delay_hours}h · 等待=${t.resource_wait_hours}h</div>
      <div style="margin-top:4px">独占写白名单：<code>${esc((t.writable_paths || []).join(", ") || "只读")}</code></div>
    </div>

    <div class="detail-section">
      <h4>全链血缘追溯 (Task → GDD → ST/EVT/IN → Canon/ADR → Git)</h4>
      <div>需求卡：<code>${esc(tr.req_id || "-")}</code> | 模块：<code>${esc(tr.gdd_module?.gdd_id || "-")}</code> ${esc(tr.gdd_module?.title || "")}</div>
      <div>状态/事件：<code>${esc([...(tr.state_ids || []), ...(tr.event_ids || [])].join(", ") || "-")}</code></div>
      <div>输入动作：<code>${esc((tr.input_ids || []).join(", ") || "-")}</code></div>
      <div>Canon / ADR：<code>${esc([...(tr.canon_refs || []), ...(tr.adr_refs || [])].join(", ") || "-")}</code></div>
      <div>产出版本 / 提交：<code>${esc(tr.produced_in_version || "-")}</code> / <code>${esc(tr.last_commit || "-")}</code></div>
    </div>

    <div class="detail-section">
      <h4>产出文件清单 (${(t.artifacts || []).length})</h4>
      ${(t.artifacts || []).map((a) => `<div>• <code>${esc(a.path)}</code> (${esc((a.sha256 || "").slice(0, 10))})</div>`).join("") || `<div style="color:var(--text-muted)">尚未合入产出</div>`}
    </div>`;

  if (det.latest_report) {
    html += `<div class="detail-section"><h4>最新 L1/L2 验收报告</h4><pre class="code-box">${esc(det.latest_report)}</pre></div>`;
  }
  if (det.latest_context) {
    html += `<div class="detail-section"><h4>最小上下文快照 (task_context.json)</h4><pre class="code-box">${esc(det.latest_context)}</pre></div>`;
  }
  if (det.scenarios && det.scenarios.length) {
    html += `<div class="detail-section"><h4>独立验收场景 (只读)</h4><pre class="code-box">${esc(JSON.stringify(det.scenarios, null, 2))}</pre></div>`;
  }

  html += `
    <div class="detail-section">
      <h4>演练故障注入（Mock 测试用）</h4>
      <div class="btn-row">
        <button class="btn btn-secondary btn-sm" onclick="injectFault('${esc(t.task_id)}',['fail_once'])">注入失败 1 次</button>
        <button class="btn btn-danger btn-sm" onclick="injectFault('${esc(t.task_id)}',['write_violation'])">注入越界写入</button>
        <button class="btn btn-purple btn-sm" onclick="injectFault('${esc(t.task_id)}',['req_defect_valid'])">注入需求缺陷</button>
        <button class="btn btn-ghost btn-sm" onclick="injectFault('${esc(t.task_id)}',[])">清除注入</button>
      </div>
    </div>`;

  box.innerHTML = html;
}

async function selectTask(taskId) {
  selectedTaskId = taskId;
  renderDag();
  if (currentProjectId && taskId) {
    try {
      selectedTaskDetail = await apiGet(
        `/api/projects/${encodeURIComponent(currentProjectId)}/tasks/${encodeURIComponent(taskId)}`
      );
    } catch {
      selectedTaskDetail = null;
    }
    renderTaskDetail();
  }
}

window.submitG1 = async () => {
  try {
    const payload = {
      tech_profile: {
        ...sessionData.tech_profile,
        platform: document.getElementById("g1-platform")?.value || "web",
        language: document.getElementById("g1-lang")?.value || "typescript",
        render: document.getElementById("g1-render")?.value || "canvas2d",
      },
    };
    await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/gates/G1/decision`, {
      option: "confirm",
      payload,
    });
    showToast("G1 技术定型已确认，调度启动！");
    await refreshSession();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.submitG2 = async (taskId, option) => {
  try {
    const note = document.getElementById(`gate-note-${taskId}`)?.value || "";
    await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/gates/G2/decision`, {
      option,
      target: taskId,
      note,
    });
    showToast(`已提交 ${taskId} 门禁裁决: ${option}`);
    await refreshSession();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.submitG3 = async (taskId, option) => {
  try {
    const note = document.getElementById(`gate-note-${taskId}`)?.value || "";
    await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/gates/G3/decision`, {
      option,
      target: taskId,
      note,
      payload: { trigger_source: "playtest_feedback", problem_statement: note || "L2 发现需求问题", requested_delta: note || "请调整需求条款" },
    });
    showToast(`G3 决策已执行: ${option}`);
    await refreshSession();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.submitG4 = async (option) => {
  try {
    const raw = document.getElementById("g4-reject-ids")?.value || "";
    const ids = raw.split(",").map((s) => s.trim()).filter(Boolean);
    await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/gates/G4/decision`, {
      option,
      payload: option === "reject_tasks" ? { task_ids: ids } : {},
    });
    showToast(option === "sign_release" ? "版本已签字封版并打 Git 标签！" : "已退回指定任务及其下游闭包");
    await refreshSession();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.injectFault = async (taskId, faults) => {
  try {
    await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/demo/inject`, {
      task_id: taskId,
      faults,
    });
    showToast(faults.length ? `已为 ${taskId} 注入故障: ${faults.join(",")}` : `已清除 ${taskId} 故障注入`);
    await refreshSession();
  } catch (err) {
    showToast(err.message, "error");
  }
};

function bindStaticEvents() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-tab");
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.toggle("active", c.id === `tab-${target}`));
      if (target === "dag") renderDag();
    });
  });

  document.querySelectorAll(".side-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-side");
      document.querySelectorAll(".side-tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".side-content").forEach((c) => c.classList.toggle("active", c.id === `side-${target}`));
    });
  });

  document.querySelectorAll(".edge-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      edgeMode = btn.getAttribute("data-edge-mode");
      document.querySelectorAll(".edge-btn").forEach((b) => b.classList.toggle("active", b === btn));
      renderDag();
    });
  });

  document.getElementById("btn-warnings").addEventListener("click", () => {
    document.getElementById("warnings-drawer").classList.toggle("hidden");
  });

  document.getElementById("project-select").addEventListener("change", async (e) => {
    currentProjectId = e.target.value;
    await refreshSession();
    connectSSE(currentProjectId);
  });

  document.getElementById("btn-load-fixture").addEventListener("click", async () => {
    try {
      const handoffDir = document.getElementById("fixture-select").value;
      const res = await apiPost("/api/projects/load", { handoff_dir: handoffDir });
      currentProjectId = res.session.project_id;
      showToast(`加载成功 (${res.load_mode})：${res.session.spec_version}`);
      await refreshProjectsList();
      await refreshSession();
      connectSSE(currentProjectId);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-reset-v1").addEventListener("click", async () => {
    try {
      const v1 = fixturesMeta.find((f) => f.spec_version === "v1.0.0") || fixturesMeta[0];
      const res = await apiPost("/api/projects/load", { handoff_dir: v1.path, force_new_project: true });
      currentProjectId = res.session.project_id;
      showToast("已全新初始化 v1.0.0");
      await refreshProjectsList();
      await refreshSession();
      connectSSE(currentProjectId);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-auto-run").addEventListener("click", async () => {
    try {
      await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/control/auto_start`);
      showToast("已开启后台自动波次调度");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btn-run-wave").addEventListener("click", async () => {
    try {
      const res = await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/wave`);
      showToast(res.dispatched.length ? `推进波次：${res.dispatched.join(", ")}` : "当前波次无可派发任务");
      await refreshSession();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  ["pause", "cancel_running", "step"].forEach((act) => {
    const btnId = act === "pause" ? "btn-pause" : act === "cancel_running" ? "btn-cancel-running" : "btn-step";
    document.getElementById(btnId).addEventListener("click", async () => {
      try {
        await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/control/${act}`);
        showToast(`控制指令已执行：${act}`);
        await refreshSession();
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });

  document.getElementById("btn-quick-g1").addEventListener("click", () => {
    document.querySelector('[data-side="gates"]').click();
  });
  document.getElementById("btn-quick-g4").addEventListener("click", () => {
    document.querySelector('[data-side="gates"]').click();
  });

  document.getElementById("modal-close").addEventListener("click", () => {
    document.getElementById("modal-backdrop").classList.add("hidden");
  });

  document.getElementById("btn-open-cr-modal").addEventListener("click", () => {
    const body = document.getElementById("modal-body");
    document.getElementById("modal-title").textContent = "生成变更回流单 (change_request.yaml)";
    body.innerHTML = `
      <div class="form-row"><label>触发来源</label>
        <select id="cr-source">
          <option value="playtest_feedback">playtest_feedback</option>
          <option value="visual_first_frame">visual_first_frame</option>
          <option value="scope_cut">scope_cut</option>
          <option value="new_chapter">new_chapter</option>
        </select>
      </div>
      <div class="form-row"><label>受影响需求 ID (逗号分隔)</label><input id="cr-reqs" value="SYS-002, AUD-002, NAR-002" /></div>
      <div class="form-row"><label>问题描述</label><textarea id="cr-prob" rows="2">试玩显示疑心值 60 提示偏晚。</textarea></div>
      <div class="form-row"><label>请求变更增量</label><textarea id="cr-delta" rows="2">将警示与紧绷音轨阈值从 60 下调至 50。</textarea></div>
      <div class="btn-row"><button id="cr-submit" class="btn btn-purple">导出 change_request.yaml</button></div>`;
    document.getElementById("modal-backdrop").classList.remove("hidden");
    document.getElementById("cr-submit").addEventListener("click", async () => {
      try {
        const reqs = document.getElementById("cr-reqs").value.split(",").map((s) => s.trim()).filter(Boolean);
        const res = await apiPost(`/api/projects/${encodeURIComponent(currentProjectId)}/change-requests`, {
          trigger_source: document.getElementById("cr-source").value,
          impacted_req_ids: reqs,
          problem_statement: document.getElementById("cr-prob").value,
          requested_delta: document.getElementById("cr-delta").value,
        });
        document.getElementById("modal-backdrop").classList.add("hidden");
        showToast(`已生成变更单: ${res.change_request.request_id}`);
        await refreshSession();
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });
}

bootstrap();
