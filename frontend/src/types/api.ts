export interface AstrBotBridgeThemePayload {
  primary?: string;
  secondary?: string;
  colors?: {
    primary?: string;
    secondary?: string;
  };
}

export interface AstrBotBridgeContext {
  pluginName?: string;
  displayName?: string;
  pageName?: string;
  pageTitle?: string;
  locale?: string;
  i18n?: Record<string, unknown>;
  isDark?: boolean;
  // Optional forward-compatible capability fields (absent in AstrBot v4.29.4).
  theme?: AstrBotBridgeThemePayload;
  colors?: {
    primary?: string;
    secondary?: string;
  };
  primaryColor?: string;
  secondaryColor?: string;
}

export interface AstrBotPluginBridge {
  ready(): Promise<AstrBotBridgeContext | null>;
  getContext?(): AstrBotBridgeContext | null;
  getLocale?(): string;
  getI18n?(): Record<string, unknown>;
  t?(key: string, fallback?: string): string;
  onContext?(handler: (ctx: AstrBotBridgeContext | null) => void): () => void;
  apiGet<T = unknown>(endpoint: string, params?: Record<string, unknown>): Promise<T>;
  apiPost<T = unknown>(endpoint: string, body?: Record<string, unknown>): Promise<T>;
}

export interface ModelCatalogItem {
  id: string;
  name: string;
}

export interface ProbeCapabilities {
  mcpCapabilities?: {
    http?: boolean;
    sse?: boolean;
  };
  promptCapabilities?: {
    image?: boolean;
    audio?: boolean;
    embeddedContext?: boolean;
  };
}

export interface ProbeCliFlags {
  disable_telemetry?: boolean;
  include_default_customizations?: boolean;
}

export interface ProbeReport {
  report_version?: number;
  status?: string;
  stage?: string;
  error_code?: string;
  exit_code?: number | null;
  cli_version?: string;
  cli_flags?: ProbeCliFlags;
  minimal_tools_status?: string;
  customizations_mode?: string;
  proxy_mode?: string;
  auth_bridge?: boolean;
  model_catalog?: string;
  model_prompt_sent?: boolean;
  mcp_loading?: string;
  host_tool_loop?: string;
  cli_update_status?: string;
  cli_update_policy?: string;
  tool_bridge_transport?: string;
  process_supervision?: string;
  protocol_version?: number;
  advertised_capabilities?: ProbeCapabilities;
  model_count?: number | null;
  models?: ModelCatalogItem[];
  selected_model?: string;
  efforts?: string[];
}

export interface EnvironmentInfo {
  system?: string;
  python?: string;
  container?: boolean;
  proxy_mode_note?: string;
  discovery_hint?: string;
  install_url?: string;
  install_command?: string;
  install_hint?: string;
}

export interface LoginSnapshot {
  state?: string;
  busy?: boolean;
  error_code?: string;
  owned?: boolean;
  ticket?: string;
  url?: string;
  expires_in?: number;
}

export interface ConfiguredProvider {
  id: string;
  model: string;
  enabled: boolean;
  tools_mode?: string;
  effective_tools?: boolean;
}

export interface RoutingSnapshot {
  scope: string;
  configured_primary_id: string | null;
  primary_exists: boolean | null;
  primary_enabled: boolean | null;
  resolved_primary_id: string | null;
  is_acp: boolean | null;
  resolution_reason: string;
  explicit_fallback_ids: string[];
  invalid_fallback_ids: string[];
  last_observed_provider_id: string | null;
  last_observed_at: string | null;
  last_observed_scope: string;
}

export interface ProviderImpactReferences {
  primary: number;
  fallback: number;
  auxiliary: number;
  observed_session_overrides: number;
  global_resolved: boolean | null;
}

export interface ProviderImpact {
  provider_id: string;
  enabled: boolean;
  references: ProviderImpactReferences;
  profiles_scanned: number;
  session_scan: string;
  auxiliary_scan: string;
  can_delete: boolean;
  can_disable: boolean;
  block_reason: 'referenced' | 'incomplete_scan' | string;
}

