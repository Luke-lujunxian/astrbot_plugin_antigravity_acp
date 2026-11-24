const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginView;
const SVG_NS = "http://www.w3.org/2000/svg";
let state, pending = false, disposed = false, timer, copyTimer, revision = 0, cachedModels = [], modelSignature = "", effortSignature = "", providerSignature = "";
let themeMode = "auto", nextManualTheme = "dark";
let previousInstallError, monitorSignature, copyAttempt = 0, toastTimer, pollFailures = 0, pollPending = false, suspended = false, refreshEpoch = 0;
const bannerErrors = {action: "", poll: ""};
const buttonFeedback = new WeakMap(), listSignatures = new WeakMap();
const themeKey = "agy-acp.setup.theme";
try { const saved = window.localStorage?.getItem(themeKey); if (["auto","light","dark"].includes(saved)) themeMode = saved; } catch {}
let monitorTimer, monitorPending = false, monitorReady = false, monitorSnapshot, reportDiagSignature = "";
const expandedMonitorSections = new Set();

const activeLogin = (login) => Boolean(login?.busy);
const stages = {
  discovery: "查找 CLI", isolation: "检查隔离目录", authentication: "检查认证",
  initialize: "ACP 握手", "session/new": "验证登录", model_catalog: "读取模型目录",
  model_selection: "检查模型档位", complete: "检查通过",
};
const loginStates = {
  idle: "等待登录", starting: "正在启动", waiting: "等待授权",
  verifying: "正在验证", complete: "登录已验证", failed: "登录未完成", cancelled: "已取消",
};
const rebuildReasonLabels = {
  no_identity: "无会话标识", abort: "请求中止", previous_error: "上轮异常",
  upstream_compaction_detected: "上游疑似压缩", process_dead: "进程退出",
  idle_expired: "空闲超时", pool_evicted: "池淘汰", runtime_restart: "运行时重启",
  cold_start: "冷启动", system_changed: "系统提示变更", model_changed: "模型变更",
  effort_changed: "思考强度变更", tool_hash_changed: "工具变更", tool_ledger_limit: "工具账本上限",
  history_rewrite: "历史重写", history_host_trim: "历史裁剪", history_append_gap: "历史断层",
  unknown: "未知原因",
};
const toolsModeLabels = {chat: "纯聊天", inherit: "跟随全局", tools: "工具模式", invalid: "无效配置"};
const turnStatusLabels = {ok: "成功", error: "失败", cancelled: "取消", short_circuited: "预检/熔断拦截", unknown: "未知"};
const transportLabels = {loopback_hmac: "本机认证连接", unix_socket: "Unix Socket", unsupported: "当前平台不支持"};
const supervisionLabels = {windows_job: "Windows Job Object", windows_taskkill_fallback: "taskkill 回退", posix_process_group: "独立进程组"};
const minimalToolsLabels = {inactive: "未启用精简", flag_available_unverified: "支持参数（待验收）", unsupported: "CLI 不支持"};
const faultLabels = {
  RATE_LIMIT: "请求受限", QUOTA: "额度不足", AUTH: "认证失败", AUTH_BRIDGE: "认证桥接失败",
  TIMEOUT: "请求超时", NETWORK: "网络异常", PROXY: "代理异常", PROXY_AUTH: "代理认证失败",
  TLS: "证书/TLS 异常", TRANSPORT: "传输中断", BACKPRESSURE: "并发过载", BUSY: "实例忙碌",
  CANCELLED: "已取消", EMPTY: "空响应", UPSTREAM: "上游异常", PROTOCOL: "协议异常",
};

function formatFaultBrief(code) {
  const label = faultLabels[code];
  return label ? `${label} (${code})` : code;
}

function applyTheme() {
  const root = document.documentElement;
  if (!root) return;
  // 手动模式写入 data-theme-mode；data-theme 保留给宿主主题同步
  root.dataset.themeMode = themeMode;
  if (themeMode === "light" || themeMode === "dark") {
    nextManualTheme = themeMode === "dark" ? "light" : "dark";
  }
  const labels = {auto: "主题：自动", light: "主题：浅色", dark: "主题：深色"};
  const btn = $("theme-toggle");
  if (btn) btn.textContent = labels[themeMode];
}

function cycleTheme() {
  themeMode = themeMode === "auto" ? nextManualTheme : "auto";
  try { window.localStorage?.setItem(themeKey, themeMode); } catch {}
  applyTheme();
}

function badge(id, text, kind = "") {
  const el = $(id);
  el.textContent = text;
  el.dataset.state = kind;
}

function setConnection(text, kind = "busy") {
  const node = $("connection");
  node.textContent = text;
  node.dataset.state = kind;
}

function showError(message = "", source = "action") {
  bannerErrors[source] = message;
  const visible = bannerErrors.action || bannerErrors.poll;
  $("error").textContent = visible;
  $("error").hidden = !visible;
}

function toast(message, kind) {
  clearTimeout(toastTimer);
  const status = $("copy-status");
  status.dataset.state = kind;
  status.textContent = message;
  toastTimer = setTimeout(() => { status.textContent = ""; }, 3000);
}

function showCopyFeedback(button, copied) {
  const previous = buttonFeedback.get(button);
  const label = previous?.label ?? button.textContent;
  clearTimeout(previous?.timer);
  button.textContent = copied ? "已复制 ✓" : "请手动复制";
  const timer = setTimeout(() => {
    button.textContent = label;
    buttonFeedback.delete(button);
  }, 2000);
  buttonFeedback.set(button, {label, timer});
  toast(copied ? "已复制" : "已选中，请按 Ctrl+C / ⌘C 复制", copied ? "ok" : "warn");
}

async function copy(input, button) {
  const text = input.value;
  if (!text) return;
  const attempt = ++copyAttempt;
  let clipboardWrite;
  try {
    if (navigator.clipboard?.writeText) {
      clipboardWrite = Promise.resolve(navigator.clipboard.writeText(text)).then(() => true, () => false);
    }
  } catch { /* 访问或调用 Clipboard API 时也可能同步抛错。 */ }

  // 等待 Clipboard Promise 会错过用户手势，须在本次点击中完成同步兜底。
  const field = document.createElement("textarea");
  let copied = false;
  try {
    field.value = text;
    field.readOnly = true;
    field.className = "copy-buffer";
    document.body.appendChild(field);
    field.focus({preventScroll: true});
    field.select();
    copied = document.execCommand("copy");
  } catch {
    // 浏览器或宿主策略可能禁用同步复制。
  } finally {
    field.remove?.();
    button?.focus?.({preventScroll: true});
  }

  if (!copied && clipboardWrite) copied = await clipboardWrite;
  if (disposed || attempt !== copyAttempt || input.value !== text) return;
  if (!copied) {
    input.focus();
    input.select();
  }
  showCopyFeedback(button, copied);
}

