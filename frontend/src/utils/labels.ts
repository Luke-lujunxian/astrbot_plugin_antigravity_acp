export const STAGE_LABELS: Record<string, string> = {
  discovery: '查找 CLI',
  isolation: '检查隔离目录',
  authentication: '检查认证',
  initialize: 'ACP 握手',
  'session/new': '验证登录',
  model_catalog: '读取模型目录',
  model_selection: '检查模型档位',
  complete: '检查通过',
  configuration: '检查配置',
  interrupted: '已中断',
};

export const LOGIN_STATE_LABELS: Record<string, string> = {
  idle: '等待登录',
  starting: '正在启动',
  waiting: '等待授权',
  verifying: '正在验证',
  complete: '登录已验证',
  failed: '登录未完成',
  cancelled: '已取消',
};

export const INSTALL_ERROR_LABELS: Record<string, string> = {
  NOT_INSTALLED: '未找到 CLI',
  COMMAND_NOT_FOUND: '配置路径无效',
  STARTUP_EXIT: '握手前退出',
  CLI_WRAPPER: '启动脚本不兼容',
};

export const REBUILD_REASON_LABELS: Record<string, string> = {
  no_identity: '无会话标识',
  abort: '请求中止',
  previous_error: '上轮异常',
  upstream_compaction_detected: '上游疑似压缩',
  process_dead: '进程退出',
  idle_expired: '空闲超时',
  pool_evicted: '池淘汰',
  runtime_restart: '运行时重启',
  cold_start: '冷启动',
  system_changed: '系统提示变更',
  model_changed: '模型变更',
  effort_changed: '思考强度变更',
  tool_hash_changed: '工具变更',
  tool_ledger_limit: '工具账本上限',
  history_rewrite: '历史重写',
  history_host_trim: '历史裁剪',
  history_append_gap: '历史断层',
  unknown: '未知原因',
};

export const TOOLS_MODE_LABELS: Record<string, string> = {
  chat: '纯聊天',
  inherit: '跟随全局',
  tools: '工具模式',
  invalid: '无效配置',
};

export const EFFORT_LABELS: Record<string, string> = {
  default: '跟随全局',
  low: '低 (low)',
  medium: '中 (medium)',
  high: '高 (high)',
};

export const TURN_STATUS_LABELS: Record<string, string> = {
  ok: '成功',
  error: '失败',
  cancelled: '取消',
  short_circuited: '预检/熔断拦截',
  unknown: '未知',
};

export const TRANSPORT_LABELS: Record<string, string> = {
  loopback_hmac: '本机认证连接 (loopback HMAC)',
  unix_socket: 'Unix Socket',
  unsupported: '当前平台不支持',
};

export const SUPERVISION_LABELS: Record<string, string> = {
  windows_job: 'Windows Job Object',
  windows_taskkill_fallback: 'taskkill 回退',
  posix_process_group: '独立进程组',
};

export const MINIMAL_TOOLS_LABELS: Record<string, string> = {
  inactive: '未启用精简',
  flag_available_unverified: '支持参数（待验收）',
  unsupported: 'CLI 不支持',
};

export const RESOLUTION_REASON_LABELS: Record<string, string> = {
  configured_primary: '按配置主 ID 解析',
  implicit_first_provider: '悬空主 ID（宿主隐式选首项）',
  missing_primary: '无可用主模型实例',
  non_local_runner: '非本地 Runner',
  unknown: '未知',
};

export const FALLBACK_REASON_LABELS: Record<string, string> = {
  no_visible_prefix: '无可见正文前缀（允许宿主回退）',
  visible_prefix: '已有可见正文前缀（禁止重放）',
  tool_handoff: '已交接宿主工具（禁止重放）',
  tool_continuation: '已进入工具续轮（禁止重放）',
};

export const BLOCK_REASON_LABELS: Record<string, string> = {
  referenced: '存在配置或已观测引用',
  incomplete_scan: '扫描边界不完整（无法枚举所有会话覆盖）',
};

export const FAULT_LABELS: Record<string, string> = {
  RATE_LIMIT: '请求受限',
  QUOTA: '额度不足',
  AUTH: '认证失败',
  AUTH_BRIDGE: '认证桥接失败',
  TIMEOUT: '请求超时',
  NETWORK: '网络异常',
  PROXY: '代理异常',
  PROXY_AUTH: '代理认证失败',
  TLS: '证书/TLS 异常',
  TRANSPORT: '传输中断',
  BACKPRESSURE: '并发过载',
  BUSY: '实例忙碌',
  CANCELLED: '已取消',
  EMPTY: '空响应',
  UPSTREAM: '上游异常',
  PROTOCOL: '协议异常',
  OUTPUT_LIMIT: '输出超限',
  INPUT_LIMIT: '输入超限',
  PERMISSION: '权限不足',
  LAUNCH: '启动失败',
  NOT_INSTALLED: '未找到 CLI',
  COMMAND_NOT_FOUND: '配置路径无效',
  STARTUP_EXIT: '握手前退出',
  CLI_WRAPPER: '启动脚本不兼容',
  NO_MODELS: '无可用模型',
  MODEL: '模型不可用',
  CLOSED: '插件已停用',
  LOCAL: '本地操作失败',
  HOST: '宿主配置操作失败',
  ROUTE_MISMATCH: '全局路由未匹配',
  REFERENCE_BLOCKED: '受引用或扫描边界阻止',
  TOOL_PERMISSION: '工具权限拒绝',
  TOOL_SCHEMA: '工具参数校验失败',
  TOOL_TIMEOUT: '工具等待超时',
  TOOL_BUDGET: '工具调用超限',
  TOOL_PROTOCOL: '工具协议异常',
  TOOLS_DISABLED: '工具已禁用',
};

export const ACTION_ERROR_LABELS: Record<string, string> = {
  ...FAULT_LABELS,
  LOGIN_EXPIRED: '登录已过期',
  LOGIN_URL: '授权链接异常',
  UNSUPPORTED: '不支持此操作',
  CONFIG: '配置错误',
  IMAGE: '图片处理失败',
};

export function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

export function actionErrorLabel(code: string): string {
  const label = hasOwn(ACTION_ERROR_LABELS, code) ? ACTION_ERROR_LABELS[code] : '操作失败';
  return `${label}（${code}）`;
}

export function formatFaultBrief(code: string): string {
  const label = hasOwn(FAULT_LABELS, code) ? FAULT_LABELS[code] : '';
  return label ? `${label} (${code})` : code;
}

export function labelOf(dict: Record<string, string>, key: string | null | undefined, fallback = '未知'): string {
  if (!key) return fallback;
  return hasOwn(dict, key) ? dict[key] : key;
}