export interface SetupApplyResult {
  provider_id: string;
  model?: string;
  tools_mode?: string;
  default_selected?: boolean;
  provider_state?: 'created' | 'existing' | string;
  applied?: boolean;
  impact?: ProviderImpact;
}

export interface SetupSnapshot {
  csrf: string;
  busy: boolean;
  operation: string;
  report: ProbeReport;
  hint: string;
  environment: EnvironmentInfo;
  login: LoginSnapshot;
  providers: ConfiguredProvider[];
  result: SetupApplyResult | null;
  routing: RoutingSnapshot | null;
  action_error: string;
  action_hint: string;
  global_effort: string;
  global_enable_tools?: boolean;
}

export interface MonitorPool {
  active_sessions: number;
  max_sessions: number;
  live_processes: number;
  active_tool_turns: number;
}

export interface MonitorSummary {
  total_turns: number;
  request_sent_turns: number;
  success_turns: number;
  failed_turns: number;
  reuse_rate: number | null;
  cache_token_ratio: number | null;
  unavailable_usage_turns: number;
  reported_usage_turns: number;
  missing_cache_field_turns: number;
  total_input_other: number | null;
  total_input_cached: number | null;
  total_output: number | null;
  rebuild_reasons: Array<[string, number]>;
}

export interface LatestContext {
  context_used: number | null;
  context_window_size: number | null;
  observed_at: string | null;
  source?: string;
  scope?: string;
  model?: string;
}

export interface Content429Candidate {
  system_hash8: string | null;
  system_bytes: number | null;
  has_output: boolean;
  attempt: number | null;
}

export interface TurnExtendedFields {
  turn_id?: string | null;
  origin_turn_id?: string | null;
  logical_request_tag?: string | null;
  attempt?: number | null;
  cli_retry_attempt?: number | null;
  negotiated_model?: string | null;
  chunk_seen?: boolean | null;
  body_seen?: boolean | null;
  body_streamed?: boolean | null;
  tool_handed_off?: boolean | null;
  tool_result_supplied?: boolean | null;
  body_bytes?: number | null;
  thought_bytes?: number | null;
  stop_reason?: string | null;
  permission_denial_count?: number | null;
  filtered_notice_count?: number | null;
  fallback_allowed?: boolean | null;
  fallback_reason?: string | null;
}

export interface RecentTurn extends TurnExtendedFields {
  recorded_at: string | null;
  model: string;
  mode: string;
  status: string;
  error_code: string | null;
  elapsed_ms: number | null;
  input_other: number | null;
  input_cached: number | null;
  output: number | null;
  usage_status: string;
  cache_fields_present?: {
    cachedReadTokens?: boolean;
    cachedWriteTokens?: boolean;
  };
  context_used?: number | null;
  context_window_size?: number | null;
  observed_at?: string | null;
  reused: boolean;
  rebuild_reasons: string[];
  prompt_bytes: number | null;
  replay_bytes: number | null;
  omitted_messages: number | null;
  content_429_candidate: Content429Candidate | null;
}

export interface MonitorInstance {
  provider_id: string;
  provider_tag?: string | null;
  model: string;
  enabled: boolean;
  tools_mode: string;
  effective_mode: string;
  tools_enabled: boolean;
  runtime_state: string;
  pool: MonitorPool | null;
  summary: MonitorSummary | null;
  latest_context: LatestContext | null;
  recent_turns: RecentTurn[];
}

export interface FailureEvent extends TurnExtendedFields {
  recorded_at: string | null;
  status: string;
  error_code: string | null;
  mode: string | null;
  provider_tag: string | null;
  elapsed_ms: number | null;
}

export interface FailureRetention {
  ttl_seconds: number;
  max_events: number;
  max_bytes: number;
  storage_state: 'available' | 'unavailable' | string;
}