function openAuthorization() {
  const url = $("auth-url").value;
  if (!url) return;
  try {
    if (window.open(url, "_blank", "noopener")) return;
  } catch { /* 沙箱可能抛错，也可能返回 null。 */ }
  toast("浏览器拦截了新窗口，请用复制链接", "warn");
}

function setInputValue(id, value) {
  const input = $(id);
  const text = value ?? "";
  if (input.value !== text) input.value = text;
}

function renderList(id, rows, createRow) {
  const list = $(id);
  const signature = JSON.stringify(rows);
  if (listSignatures.get(list) === signature) return;
  list.replaceChildren(...rows.map(createRow));
  listSignatures.set(list, signature);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgNode(tag, attrs = {}, text) {
  const node = typeof document.createElementNS === "function"
    ? document.createElementNS(SVG_NS, tag)
    : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

const monitorCount = value => Number.isFinite(value) ? value.toLocaleString() : "未知";
const monitorPercent = value => Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "未知";

function monitorTime(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleString() : "未报告";
}

function monitorShortTime(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return "未报告";
  try {
    return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
  } catch {
    return date.toLocaleTimeString();
  }
}

function monitorAgo(value) {
  const timestamp = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(timestamp)) return "时间未报告";
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  return `${Math.floor(seconds / 3600)} 小时前`;
}

function formatDuration(ms) {
  if (!Number.isFinite(ms)) return "未知";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
}

function kvItem(label, value) {
  const item = el("div", "kv-item");
  item.append(el("dt", "", label), el("dd", "", value));
  return item;
}

function createLayerDetails(storeKey, kindClass, title, badgeText) {
  const details = el("details", `monitor-layer ${kindClass}`);
  if (expandedMonitorSections.has(storeKey)) details.open = true;
  details.addEventListener("toggle", () => {
    if (details.open) expandedMonitorSections.add(storeKey);
    else expandedMonitorSections.delete(storeKey);
  });
  const summary = el("summary", "");
  summary.append(el("span", "", title));
  if (badgeText) summary.append(el("span", "layer-badge", badgeText));
  details.append(summary);
  return details;
}

const RING_R = 15;
const RING_C = 2 * Math.PI * RING_R;

function ringSvg(rate, strokeColor) {
  const svg = svgNode("svg", {class: "gauge-svg", viewBox: "0 0 40 40", "aria-hidden": "true"});
  const valid = Number.isFinite(rate);
  svg.append(svgNode("circle", {
    cx: 20, cy: 20, r: RING_R, fill: "none", stroke: "var(--chart-track)", "stroke-width": 4.5,
    ...(valid ? {} : {"stroke-dasharray": "3 3"}),
  }));
  if (valid) {
    const clamped = Math.max(0, Math.min(1, rate));
    svg.append(svgNode("circle", {
      cx: 20, cy: 20, r: RING_R, fill: "none", stroke: strokeColor, "stroke-width": 4.5, "stroke-linecap": "round",
      "stroke-dasharray": `${(clamped * RING_C).toFixed(2)} ${RING_C.toFixed(2)}`,
      transform: "rotate(-90 20 20)",
    }));
  }
  return svg;
}

// 环形占比卡片：复用率 / 缓存命中
function renderRingTile(label, rate, subText, emptyLabel, strokeColor) {
  const tile = el("div", "kpi");
  const valid = Number.isFinite(rate);
  tile.append(el("span", "kpi-label", label));
  const wrap = el("div", "ring-wrap");
  wrap.append(ringSvg(rate, strokeColor), el("span", "ring-value", valid ? monitorPercent(rate) : "—"));
  tile.append(wrap);
  const note = valid ? subText : emptyLabel;
  if (note) tile.append(el("span", "kpi-sub", note));
  return tile;
}

// 会话池：分段占用条
function renderPoolTile(pool) {
  const tile = el("div", "kpi");
  tile.append(el("span", "kpi-label", "活动会话"));
  if (!pool) {
    tile.append(el("span", "kpi-value", "未知"));
    return tile;
  }
  tile.append(el("span", "kpi-value", `${monitorCount(pool.active_sessions)} / ${monitorCount(pool.max_sessions)}`));
  if (Number.isFinite(pool.active_sessions) && Number.isFinite(pool.max_sessions) && pool.max_sessions > 0) {
    const segments = Math.min(pool.max_sessions, 12);
    const ratio = Math.min(1, pool.active_sessions / pool.max_sessions);
    let filled = Math.round(ratio * segments);
    if (pool.active_sessions > 0) filled = Math.max(1, filled);
    const gap = 2;
    const width = 120;
    const segW = (width - gap * (segments - 1)) / segments;
    const svg = svgNode("svg", {
      class: "seg-svg", viewBox: `0 0 ${width} 8`, preserveAspectRatio: "none", "aria-hidden": "true",
    });
    for (let i = 0; i < segments; i++) {
      svg.append(svgNode("rect", {
        x: (i * (segW + gap)).toFixed(2), y: 0, width: segW.toFixed(2), height: 8, rx: 2,
        fill: i < filled ? (ratio >= 0.9 ? "var(--warn)" : "var(--accent)") : "var(--chart-track)",
      }));
    }
    tile.append(svg);
  }
  tile.append(el("span", "kpi-sub", `存活进程 ${monitorCount(pool.live_processes)} · 续轮 ${monitorCount(pool.active_tool_turns)}`));
  return tile;
}

// 近 24h 请求：成功 / 失败环形图
function renderRequestsTile(summary) {
  const tile = el("div", "kpi");
  tile.append(el("span", "kpi-label", "近 24h 请求"));
  const total = Number.isFinite(summary?.total_turns) ? summary.total_turns : 0;
  const success = Number.isFinite(summary?.success_turns) ? summary.success_turns : 0;
  const failed = Number.isFinite(summary?.failed_turns) ? summary.failed_turns : 0;
  const wrap = el("div", "ring-wrap");
  const svg = svgNode("svg", {class: "donut-svg", viewBox: "0 0 40 40", "aria-hidden": "true"});
  svg.append(svgNode("circle", {cx: 20, cy: 20, r: RING_R, fill: "none", stroke: "var(--chart-track)", "stroke-width": 4.5}));
  if (total > 0) {
    let cursor = 0;
    [[success, "var(--chart-cached)"], [failed, "var(--error)"]].forEach(([count, color]) => {
      if (count <= 0) return;
      const len = Math.min(count / total, 1) * RING_C;
      svg.append(svgNode("circle", {
        cx: 20, cy: 20, r: RING_R, fill: "none", stroke: color, "stroke-width": 4.5,
        "stroke-dasharray": `${len.toFixed(2)} ${(RING_C - len).toFixed(2)}`,
        "stroke-dashoffset": (-cursor).toFixed(2),
        transform: "rotate(-90 20 20)",
      }));
      cursor += len;
    });
  }
  wrap.append(svg, el("span", "ring-value", summary ? monitorCount(total) : "—"));
  tile.append(wrap);
  if (summary && total > 0) {
    const split = el("div", "kpi-split");
    split.append(el("span", "kpi-sub", "成功 / 失败"), el("span", failed > 0 ? "kpi-strong tone-warn" : "kpi-strong", `${monitorCount(success)} / ${monitorCount(failed)}`));
    tile.append(split);
    const sent = summary.request_sent_turns;
    if (Number.isFinite(sent) && sent !== total) tile.append(el("span", "kpi-sub", `实际发送 ${monitorCount(sent)}`));
  } else {
    tile.append(el("span", "kpi-sub", summary ? "暂无样本" : "未知"));
  }
  return tile;
}

function renderContextPanel(context, row) {
  const panel = el("div", "panel monitor-context");
  const head = el("div", "panel-head");
  head.append(el("span", "panel-title", "上下文占用"));
  const valid = Number.isFinite(context.context_used) && Number.isFinite(context.context_window_size)
    && context.context_window_size > 0 && context.context_used >= 0 && Boolean(context.observed_at);
  if (valid) {
    const ratio = context.context_used / context.context_window_size;
    head.append(el("span", "panel-meta monitor-context-val", `${monitorCount(context.context_used)} / ${monitorCount(context.context_window_size)} Token · ${monitorPercent(ratio)}`));
    const progress = el("progress", "monitor-progress");
    progress.max = context.context_window_size;
    progress.value = context.context_used;
    if (ratio >= 0.9) progress.dataset.level = "high";
    else if (ratio >= 0.7) progress.dataset.level = "warn";
    progress.setAttribute("aria-label", "上下文占用");
    panel.append(head, progress, el("p", "small", `${context.model || row.model} · 采样于 ${monitorTime(context.observed_at)}`));
  } else {
    head.append(el("span", "panel-meta monitor-context-val", "上游未报告"));
    panel.append(head);
  }
  return panel;
}

function renderTokenChart(summary) {
  const reported = summary?.reported_usage_turns || 0;
  const missingCache = summary?.missing_cache_field_turns || 0;
  if (reported <= 0) return null;

  const other = Number.isFinite(summary.total_input_other) ? summary.total_input_other : 0;
  const hasCached = reported > missingCache && Number.isFinite(summary.total_input_cached);
  const cached = hasCached ? summary.total_input_cached : 0;
  const output = Number.isFinite(summary.total_output) ? summary.total_output : 0;
  const total = other + cached + output;
  if (total <= 0) return null;

  const block = el("div", "panel chart-block");
  const head = el("div", "panel-head");
  head.append(el("span", "panel-title", "24h Token 构成"), el("span", "panel-meta", `已上报 ${reported} 轮`));
  block.append(head);

  const width = 300;
  const parts = [
    {key: "input", label: "非缓存输入", value: other, color: "var(--chart-input)"},
    ...(hasCached ? [{key: "cached", label: "缓存读取", value: cached, color: "var(--chart-cached)"}] : []),
    {key: "output", label: "输出", value: output, color: "var(--chart-output)"},
  ];
  const svg = svgNode("svg", {
    class: "token-stack-svg", role: "img", viewBox: `0 0 ${width} 14`, preserveAspectRatio: "none",
    "aria-label": `24h Token 构成：${parts.map(p => `${p.label} ${monitorCount(p.value)}`).join("，")}`,
  });
  svg.append(svgNode("title", {}, parts.map(p => `${p.label} ${monitorCount(p.value)}`).join(" · ")));

  let cursor = 0;
  const active = parts.filter(p => p.value > 0);
  active.forEach((part, index) => {
    const remaining = width - cursor;
    const w = index === active.length - 1
      ? Math.max(0, remaining)
      : Math.min(remaining, Math.max(2, Math.round((part.value / total) * width)));
    if (w > 0) {
      svg.append(svgNode("rect", {x: cursor, y: 0, width: w, height: 14, fill: part.color}));
      cursor += w;
    }
  });
  block.append(svg);

  const legend = el("div", "chart-legend");
  const addLegend = (dotClass, text) => {
    const item = el("span", "legend-item");
    item.append(el("span", `legend-dot ${dotClass}`), el("span", "", text));
    legend.append(item);
  };
  addLegend("input", `非缓存输入 ${monitorCount(other)} (${((other / total) * 100).toFixed(1)}%)`);
  addLegend("cached", hasCached ? `缓存读取 ${monitorCount(cached)} (${((cached / total) * 100).toFixed(1)}%)` : "缓存读取 上游未报告");
  addLegend("output", `输出 ${monitorCount(output)} (${((output / total) * 100).toFixed(1)}%)`);
  block.append(legend);
  return block;
}

function renderLatencyChart(recent) {
  const timed = recent.slice().reverse().filter(turn => Number.isFinite(turn.elapsed_ms));
  if (!timed.length) return null;
  const block = el("div", "panel chart-block");
  const head = el("div", "panel-head");
  const maxMs = Math.max(...timed.map(t => t.elapsed_ms), 1);
  const avgMs = Math.round(timed.reduce((sum, t) => sum + t.elapsed_ms, 0) / timed.length);
  const latestMs = timed[timed.length - 1].elapsed_ms;
  head.append(
    el("span", "panel-title", `最近请求耗时（近 ${timed.length} 轮）`),
    el("span", "panel-meta", `最新 ${formatDuration(latestMs)} · 均值 ${formatDuration(avgMs)}`),
  );
  block.append(head);

  const width = 600;
  const baseY = 60;
  const maxBarH = 52;
  const svg = svgNode("svg", {
    class: "latency-svg", role: "img", viewBox: `0 0 ${width} 64`, preserveAspectRatio: "none",
    "aria-label": `最近 ${timed.length} 轮请求耗时分布，峰值 ${formatDuration(maxMs)}，均值 ${formatDuration(avgMs)}`,
  });
  const avgY = baseY - Math.max(4, Math.round((avgMs / maxMs) * maxBarH));
  svg.append(
    svgNode("line", {x1: 0, y1: baseY, x2: width, y2: baseY, stroke: "var(--border-strong)", "stroke-width": 1}),
  );

  const slot = width / Math.max(timed.length, 8);
  const bw = Math.min(28, Math.max(8, slot * 0.56));
  timed.forEach((turn, idx) => {
    const barH = Math.max(4, Math.round((turn.elapsed_ms / maxMs) * maxBarH));
    const x = (idx * slot + (slot - bw) / 2).toFixed(1);
    const y = (baseY - barH).toFixed(1);
    const color = turn.status === "ok" ? "var(--chart-input)" : turn.status === "cancelled" ? "var(--warn)" : "var(--error)";
    const rect = svgNode("rect", {class: "latency-bar", x, y, width: bw.toFixed(1), height: barH, rx: 3, fill: color});
    const statusText = turnStatusLabels[turn.status] || "未知";
    rect.append(svgNode("title", {}, `${formatDuration(turn.elapsed_ms)} · ${statusText}${turn.error_code ? ` (${turn.error_code})` : ""} · ${monitorAgo(turn.recorded_at)}`));
    svg.append(rect);
  });
  // 均值参考线
  svg.append(svgNode("line", {x1: 0, y1: avgY, x2: width, y2: avgY, stroke: "var(--muted)", "stroke-dasharray": "6 5", "stroke-width": 1, opacity: 0.7}));
  block.append(svg);

  const axis = el("div", "chart-axis");
  axis.append(el("span", "", "较早"), el("span", "", `峰值 ${formatDuration(maxMs)}`), el("span", "", "最新"));
  block.append(axis);
  return block;
}

// 会话重建原因：横向条形图
function renderReasonBars(reasons) {
  const block = el("div", "panel chart-block");
  const head = el("div", "panel-head");
  const total = reasons.reduce((sum, [, count]) => sum + (Number.isFinite(count) ? count : 0), 0);
  head.append(el("span", "panel-title", "会话重建原因 (24h)"), el("span", "panel-meta", `合计 ${monitorCount(total)} 次`));
  block.append(head);
  const top = reasons.slice(0, 8);
  const max = Math.max(...top.map(([, count]) => (Number.isFinite(count) ? count : 0)), 1);
  const list = el("div", "reason-bars");
  top.forEach(([reason, count]) => {
    const row = el("div", "reason-row");
    row.append(el("span", "reason-label", `${rebuildReasonLabels[reason] || reason} × ${monitorCount(count)}`));
    const svg = svgNode("svg", {class: "reason-svg", viewBox: "0 0 300 6", preserveAspectRatio: "none", "aria-hidden": "true"});
    svg.append(
      svgNode("rect", {x: 0, y: 0, width: 300, height: 6, rx: 3, fill: "var(--chart-track)"}),
      svgNode("rect", {x: 0, y: 0, width: Math.max(8, ((Number.isFinite(count) ? count : 0) / max) * 300).toFixed(1), height: 6, rx: 3, fill: "var(--accent)"}),
    );
    row.append(svg);
    list.append(row);
  });
  block.append(list);
  return block;
}

function renderHistory(recent, row) {
  const block = el("div", "panel chart-block");
  const head = el("div", "panel-head");
  head.append(el("span", "panel-title", "历史请求记录"), el("span", "panel-meta", `近 ${recent.length} 轮`));
  const list = el("ul", "turn-list");
  recent.forEach(turn => {
    const item = el("li", "turn-row");
    const top = el("div", "turn-row-top");
    const statusLabel = turnStatusLabels[turn.status] || "未知";
    const statusClass = turn.status === "ok" ? "tone-ok" : turn.status === "cancelled" ? "tone-warn" : "tone-error";
    top.append(
      el("span", statusClass, `${statusLabel}${turn.error_code ? ` · ${turn.error_code}` : ""}`),
      el("span", "small", `${turn.reused ? "复用" : "新建"} · ${formatDuration(turn.elapsed_ms)} · ${monitorAgo(turn.recorded_at)}`),
    );
    const meta = el("div", "turn-row-meta");
    const usageText = turn.usage_status === "reported"
      ? `入 ${monitorCount(turn.input_other)} · 缓存 ${turn.cache_fields_present?.cachedReadTokens ? monitorCount(turn.input_cached) : "未报告"} · 出 ${monitorCount(turn.output)}`
      : turn.usage_status === "not_sent" ? "未发送请求" : "用量未报告";
    meta.append(el("span", "", turn.model || row.model || "未知模型"), el("span", "", usageText));
    item.append(top, meta);
    list.append(item);
  });
  block.append(head, list);
  return block;
}

function renderDiagnostics(row, recent, pool, idKey) {
  const diagLayer = createLayerDetails(`${idKey}::diag`, "monitor-diag", "诊断");
  const diagBody = el("div", "monitor-layer-body");

  const providerGroup = el("div", "diag-group");
  providerGroup.append(el("h4", "", "CLI 与 Provider 状态"));
  const pKv = el("dl", "kv-list");
  pKv.append(
    kvItem("provider_id", row.provider_id || "未知"),
    kvItem("runtime_state", `${row.runtime_state || "未知"} (${row.enabled ? "enabled" : "disabled"})`),
    kvItem("tools_mode → effective", `${row.tools_mode || "inherit"} → ${row.effective_mode || "未知"} (tools_enabled=${String(row.tools_enabled)})`),
    kvItem("pool", pool ? `active=${pool.active_sessions}/${pool.max_sessions}, live=${pool.live_processes}, tool_turns=${pool.active_tool_turns}` : "未初始化（无运行时）"),
  );
  if (state?.report) {
    const rep = state.report;
    pKv.append(
      kvItem("CLI 状态与版本", `${rep.status || "未知"} (${stages[rep.stage] || rep.stage || "未知"}) · ${rep.cli_version || "未探测"}`),
      kvItem("进程托管 / 工具桥", `${supervisionLabels[rep.process_supervision] || rep.process_supervision || "未知"} · ${transportLabels[rep.tool_bridge_transport] || rep.tool_bridge_transport || "未知"}`),
    );
  }
  providerGroup.append(pKv);
  diagBody.append(providerGroup);

  const c429Turns = recent.filter(turn => turn.content_429_candidate);
  if (c429Turns.length) {
    const group = el("div", "diag-group");
    group.append(el("h4", "", `429 候选 (${c429Turns.length})`));
    const list = el("ul", "monitor-faults");
    c429Turns.forEach(turn => {
      const c = turn.content_429_candidate;
      const item = el("li", "");
      item.append(
        el("code", "", `${turn.error_code || "429"} · hash=${c.system_hash8 || "未知"} · sys=${monitorCount(c.system_bytes)}B · attempt=${c.attempt ?? "未知"} · output=${c.has_output ? "是" : "否"}`),
        el("span", "small", monitorTime(turn.recorded_at)),
      );
      list.append(item);
    });
    group.append(list);
    diagBody.append(group);
  }

  const faultTurns = recent.filter(turn => turn.error_code || turn.status !== "ok");
  if (faultTurns.length) {
    const group = el("div", "diag-group");
    group.append(el("h4", "", `异常记录 (${faultTurns.length})`));
    const list = el("ul", "monitor-faults");
    faultTurns.forEach(turn => {
      const item = el("li", "");
      const reasonsText = Array.isArray(turn.rebuild_reasons) && turn.rebuild_reasons.length ? turn.rebuild_reasons.join(",") : "none";
      item.append(
        el("code", "", `${turn.status}${turn.error_code ? `/${turn.error_code}` : ""} · ${formatDuration(turn.elapsed_ms)} · prompt=${monitorCount(turn.prompt_bytes)}B replay=${monitorCount(turn.replay_bytes)}B omit=${monitorCount(turn.omitted_messages)} · reasons=${reasonsText}`),
        el("span", "small", monitorTime(turn.recorded_at)),
      );
      list.append(item);
    });
    group.append(list);
    diagBody.append(group);
  }

  diagLayer.append(diagBody);
  return diagLayer;
}

function renderRouting(routing) {
  const panel = $("routing-summary");
  const known = value => typeof value === "string" && value ? value : "未报告";
  const fields = routing && typeof routing === "object" ? [
    ["配置主模型", known(routing.configured_primary_id)],
    ["实际解析主模型", known(routing.resolved_primary_id)],
    ["最近服务观测", known(routing.last_observed_provider_id)],
    ["观测时间", routing.last_observed_at ? monitorTime(routing.last_observed_at) : "未报告"],
    ["显式备用模型", Array.isArray(routing.explicit_fallback_ids) ? routing.explicit_fallback_ids.join("、") || "无" : "未报告"],
  ] : [["路由状态", "未报告"]];
  const sig = JSON.stringify(fields);
  if (listSignatures.get(panel) === sig) return;
  panel.replaceChildren(...fields.map(([label, value]) => kvItem(label, value)));
  listSignatures.set(panel, sig);
}
function renderFailureEvents(data) {
  const panel = $("persistent-failures");
  const status = $("failure-storage");
  if (data.schema_version !== 2 || !Array.isArray(data.failure_events)) {
    status.textContent = "持久失败诊断未报告";
    panel.replaceChildren();
    return;
  }
  status.textContent = data.failure_retention?.storage_state === "available" ? "持久失败诊断可用" : "持久存储状态未确认";
  const rows = data.failure_events.slice(0, 50);
  panel.replaceChildren(...rows.map(event => {
    const item = el("div", "provider");
    item.append(el("strong", "", formatFaultBrief(event.error_code || "UNKNOWN")),
      el("p", "small", [monitorTime(event.recorded_at), event.provider_tag || "未知实例", formatDuration(event.elapsed_ms)].join(" · ")));
    return item;
  }));
  if (!rows.length) panel.append(el("p", "small", "暂无失败记录"));
}
function renderMonitor(data) {
  if (![1, 2].includes(data.schema_version) || !Array.isArray(data.instances)) throw new Error("monitor schema");
  const signature = JSON.stringify([data.instances, state?.report, data.routing, data.failure_events, data.failure_retention]);
  if (monitorSignature === signature) {
    $("monitor").dataset.stale = "false";
    badge("monitor-badge", "正常", data.instances.length ? "ready" : "");
    $("monitor-message").textContent = data.instances.length ? "" : "尚未配置 AGY 实例，请在下方完成模型配置。";
    $("monitor-updated").textContent = `更新于 ${monitorShortTime(data.sampled_at)}`;
    monitorSnapshot = data;
    return;
  }
  monitorSignature = signature;
  renderRouting(data.routing ?? state?.routing);
  renderFailureEvents(data);
  const cards = data.instances.map((row, index) => {
    const idKey = `${row.provider_id || "unknown"}::${index}`;
    const card = el("article", "monitor-instance");

    const recent = Array.isArray(row.recent_turns) ? row.recent_turns : [];
    const pool = row.pool;
    const summary = row.summary;
    const context = row.latest_context || {};
    const faults = recent.filter(turn => turn.error_code || turn.status === "error");

    const head = el("div", "monitor-instance-head");
    const idGroup = el("div", "monitor-id-group");
    idGroup.append(el("h3", "", row.provider_id), el("p", "monitor-model", row.model || "未选择模型"));
    const badges = el("div", "monitor-badges");
    const enabledBadge = el("span", "badge", row.enabled ? "已启用" : "已停用");
    if (row.enabled && row.runtime_state === "active") enabledBadge.dataset.state = "ready";
    const modeLabel = row.effective_mode === "tools" ? "工具模式" : row.effective_mode === "chat" ? "纯聊天" : "模式未知";
    badges.append(enabledBadge, el("span", "badge", modeLabel));
    if (row.runtime_state === "active" && recent.length && !faults.length) {
      const healthy = el("span", "badge", "近期无异常");
      healthy.dataset.state = "ready";
      badges.append(healthy);
    }
    head.append(idGroup, badges);
    card.append(head);

    if (row.runtime_state !== "active") {
      card.append(el("p", "monitor-empty", "已配置未初始化，暂无运行统计。"));
    } else {
      const overview = el("div", "monitor-overview");

      if (faults.length) {
        const banner = el("div", "fault-banner");
        const label = faults[0].error_code ? formatFaultBrief(faults[0].error_code) : "请求异常";
        banner.append(
          el("strong", "", label),
          el("span", "", `${monitorAgo(faults[0].recorded_at)}${faults.length > 1 ? ` · 近期共 ${faults.length} 次` : ""}`),
        );
        overview.append(banner);
      }

      const sentTurns = summary?.request_sent_turns || 0;
      const missingCache = summary?.missing_cache_field_turns || 0;
      const reportedTurns = summary?.reported_usage_turns || 0;
      const grid = el("div", "kpi-grid");
      grid.append(
        renderPoolTile(pool),
        renderRequestsTile(summary),
        renderRingTile(
          "会话复用率",
          summary?.reuse_rate,
          sentTurns > 0 ? `基于 ${monitorCount(sentTurns)} 次实际发送` : "",
          sentTurns === 0 ? "暂无样本" : "未知",
          "var(--chart-input)",
        ),
        renderRingTile(
          "缓存读取占比",
          summary?.cache_token_ratio,
          missingCache > 0 ? `${monitorCount(missingCache)} 轮缺缓存字段` : reportedTurns > 0 ? `基于 ${monitorCount(reportedTurns)} 轮已上报` : "",
          reportedTurns > 0 && reportedTurns === missingCache ? "未报告缓存字段" : "暂无样本",
          "var(--chart-cached)",
        ),
      );
      overview.append(grid);

      const panels = el("div", "panel-row");
      panels.append(renderContextPanel(context, row));
      const tokenChart = renderTokenChart(summary);
      if (tokenChart) panels.append(tokenChart);
      overview.append(panels);

      const latencyChart = renderLatencyChart(recent);
      if (latencyChart) overview.append(latencyChart);
      card.append(overview);

      const reasons = Array.isArray(summary?.rebuild_reasons) ? summary.rebuild_reasons : [];
      if (reasons.length || recent.length) {
        const detailsBadge = recent.length ? `${monitorCount(recent.length)} 轮` : "";
        const layer2 = createLayerDetails(`${idKey}::details`, "monitor-details", "详细记录", detailsBadge);
        const layer2Body = el("div", "monitor-layer-body");
        if (reasons.length) layer2Body.append(renderReasonBars(reasons));
        if (recent.length) layer2Body.append(renderHistory(recent, row));
        layer2.append(layer2Body);
        card.append(layer2);
      }
    }

    card.append(renderDiagnostics(row, recent, pool, idKey));
    return card;
  });

  $("monitor-instances").replaceChildren(...cards);
  $("monitor").dataset.stale = "false";
  badge("monitor-badge", "正常", cards.length ? "ready" : "");
  $("monitor-message").textContent = cards.length ? "" : "尚未配置 AGY 实例，请在下方完成模型配置。";
  $("monitor-updated").textContent = `更新于 ${monitorShortTime(data.sampled_at)}`;
  monitorSnapshot = data;
}

function renderSetupProgress(data, passed) {
  const configured = data.providers || [];
  const steps = [
    ["运行环境", Boolean(data.report.cli_version)],
    ["账号认证", passed],
    ["模型配置", configured.length > 0],
    ["启用实例", configured.some(p => p.enabled)],
  ];
  const current = steps.findIndex(([, done]) => !done);
  $("setup-progress").replaceChildren(...steps.map(([label, done], index) => {
    const item = el("li", done ? "is-done" : index === current ? "is-current" : "");
    item.append(el("span", "step-dot", done ? "✓" : String(index + 1)), el("span", "step-label", label));
    return item;
  }));
}
async function refreshMonitor() {
  clearTimeout(monitorTimer);
  if (disposed || suspended || document.hidden || monitorPending || !monitorReady) return;
  const epoch = refreshEpoch;
  monitorPending = true;
  $("monitor-refresh").disabled = true;
  $("monitor-refresh").textContent = "刷新中…";
  try {
    const data = await bridge.apiGet("monitor/status");
    if (!disposed && epoch === refreshEpoch) renderMonitor(data);
  } catch (error) {
    if (disposed || epoch !== refreshEpoch) return;
    const status = error?.status || error?.statusCode || error?.status_code;
    const denied = status === 401 || status === 403 || /登录|权限|管理员|unauthorized|forbidden/i.test(error?.message || "");
    $("monitor").dataset.stale = "true";
    badge("monitor-badge", "数据过期", "error");
    $("monitor-message").textContent = denied
      ? "无权读取监控，请使用 AstrBot 管理员账号登录后刷新。"
      : monitorSnapshot ? "监控读取失败，以下为过期快照。" : "暂时无法读取监控数据，请稍后刷新。";
    if (denied) {
      $("monitor-instances").replaceChildren();
      monitorSnapshot = undefined;
      monitorSignature = undefined;
      $("persistent-failures").replaceChildren();
      $("failure-storage").textContent = "";
      renderRouting(null);
    }
  } finally {
    if (!disposed && epoch === refreshEpoch) {
      monitorPending = false;
      $("monitor-refresh").disabled = false;
      $("monitor-refresh").textContent = "刷新";
      if (!document.hidden) monitorTimer = setTimeout(refreshMonitor, 10000);
    }
  }
}

function render(data) {
  state = data;
  data = {...data, report: data.report || {}, login: data.login || {}, environment: data.environment || {}, providers: Array.isArray(data.providers) ? data.providers : []};
  state = data;
  const r = data.report, login = data.login;
  renderRouting(data.routing ?? monitorSnapshot?.routing);
  const busy = pending || data.busy || activeLogin(login);
  const passed = r.status === "passed";
  if (Array.isArray(r.models)) cachedModels = r.models;
  else if (!busy) cachedModels = [];
  const models = cachedModels;

  renderSetupProgress(data, passed);
  setConnection(busy ? "正在同步…" : "已连接 AstrBot", busy ? "busy" : "ok");
  $("environment").textContent = `${data.environment.system} · Python ${data.environment.python}${data.environment.container ? " · 容器环境" : ""}`;
  $("discovery-hint").textContent = data.environment.discovery_hint || "";
  $("install-hint").textContent = data.environment.install_hint;
  setInputValue("install-url", data.environment.install_url);
  setInputValue("install-command", data.environment.install_command);

  // 默认仅展示 CLI 版本、可用模型数量，以及失败时的退出码与阶段
  $("facts").replaceChildren(...[
    r.cli_version ? `CLI ${r.cli_version}` : null,
    r.model_count != null ? `${r.model_count} 个可用模型` : null,
    Number.isInteger(r.exit_code) ? `CLI 退出码：${r.exit_code}` : null,
    r.error_code && stages[r.stage] ? `失败阶段：${stages[r.stage]}` : null,
  ].filter(Boolean).map(text => el("span", "fact", text)));

  // 高级诊断明细移入 env-diag-list
  const caps = r.advertised_capabilities;
  const capSummary = caps
    ? `MCP(http=${Boolean(caps.mcpCapabilities?.http)}, sse=${Boolean(caps.mcpCapabilities?.sse)}) · 模态(img=${Boolean(caps.promptCapabilities?.image)}, audio=${Boolean(caps.promptCapabilities?.audio)})`
    : null;
  $("env-diag-list").replaceChildren(...[
    r.customizations_mode ? kvItem("组件模式", r.customizations_mode) : null,
    r.cli_flags ? kvItem("精简参数", `${r.cli_flags.include_default_customizations ? "支持" : "未探测到"} · 禁用遥测=${r.cli_flags.disable_telemetry ? "支持" : "不支持"}`) : null,
    r.minimal_tools_status ? kvItem("精简状态", minimalToolsLabels[r.minimal_tools_status] || r.minimal_tools_status) : null,
    r.tool_bridge_transport ? kvItem("工具桥 / Socket", transportLabels[r.tool_bridge_transport] || "未知") : null,
    r.process_supervision ? kvItem("进程托管", supervisionLabels[r.process_supervision] || "未知") : null,
    r.proxy_mode ? kvItem("代理配置", `${r.proxy_mode}${data.environment.proxy_mode_note ? `（${data.environment.proxy_mode_note}）` : ""}`) : null,
    r.auth_bridge !== undefined ? kvItem("认证桥接", r.auth_bridge ? "开启" : "关闭") : null,
    capSummary ? kvItem("ACP 能力声明", capSummary) : null,
  ].filter(Boolean));

  const errorLabels = {NOT_INSTALLED: "未找到 CLI", COMMAND_NOT_FOUND: "配置路径无效", STARTUP_EXIT: "握手前退出", CLI_WRAPPER: "启动脚本不兼容"};
  badge("check-badge", data.busy ? stages[r.stage] || "正在检测" : passed ? "环境就绪" : errorLabels[r.error_code] || r.error_code || "等待检测", passed ? "ready" : r.error_code ? "error" : "");
  $("check-hint").textContent = data.busy
    ? `正在${stages[r.stage] || "检查环境"}…`
    : passed
      ? (r.minimal_tools_status === "unsupported" ? data.hint : "")
      : data.hint;
  $("check").textContent = data.busy ? "检测中…" : "重新检测";
  $("check").disabled = busy;
  if (r.error_code !== previousInstallError && ["NOT_INSTALLED", "COMMAND_NOT_FOUND", "STARTUP_EXIT", "CLI_WRAPPER"].includes(r.error_code)) $("install-details").open = true;
  previousInstallError = r.error_code;

  badge("login-badge", passed ? "已连接" : loginStates[login.state] || "等待登录", passed ? "ready" : login.state === "failed" ? "error" : "");
  $("login").disabled = busy || !r.cli_version;
  $("login").textContent = passed ? "重新登录" : "开始官方登录";
  $("cancel-login").hidden = !activeLogin(login) || !login.owned;
  $("cancel-login").disabled = pending;
  $("login-hint").textContent = activeLogin(login)
    ? `${login.owned ? "请在浏览器完成授权" : "另一位管理员正在登录"}（剩余 ${login.expires_in}s）`
    : passed ? ""
    : login.state === "failed" ? `登录未完成（${login.error_code}），请重试或使用终端登录。`
    : "请启动官方登录并在浏览器完成授权。";
  $("authorization").hidden = !login.url || !login.owned;
  setInputValue("auth-url", login.owned ? login.url : "");
  if (login.state !== "waiting") $("auth-code").value = "";
  $("submit-code").disabled = pending || login.state !== "waiting";

  const signature = JSON.stringify(models);
  if (modelSignature !== signature) {
    const previous = $("model").value;
    $("model").replaceChildren(new Option(models.length ? "请选择模型" : "先完成环境检测", ""), ...models.map(m => new Option(m.name, m.id)));
    const preferred = [previous, r.selected_model, data.providers[0]?.model].find(id => models.some(m => m.id === id));
    if (preferred) $("model").value = preferred;
    modelSignature = signature;
  }
  const selected = $("model").value;
  const efforts = r.selected_model === selected ? r.efforts || [] : [];
  const effortKey = JSON.stringify([selected, efforts, data.global_effort]);
  if (effortSignature !== effortKey && (!busy || r.selected_model === selected)) {
    const previous = $("effort").value;
    $("effort").replaceChildren(new Option(`跟随全局（${data.global_effort}）`, "default"), ...efforts.map(e => new Option({low: "低", medium: "中", high: "高"}[e], e)));
    if (["default", ...efforts].includes(previous)) $("effort").value = previous;
    effortSignature = effortKey;
  }
  $("model").disabled = busy || !models.length;
  $("effort").disabled = busy || !passed || !selected;
  if (!$("tools-mode").value) $("tools-mode").value = "chat";
  $("tools-mode").disabled = busy || !passed || !selected;
  $("apply").disabled = busy || !passed || !selected;
  $("use-default").disabled = busy;
  badge("model-badge", models.length ? `${models.length} 个模型` : "等待登录", passed ? "ready" : "");

  const configured = data.providers;
  badge("finish-badge", data.result ? "已保存" : configured.length ? "已配置" : "等待配置", configured.length ? "ready" : "");
  $("finish-hint").textContent = data.result?.default_selected
    ? "已同步设为全局默认模型。"
    : data.result?.provider_id && data.action_error ? "实例已保存；全局默认切换未确认，请核对路由。"
    : configured.length ? "" : "保存模型后将在此生成会话切换命令。";

  const providerKey = JSON.stringify(configured);
  if (providerSignature !== providerKey) {
    $("configured").replaceChildren(...configured.map(row => {
      const wrapper = el("div", "provider");
      const pHead = el("div", "provider-head");
      const title = el("strong", "", row.model);
      const meta = el("span", "badge", `${toolsModeLabels[row.tools_mode] || "跟随全局"} · ${row.enabled ? "已启用" : "已停用"}`);
      if (row.enabled) meta.dataset.state = "ready";
      pHead.append(title, meta);

      const line = el("div", "copy-row");
      const input = document.createElement("input");
      input.readOnly = true;
      input.value = `/agy use ${row.id}`;
      input.setAttribute("aria-label", "切换模型命令");
      const button = el("button", "btn btn-sm", "复制命令");
      button.type = "button";
      button.addEventListener("click", () => copy(input, button));
      line.append(input, button);
      wrapper.append(pHead, line);
      return wrapper;
    }));
    providerSignature = providerKey;
  }
  if (data.action_error) showError(`${data.action_error}：${data.action_hint}`);
  const nextDiagSig = JSON.stringify([r.status, r.stage, r.cli_version, r.process_supervision, r.tool_bridge_transport]);
  if (monitorSnapshot && nextDiagSig !== reportDiagSignature) {
    reportDiagSignature = nextDiagSig;
    renderMonitor(monitorSnapshot);
  } else {
    reportDiagSignature = nextDiagSig;
  }
}

async function action(name, body = {}) {
  if (!state || pending) return;
  revision++;
  pending = true; showError(); render(state);
  try {
    const data = await bridge.apiPost(`setup/${name}`, {...body, csrf: state.csrf});
    if (disposed) return;
    pending = false; render(data);
  } catch (error) {
    if (disposed) return;
    pending = false; render(state); showError(error?.message || "请求失败，请刷新页面。");
  }
}

$("theme-toggle").onclick = cycleTheme;
$("monitor-refresh").onclick = refreshMonitor;
$("check").onclick = () => action("check");
$("login").onclick = () => action("login");
$("cancel-login").onclick = () => action("login-cancel", {ticket: state.login.ticket});
$("open-auth").onclick = openAuthorization;
$("copy-auth").onclick = () => copy($("auth-url"), $("copy-auth"));
$("copy-install").onclick = () => copy($("install-url"), $("copy-install"));
$("copy-command").onclick = () => copy($("install-command"), $("copy-command"));
$("code-form").onsubmit = async event => {
  event.preventDefault();
  const code = $("auth-code").value; $("auth-code").value = "";
  await action("login-code", {ticket: state.login.ticket, code});
};
$("model").onchange = () => {
  $("effort").value = "default";
  if ($("model").value) action("check", {model: $("model").value});
  else render(state);
};
$("model-form").onsubmit = event => {
  event.preventDefault();
  action("apply", {
    model: $("model").value,
    effort: $("effort").value,
    tools_mode: $("tools-mode").value || "chat",
    use_default: $("use-default").checked,
  });
};

async function poll() {
  clearTimeout(timer);
  if (disposed || suspended || document.hidden || pollPending || !monitorReady) return;
  const epoch = refreshEpoch;
  const currentRevision = revision;
  pollPending = true;
  try {
    if (!pending) {
      const data = await bridge.apiGet("setup/status");
      if (!disposed && epoch === refreshEpoch && currentRevision === revision) {
        render(data);
        pollFailures = 0;
        showError("", "poll");
      }
    }
  } catch (error) {
    if (!disposed && epoch === refreshEpoch && currentRevision === revision) {
      pollFailures = Math.min(pollFailures + 1, 4);
      setConnection("连接中断，正在重试…", "error");
      showError(error?.message || "无法读取状态。", "poll");
    }
  } finally {
    if (!disposed && epoch === refreshEpoch) {
      pollPending = false;
      const delay = pollFailures ? Math.min(5000 * 2 ** (pollFailures - 1), 30000)
        : state?.busy || activeLogin(state?.login) ? 1200 : 5000;
      if (!document.hidden) timer = setTimeout(poll, delay);
    }
  }
}

function pauseRefresh() {
  ++refreshEpoch;
  clearTimeout(timer);
  clearTimeout(monitorTimer);
  pollPending = false;
  monitorPending = false;
}

function resumeRefresh() {
  if (disposed || suspended || document.hidden || !monitorReady) return;
  poll();
  refreshMonitor();
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) pauseRefresh();
  else resumeRefresh();
});

window.addEventListener("pagehide", (event = {}) => {
  pauseRefresh();
  clearTimeout(copyTimer);
  clearTimeout(toastTimer);
  ++copyAttempt;
  if (event.persisted) { suspended = true; return; }
  disposed = true;
  monitorSnapshot = undefined;
  $("auth-code").value = "";
  $("auth-url").value = "";
  state = null;
});
window.addEventListener("pageshow", event => {
  if (event.persisted) { suspended = false; resumeRefresh(); }
});
if (!bridge) {
  setConnection("未连接 AstrBot", "error");
  showError("请从 AstrBot WebUI 侧边栏或插件详情打开 Antigravity ACP 面板。");
  badge("monitor-badge", "不可用");
  $("monitor-message").textContent = "请从 AstrBot 管理面板打开运行监控。";
} else {
  try {
    await bridge.ready();
    if (!disposed) {
      monitorReady = true;
      applyTheme();
      refreshMonitor();
      await poll();
    }
  } catch (error) {
    setConnection("面板连接失败", "error");
    showError(error.message || "面板连接失败。");
    badge("monitor-badge", "不可用", "error");
    $("monitor-message").textContent = "面板连接失败，请刷新页面。";
  }
}
