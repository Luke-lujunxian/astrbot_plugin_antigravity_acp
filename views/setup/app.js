const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginView;
const SVG_NS = "http://www.w3.org/2000/svg";
let state, pending = false, disposed = false, timer, copyTimer, revision = 0;
let cachedModels = [], cachedEffortsByModel = {}, modelSignature = "", effortSignature = "", providerSignature = "";
let themeMode = "auto", nextManualTheme = "dark", activeTab = "monitor";
let editingProviderId = null, formModalOpen = false, impactContext = null, commandsModalOpen = false;
let previousInstallError, monitorSignature, copyAttempt = 0, toastTimer, pollFailures = 0, pollPending = false, suspended = false, refreshEpoch = 0;
const bannerErrors = {action: "", poll: ""};
const buttonFeedback = new WeakMap(), listSignatures = new WeakMap();
const themeKey = "agy-acp.setup.theme";
try { const saved = window.localStorage?.getItem(themeKey); if (["auto", "light", "dark"].includes(saved)) themeMode = saved; } catch {}
let monitorTimer, monitorPending = false, monitorReady = false, monitorSnapshot;

// 账号额度状态（GET monitor/quota 只读缓存，POST setup/quota-refresh 手动触发，无后台轮询）
let quotaSnapshot = null, quotaLoading = false, quotaRequestError = "", quotaCountdownTimer;

// 每日用量与热力图状态（GET monitor/daily/{30|90|365}）
let dailyDays = 90, dailyMetric = "requests", dailyModel = "";
let dailyData = null, dailyLoading = false, dailyError = "", dailyFetchSeq = 0;
let dailySelectedDate = null, dailyHoverDate = null, dailyCellButtons = new Map();

// 工具权限状态（setup/status.tool_policy 与 POST setup/tool-policy）
let toolPolicyServer = null, toolPolicyDraft = {}, toolPolicyDirty = false, toolPolicySaving = false;
let toolPolicyFeedback = {message: "", kind: ""}, toolPolicyRenderSig = "";

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
const effortLabels = {default: "CLI默认", low: "低", medium: "中", high: "高", invalid: "无效配置"};
const toolsModeLabels = {chat: "纯聊天", inherit: "跟随总闸", tools: "工具模式", invalid: "无效配置"};
const turnStatusLabels = {ok: "成功", error: "失败", cancelled: "取消", short_circuited: "预检/熔断拦截", unknown: "未知"};
const transportLabels = {loopback_hmac: "本机认证连接", unix_socket: "Unix Socket", unsupported: "当前平台不支持"};
const supervisionLabels = {windows_job: "Windows Job Object", windows_taskkill_fallback: "taskkill 回退", posix_process_group: "独立进程组"};
const minimalToolsLabels = {inactive: "未启用精简", flag_available_unverified: "支持参数（待验收）", unsupported: "CLI 不支持"};
const faultLabels = {
  RATE_LIMIT: "请求受限", QUOTA: "额度不足", AUTH: "认证失败", AUTH_BRIDGE: "认证桥接失败",
  TIMEOUT: "请求超时", NETWORK: "网络异常", PROXY: "代理异常", PROXY_AUTH: "代理认证失败",
  TLS: "证书/TLS 异常", TRANSPORT: "传输中断", BACKPRESSURE: "并发过载", BUSY: "实例忙碌",
  CANCELLED: "已取消", EMPTY: "空响应", UPSTREAM: "上游异常", PROTOCOL: "协议异常",
  TOOL_PERMISSION: "工具权限受限",
};

// 官方 CLI 额度固定脱敏错误文案（严格按契约 error.code 映射）
const quotaErrorMessages = {
  AUTH: "尚未登录或登录态已失效，请前往「环境与认证」完成登录后再刷新额度。",
  TIMEOUT: "额度查询超时（超过 30 秒），请检查网络或代理设置后重试。",
  NOT_INSTALLED: "未检测到官方 AGY CLI，请先在「环境与认证」完成安装配置。",
  UNSUPPORTED: "当前官方 CLI 版本暂不支持额度查询，请升级 CLI 后重试。",
  QUOTA_FORMAT: "未能解析官方 CLI 返回的额度信息，请稍后重试或检查 CLI 版本。",
  QUOTA_FAILED: "官方 CLI 额度查询失败，请稍后重试。",
  ENV_CHANGED: "检测到登录环境已变更，旧缓存已清空，请点击「刷新额度」重新获取。",
};

const quotaWindowLabels = {
  "5h": "5 小时窗口",
  weekly: "周窗口",
  daily: "日窗口",
  monthly: "月窗口",
};

const toolPolicyChoiceLabels = {
  deny: "拒绝",
  allow_once: "单次允许",
};

const toolRiskLabels = {
  high: {text: "高风险", state: "error"},
  network: {text: "联网风险", state: "warn"},
  host: {text: "宿主管控", state: "primary"},
};

const toolCapabilityLabels = {
  supported: {text: "支持", state: "ready"},
  unverified: {text: "未验证", state: "warn"},
  unsupported: {text: "暂不支持", state: ""},
};

const toolSourceSections = {
  mcp: {
    title: "AstrBot MCP 桥接工具",
    desc: "由 AstrBot 宿主按每轮快照提供并执行审批，通过一次性许可桥接。",
  },
  builtin: {
    title: "AGY CLI 内置工具",
    desc: "默认全部拒绝；仅后端确认支持的内置工具可切换为单次允许，并与 MCP 共用每轮调用上限。",
  },
};

// 契约注册的聊天管理员指令清单
const adminCommands = [
  {cmd: "/agy help", copy: "/agy help", desc: "列出所有可用指令与参数说明"},
  {cmd: "/agy setup", copy: "/agy setup", desc: "查看设置入口及已有模型实例"},
  {cmd: "/agy use <provider_id>", copy: "/agy use ", desc: "切换当前会话使用的模型实例（如 /agy use agy-main）"},
  {cmd: "/agy cost", copy: "/agy cost", desc: "查看本地成本与会话复用统计"},
  {cmd: "/agy doctor", copy: "/agy doctor", desc: "执行无生成环境与认证自检"},
  {cmd: "/agy quota", copy: "/agy quota", desc: "查询官方 CLI 账号剩余额度"},
  {cmd: "/agy status", copy: "/agy status", desc: "查看已加载实例及运行状态"},
  {cmd: "/agy models", copy: "/agy models", desc: "查看已配置模型与实例 ID"},
  {cmd: "/agy usage [30|90|365]", copy: "/agy usage 90", desc: "查看本地每日统计摘要及最近 28 天文本热力图（默认 90 天）"},
];

function formatFaultBrief(code) {
  if (!code) return "请求异常";
  return faultLabels[code] || "请求异常";
}

function formatQuotaError(error) {
  if (!error || typeof error !== "object") return "";
  return quotaErrorMessages[error.code] || "额度查询暂不可用，请稍后重试。";
}

function formatQuotaWindow(win) {
  if (typeof win !== "string" || !win.trim()) return "";
  return quotaWindowLabels[win] || win;
}

function globalEffortText(globalEffort = state?.global_effort || "default") {
  return globalEffort === "default"
    ? "跟随全局（CLI默认）"
    : `跟随全局（${effortLabels[globalEffort] || globalEffort}）`;
}

function formatEffortBadge(effort, globalEffort) {
  if (effort === "default") return globalEffortText(globalEffort);
  return `思考：${effortLabels[effort] || effort}`;
}

function switchTab(next) {
  activeTab = next;
  for (const name of ["monitor", "models", "tools", "setup"]) {
    const panel = $(`tab-${name}`);
    const btn = $(`tab-btn-${name}`);
    if (panel) panel.hidden = name !== next;
    if (btn) {
      btn.classList.toggle("is-active", name === next);
      if (name === next) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute?.("aria-current");
    }
  }
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
  const node = $(id);
  if (!node) return;
  node.textContent = text;
  node.dataset.state = kind;
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
  const t = setTimeout(() => {
    button.textContent = label;
    buttonFeedback.delete(button);
  }, 2000);
  buttonFeedback.set(button, {label, timer: t});
  toast(copied ? "已复制" : "已选中，请按 Ctrl+C / ⌘C 复制", copied ? "ok" : "warn");
}

async function copyText(text, button, fallbackInput = null) {
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
  if (disposed || attempt !== copyAttempt) return;
  if (fallbackInput && fallbackInput.value !== text) return;
  if (!copied && fallbackInput) {
    fallbackInput.focus();
    fallbackInput.select();
  }
  showCopyFeedback(button, copied);
}