export interface MonitorSnapshot {
  schema_version: number;
  sampled_at: string;
  window: {
    hours: number;
    max_turns_per_instance: number;
  };
  instances: MonitorInstance[];
  routing: RoutingSnapshot | null;
  failure_events: FailureEvent[] | null;
  failure_retention: FailureRetention | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asBooleanOrNull(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string');
}

export function normalizeRoutingSnapshot(raw: unknown): RoutingSnapshot | null {
  const obj = asRecord(raw);
  if (!obj) return null;
  return {
    scope: typeof obj.scope === 'string' && obj.scope ? obj.scope : 'global',
    configured_primary_id: asStringOrNull(obj.configured_primary_id),
    primary_exists: asBooleanOrNull(obj.primary_exists),
    primary_enabled: asBooleanOrNull(obj.primary_enabled),
    resolved_primary_id: asStringOrNull(obj.resolved_primary_id),
    is_acp: asBooleanOrNull(obj.is_acp),
    resolution_reason:
      typeof obj.resolution_reason === 'string' && obj.resolution_reason
        ? obj.resolution_reason
        : 'unknown',
    explicit_fallback_ids: asStringArray(obj.explicit_fallback_ids),
    invalid_fallback_ids: asStringArray(obj.invalid_fallback_ids),
    last_observed_provider_id: asStringOrNull(obj.last_observed_provider_id),
    last_observed_at: asStringOrNull(obj.last_observed_at),
    last_observed_scope:
      typeof obj.last_observed_scope === 'string' && obj.last_observed_scope
        ? obj.last_observed_scope
        : 'unknown',
  };
}

export function normalizeSetupSnapshot(raw: unknown): SetupSnapshot {
  const obj = asRecord(raw) ?? {};
  const reportObj = asRecord(obj.report) ?? {};
  const envObj = asRecord(obj.environment) ?? {};
  const loginObj = asRecord(obj.login) ?? {};
  const resultObj = asRecord(obj.result);

  return {
    csrf: typeof obj.csrf === 'string' ? obj.csrf : '',
    busy: Boolean(obj.busy),
    operation: typeof obj.operation === 'string' ? obj.operation : '',
    report: reportObj as ProbeReport,
    hint: typeof obj.hint === 'string' ? obj.hint : '',
    environment: envObj as EnvironmentInfo,
    login: loginObj as LoginSnapshot,
    providers: Array.isArray(obj.providers)
      ? (obj.providers.filter((item) => Boolean(asRecord(item))) as ConfiguredProvider[])
      : [],
    result: resultObj ? (resultObj as unknown as SetupApplyResult) : null,
    routing: normalizeRoutingSnapshot(obj.routing),
    action_error: typeof obj.action_error === 'string' ? obj.action_error : '',
    action_hint: typeof obj.action_hint === 'string' ? obj.action_hint : '',
    global_effort: typeof obj.global_effort === 'string' ? obj.global_effort : 'default',
    global_enable_tools:
      typeof obj.global_enable_tools === 'boolean' ? obj.global_enable_tools : undefined,
  };
}

export function normalizeMonitorSnapshot(raw: unknown): MonitorSnapshot {
  const obj = asRecord(raw);
  if (
    !obj ||
    (obj.schema_version !== 1 && obj.schema_version !== 2) ||
    !Array.isArray(obj.instances)
  ) {
    throw new Error('monitor schema');
  }

  const windowObj = asRecord(obj.window);
  const retentionObj = asRecord(obj.failure_retention);

  return {
    schema_version: obj.schema_version,
    sampled_at: typeof obj.sampled_at === 'string' ? obj.sampled_at : '',
    window: {
      hours: typeof windowObj?.hours === 'number' ? windowObj.hours : 24,
      max_turns_per_instance:
        typeof windowObj?.max_turns_per_instance === 'number'
          ? windowObj.max_turns_per_instance
          : 100,
    },
    instances: obj.instances as MonitorInstance[],
    routing: normalizeRoutingSnapshot(obj.routing),
    failure_events: Array.isArray(obj.failure_events)
      ? (obj.failure_events as FailureEvent[])
      : null,
    failure_retention: retentionObj
      ? {
          ttl_seconds:
            typeof retentionObj.ttl_seconds === 'number' ? retentionObj.ttl_seconds : 604800,
          max_events:
            typeof retentionObj.max_events === 'number' ? retentionObj.max_events : 128,
          max_bytes:
            typeof retentionObj.max_bytes === 'number' ? retentionObj.max_bytes : 65536,
          storage_state:
            typeof retentionObj.storage_state === 'string'
              ? retentionObj.storage_state
              : 'unavailable',
        }
      : null,
  };
}
