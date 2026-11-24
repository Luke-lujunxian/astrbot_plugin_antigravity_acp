import type {
  FailureEvent,
  FailureRetention,
  MonitorSnapshot,
  RoutingSnapshot,
  SetupSnapshot,
} from '@/types/api';

/**
 * Build a strictly allowlisted, sanitized diagnostic payload.
 *
 * Never reads or exports CSRF tokens, login tickets, OAuth URLs, auth codes,
 * raw provider objects, or any non-allowlisted setup snapshot properties.
 */
export function buildSanitizedDiagnosticExport(
  monitor: MonitorSnapshot | null,
  setup: SetupSnapshot | null,
): Record<string, unknown> {
  const routingSource: RoutingSnapshot | null = monitor?.routing ?? setup?.routing ?? null;

  const routing = routingSource
    ? {
        scope: routingSource.scope,
        configured_primary_id: routingSource.configured_primary_id,
        primary_exists: routingSource.primary_exists,
        primary_enabled: routingSource.primary_enabled,
        resolved_primary_id: routingSource.resolved_primary_id,
        is_acp: routingSource.is_acp,
        resolution_reason: routingSource.resolution_reason,
        explicit_fallback_ids: [...routingSource.explicit_fallback_ids],
        invalid_fallback_ids: [...routingSource.invalid_fallback_ids],
        last_observed_provider_id: routingSource.last_observed_provider_id,
        last_observed_at: routingSource.last_observed_at,
        last_observed_scope: routingSource.last_observed_scope,
      }
    : null;

  const retentionSource = monitor?.failure_retention;
  const failureRetention: FailureRetention | null = retentionSource
    ? {
        ttl_seconds: retentionSource.ttl_seconds,
        max_events: retentionSource.max_events,
        max_bytes: retentionSource.max_bytes,
        storage_state: retentionSource.storage_state,
      }
    : null;

  const rawFailureEvents = monitor?.failure_events;
  const failureEvents = Array.isArray(rawFailureEvents)
    ? rawFailureEvents.map((row: FailureEvent) => ({
        recorded_at: row.recorded_at ?? null,
        status: row.status ?? null,
        error_code: row.error_code ?? null,
        mode: row.mode ?? null,
        provider_tag: row.provider_tag ?? null,
        turn_id: row.turn_id ?? null,
        origin_turn_id: row.origin_turn_id ?? null,
        logical_request_tag: row.logical_request_tag ?? null,
        elapsed_ms: row.elapsed_ms ?? null,
        attempt: row.attempt ?? null,
        cli_retry_attempt: row.cli_retry_attempt ?? null,
        chunk_seen: row.chunk_seen ?? null,
        body_seen: row.body_seen ?? null,
        body_streamed: row.body_streamed ?? null,
        tool_handed_off: row.tool_handed_off ?? null,
        tool_result_supplied: row.tool_result_supplied ?? null,
        body_bytes: row.body_bytes ?? null,
        thought_bytes: row.thought_bytes ?? null,
        stop_reason: row.stop_reason ?? null,
        permission_denial_count: row.permission_denial_count ?? null,
        filtered_notice_count: row.filtered_notice_count ?? null,
        fallback_allowed: row.fallback_allowed ?? null,
        fallback_reason: row.fallback_reason ?? null,
      }))
    : null;

  const windowSource = monitor?.window;
  const report = setup?.report;
  const env = setup?.environment;

  return {
    export_format: 'agy_acp_sanitized_diagnostics_v1',
    exported_at: new Date().toISOString(),
    monitor_schema_version: monitor?.schema_version ?? null,
    sampled_at: monitor?.sampled_at ?? null,
    window: windowSource
      ? {
          hours: windowSource.hours,
          max_turns_per_instance: windowSource.max_turns_per_instance,
        }
      : null,
    routing,
    failure_retention: failureRetention,
    failure_events: failureEvents,
    preflight_summary: report
      ? {
          status: report.status ?? null,
          stage: report.stage ?? null,
          error_code: report.error_code ?? null,
          exit_code: Number.isInteger(report.exit_code) ? report.exit_code : null,
          cli_version: report.cli_version ?? null,
          model_count: typeof report.model_count === 'number' ? report.model_count : null,
          proxy_mode: report.proxy_mode ?? null,
          auth_bridge: typeof report.auth_bridge === 'boolean' ? report.auth_bridge : null,
          customizations_mode: report.customizations_mode ?? null,
          minimal_tools_status: report.minimal_tools_status ?? null,
          tool_bridge_transport: report.tool_bridge_transport ?? null,
          process_supervision: report.process_supervision ?? null,
          cli_update_policy: report.cli_update_policy ?? null,
          advertised_capabilities: report.advertised_capabilities ?? null,
        }
      : null,
    environment_summary: env
      ? {
          system: env.system ?? null,
          python: env.python ?? null,
          container: typeof env.container === 'boolean' ? env.container : null,
        }
      : null,
  };
}

export function downloadSanitizedJson(filename: string, jsonText: string): boolean {
  try {
    const blob = new Blob([jsonText], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  } catch {
    return false;
  }
}