async function copy(input, button) {
  return copyText(input.value, button, input);
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

function formatCompactTokens(value) {
  if (!Number.isFinite(value)) return "未知";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString();
}

function monitorTime(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return "未报告";
  try {
    return date.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch {
    return date.toLocaleString();
  }
}

function formatLocalShortDateTime(date) {
  try {
    return date.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return date.toLocaleString();
  }
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

function isAuthDeniedError(error) {
  const status = error?.status || error?.statusCode || error?.status_code;
  return status === 401 || status === 403 || /登录|权限|管理员|unauthorized|forbidden/i.test(error?.message || "");
}

// 仅认定最新一轮未恢复且非取消的异常为「当前故障」；历史故障和 CANCELLED 不常驻提示
function getCurrentFault(recent) {
  if (!Array.isArray(recent) || !recent.length) return null;
  const latest = recent[0];
  if (!latest || latest.status === "ok" || latest.status === "cancelled") return null;
  if (latest.error_code === "CANCELLED") return null;
  if (latest.error_code || latest.status === "error" || latest.status === "short_circuited") return latest;
  return null;
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
    el("span", "panel-title", `近期耗时（近 ${timed.length} 轮）`),
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
    rect.append(svgNode("title", {}, `${formatDuration(turn.elapsed_ms)} · ${statusText} · ${monitorAgo(turn.recorded_at)}`));
    svg.append(rect);
  });
  svg.append(svgNode("line", {x1: 0, y1: avgY, x2: width, y2: avgY, stroke: "var(--muted)", "stroke-dasharray": "6 5", "stroke-width": 1, opacity: 0.7}));
  block.append(svg);

  const axis = el("div", "chart-axis");
  axis.append(el("span", "", "较早"), el("span", "", `峰值 ${formatDuration(maxMs)}`), el("span", "", "最新"));
  block.append(axis);
  return block;
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
  if (listSignatures.get(panel) !== sig) {
    panel.replaceChildren(...fields.map(([label, value]) => kvItem(label, value)));
    listSignatures.set(panel, sig);
  }

  const providers = state?.providers || [];
  const primaryId = routing?.configured_primary_id;
  const matched = providers.find(p => p.id === primaryId);
  const stripText = $("routing-strip-text");
  const stripMeta = $("routing-strip-meta");
  if (!routing || typeof routing !== "object" || routing.resolution_reason === "unknown") {
    stripText.textContent = providers.length ? "未报告" : "尚未添加模型";
    badge("routing-strip-badge", "未知", "");
    stripMeta.textContent = "";
    return;
  }
  if (routing.resolution_reason === "configured_primary") {
    stripText.textContent = matched
      ? `${matched.model} · ${formatEffortBadge(matched.thought_level || "default", state?.global_effort)} · ${toolsModeLabels[matched.tools_mode] || "跟随总闸"}`
      : (routing.resolved_primary_id || "未知");
    badge("routing-strip-badge", "生效中", "ready");
  } else if (routing.resolution_reason === "implicit_first_provider") {
    stripText.textContent = primaryId ? `已失效 (${primaryId})` : "未设置";
    badge("routing-strip-badge", `回退：${routing.resolved_primary_id || "未知"}`, "error");
  } else if (routing.resolution_reason === "non_local_runner") {
    stripText.textContent = "非本地 runner";
    badge("routing-strip-badge", "非本地", "warn");
  } else {
    stripText.textContent = "未设置默认模型";
    badge("routing-strip-badge", "未命中", "error");
  }
  const fbCount = Array.isArray(routing.explicit_fallback_ids) ? routing.explicit_fallback_ids.length : 0;
  const profCount = Number(routing.non_default_profile_overrides || 0);
  const extras = [];
  if (fbCount) extras.push(`备用 ${fbCount} 项`);
  if (profCount) extras.push(`${profCount} 个独立 Profile 覆盖`);
  stripMeta.textContent = extras.join(" · ");
}

function renderAlerts(data) {
  const routing = data.routing ?? monitorSnapshot?.routing;
  const providers = data.providers || [];
  const routeAlert = $("route-alert");
  const enabledAcp = providers.find(p => p.enabled);
  const busy = pending || data.busy || activeLogin(data.login);

  if (routing && (routing.resolution_reason === "implicit_first_provider" || (routing.resolution_reason === "missing_primary" && enabledAcp))) {
    const msg = routing.resolution_reason === "implicit_first_provider"
      ? `全局默认配置（${routing.configured_primary_id || "未设置"}）未命中，当前隐式路由至 ${routing.resolved_primary_id || "未知"}。`
      : "当前未设置可用全局默认模型。";
    const span = el("span", "", msg);
    const btn = el("button", "btn btn-sm", enabledAcp ? `切换为 ${enabledAcp.model}` : "前往设置");
    btn.type = "button";
    btn.disabled = busy;
    btn.addEventListener("click", () => {
      if (enabledAcp) action("provider-default", {provider_id: enabledAcp.id, confirm: true});
      else switchTab("models");
    });
    routeAlert.replaceChildren(span, btn);
    routeAlert.hidden = false;
  } else {
    routeAlert.hidden = true;
  }

  const drifted = providers.filter(p => p.config_drifted);
  const driftAlert = $("drift-alert");
  if (drifted.length) {
    const span = el("span", "", `${drifted.length} 个模型配置与当前全局总闸或 ACP 规范不一致。`);
    const btn = el("button", "btn btn-sm", "一键同步");
    btn.type = "button";
    btn.disabled = busy;
    btn.addEventListener("click", () => action("provider-repair", {all: true}));
    driftAlert.replaceChildren(span, btn);
    driftAlert.hidden = false;
  } else {
    driftAlert.hidden = true;
  }

  const scopeAlert = $("command-scope-alert");
  const scopeWarning = typeof data.command_scope_warning === "string" ? data.command_scope_warning.trim() : "";
  scopeAlert.textContent = scopeWarning;
  scopeAlert.hidden = !scopeWarning;
}

function renderMonitor(data) {
  if (![1, 2].includes(data.schema_version) || !Array.isArray(data.instances)) throw new Error("monitor schema");
  const providerMeta = state?.providers || [];
  const signature = JSON.stringify([data.instances, data.routing, providerMeta]);
  if (monitorSignature === signature) {
    $("monitor").dataset.stale = "false";
    badge("monitor-badge", "正常", data.instances.length ? "ready" : "");
    $("monitor-message").textContent = data.instances.length ? "" : "尚未添加模型，请前往「模型管理」添加。";
    $("monitor-updated").textContent = `更新于 ${monitorShortTime(data.sampled_at)}`;
    monitorSnapshot = data;
    return;
  }
  monitorSignature = signature;
  renderRouting(data.routing ?? state?.routing);
  const cards = data.instances.map((row) => {
    const card = el("article", "monitor-instance");

    const recent = Array.isArray(row.recent_turns) ? row.recent_turns : [];
    const pool = row.pool;
    const summary = row.summary;
    const currentFault = getCurrentFault(recent);
    const extraMeta = providerMeta.find(p => p.id === row.provider_id);

    const head = el("div", "monitor-instance-head");
    const idGroup = el("div", "monitor-id-group");
    idGroup.append(el("h3", "", row.model || row.provider_id || "未选择模型"));
    if (row.provider_id && row.model && row.provider_id !== row.model) {
      idGroup.append(el("p", "monitor-model", row.provider_id));
    }
    const badges = el("div", "monitor-badges");
    if (extraMeta?.is_default) {
      const defBadge = el("span", "badge", "默认");
      defBadge.dataset.state = "primary";
      badges.append(defBadge);
    }
    if (extraMeta?.thought_level) {
      badges.append(el("span", "badge", formatEffortBadge(extraMeta.thought_level, state?.global_effort)));
    }
    if (extraMeta?.config_drifted) {
      const driftBadge = el("span", "badge", "需同步");
      driftBadge.dataset.state = "warn";
      badges.append(driftBadge);
    }
    const enabledBadge = el("span", "badge", row.enabled ? (row.runtime_state === "active" ? "运行中" : "已启用") : "已停用");
    if (row.enabled && row.runtime_state === "active") enabledBadge.dataset.state = "ready";
    const modeLabel = row.effective_mode === "tools" ? "工具模式" : row.effective_mode === "chat" ? "纯聊天" : "模式未知";
    badges.append(enabledBadge, el("span", "badge", modeLabel));
    head.append(idGroup, badges);
    card.append(head);

    if (row.runtime_state !== "active") {
      card.append(el("p", "monitor-empty", "已配置未初始化，暂无运行统计。"));
    } else {
      const overview = el("div", "monitor-overview");

      if (currentFault) {
        const banner = el("div", "fault-banner");
        banner.setAttribute("role", "status");
        banner.append(
          el("strong", "", `当前异常：${formatFaultBrief(currentFault.error_code)}`),
          el("span", "", monitorAgo(currentFault.recorded_at)),
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

      const tokenChart = renderTokenChart(summary);
      const latencyChart = renderLatencyChart(recent);
      if (tokenChart || latencyChart) {
        const panels = el("div", "panel-row");
        if (tokenChart) panels.append(tokenChart);
        if (latencyChart) panels.append(latencyChart);
        overview.append(panels);
      }
      card.append(overview);
    }

    return card;
  });

  $("monitor-instances").replaceChildren(...cards);
  $("monitor").dataset.stale = "false";
  badge("monitor-badge", "正常", cards.length ? "ready" : "");
  $("monitor-message").textContent = cards.length ? "" : "尚未添加模型，请前往「模型管理」添加。";
  $("monitor-updated").textContent = `更新于 ${monitorShortTime(data.sampled_at)}`;
  monitorSnapshot = data;
}

// ---------- 官方 CLI 账号额度 ----------

function formatQuotaFraction(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) {
    return {valid: false, text: "未知", pct: null, level: "unknown"};
  }
  const clamped = Math.max(0, Math.min(1, fraction));
  const pct = clamped * 100;
  const rounded = Math.round(pct);
  const text = Math.abs(pct - rounded) < 0.05 ? `${rounded}%` : `${pct.toFixed(1)}%`;
  const level = clamped <= 0.15 ? "low" : clamped <= 0.4 ? "warn" : "ok";
  return {valid: true, text, pct, level};
}

function formatQuotaReset(resetTime, nowMs = Date.now()) {
  if (!resetTime || typeof resetTime !== "string") return {text: "重置时间：不适用", applicable: false};
  const ts = Date.parse(resetTime);
  if (!Number.isFinite(ts) || ts <= 86_400_000) return {text: "重置时间：不适用", applicable: false};
  const localStr = formatLocalShortDateTime(new Date(ts));
  const diffMs = ts - nowMs;
  if (diffMs <= 0) return {text: `已到重置时间（${localStr}）`, applicable: true};
  const totalMinutes = Math.max(1, Math.round(diffMs / 60_000));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  let countdown;
  if (days > 0) countdown = hours > 0 ? `${days} 天 ${hours} 小时后重置` : `${days} 天后重置`;
  else if (hours > 0) countdown = minutes > 0 ? `${hours} 小时 ${minutes} 分钟后重置` : `${hours} 小时后重置`;
  else countdown = `${minutes} 分钟后重置`;
  return {text: `${countdown} · ${localStr}`, applicable: true};
}

function scheduleQuotaCountdown() {
  clearTimeout(quotaCountdownTimer);
  if (disposed || suspended || document.hidden || !quotaSnapshot?.groups?.length) return;
  const hasFuture = quotaSnapshot.groups.some(g =>
    Array.isArray(g.buckets) && g.buckets.some(b => {
      const ts = b?.reset_time ? Date.parse(b.reset_time) : NaN;
      return Number.isFinite(ts) && ts > Date.now();
    }),
  );
  if (!hasFuture) return;
  quotaCountdownTimer = setTimeout(() => {
    if (!disposed && !suspended && !document.hidden) renderQuota();
  }, 60_000);
}

function renderQuota(nextData) {
  if (nextData !== undefined) {
    if (!nextData || nextData.schema_version !== 1 || !Array.isArray(nextData.groups)) {
      throw new Error("quota schema");
    }
    quotaSnapshot = nextData;
    quotaRequestError = "";
  }

  const card = $("quota-card");
  const alertEl = $("quota-alert");
  const bodyEl = $("quota-body");
  const metaEl = $("quota-meta");
  const updatedEl = $("quota-updated");
  const refreshBtn = $("quota-refresh");

  refreshBtn.disabled = quotaLoading || !monitorReady || !state?.csrf || activeLogin(state?.login);
  refreshBtn.textContent = quotaLoading ? "查询中…" : "刷新额度";

  const snap = quotaSnapshot;
  const groups = Array.isArray(snap?.groups) ? snap.groups : [];
  const hasGroups = groups.length > 0;
  const snapError = snap?.error && typeof snap.error === "object" ? snap.error : null;
  const isStale = Boolean(snap?.stale || (quotaRequestError && hasGroups));
  const isUnsupported = snap?.capability === "unsupported" || snapError?.code === "UNSUPPORTED";
  const isUnqueried = Boolean(!snap || (!snap.fetched_at && !snapError && !hasGroups && !isUnsupported));

  card.dataset.stale = String(isStale);
  const fetchedDate = snap?.fetched_at ? new Date(snap.fetched_at) : null;
  updatedEl.textContent = fetchedDate && Number.isFinite(fetchedDate.getTime())
    ? `更新于 ${formatLocalShortDateTime(fetchedDate)}`
    : "";

  // 状态徽标
  if (quotaLoading) {
    badge("quota-badge", "查询中", "");
  } else if (quotaRequestError) {
    badge("quota-badge", hasGroups ? "数据过期" : "查询失败", hasGroups ? "warn" : "error");
  } else if (isUnsupported) {
    badge("quota-badge", "暂不支持", "warn");
  } else if (snapError) {
    badge("quota-badge", hasGroups ? "数据过期" : "查询失败", hasGroups ? "warn" : "error");
  } else if (isUnqueried) {
    badge("quota-badge", "未查询", "");
  } else if (isStale) {
    badge("quota-badge", "数据过期", "warn");
  } else {
    badge("quota-badge", "已更新", "ready");
  }

  // 提示横幅（加载 / 错误 / 过期）
  if (quotaLoading && hasGroups) {
    alertEl.className = "alert alert-warn";
    alertEl.textContent = "正在通过官方 CLI 获取最新额度（最长约 30 秒），以下暂显示上次结果…";
    alertEl.hidden = false;
  } else if (quotaLoading) {
    alertEl.textContent = "";
    alertEl.hidden = true;
  } else if (quotaRequestError) {
    alertEl.className = "alert alert-error";
    alertEl.textContent = hasGroups ? `${quotaRequestError} 以下保留上次缓存数据（已过期）。` : quotaRequestError;
    alertEl.hidden = false;
  } else if (snapError) {
    alertEl.className = "alert alert-error";
    const errText = formatQuotaError(snapError);
    alertEl.textContent = hasGroups ? `${errText} 以下保留上次缓存数据（已过期）。` : errText;
    alertEl.hidden = false;
  } else if (isStale) {
    alertEl.className = "alert alert-warn";
    alertEl.textContent = "当前展示的是缓存额度且已过期，点击右上角「刷新额度」获取最新状态。";
    alertEl.hidden = false;
  } else {
    alertEl.textContent = "";
    alertEl.hidden = true;
  }

  // 主体内容
  if (quotaLoading && !hasGroups) {
    bodyEl.replaceChildren(el("div", "quota-empty", "正在通过官方 CLI 查询账号额度，最长约 30 秒，请稍候…"));
  } else if (hasGroups) {
    const grid = el("div", "quota-groups");
    groups.forEach((group) => {
      const box = el("article", "quota-group");
      const head = el("div", "quota-group-head");
      head.append(el("h3", "quota-group-title", group.name || "未命名额度池"));
      const shared = Array.isArray(group.models_shared) ? group.models_shared.filter(Boolean) : [];
      if (shared.length) {
        const chips = el("div", "quota-models");
        shared.forEach(modelName => chips.append(el("span", "quota-model-chip", modelName)));
        head.append(chips);
      } else {
        head.append(el("p", "small", "同组模型共享以下额度窗口"));
      }
      box.append(head);

      const bucketsWrap = el("div", "quota-buckets");
      const buckets = Array.isArray(group.buckets) ? group.buckets : [];
      if (!buckets.length) {
        bucketsWrap.append(el("p", "small", "未返回可用额度窗口"));
      } else {
        buckets.forEach((bucket) => {
          const item = el("div", "quota-bucket");
          const frac = formatQuotaFraction(bucket.remaining_fraction);
          const winLabel = formatQuotaWindow(bucket.window);
          const resetInfo = formatQuotaReset(bucket.reset_time);

          const bHead = el("div", "quota-bucket-head");
          const titleWrap = el("div", "quota-bucket-title");
          titleWrap.append(el("span", "", bucket.name || bucket.id || "额度窗口"));
          if (winLabel) titleWrap.append(el("span", "badge", winLabel));
          const pctEl = el("span", "quota-pct", frac.text);
          pctEl.dataset.level = frac.level;
          bHead.append(titleWrap, pctEl);
          item.append(bHead);

          if (frac.valid) {
            const progress = el("progress", "quota-progress");
            progress.max = 100;
            progress.value = Number(frac.pct.toFixed(1));
            progress.dataset.level = frac.level;
            progress.setAttribute("aria-label", `${group.name || "额度池"} ${bucket.name || ""} 剩余 ${frac.text}`);
            item.append(progress);
          } else {
            const placeholder = el("div", "quota-progress-unknown");
            placeholder.setAttribute("role", "img");
            placeholder.setAttribute("aria-label", "剩余额度未知");
            item.append(placeholder);
          }

          const resetRow = el("div", "quota-reset");
          resetRow.append(el("span", "", resetInfo.text));
          item.append(resetRow);
          bucketsWrap.append(item);
        });
      }
      box.append(bucketsWrap);
      grid.append(box);
    });
    bodyEl.replaceChildren(grid);
  } else if (isUnsupported) {
    bodyEl.replaceChildren(el("div", "quota-empty", "当前官方 AGY CLI 版本暂不支持额度查询，请升级官方 CLI 后重试。"));
  } else if (snapError || quotaRequestError) {
    bodyEl.replaceChildren(el("div", "quota-empty", "暂无可展示的账号额度数据，解决问题后点击「刷新额度」。"));
  } else if (isUnqueried) {
    bodyEl.replaceChildren(el("div", "quota-empty", "尚未查询账号额度。点击右上角「刷新额度」或发送 /agy quota 通过官方 CLI 获取。"));
  } else {
    bodyEl.replaceChildren(el("div", "quota-empty", "本次查询未返回可用额度组。"));
  }

  // 紧凑元信息（不暴露内部 login_env，不猜测套餐）
  if (snap) {
    const parts = [];
    if (snap.cli_version) parts.push(`官方 CLI ${snap.cli_version}`);
    if (snap.fetched_at) parts.push(`采样于 ${monitorTime(snap.fetched_at)}`);
    parts.push("同组模型共享额度，仅手动刷新或指令查询");
    metaEl.textContent = parts.join(" · ");
  } else {
    metaEl.textContent = "仅在手动刷新或执行 /agy quota 时查询，无后台轮询。";
  }

  scheduleQuotaCountdown();
}

async function refreshQuotaCache() {
  if (disposed || suspended || !monitorReady) return;
  const epoch = refreshEpoch;
  try {
    const data = await bridge.apiGet("monitor/quota");
    if (!disposed && epoch === refreshEpoch) renderQuota(data);
  } catch (error) {
    if (disposed || epoch !== refreshEpoch) return;
    if (error?.message === "quota schema") {
      // 兼容尚未提供该接口的测试桩或旧响应，保持未查询态不报全局错误
      if (!quotaSnapshot) renderQuota();
      return;
    }
    const status = error?.status || error?.statusCode || error?.status_code;
    quotaRequestError = isAuthDeniedError(error)
      ? "无权读取账号额度，请使用 AstrBot 管理员账号登录后重试。"
      : status === 503
        ? "插件当前已停用或服务不可用（503），请确认插件已启用后重试。"
        : "暂时无法读取额度缓存，请点击「刷新额度」重试。";
    renderQuota();
  }
}

async function refreshQuotaManual() {
  if (disposed || quotaLoading || !monitorReady || !state?.csrf || activeLogin(state?.login)) return;
  const epoch = refreshEpoch;
  quotaLoading = true;
  quotaRequestError = "";
  renderQuota();
  try {
    const data = await bridge.apiPost("setup/quota-refresh", {csrf: state.csrf});
    if (disposed || epoch !== refreshEpoch) return;
    quotaLoading = false;
    renderQuota(data);
  } catch (error) {
    if (disposed || epoch !== refreshEpoch) return;
    quotaLoading = false;
    const status = error?.status || error?.statusCode || error?.status_code;
    quotaRequestError = isAuthDeniedError(error)
      ? "无权刷新账号额度或会话已过期，请重新登录后重试。"
      : status === 409
        ? "官方登录正在进行中，请等待登录完成后再刷新额度。"
        : status === 503
          ? "插件当前已停用（503），请启用插件后再刷新额度。"
          : "额度刷新请求失败，请稍后重试。";
    renderQuota();
  }
}

// ---------- 每日用量与热力图 ----------

function parseIsoDay(str) {
  const match = typeof str === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(str) : null;
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function formatIsoDay(utcMs) {
  const d = new Date(utcMs);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function getFilteredDayEntry(dayRow, modelFilter) {
  if (!dayRow) return null;
  if (!modelFilter) return dayRow;
  if (dayRow.by_model && Object.hasOwn(dayRow.by_model, modelFilter)) {
    return dayRow.by_model[modelFilter];
  }
  return null;
}

function computePositiveThresholds(values) {
  if (!values.length) return [1, 2, 3];
  const sorted = values.slice().sort((a, b) => a - b);
  const max = sorted[sorted.length - 1];
  const distinct = new Set(sorted).size;
  if (distinct < 4) {
    return [max * 0.25, max * 0.5, max * 0.75];
  }
  const at = p => sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))];
  return [at(0.25), at(0.5), at(0.75)];
}

function getHeatmapLevel(entry, metric, thresholds) {
  if (!entry) return "empty";
  const value = metric === "tokens" ? entry.total_tokens : entry.requests;
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  if (value <= 0) return "zero";
  if (value <= thresholds[0]) return "1";
  if (value <= thresholds[1]) return "2";
  if (value <= thresholds[2]) return "3";
  return "4";
}

function formatDayDetailText(dateStr, entry) {
  if (!dateStr) return "悬停或点击任意日期查看详情";
  if (!entry) return `${dateStr}：无记录`;
  const reqPart = `${monitorCount(entry.requests)} 次请求（成功 ${monitorCount(entry.success)} · 失败 ${monitorCount(entry.failed)}）`;
  const inText = Number.isFinite(entry.input_tokens) ? monitorCount(entry.input_tokens) : "未知";
  const cachePart = Number.isFinite(entry.cached_tokens) ? `（含缓存 ${monitorCount(entry.cached_tokens)}）` : "";
  const outText = Number.isFinite(entry.output_tokens) ? monitorCount(entry.output_tokens) : "未知";
  const totalText = Number.isFinite(entry.total_tokens) ? monitorCount(entry.total_tokens) : "未知";
  const unknownPart = Number.isFinite(entry.usage_unknown_turns) && entry.usage_unknown_turns > 0
    ? ` · ${monitorCount(entry.usage_unknown_turns)} 轮用量未知`
    : "";
  return `${dateStr}：${reqPart} · 输入 ${inText}${cachePart} · 输出 ${outText} · 合计 ${totalText} Token${unknownPart}`;
}

function syncDailyControls() {
  for (const days of [30, 90, 365]) {
    const btn = $(`daily-range-${days}`);
    if (!btn) continue;
    const active = dailyDays === days;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
    btn.disabled = dailyLoading;
  }
  const reqBtn = $("daily-metric-requests");
  const tokBtn = $("daily-metric-tokens");
  reqBtn.classList.toggle("is-active", dailyMetric === "requests");
  reqBtn.setAttribute("aria-pressed", String(dailyMetric === "requests"));
  tokBtn.classList.toggle("is-active", dailyMetric === "tokens");
  tokBtn.setAttribute("aria-pressed", String(dailyMetric === "tokens"));
}

function updateDailyDetail(dayMap) {
  const detailEl = $("daily-detail");
  const targetDate = dailyHoverDate || dailySelectedDate;
  const entry = targetDate ? (dayMap.get(targetDate) || null) : null;
  detailEl.textContent = formatDayDetailText(targetDate, entry);
  for (const [dateStr, btn] of dailyCellButtons.entries()) {
    const selected = dateStr === dailySelectedDate;
    btn.classList.toggle("is-selected", selected);
    btn.setAttribute("aria-pressed", String(selected));
  }
}

function renderDaily(nextData) {
  if (nextData !== undefined) {
    if (!nextData || nextData.schema_version !== 1 || !Array.isArray(nextData.days) || !nextData.range) {
      throw new Error("daily schema");
    }
    dailyData = nextData;
    dailyError = "";
  }

  syncDailyControls();

  const alertEl = $("daily-alert");
  const summaryEl = $("daily-summary");
  const heatmapEl = $("daily-heatmap");
  const legendEl = $("daily-legend");
  const detailEl = $("daily-detail");
  const modelSelect = $("daily-model-filter");

  // 错误提示条（含重试按钮）
  if (dailyError) {
    const span = el("span", "", dailyError);
    const retryBtn = el("button", "btn btn-sm", "重试");
    retryBtn.type = "button";
    retryBtn.disabled = dailyLoading;
    retryBtn.addEventListener("click", () => loadDailyUsage(dailyDays));
    alertEl.replaceChildren(span, retryBtn);
    alertEl.hidden = false;
  } else {
    alertEl.replaceChildren();
    alertEl.hidden = true;
  }

  // 同步模型筛选选项
  const models = Array.isArray(dailyData?.models) ? dailyData.models.filter(Boolean) : [];
  if (dailyModel && !models.includes(dailyModel)) dailyModel = "";
  const modelOptSig = JSON.stringify(models);
  if (listSignatures.get(modelSelect) !== modelOptSig) {
    modelSelect.replaceChildren(
      new Option("全部模型", ""),
      ...models.map(m => new Option(m, m)),
    );
    listSignatures.set(modelSelect, modelOptSig);
  }
  if (modelSelect.value !== dailyModel) modelSelect.value = dailyModel;
  modelSelect.disabled = dailyLoading || !models.length;

  if (dailyLoading && !dailyData) {
    summaryEl.replaceChildren();
    heatmapEl.replaceChildren(el("p", "small", "正在加载每日使用统计…"));
    detailEl.textContent = "";
    legendEl.replaceChildren();
    return;
  }

  if (!dailyData) {
    summaryEl.replaceChildren();
    heatmapEl.replaceChildren(el("p", "small", dailyError ? "暂无可展示的每日统计数据。" : "等待加载每日使用统计…"));
    detailEl.textContent = "";
    legendEl.replaceChildren();
    return;
  }

  const startMs = parseIsoDay(dailyData.range.start);
  const endMs = parseIsoDay(dailyData.range.end);
  const rangeDays = Number.isFinite(dailyData.range.days) ? dailyData.range.days : dailyDays;
  const todayStr = dailyData.range.end || "";

  // 构建日期 → 过滤后记录映射（缺失即为「无记录」）
  const dayMap = new Map();
  for (const row of dailyData.days) {
    if (!row?.date) continue;
    const entry = getFilteredDayEntry(row, dailyModel);
    if (entry) dayMap.set(row.date, entry);
  }

  // 汇总统计（未知列保持未知，绝不填成 0）
  let activeDays = 0;
  let sumRequests = 0, sumSuccess = 0, sumFailed = 0, sumUnknownTurns = 0;
  let sumInput = 0, hasInput = false;
  let sumCached = 0, hasCached = false;
  let sumOutput = 0, hasOutput = false;
  let sumTotal = 0, hasTotal = false;
  const positiveMetricValues = [];

  for (const entry of dayMap.values()) {
    activeDays++;
    if (Number.isFinite(entry.requests)) sumRequests += entry.requests;
    if (Number.isFinite(entry.success)) sumSuccess += entry.success;
    if (Number.isFinite(entry.failed)) sumFailed += entry.failed;
    if (Number.isFinite(entry.usage_unknown_turns)) sumUnknownTurns += entry.usage_unknown_turns;
    if (Number.isFinite(entry.input_tokens)) { sumInput += entry.input_tokens; hasInput = true; }
    if (Number.isFinite(entry.cached_tokens)) { sumCached += entry.cached_tokens; hasCached = true; }
    if (Number.isFinite(entry.output_tokens)) { sumOutput += entry.output_tokens; hasOutput = true; }
    if (Number.isFinite(entry.total_tokens)) { sumTotal += entry.total_tokens; hasTotal = true; }
    const mv = dailyMetric === "tokens" ? entry.total_tokens : entry.requests;
    if (Number.isFinite(mv) && mv > 0) positiveMetricValues.push(mv);
  }

  const todayEntry = todayStr ? (dayMap.get(todayStr) || null) : null;

  // 4 张紧凑汇总 KPI 卡
  const kpiTodayReq = el("div", "kpi");
  kpiTodayReq.append(
    el("span", "kpi-label", "今日请求"),
    el("span", "kpi-value", todayEntry ? monitorCount(todayEntry.requests) : "无记录"),
    el("span", "kpi-sub", todayEntry
      ? `成功 ${monitorCount(todayEntry.success)} · 失败 ${monitorCount(todayEntry.failed)}`
      : `${todayStr || "今日"} 暂无本地记录`),
  );

  const kpiTodayTok = el("div", "kpi");
  if (!todayEntry) {
    kpiTodayTok.append(
      el("span", "kpi-label", "今日 Token"),
      el("span", "kpi-value", "无记录"),
      el("span", "kpi-sub", "输入 — · 输出 —"),
    );
  } else {
    const todayIn = Number.isFinite(todayEntry.input_tokens) ? formatCompactTokens(todayEntry.input_tokens) : "未知";
    const todayOut = Number.isFinite(todayEntry.output_tokens) ? formatCompactTokens(todayEntry.output_tokens) : "未知";
    const todayUnk = Number.isFinite(todayEntry.usage_unknown_turns) && todayEntry.usage_unknown_turns > 0
      ? ` · ${todayEntry.usage_unknown_turns} 轮未知`
      : "";
    kpiTodayTok.append(
      el("span", "kpi-label", "今日 Token"),
      el("span", "kpi-value", Number.isFinite(todayEntry.total_tokens) ? formatCompactTokens(todayEntry.total_tokens) : "未知"),
      el("span", "kpi-sub", `入 ${todayIn} · 出 ${todayOut}${todayUnk}`),
    );
  }

  const kpiRange = el("div", "kpi");
  kpiRange.append(el("span", "kpi-label", `近 ${rangeDays} 天累计`));
  if (activeDays === 0) {
    kpiRange.append(
      el("span", "kpi-value", "暂无记录"),
      el("span", "kpi-sub", dailyModel ? `模型 ${dailyModel} 在此区间无记录` : "此区间内无已完成的本地轮次"),
    );
  } else if (dailyMetric === "tokens") {
    kpiRange.append(
      el("span", "kpi-value", hasTotal ? formatCompactTokens(sumTotal) : "未知"),
      el("span", "kpi-sub", `共 ${monitorCount(sumRequests)} 次 · 入 ${hasInput ? formatCompactTokens(sumInput) : "未知"}${hasCached ? `（缓存 ${formatCompactTokens(sumCached)}）` : ""} · 出 ${hasOutput ? formatCompactTokens(sumOutput) : "未知"}`),
    );
  } else {
    kpiRange.append(
      el("span", "kpi-value", `${monitorCount(sumRequests)} 次`),
      el("span", "kpi-sub", `Token ${hasTotal ? formatCompactTokens(sumTotal) : "未知"} · 成功 ${monitorCount(sumSuccess)} / 失败 ${monitorCount(sumFailed)}`),
    );
  }

  const kpiActive = el("div", "kpi");
  kpiActive.append(
    el("span", "kpi-label", "活跃天数 / 活跃日均"),
    el("span", "kpi-value", `${activeDays} / ${rangeDays} 天`),
  );
  if (activeDays === 0) {
    kpiActive.append(el("span", "kpi-sub", "日均：无记录"));
  } else if (dailyMetric === "tokens") {
    const avgTokText = hasTotal ? `日均 ${formatCompactTokens(Math.round(sumTotal / activeDays))} Token` : "日均 Token：未知";
    kpiActive.append(el("span", "kpi-sub", `${avgTokText}${sumUnknownTurns > 0 ? ` · ${sumUnknownTurns} 轮未知` : ""}`));
  } else {
    const avgReq = (sumRequests / activeDays).toFixed(1);
    const avgTok = hasTotal ? `${formatCompactTokens(Math.round(sumTotal / activeDays))} Token/天` : "Token 未知";
    kpiActive.append(el("span", "kpi-sub", `日均 ${avgReq} 次 · ${avgTok}`));
  }

  summaryEl.replaceChildren(kpiTodayReq, kpiTodayTok, kpiRange, kpiActive);

  // 构建 GitHub Contributions 风格日历网格
  dailyCellButtons = new Map();
  if (startMs === null || endMs === null || startMs > endMs) {
    heatmapEl.replaceChildren(el("p", "small", "日期范围无效，无法渲染热力图。"));
    detailEl.textContent = "";
    legendEl.replaceChildren();
    return;
  }

  const thresholds = computePositiveThresholds(positiveMetricValues);
  const calendarDates = [];
  for (let ms = startMs; ms <= endMs; ms += 86_400_000) {
    calendarDates.push({date: formatIsoDay(ms), utcMs: ms, dow: new Date(ms).getUTCDay()});
  }

  // 默认选中今天或最近活跃日期
  const validDateSet = new Set(calendarDates.map(d => d.date));
  if (!dailySelectedDate || !validDateSet.has(dailySelectedDate)) {
    const recordedDates = [...dayMap.keys()].filter(d => validDateSet.has(d)).sort();
    dailySelectedDate = recordedDates.length ? recordedDates[recordedDates.length - 1] : todayStr;
  }
  if (dailyHoverDate && !validDateSet.has(dailyHoverDate)) dailyHoverDate = null;

  const leadingPads = calendarDates[0].dow; // 0=周日 .. 6=周六
  const totalSlots = leadingPads + calendarDates.length;
  const totalWeeks = Math.ceil(totalSlots / 7);

  const board = el("div", "heatmap-board");

  // 月份标签行
  const monthsRow = el("div", "heatmap-months");
  monthsRow.setAttribute("aria-hidden", "true");
  let lastMonth = -1;
  for (let w = 0; w < totalWeeks; w++) {
    const firstSlotIdx = w * 7;
    const dayIdx = firstSlotIdx - leadingPads;
    const sampleIdx = dayIdx < 0 ? 0 : dayIdx;
    const cellInfo = calendarDates[sampleIdx];
    const span = el("span", "heatmap-month-label", "");
    if (cellInfo) {
      const m = new Date(cellInfo.utcMs).getUTCMonth() + 1;
      if (m !== lastMonth) {
        span.textContent = `${m}月`;
        lastMonth = m;
      }
    }
    monthsRow.append(span);
  }
  board.append(monthsRow);

  // 星期列（仅标 一 / 三 / 五，对齐 GitHub 风格）
  const weekdaysCol = el("div", "heatmap-weekdays");
  weekdaysCol.setAttribute("aria-hidden", "true");
  ["", "一", "", "三", "", "五", ""].forEach(label => weekdaysCol.append(el("span", "heatmap-weekday", label)));
  board.append(weekdaysCol);

  // 日期格子网格
  const grid = el("div", "heatmap-grid");
  grid.setAttribute("role", "group");
  grid.setAttribute("aria-label", `近 ${rangeDays} 天每日${dailyMetric === "tokens" ? " Token " : "请求"}热力图`);

  for (let i = 0; i < leadingPads; i++) {
    const pad = el("span", "hm-pad");
    pad.setAttribute("aria-hidden", "true");
    grid.append(pad);
  }

  let hasUnknownCell = false;
  calendarDates.forEach(({date}, idx) => {
    const entry = dayMap.get(date) || null;
    const level = getHeatmapLevel(entry, dailyMetric, thresholds);
    if (level === "unknown") hasUnknownCell = true;
    const btn = el("button", "hm-cell");
    btn.type = "button";
    btn.dataset.date = date;
    btn.dataset.level = level;
    btn.setAttribute("aria-label", formatDayDetailText(date, entry));
    btn.setAttribute("aria-pressed", String(date === dailySelectedDate));
    if (date === dailySelectedDate) btn.classList.add("is-selected");
    btn.addEventListener("mouseenter", () => {
      dailyHoverDate = date;
      updateDailyDetail(dayMap);
    });
    btn.addEventListener("mouseleave", () => {
      if (dailyHoverDate === date) {
        dailyHoverDate = null;
        updateDailyDetail(dayMap);
      }
    });
    btn.addEventListener("focus", () => {
      dailyHoverDate = date;
      updateDailyDetail(dayMap);
    });
    btn.addEventListener("blur", () => {
      if (dailyHoverDate === date) {
        dailyHoverDate = null;
        updateDailyDetail(dayMap);
      }
    });
    btn.addEventListener("click", () => {
      dailySelectedDate = date;
      dailyHoverDate = null;
      updateDailyDetail(dayMap);
    });
    btn.addEventListener("keydown", (event) => {
      let delta = 0;
      if (event.key === "ArrowUp") delta = -1;
      else if (event.key === "ArrowDown") delta = 1;
      else if (event.key === "ArrowLeft") delta = -7;
      else if (event.key === "ArrowRight") delta = 7;
      if (!delta) return;
      const target = calendarDates[idx + delta];
      if (!target) return;
      event.preventDefault?.();
      dailyCellButtons.get(target.date)?.focus?.();
    });
    dailyCellButtons.set(date, btn);
    grid.append(btn);
  });

  board.append(grid);
  heatmapEl.replaceChildren(board);
  if (typeof heatmapEl.scrollWidth === "number" && typeof heatmapEl.clientWidth === "number") {
    heatmapEl.scrollLeft = Math.max(0, heatmapEl.scrollWidth - heatmapEl.clientWidth);
  }

  // 图例（清晰区分无记录 / 零消耗 / 用量未知 / 少→多）
  const addSwatch = (level, label) => {
    const item = el("span", "heatmap-legend-item");
    const box = el("span", "hm-swatch");
    box.dataset.level = level;
    box.setAttribute("aria-hidden", "true");
    item.append(box);
    if (label) item.append(el("span", "", label));
    return item;
  };
  const legendItems = [
    addSwatch("empty", "无记录"),
    addSwatch("zero", dailyMetric === "tokens" ? "0 Token" : "0 次"),
  ];
  if (dailyMetric === "tokens" || hasUnknownCell) {
    legendItems.push(addSwatch("unknown", "用量未知"));
  }
  const scaleWrap = el("span", "heatmap-legend-item");
  scaleWrap.append(el("span", "", "少"));
  for (const lvl of ["1", "2", "3", "4"]) {
    const s = el("span", "hm-swatch");
    s.dataset.level = lvl;
    s.setAttribute("aria-hidden", "true");
    scaleWrap.append(s);
  }
  scaleWrap.append(el("span", "", "多"));
  legendItems.push(scaleWrap);
  legendEl.replaceChildren(...legendItems);

  updateDailyDetail(dayMap);
}

async function loadDailyUsage(days = dailyDays) {
  if (disposed || suspended || !monitorReady) return;
  dailyDays = [30, 90, 365].includes(days) ? days : 90;
  const seq = ++dailyFetchSeq;
  const epoch = refreshEpoch;
  dailyLoading = true;
  dailyError = "";
  renderDaily();
  try {
    const data = await bridge.apiGet(`monitor/daily/${dailyDays}`);
    if (disposed || epoch !== refreshEpoch || seq !== dailyFetchSeq) return;
    dailyLoading = false;
    renderDaily(data);
  } catch (error) {
    if (disposed || epoch !== refreshEpoch || seq !== dailyFetchSeq) return;
    dailyLoading = false;
    if (error?.message === "daily schema") {
      renderDaily();
      return;
    }
    const status = error?.status || error?.statusCode || error?.status_code;
    dailyError = isAuthDeniedError(error)
      ? "无权读取每日统计，请使用 AstrBot 管理员账号登录后重试。"
      : status === 503
        ? "本地统计存储当前不可用（503），请检查插件数据目录权限或磁盘空间后重试。"
        : "每日统计读取失败，请稍后重试。";
    renderDaily();
  }
}

// ---------- 工具权限逐项配置 ----------

function isToolEditable(tool) {
  return Boolean(
    tool
    && tool.capability === "supported"
    && Array.isArray(tool.choices)
    && tool.choices.length > 1
  );
}

function recomputeToolPolicyDirty() {
  const tools = Array.isArray(toolPolicyServer?.tools) ? toolPolicyServer.tools : [];
  toolPolicyDirty = tools.some(t => isToolEditable(t) && toolPolicyDraft[t.id] !== t.policy);
}

function syncToolPolicyFromServer(policyData) {
  if (!policyData || typeof policyData !== "object" || !Array.isArray(policyData.tools)) {
    if (!toolPolicyDirty && !toolPolicySaving) {
      toolPolicyServer = null;
      toolPolicyDraft = {};
      renderToolPolicy();
    }
    return;
  }
  toolPolicyServer = policyData;
  if (!toolPolicyDirty && !toolPolicySaving) {
    const nextDraft = {};
    for (const tool of policyData.tools) {
      if (isToolEditable(tool)) nextDraft[tool.id] = tool.policy;
    }
    toolPolicyDraft = nextDraft;
  }
  recomputeToolPolicyDirty();
  renderToolPolicy();
}

function renderToolPolicy() {
  const masterAlert = $("tool-policy-master-alert");
  const reloadAlert = $("tool-policy-reload-alert");
  const listEl = $("tool-policy-list");
  const feedbackEl = $("tool-policy-feedback");
  const actionsEl = $("tool-policy-actions");
  const dirtyBadge = $("tool-policy-dirty-badge");
  const resetBtn = $("tool-policy-reset");
  const saveBtn = $("tool-policy-save");

  const busy = pending || Boolean(state?.busy) || activeLogin(state?.login);
  const policy = toolPolicyServer;

  // 保存反馈区
  if (toolPolicyFeedback.message) {
    feedbackEl.className = `alert ${toolPolicyFeedback.kind === "ok" ? "alert-ok" : "alert-error"}`;
    feedbackEl.textContent = toolPolicyFeedback.message;
    feedbackEl.hidden = false;
  } else {
    feedbackEl.textContent = "";
    feedbackEl.hidden = true;
  }

  dirtyBadge.hidden = !toolPolicyDirty;

  if (!policy) {
    badge("tool-policy-master-badge", "状态未知", "");
    masterAlert.hidden = true;
    reloadAlert.hidden = true;
    actionsEl.hidden = true;
    const emptySig = "empty-policy";
    if (toolPolicyRenderSig !== emptySig) {
      listEl.replaceChildren(el("p", "small", "尚未获取到工具策略信息，等待后端状态返回。"));
      toolPolicyRenderSig = emptySig;
    }
    return;
  }

  const masterEnabled = policy.enable_tools === true;
  const masterKnown = typeof policy.enable_tools === "boolean";
  badge(
    "tool-policy-master-badge",
    !masterKnown ? "总闸状态未知" : masterEnabled ? "总闸已开启" : "总闸已关闭",
    !masterKnown ? "" : masterEnabled ? "ready" : "warn",
  );

  if (masterKnown && !masterEnabled) {
    masterAlert.textContent = "全局工具总闸当前已关闭，以下工具策略均不生效。如需启用，请在 AstrBot 插件配置中开启工具总闸并重载插件。";
    masterAlert.hidden = false;
  } else {
    masterAlert.hidden = true;
  }

  if (policy.reload_required) {
    reloadAlert.textContent = "已保存新的内置工具策略，请重载插件使其生效。";
    reloadAlert.hidden = false;
  } else {
    reloadAlert.hidden = true;
  }

  const tools = Array.isArray(policy.tools) ? policy.tools : [];
  const hasEditable = tools.some(isToolEditable);
  actionsEl.hidden = !hasEditable;
  resetBtn.disabled = !toolPolicyDirty || toolPolicySaving;
  saveBtn.disabled = !toolPolicyDirty || toolPolicySaving || busy || !state?.csrf;
  saveBtn.textContent = toolPolicySaving ? "保存中…" : "保存策略";

  const sig = JSON.stringify([policy, toolPolicyDraft, toolPolicySaving, busy]);
  if (toolPolicyRenderSig === sig) return;
  toolPolicyRenderSig = sig;

  if (!tools.length) {
    listEl.replaceChildren(el("p", "small", "后端未返回任何工具项。"));
    return;
  }

  // 按 source 动态分组（区分 MCP 与 CLI 内置工具，兼容未来新分组）
  const grouped = new Map();
  for (const tool of tools) {
    const src = typeof tool.source === "string" && tool.source ? tool.source : "other";
    if (!grouped.has(src)) grouped.set(src, []);
    grouped.get(src).push(tool);
  }
  const orderedSources = ["mcp", "builtin", ...[...grouped.keys()].filter(s => s !== "mcp" && s !== "builtin")];

  const groupNodes = [];
  for (const src of orderedSources) {
    const items = grouped.get(src);
    if (!items?.length) continue;
    const secInfo = toolSourceSections[src] || {title: `其他工具（${src}）`, desc: ""};
    const groupEl = el("div", "tool-group");
    const gHead = el("div", "tool-group-head");
    gHead.append(el("h3", "", secInfo.title));
    if (secInfo.desc) gHead.append(el("p", "small", secInfo.desc));
    groupEl.append(gHead);

    const ul = el("div", "tool-list");
    items.forEach((tool) => {
      const row = el("article", "tool-row");
      const top = el("div", "tool-row-top");
      const info = el("div", "tool-row-info");

      const titleRow = el("div", "tool-row-title");
      titleRow.append(el("strong", "", tool.purpose || tool.id || "未命名工具"));
      if (tool.id) titleRow.append(el("code", "", tool.id));

      // 风险徽标
      const riskInfo = toolRiskLabels[tool.risk];
      if (riskInfo) {
        const riskBadge = el("span", "badge", riskInfo.text);
        if (riskInfo.state) riskBadge.dataset.state = riskInfo.state;
        titleRow.append(riskBadge);
      } else if (tool.risk) {
        titleRow.append(el("span", "badge", String(tool.risk)));
      }

      // 能力状态徽标（unverified / unsupported 明确标识）
      if (tool.capability && tool.capability !== "supported") {
        const capInfo = toolCapabilityLabels[tool.capability] || {text: "能力未知", state: "warn"};
        const capBadge = el("span", "badge", capInfo.text);
        if (capInfo.state) capBadge.dataset.state = capInfo.state;
        titleRow.append(capBadge);
      }

      // 生效状态徽标
      let effText = "状态未知", effState = "";
      if (masterKnown && !masterEnabled) {
        effText = "未生效（总闸关闭）";
        effState = "";
      } else if (tool.effective === true) {
        effText = "当前生效";
        effState = "ready";
      } else if (tool.effective === false) {
        effText = policy.reload_required && tool.policy === "allow_once" ? "重载后生效" : "未生效";
        effState = policy.reload_required && tool.policy === "allow_once" ? "warn" : "";
      }
      const effBadge = el("span", "badge", effText);
      if (effState) effBadge.dataset.state = effState;
      titleRow.append(effBadge);

      info.append(titleRow);

      // 不可切换工具的能力说明
      if (tool.capability === "unverified") {
        info.append(el("p", "small", "当前系统环境或 CLI 握手尚未确认支持此工具，保持拒绝，不可开启。"));
      } else if (tool.capability === "unsupported") {
        info.append(el("p", "small", "当前版本或安全边界不支持此工具，保持拒绝，不可开启。"));
      } else if (tool.source === "mcp") {
        info.append(el("p", "small", "工具列表由宿主每轮快照决定，执行仍由宿主审批与隔离。"));
      }

      // 策略控件：仅 capability === "supported" 且 choices.length > 1 时渲染可切换控件
      const controlWrap = el("div", "tool-row-control");
      const editable = isToolEditable(tool);
      const currentVal = editable ? (toolPolicyDraft[tool.id] ?? tool.policy) : tool.policy;

      if (editable) {
        const seg = el("div", "seg-group");
        seg.setAttribute("role", "group");
        seg.setAttribute("aria-label", `${tool.purpose || tool.id} 策略`);
        tool.choices.forEach((choice) => {
          const btn = el("button", "seg-btn", toolPolicyChoiceLabels[choice] || choice);
          btn.type = "button";
          const active = currentVal === choice;
          btn.classList.toggle("is-active", active);
          if (active && choice === "allow_once" && tool.risk === "high") btn.classList.add("is-danger");
          btn.setAttribute("aria-pressed", String(active));
          btn.disabled = toolPolicySaving || busy;
          btn.addEventListener("click", () => {
            toolPolicyDraft[tool.id] = choice;
            recomputeToolPolicyDirty();
            if (toolPolicyFeedback.kind === "ok") toolPolicyFeedback = {message: "", kind: ""};
            renderToolPolicy();
          });
          seg.append(btn);
        });
        controlWrap.append(seg);
      } else {
        const roLabel = tool.source === "mcp"
          ? `${toolPolicyChoiceLabels[currentVal] || currentVal || "未知"}（宿主管控）`
          : `${toolPolicyChoiceLabels[currentVal] || currentVal || "拒绝"}（只读）`;
        controlWrap.append(el("span", "policy-readonly", roLabel));
      }

      top.append(info, controlWrap);
      row.append(top);

      // 高风险警示
      if (tool.risk === "high" && (editable || currentVal === "allow_once")) {
        const warnText = currentVal === "allow_once"
          ? "高风险警示：单次允许仅绑定当前轮 ACP 请求，并与宿主 MCP 共用调用次数上限；仍建议仅在受控工作区按需启用。"
          : "高风险内置工具：默认拒绝；开启单次允许前请确认了解其访问范围。";
        row.append(el("div", "tool-risk-note", warnText));
      }

      ul.append(row);
    });

    groupEl.append(ul);
    groupNodes.push(groupEl);
  }

  listEl.replaceChildren(...groupNodes);
}

async function saveToolPolicy() {
  if (disposed || !state?.csrf || !toolPolicyServer || toolPolicySaving || !toolPolicyDirty) return;
  const tools = Array.isArray(toolPolicyServer.tools) ? toolPolicyServer.tools : [];
  const payload = {csrf: state.csrf};
  let count = 0;
  for (const tool of tools) {
    if (isToolEditable(tool)) {
      payload[tool.id] = toolPolicyDraft[tool.id] ?? tool.policy;
      count++;
    }
  }
  if (!count) return;

  toolPolicySaving = true;
  toolPolicyFeedback = {message: "", kind: ""};
  renderToolPolicy();
  try {
    const saved = await bridge.apiPost("setup/tool-policy", payload);
    if (disposed) return;
    if (!saved || typeof saved !== "object" || !Array.isArray(saved.tools)) {
      throw new Error("返回的工具策略格式异常");
    }
    toolPolicySaving = false;
    toolPolicyServer = saved;
    if (state) state.tool_policy = saved;
    const nextDraft = {};
    for (const tool of saved.tools) {
      if (isToolEditable(tool)) nextDraft[tool.id] = tool.policy;
    }
    toolPolicyDraft = nextDraft;
    toolPolicyDirty = false;
    toolPolicyFeedback = {
      message: saved.reload_required ? "工具策略已保存，请重载插件使其生效。" : "工具策略已保存。",
      kind: "ok",
    };
    renderToolPolicy();
    toast("工具策略已保存", "ok");
  } catch (error) {
    if (disposed) return;
    toolPolicySaving = false;
    // 保存失败：严格保留 toolPolicyDraft 与 toolPolicyDirty，不丢失用户编辑内容
    const status = error?.status || error?.statusCode || error?.status_code;
    const msg = status === 403
      ? "保存失败：登录态或安全令牌已过期，请刷新页面后重试（已保留当前编辑内容）。"
      : `${error?.message || "保存工具策略失败"}（已保留当前编辑内容，可修正后重试）`;
    toolPolicyFeedback = {message: msg, kind: "error"};
    renderToolPolicy();
  }
}

function resetToolPolicyDraft() {
  if (!toolPolicyServer || toolPolicySaving) return;
  const nextDraft = {};
  for (const tool of toolPolicyServer.tools || []) {
    if (isToolEditable(tool)) nextDraft[tool.id] = tool.policy;
  }
  toolPolicyDraft = nextDraft;
  toolPolicyDirty = false;
  toolPolicyFeedback = {message: "", kind: ""};
  renderToolPolicy();
}

// ---------- 管理员指令帮助弹窗 ----------

function renderCommandsModal() {
  const list = $("commands-list");
  if (listSignatures.get(list) === "rendered") return;
  list.replaceChildren(...adminCommands.map((item) => {
    const row = el("div", "command-row");
    const main = el("div", "command-main");
    main.append(el("code", "command-code", item.cmd), el("span", "small", item.desc));
    const btn = el("button", "btn btn-ghost btn-sm", "复制");
    btn.type = "button";
    btn.addEventListener("click", () => copyText(item.copy, btn));
    row.append(main, btn);
    return row;
  }));
  listSignatures.set(list, "rendered");
}

function openCommandsModal() {
  renderCommandsModal();
  commandsModalOpen = true;
  $("modal-commands").hidden = false;
  $("commands-close").focus?.();
}

function closeCommandsModal() {
  if (!commandsModalOpen) return;
  commandsModalOpen = false;
  $("modal-commands").hidden = true;
  $("open-commands").focus?.();
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
    const denied = isAuthDeniedError(error);
    $("monitor").dataset.stale = "true";
    badge("monitor-badge", "数据过期", "error");
    $("monitor-message").textContent = denied
      ? "无权读取监控，请使用 AstrBot 管理员账号登录后刷新。"
      : monitorSnapshot ? "监控读取失败，以下为过期快照。" : "暂时无法读取监控数据，请稍后刷新。";
    if (denied) {
      $("monitor-instances").replaceChildren();
      monitorSnapshot = undefined;
      monitorSignature = undefined;
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

function syncEffortOptions(selectedModel, preferredValue) {
  const efforts = cachedEffortsByModel[selectedModel] || state?.report?.efforts || ["low", "medium", "high"];
  const validEfforts = efforts.filter(e => ["low", "medium", "high"].includes(e));
  const effortKey = JSON.stringify([selectedModel, validEfforts, state?.global_effort]);
  const allowed = ["default", ...validEfforts];
  const previous = preferredValue ?? $("effort").value;
  if (effortSignature !== effortKey) {
    $("effort").replaceChildren(
      new Option(globalEffortText(state?.global_effort), "default"),
      ...validEfforts.map(e => new Option(effortLabels[e] || e, e)),
    );
    effortSignature = effortKey;
  }
  const target = allowed.includes(previous) ? previous : "default";
  if ($("effort").value !== target) $("effort").value = target;
}

function syncFormValidation() {
  const m = $("model").value;
  const e = $("effort").value;
  const mode = $("tools-mode").value;
  const providers = state?.providers || [];
  const editingRow = editingProviderId ? providers.find(p => p.id === editingProviderId) : null;

  $("form-model-warn").hidden = !(editingRow && editingRow.model !== m);
  const dup = providers.some(p =>
    p.id !== editingProviderId
    && p.model === m
    && (p.thought_level || "default") === e
    && (p.tools_mode || "inherit") === mode
  );
  $("form-dup-warn").hidden = !dup;

  const busy = pending || Boolean(state?.busy) || activeLogin(state?.login);
  const passed = state?.report?.status === "passed";
  const allowSubmit = !busy && Boolean(m) && !dup && (Boolean(editingProviderId) || passed);
  $("apply").disabled = !allowSubmit;
}

function openAddModal() {
  if (!state) return;
  editingProviderId = null;
  formModalOpen = true;
  $("modal-form-title").textContent = "添加模型";
  $("form-id-row").hidden = true;
  $("use-default-row").hidden = false;
  $("use-default").checked = false;
  $("tools-mode").value = "chat";
  syncEffortOptions($("model").value, "default");
  syncFormValidation();
  $("modal-form").hidden = false;
}

function openEditModal(providerId) {
  if (!state) return;
  const row = (state.providers || []).find(p => p.id === providerId);
  if (!row) return;
  editingProviderId = providerId;
  formModalOpen = true;
  $("modal-form-title").textContent = "编辑模型";
  $("form-id-row").hidden = false;
  $("form-id-val").textContent = providerId;
  $("use-default-row").hidden = true;

  if (cachedModels.some(m => m.id === row.model)) {
    $("model").value = row.model;
  }
  syncEffortOptions($("model").value, ["default", "low", "medium", "high"].includes(row.thought_level) ? row.thought_level : "default");
  $("tools-mode").value = ["chat", "inherit", "tools"].includes(row.tools_mode) ? row.tools_mode : "inherit";
  syncFormValidation();
  $("modal-form").hidden = false;
}

function closeFormModal() {
  formModalOpen = false;
  $("modal-form").hidden = true;
  editingProviderId = null;
}

function closeImpactModal() {
  $("modal-impact").hidden = true;
  impactContext = null;
}

async function openImpactModal(providerId, op) {
  if (!state || pending) return;
  const row = (state.providers || []).find(p => p.id === providerId);
  if (!row) return;
  try {
    const resp = await bridge.apiPost("setup/provider-impact", {csrf: state.csrf, provider_id: providerId});
    const impact = resp?.impact;
    if (!impact || disposed) return;
    impactContext = {providerId, op, impact};

    $("impact-title").textContent = op === "delete" ? `删除 ${row.model}` : `停用 ${row.model}`;
    const refs = impact.references || {};
    $("impact-kv").replaceChildren(...[
      ["全局默认引用", impact.requires_migration ? "是" : "否"],
      ["Fallback 引用", `${refs.fallback || 0} 处`],
      ["辅助配置引用", `${refs.auxiliary || 0} 处`],
      ["已观测会话绑定", `${refs.observed_session_overrides || 0} 个`],
    ].map(([k, v]) => {
      const line = el("div", "impact-row");
      line.append(el("span", "small", k), el("strong", "", v));
      return line;
    }));

    const migWrap = $("impact-mig-wrap");
    const migSelect = $("impact-mig-select");
    if (impact.requires_migration) {
      const candidates = Array.isArray(impact.replacement_candidates) ? impact.replacement_candidates : [];
      migSelect.replaceChildren(
        ...candidates.map(c => new Option(
          c.is_acp ? `${c.model} (${effortLabels[c.thought_level] || c.thought_level} · ${c.id})` : `${c.model} (${c.id})`,
          c.id,
        )),
        new Option("置空默认（可能触发隐式回退）", "__NONE__"),
      );
      migWrap.hidden = false;
    } else {
      migSelect.replaceChildren();
      migWrap.hidden = true;
    }

    const btn = $("impact-confirm");
    btn.className = `btn ${op === "delete" ? "btn-danger-soft" : "btn-warn-soft"}`;
    btn.textContent = op === "delete" ? "确认删除" : "确认停用";
    $("modal-impact").hidden = false;
  } catch (error) {
    showError(error?.message || "读取影响范围失败。");
  }
}

function render(data) {
  const prevBusy = Boolean(state?.busy);
  const prevLoginBusy = activeLogin(state?.login);
  data = {...data, report: data.report || {}, login: data.login || {}, environment: data.environment || {}, providers: Array.isArray(data.providers) ? data.providers : []};
  state = data;
  const r = data.report, login = data.login;
  renderRouting(data.routing ?? monitorSnapshot?.routing);
  renderAlerts(data);
  syncToolPolicyFromServer(data.tool_policy);
  renderQuota();
  const busy = pending || data.busy || activeLogin(login);
  const passed = r.status === "passed";

  if (Array.isArray(r.models) && r.models.length) cachedModels = r.models;
  else if (Array.isArray(data.cached_models) && data.cached_models.length) cachedModels = data.cached_models;
  else if (!busy && r.status === "blocked" && ["NOT_INSTALLED", "COMMAND_NOT_FOUND", "AUTH", "NO_MODELS"].includes(r.error_code)) {
    cachedModels = [];
  }
  if (data.efforts_by_model && typeof data.efforts_by_model === "object") {
    cachedEffortsByModel = {...cachedEffortsByModel, ...data.efforts_by_model};
  }
  if (r.selected_model && Array.isArray(r.efforts)) {
    cachedEffortsByModel[r.selected_model] = r.efforts;
  }
  const models = cachedModels;

  renderSetupProgress(data, passed);
  setConnection(busy ? "正在同步…" : "已连接 AstrBot", busy ? "busy" : "ok");
  $("environment").textContent = `${data.environment.system} · Python ${data.environment.python}${data.environment.container ? " · 容器环境" : ""}`;
  $("discovery-hint").textContent = data.environment.discovery_hint || "";
  $("install-hint").textContent = data.environment.install_hint;
  setInputValue("install-url", data.environment.install_url);
  setInputValue("install-command", data.environment.install_command);

  $("facts").replaceChildren(...[
    r.cli_version ? `CLI ${r.cli_version}` : null,
    r.model_count != null ? `${r.model_count} 个可用模型` : null,
    Number.isInteger(r.exit_code) ? `CLI 退出码：${r.exit_code}` : null,
    r.error_code && stages[r.stage] ? `失败阶段：${stages[r.stage]}` : null,
  ].filter(Boolean).map(text => el("span", "fact", text)));

  $("global-policy-summary").textContent = `插件全局策略：思考 ${effortLabels[data.global_effort] || data.global_effort} · 工具 ${data.global_enable_tools ? "开启" : "关闭"} · 识图 ${data.global_enable_images ? "开启" : "关闭"}`;

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

  // 弹窗打开期间不覆盖用户正在编辑的表单选项
  const modalOpen = formModalOpen;
  const signature = JSON.stringify(models);
  if (modelSignature !== signature && !modalOpen) {
    const previous = $("model").value;
    $("model").replaceChildren(new Option(models.length ? "请选择模型" : "先完成环境检测", ""), ...models.map(m => new Option(m.name, m.id)));
    const preferred = [previous, r.selected_model, data.providers[0]?.model].find(id => models.some(m => m.id === id));
    if (preferred) $("model").value = preferred;
    modelSignature = signature;
  }
  const selected = $("model").value;
  if (!modalOpen) {
    syncEffortOptions(selected);
  }
  $("model").disabled = busy || !models.length;
  $("effort").disabled = busy || !selected;
  if (!$("tools-mode").value) $("tools-mode").value = "chat";
  $("tools-mode").disabled = busy || !selected;
  $("use-default").disabled = busy;
  $("refresh-catalog").disabled = busy;
  $("open-add-model").disabled = busy || !passed || !models.length;
  syncFormValidation();

  badge("model-badge", models.length ? `${models.length} 个可用` : "等待登录", passed ? "ready" : "");
  const configured = data.providers;
  badge("finish-badge", data.result?.applied || data.result?.provider_id ? "已保存" : configured.length ? `${configured.length} 项` : "等待配置", configured.length ? "ready" : "");
  $("finish-hint").textContent = data.result?.default_selected
    ? "已同步设为全局默认模型。"
    : data.result?.provider_id && data.action_error ? "实例已保存；全局默认切换未确认，请核对路由。"
    : data.result?.model_changed ? "已更新底层模型，将在下轮对话重建会话。"
    : "";

  const providerKey = JSON.stringify([configured, data.global_effort, busy]);
  if (providerSignature !== providerKey) {
    if (!configured.length) {
      $("configured").replaceChildren(el("p", "small", passed ? "尚未添加模型，点击右上角「添加模型」。" : "请先在「环境与认证」完成登录。"));
    } else {
      $("configured").replaceChildren(...configured.map(row => {
        const wrapper = el("div", "provider");
        const pHead = el("div", "provider-head");
        const titleGroup = el("div", "provider-title-group");
        titleGroup.append(el("strong", "", row.model || row.id));
        if (row.is_default) {
          const defBadge = el("span", "badge", "默认");
          defBadge.dataset.state = "primary";
          titleGroup.append(defBadge);
        }
        const statusBadge = el("span", "badge", row.enabled ? "已启用" : "已停用");
        if (row.enabled) statusBadge.dataset.state = "ready";
        titleGroup.append(statusBadge);
        if (row.config_drifted) {
          const driftBadge = el("span", "badge", "需同步");
          driftBadge.dataset.state = "warn";
          titleGroup.append(driftBadge);
        }

        const actions = el("div", "provider-actions");
        if (row.config_drifted) {
          const repairBtn = el("button", "btn btn-warn-soft btn-sm", "修复");
          repairBtn.type = "button";
          repairBtn.disabled = busy;
          repairBtn.addEventListener("click", () => action("provider-repair", {provider_id: row.id}));
          actions.append(repairBtn);
        }
        if (!row.is_default) {
          const defBtn = el("button", "btn btn-sm", "设为默认");
          defBtn.type = "button";
          defBtn.disabled = busy || !row.enabled;
          defBtn.addEventListener("click", () => action("provider-default", {provider_id: row.id, confirm: true}));
          actions.append(defBtn);
        }
        const editBtn = el("button", "btn btn-ghost btn-sm", "编辑");
        editBtn.type = "button";
        editBtn.disabled = busy;
        editBtn.addEventListener("click", () => openEditModal(row.id));
        actions.append(editBtn);

        const toggleBtn = el("button", "btn btn-ghost btn-sm", row.enabled ? "停用" : "启用");
        toggleBtn.type = "button";
        toggleBtn.disabled = busy;
        toggleBtn.addEventListener("click", () => {
          if (row.enabled) openImpactModal(row.id, "disable");
          else action("provider-toggle", {provider_id: row.id, enabled: true, confirm: true});
        });
        actions.append(toggleBtn);

        const delBtn = el("button", "btn btn-danger-soft btn-sm", "删除");
        delBtn.type = "button";
        delBtn.disabled = busy;
        delBtn.addEventListener("click", () => openImpactModal(row.id, "delete"));
        actions.append(delBtn);

        pHead.append(titleGroup, actions);

        const meta = el("div", "provider-meta");
        const metaLeft = el("span", "");
        metaLeft.append(
          `${formatEffortBadge(row.thought_level || "default", data.global_effort)} · ${toolsModeLabels[row.tools_mode] || "跟随总闸"} · `,
          el("code", "", row.id),
        );
        const copyBtn = el("button", "btn btn-ghost btn-sm", "复制 /agy use");
        copyBtn.type = "button";
        copyBtn.addEventListener("click", () => copyText(`/agy use ${row.id}`, copyBtn));
        meta.append(metaLeft, copyBtn);

        wrapper.append(pHead, meta);
        return wrapper;
      }));
    }
    providerSignature = providerKey;
  }

  if (data.action_error) showError(`${data.action_error}：${data.action_hint}`);
  if (monitorSnapshot) renderMonitor(monitorSnapshot);
  if ((prevBusy && !data.busy) || (prevLoginBusy && !activeLogin(login))) {
    if (monitorReady) {
      refreshMonitor();
      refreshQuotaCache();
    }
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
    if (!data.busy && monitorReady) refreshMonitor();
  } catch (error) {
    if (disposed) return;
    pending = false; render(state); showError(error?.message || "请求失败，请刷新页面。");
  }
}

$("theme-toggle").onclick = cycleTheme;
$("open-commands").onclick = openCommandsModal;
$("commands-close").onclick = closeCommandsModal;
$("tab-btn-monitor").onclick = () => switchTab("monitor");
$("tab-btn-models").onclick = () => switchTab("models");
$("tab-btn-tools").onclick = () => switchTab("tools");
$("tab-btn-setup").onclick = () => switchTab("setup");
$("goto-models").onclick = () => switchTab("models");
$("tool-policy-goto-models").onclick = () => switchTab("models");
$("monitor-refresh").onclick = () => {
  refreshMonitor();
  loadDailyUsage(dailyDays);
};
$("quota-refresh").onclick = refreshQuotaManual;
$("daily-range-30").onclick = () => { if (dailyDays !== 30) loadDailyUsage(30); };
$("daily-range-90").onclick = () => { if (dailyDays !== 90) loadDailyUsage(90); };
$("daily-range-365").onclick = () => { if (dailyDays !== 365) loadDailyUsage(365); };
$("daily-metric-requests").onclick = () => {
  if (dailyMetric !== "requests") { dailyMetric = "requests"; renderDaily(); }
};
$("daily-metric-tokens").onclick = () => {
  if (dailyMetric !== "tokens") { dailyMetric = "tokens"; renderDaily(); }
};
$("daily-model-filter").onchange = () => {
  dailyModel = $("daily-model-filter").value;
  renderDaily();
};
$("tool-policy-save").onclick = saveToolPolicy;
$("tool-policy-reset").onclick = resetToolPolicyDraft;
$("check").onclick = () => action("check");
$("refresh-catalog").onclick = () => action("check");
$("open-add-model").onclick = openAddModal;
$("modal-close").onclick = closeFormModal;
$("modal-cancel").onclick = closeFormModal;
$("impact-close").onclick = closeImpactModal;
$("impact-cancel").onclick = closeImpactModal;
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
  syncEffortOptions($("model").value, "default");
  syncFormValidation();
};
$("effort").onchange = syncFormValidation;
$("tools-mode").onchange = syncFormValidation;
$("model-form").onsubmit = event => {
  event.preventDefault();
  const payload = {
    model: $("model").value,
    effort: $("effort").value,
    tools_mode: $("tools-mode").value || "chat",
  };
  if (editingProviderId) {
    const targetId = editingProviderId;
    closeFormModal();
    action("provider-update", {provider_id: targetId, ...payload});
  } else {
    const useDefault = $("use-default").checked;
    closeFormModal();
    action("apply", {...payload, use_default: useDefault, create_only: true});
  }
};
$("impact-confirm").onclick = () => {
  if (!impactContext) return;
  const {providerId, op, impact} = impactContext;
  const payload = {provider_id: providerId, confirm: true, force_confirm: true};
  if (impact.requires_migration) {
    const chosen = $("impact-mig-select").value;
    payload.migrate_default_to = chosen === "__NONE__" ? "" : chosen;
  }
  closeImpactModal();
  if (op === "delete") action("provider-delete", payload);
  else action("provider-toggle", {...payload, enabled: false});
};

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (commandsModalOpen) closeCommandsModal();
  else if (impactContext) closeImpactModal();
  else if (formModalOpen) closeFormModal();
});

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
  clearTimeout(quotaCountdownTimer);
  pollPending = false;
  monitorPending = false;
}

function resumeRefresh() {
  if (disposed || suspended || document.hidden || !monitorReady) return;
  poll();
  refreshMonitor();
  scheduleQuotaCountdown();
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
  quotaSnapshot = null;
  dailyData = null;
  toolPolicyServer = null;
  toolPolicyDraft = {};
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
  badge("quota-badge", "不可用");
  $("quota-body").replaceChildren(el("div", "quota-empty", "请从 AstrBot 管理面板打开后查看账号额度。"));
} else {
  try {
    await bridge.ready();
    if (!disposed) {
      monitorReady = true;
      applyTheme();
      switchTab("monitor");
      renderQuota();
      renderToolPolicy();
      refreshMonitor();
      refreshQuotaCache();
      loadDailyUsage(dailyDays);
      await poll();
    }
  } catch (error) {
    setConnection("面板连接失败", "error");
    showError(error.message || "面板连接失败。");
    badge("monitor-badge", "不可用", "error");
    $("monitor-message").textContent = "面板连接失败，请刷新页面。";
  }
}
