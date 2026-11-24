<script setup lang="ts">
import { computed, ref } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import type { FailureEvent, MonitorInstance, RecentTurn } from '@/types/api';
import MonitorCharts from '@/components/MonitorCharts.vue';
import RoutingSummaryCard from '@/components/RoutingSummaryCard.vue';
import TurnDetailDialog, { type DetailRecord } from '@/components/TurnDetailDialog.vue';
import {
  formatBytes,
  formatByteSizeHuman,
  formatCount,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRelativeAgo,
  formatSeconds,
  formatShortTime,
} from '@/utils/format';
import {
  mdiAlertOutline,
  mdiChartBoxOutline,
  mdiChevronDown,
  mdiChevronUp,
  mdiClose,
  mdiEyeOutline,
  mdiHelpCircleOutline,
  mdiMagnify,
  mdiRefresh,
} from '@/utils/icons';
import {
  formatFaultBrief,
  labelOf,
  STAGE_LABELS,
  SUPERVISION_LABELS,
  TRANSPORT_LABELS,
  TURN_STATUS_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const helpDialogOpen = ref(false);
const detailDialogOpen = ref(false);
const selectedDetail = ref<DetailRecord | null>(null);

// Independent filter / pagination state preserved across background 10s polls (#28)
const turnSearch = ref('');
const turnInstanceFilter = ref<string>('all');
const turnStatusFilter = ref<string>('all');
const turnPage = ref(1);
const turnItemsPerPage = ref(10);

const failureSearch = ref('');
const failureCodeFilter = ref<string>('all');
const failurePage = ref(1);
const failureItemsPerPage = ref(10);

const monitor = computed(() => props.ctrl.monitorSnapshot.value);
const setup = computed(() => props.ctrl.setupSnapshot.value);
const instances = computed(() => monitor.value?.instances ?? []);

const providerByTag = computed(() => {
  const map = new Map<string, string>();
  for (const inst of instances.value) {
    if (inst.provider_tag) map.set(inst.provider_tag, inst.provider_id);
  }
  return map;
});

function resolveProviderTag(tag: string | null): string {
  if (!tag) return '未知实例';
  return providerByTag.value.get(tag) || `tag:${tag.slice(0, 8)}`;
}

function toggleDetailSection(id: string): void {
  props.ctrl.expandedMonitorDetails.value = {
    ...props.ctrl.expandedMonitorDetails.value,
    [id]: !props.ctrl.expandedMonitorDetails.value[id],
  };
}

function toggleDiagSection(id: string): void {
  props.ctrl.expandedMonitorDiag.value = {
    ...props.ctrl.expandedMonitorDiag.value,
    [id]: !props.ctrl.expandedMonitorDiag.value[id],
  };
}

function hasValidContext(inst: MonitorInstance): boolean {
  const ctx = inst.latest_context;
  return Boolean(
    ctx &&
      typeof ctx.context_used === 'number' &&
      Number.isFinite(ctx.context_used) &&
      typeof ctx.context_window_size === 'number' &&
      Number.isFinite(ctx.context_window_size) &&
      ctx.context_window_size > 0 &&
      ctx.context_used >= 0 &&
      ctx.observed_at,
  );
}

function contextRatio(inst: MonitorInstance): number {
  if (!hasValidContext(inst) || !inst.latest_context) return 0;
  return (inst.latest_context.context_used! / inst.latest_context.context_window_size!) * 100;
}

function contextBarColor(inst: MonitorInstance): string {
  const pct = contextRatio(inst);
  if (pct >= 90) return 'error';
  if (pct >= 70) return 'warning';
  return 'success';
}

function latestFaultOf(inst: MonitorInstance): RecentTurn | null {
  return inst.recent_turns.find((t) => Boolean(t.error_code) || t.status === 'error') ?? null;
}

function faultCountOf(inst: MonitorInstance): number {
  return inst.recent_turns.filter((t) => Boolean(t.error_code) || t.status === 'error').length;
}

function c429TurnsOf(inst: MonitorInstance): RecentTurn[] {
  return inst.recent_turns.filter((t) => Boolean(t.content_429_candidate));
}

function nonOkTurnsOf(inst: MonitorInstance): RecentTurn[] {
  return inst.recent_turns.filter((t) => Boolean(t.error_code) || t.status !== 'ok');
}

// Flattened turns table
interface TurnRow {
  row_key: string;
  provider_id: string;
  recorded_at: string | null;
  model: string;
  negotiated_model: string | null;
  status: string;
  error_code: string | null;
  elapsed_ms: number | null;
  reused: boolean;
  usage_summary: string;
  turn: RecentTurn;
}

const allTurnRows = computed<TurnRow[]>(() => {
  const rows: TurnRow[] = [];
  for (const inst of instances.value) {
    inst.recent_turns.forEach((turn, idx) => {
      const usageSummary =
        turn.usage_status === 'reported'
          ? `入 ${formatCount(turn.input_other)} · 缓 ${turn.cache_fields_present?.cachedReadTokens ? formatCount(turn.input_cached) : '未知'} · 出 ${formatCount(turn.output)}`
          : turn.usage_status === 'not_sent'
            ? '未发送请求'
            : '用量未知';
      rows.push({
        row_key: `${inst.provider_id}::${turn.turn_id || turn.recorded_at || idx}::${idx}`,
        provider_id: inst.provider_id,
        recorded_at: turn.recorded_at,
        model: turn.model || inst.model || '未知模型',
        negotiated_model: turn.negotiated_model ?? null,
        status: turn.status,
        error_code: turn.error_code,
        elapsed_ms: turn.elapsed_ms,
        reused: turn.reused,
        usage_summary: usageSummary,
        turn,
      });
    });
  }
  return rows.sort((a, b) => Date.parse(b.recorded_at || '') - Date.parse(a.recorded_at || ''));
});

const instanceFilterOptions = computed(() => [
  { title: '全部实例', value: 'all' },
  ...instances.value.map((i) => ({ title: i.provider_id, value: i.provider_id })),
]);

const statusFilterOptions = [
  { title: '全部状态', value: 'all' },
  { title: '成功 (ok)', value: 'ok' },
  { title: '失败 (error)', value: 'error' },
  { title: '取消 (cancelled)', value: 'cancelled' },
  { title: '预检/熔断拦截', value: 'short_circuited' },
];

const filteredTurnRows = computed(() =>
  allTurnRows.value.filter((row) => {
    if (turnInstanceFilter.value !== 'all' && row.provider_id !== turnInstanceFilter.value) {
      return false;
    }
    if (turnStatusFilter.value !== 'all' && row.status !== turnStatusFilter.value) {
      return false;
    }
    return true;
  }),
);

const turnHeaders = [
  { title: '时间', key: 'recorded_at', sortable: true },
  { title: '实例', key: 'provider_id', sortable: true },
  { title: '模型', key: 'model', sortable: true },
  { title: '状态 / 错误码', key: 'status', sortable: true },
  { title: '耗时', key: 'elapsed_ms', sortable: true, align: 'end' as const },
  { title: 'Token / 复用', key: 'usage_summary', sortable: false },
  { title: '详情', key: 'actions', sortable: false, align: 'end' as const },
];

// Failure events table (schema v2)
interface FailureRow {
  row_key: string;
  recorded_at: string | null;
  provider_label: string;
  status: string;
  error_code: string;
  mode: string;
  elapsed_ms: number | null;
  fallback_allowed: boolean | null;
  event: FailureEvent;
}

const allFailureRows = computed<FailureRow[]>(() => {
  const list = monitor.value?.failure_events;
  if (!Array.isArray(list)) return [];
  return list.map((event, idx) => ({
    row_key: `${event.turn_id || event.recorded_at || idx}::${idx}`,
    recorded_at: event.recorded_at,
    provider_label: resolveProviderTag(event.provider_tag),
    status: event.status,
    error_code: event.error_code || 'UNKNOWN',
    mode: event.mode || '未知',
    elapsed_ms: event.elapsed_ms,
    fallback_allowed: event.fallback_allowed ?? null,
    event,
  }));
});

const failureCodeOptions = computed(() => {
  const codes = Array.from(new Set(allFailureRows.value.map((r) => r.error_code))).sort();
  return [
    { title: '全部错误码', value: 'all' },
    ...codes.map((c) => ({ title: formatFaultBrief(c), value: c })),
  ];
});

const filteredFailureRows = computed(() =>
  allFailureRows.value.filter((row) => {
    if (failureCodeFilter.value !== 'all' && row.error_code !== failureCodeFilter.value) {
      return false;
    }
    return true;
  }),
);

const failureHeaders = [
  { title: '时间', key: 'recorded_at', sortable: true },
  { title: '实例（标签映射）', key: 'provider_label', sortable: true },
  { title: '状态', key: 'status', sortable: true },
  { title: '错误码', key: 'error_code', sortable: true },
  { title: '耗时', key: 'elapsed_ms', sortable: true, align: 'end' as const },
  { title: '允许回退', key: 'fallback_allowed', sortable: true },
  { title: '详情', key: 'actions', sortable: false, align: 'end' as const },
];

function openTurnDetail(row: TurnRow): void {
  selectedDetail.value = { kind: 'turn', providerId: row.provider_id, turn: row.turn };
  detailDialogOpen.value = true;
}

function openFailureDetail(row: FailureRow): void {
  selectedDetail.value = {
    kind: 'failure',
    providerLabel: row.provider_label,
    event: row.event,
  };
  detailDialogOpen.value = true;
}

function statusChipColor(status: string): 'success' | 'error' | 'warning' | 'default' {
  if (status === 'ok') return 'success';
  if (status === 'error') return 'error';
  if (status === 'cancelled' || status === 'short_circuited') return 'warning';
  return 'default';
}
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <!-- 监控顶栏与快照元数据 -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiChartBoxOutline" color="primary" />
        </template>
        <v-card-title class="d-flex align-center flex-wrap ga-2">
          <span>本地运行监控</span>
          <v-chip
            size="x-small"
            :color="ctrl.monitorStale.value ? 'error' : instances.length ? 'success' : 'default'"
            variant="tonal"
          >
            {{ ctrl.monitorStale.value ? '数据过期 / 不可用' : '本地只读快照' }}
          </v-chip>
          <v-chip v-if="monitor" size="x-small" variant="outlined">
            schema v{{ monitor.schema_version }}
          </v-chip>
        </v-card-title>
        <v-card-subtitle>
          <template v-if="monitor">
            快照时间 {{ formatShortTime(monitor.sampled_at) }} · 10s 自动刷新（后台标签页暂停）· 不发起 CLI 或模型请求
          </template>
          <template v-else>{{ ctrl.monitorMessage.value }}</template>
        </v-card-subtitle>
        <template #append>
          <div class="d-flex ga-2 align-center">
            <v-btn
              size="small"
              variant="text"
              :prepend-icon="mdiHelpCircleOutline"
              @click="helpDialogOpen = true"
            >
              统计口径
            </v-btn>
            <v-btn
              size="small"
              variant="tonal"
              color="primary"
              :loading="ctrl.monitorPending.value"
              :prepend-icon="mdiRefresh"
              @click="ctrl.refreshMonitor()"
            >
              刷新
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <v-card-text v-if="ctrl.monitorMessage.value || ctrl.monitorStale.value" class="pt-0">
        <v-alert
          :type="ctrl.monitorPermissionDenied.value ? 'error' : ctrl.monitorStale.value ? 'warning' : 'info'"
          variant="tonal"
          density="compact"
          :icon="mdiAlertOutline"
        >
          {{ ctrl.monitorMessage.value }}
        </v-alert>
      </v-card-text>
    </v-card>

    <!-- 路由配置与真实服务观测分离卡片 -->
    <RoutingSummaryCard
      :routing="ctrl.combinedRouting.value"
      :schema-version="monitor?.schema_version ?? null"
      :now-tick="ctrl.nowTick.value"
    />

    <!-- 实例监控卡片（三层信息架构：概览 + 详细图表 + 高级诊断） -->
    <v-row v-if="instances.length > 0" dense :class="{ 'agy-stale': ctrl.monitorStale.value }">
      <v-col v-for="inst in instances" :key="inst.provider_id" cols="12" xl="6">
        <v-card variant="outlined" class="h-100">
          <v-card-item>
            <v-card-title class="d-flex align-center justify-space-between flex-wrap ga-2">
              <span class="agy-mono agy-break">{{ inst.provider_id }}</span>
              <div class="d-flex flex-wrap ga-1">
                <v-chip
                  size="x-small"
                  :color="inst.enabled && inst.runtime_state === 'active' ? 'success' : 'default'"
                  variant="tonal"
                >
                  {{ inst.enabled ? '已启用' : '已停用' }}
                </v-chip>
                <v-chip size="x-small" variant="outlined">
                  {{ inst.runtime_state === 'active' ? '已初始化 (active)' : '未初始化' }}
                </v-chip>
                <v-chip size="x-small" variant="outlined">
                  {{
                    inst.effective_mode === 'tools'
                      ? '工具模式'
                      : inst.effective_mode === 'chat'
                        ? '纯聊天'
                        : '模式未知'
                  }}
                </v-chip>
              </div>
            </v-card-title>
            <v-card-subtitle class="agy-mono agy-break">
              {{ inst.model || '未选择模型' }}
            </v-card-subtitle>
          </v-card-item>

          <v-divider />

          <v-card-text class="d-flex flex-column ga-3">
            <p v-if="inst.runtime_state !== 'active'" class="text-body-2 text-medium-emphasis mb-0">
              已配置未初始化，暂无运行统计（需触发首次会话或加载后才有实时会话池数据）。
            </p>

            <template v-else>
              <!-- 第一层：核心运行概览 -->
              <div class="d-flex align-center justify-space-between flex-wrap ga-2">
                <div class="d-flex flex-wrap ga-1">
                  <v-chip size="x-small" variant="tonal">实时会话池</v-chip>
                  <v-chip size="x-small" variant="tonal">近 24h (≤100轮)</v-chip>
                  <v-chip size="x-small" variant="tonal">最近采样</v-chip>
                </div>
                <span v-if="inst.recent_turns.length" class="text-caption text-medium-emphasis">
                  最近一轮 {{ formatRelativeAgo(inst.recent_turns[0].recorded_at, ctrl.nowTick.value) }}
                </span>
              </div>

              <v-row dense>
                <v-col cols="6">
                  <div class="agy-subtle-panel h-100">
                    <div class="text-caption text-medium-emphasis">活动会话（实时）</div>
                    <div class="text-subtitle-1 font-weight-bold agy-tabular">
                      {{
                        inst.pool
                          ? `${formatCount(inst.pool.active_sessions)} / ${formatCount(inst.pool.max_sessions)}`
                          : '未知'
                      }}
                    </div>
                    <div v-if="inst.pool" class="text-caption text-medium-emphasis agy-tabular">
                      存活进程 {{ formatCount(inst.pool.live_processes) }} · 续轮
                      {{ formatCount(inst.pool.active_tool_turns) }}
                    </div>
                  </div>
                </v-col>

                <v-col cols="6">
                  <div class="agy-subtle-panel h-100">
                    <div class="text-caption text-medium-emphasis">请求轮数（近 24h）</div>
                    <div class="text-subtitle-1 font-weight-bold agy-tabular">
                      {{ inst.summary ? formatCount(inst.summary.total_turns) : '未知' }}
                    </div>
                    <div
                      v-if="inst.summary && inst.summary.request_sent_turns !== inst.summary.total_turns"
                      class="text-caption text-medium-emphasis agy-tabular"
                    >
                      实际发送 {{ formatCount(inst.summary.request_sent_turns) }}
                    </div>
                  </div>
                </v-col>

                <v-col cols="6">
                  <div class="agy-subtle-panel h-100">
                    <div class="text-caption text-medium-emphasis">成功 / 失败（近 24h）</div>
                    <div
                      class="text-subtitle-1 font-weight-bold agy-tabular"
                      :class="{ 'text-warning': (inst.summary?.failed_turns ?? 0) > 0 }"
                    >
                      {{
                        inst.summary
                          ? `${formatCount(inst.summary.success_turns)} / ${formatCount(inst.summary.failed_turns)}`
                          : '未知'
                      }}
                    </div>
                  </div>
                </v-col>

                <v-col cols="6">
                  <div class="agy-subtle-panel h-100">
                    <div class="text-caption text-medium-emphasis">最近异常（近 20 轮）</div>
                    <div
                      class="text-subtitle-2 font-weight-bold agy-break"
                      :class="{ 'text-error': faultCountOf(inst) > 0 }"
                    >
                      <template v-if="latestFaultOf(inst)">
                        {{
                          latestFaultOf(inst)?.error_code
                            ? formatFaultBrief(latestFaultOf(inst)!.error_code!)
                            : '请求异常'
                        }}
                      </template>
                      <template v-else>
                        {{ inst.recent_turns.length ? '近期无异常' : '暂无记录' }}
                      </template>
                    </div>
                    <div v-if="latestFaultOf(inst)" class="text-caption text-medium-emphasis">
                      {{ formatRelativeAgo(latestFaultOf(inst)?.recorded_at, ctrl.nowTick.value) }}
                      <template v-if="faultCountOf(inst) > 1">
                        · 共 {{ faultCountOf(inst) }} 次
                      </template>
                    </div>
                  </div>
                </v-col>
              </v-row>

              <!-- 上下文占用（未知时严禁显示 0%） -->
              <div class="agy-subtle-panel d-flex flex-column ga-2">
                <div class="d-flex align-center justify-space-between flex-wrap ga-2">
                  <span class="text-body-2 font-weight-semibold">上下文占用（最近单次存活会话采样）</span>
                  <span class="text-body-2 agy-tabular font-weight-medium">
                    <template v-if="hasValidContext(inst) && inst.latest_context">
                      {{ formatCount(inst.latest_context.context_used) }} /
                      {{ formatCount(inst.latest_context.context_window_size) }} Token ·
                      {{
                        formatPercent(
                          inst.latest_context.context_used! /
                            inst.latest_context.context_window_size!,
                        )
                      }}
                    </template>
                    <template v-else>上游未报告</template>
                  </span>
                </div>
                <template v-if="hasValidContext(inst) && inst.latest_context">
                  <v-progress-linear
                    :model-value="contextRatio(inst)"
                    :color="contextBarColor(inst)"
                    height="7"
                    rounded
                  />
                  <div class="text-caption text-medium-emphasis">
                    {{ inst.latest_context.model || inst.model }} · 采样于
                    {{ formatDateTime(inst.latest_context.observed_at) }}
                  </div>
                </template>
              </div>

              <!-- 第二层：详细统计与 SVG 图表（跨轮询保持展开状态） -->
              <div>
                <v-btn
                  block
                  variant="text"
                  size="small"
                  class="justify-space-between px-2"
                  @click="toggleDetailSection(inst.provider_id)"
                >
                  <span>
                    详细统计与图表（{{
                      inst.summary && inst.summary.total_turns > 0
                        ? `${formatCount(inst.summary.total_turns)} 轮`
                        : '暂无样本'
                    }}）
                  </span>
                  <v-icon
                    :icon="
                      ctrl.expandedMonitorDetails.value[inst.provider_id]
                        ? mdiChevronUp
                        : mdiChevronDown
                    "
                  />
                </v-btn>

                <v-expand-transition>
                  <div v-if="ctrl.expandedMonitorDetails.value[inst.provider_id]" class="pt-2">
                    <MonitorCharts
                      :summary="inst.summary"
                      :recent-turns="inst.recent_turns"
                      :now-tick="ctrl.nowTick.value"
                    />
                  </div>
                </v-expand-transition>
              </div>
            </template>

            <!-- 第三层：高级诊断与 429 候选（跨轮询保持展开状态） -->
            <div>
              <v-divider class="mb-2" />
              <v-btn
                block
                variant="text"
                size="small"
                class="justify-space-between px-2"
                @click="toggleDiagSection(inst.provider_id)"
              >
                <span>高级诊断（原始字段与 429 候选）</span>
                <v-icon
                  :icon="
                    ctrl.expandedMonitorDiag.value[inst.provider_id]
                      ? mdiChevronUp
                      : mdiChevronDown
                  "
                />
              </v-btn>

              <v-expand-transition>
                <div
                  v-if="ctrl.expandedMonitorDiag.value[inst.provider_id]"
                  class="pt-2 d-flex flex-column ga-3"
                >
                  <div class="agy-subtle-panel">
                    <div class="text-caption font-weight-bold mb-2">实例与运行字段</div>
                    <dl class="agy-kv-grid">
                      <div class="agy-kv-item">
                        <dt>provider_id / tag</dt>
                        <dd class="agy-mono">
                          {{ inst.provider_id }}
                          <template v-if="inst.provider_tag">
                            ({{ inst.provider_tag.slice(0, 8) }}…)
                          </template>
                        </dd>
                      </div>
                      <div class="agy-kv-item">
                        <dt>tools_mode → effective</dt>
                        <dd class="agy-mono">
                          {{ inst.tools_mode }} → {{ inst.effective_mode }} (tools_enabled={{ String(inst.tools_enabled) }})
                        </dd>
                      </div>
                      <div v-if="setup?.report" class="agy-kv-item">
                        <dt>CLI 预检与版本</dt>
                        <dd>
                          {{ setup.report.status || '未知' }} ({{ labelOf(STAGE_LABELS, setup.report.stage, '未知') }}) ·
                          {{ setup.report.cli_version || '未探测' }}
                        </dd>
                      </div>
                      <div v-if="setup?.report" class="agy-kv-item">
                        <dt>进程托管 / 工具桥</dt>
                        <dd>
                          {{ labelOf(SUPERVISION_LABELS, setup.report.process_supervision, '未知') }} ·
                          {{ labelOf(TRANSPORT_LABELS, setup.report.tool_bridge_transport, '未知') }}
                        </dd>
                      </div>
                    </dl>
                  </div>

                  <div class="agy-subtle-panel">
                    <div class="text-caption font-weight-bold mb-1">
                      429 诊断候选遥测（{{ c429TurnsOf(inst).length }}）
                    </div>
                    <p class="text-caption text-medium-emphasis mb-2">
                      仅启发式候选信号，不能证明内容过滤、风控或额度根因。
                    </p>
                    <div v-if="c429TurnsOf(inst).length" class="d-flex flex-column ga-1">
                      <div
                        v-for="(turn, idx) in c429TurnsOf(inst)"
                        :key="idx"
                        class="text-caption agy-mono d-flex justify-space-between flex-wrap ga-2"
                      >
                        <span class="text-error">
                          {{ turn.error_code || '429' }} · hash={{ turn.content_429_candidate?.system_hash8 || '未知' }} ·
                          sys={{ formatBytes(turn.content_429_candidate?.system_bytes) }} ·
                          attempt={{ turn.content_429_candidate?.attempt ?? '未知' }} ·
                          output={{ turn.content_429_candidate?.has_output ? '是' : '否' }}
                        </span>
                        <span class="text-medium-emphasis">{{ formatDateTime(turn.recorded_at) }}</span>
                      </div>
                    </div>
                    <p v-else class="text-caption text-medium-emphasis mb-0">近 20 轮无 429 候选记录</p>
                  </div>

                  <div class="agy-subtle-panel">
                    <div class="text-caption font-weight-bold mb-1">
                      异常与中断摘要（{{ nonOkTurnsOf(inst).length }}）
                    </div>
                    <div v-if="nonOkTurnsOf(inst).length" class="d-flex flex-column ga-1">
                      <div
                        v-for="(turn, idx) in nonOkTurnsOf(inst)"
                        :key="idx"
                        class="text-caption agy-mono d-flex justify-space-between flex-wrap ga-2"
                      >
                        <span>
                          {{ turn.status }}{{ turn.error_code ? `/${turn.error_code}` : '' }} ·
                          {{ formatDuration(turn.elapsed_ms) }} ·
                          prompt={{ formatBytes(turn.prompt_bytes) }} replay={{ formatBytes(turn.replay_bytes) }}
                          omit={{ formatCount(turn.omitted_messages) }}
                        </span>
                        <span class="text-medium-emphasis">{{ formatDateTime(turn.recorded_at) }}</span>
                      </div>
                    </div>
                    <p v-else class="text-caption text-medium-emphasis mb-0">近 20 轮无异常或中断记录</p>
                  </div>
                </div>
              </v-expand-transition>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 近期请求记录 VDataTable（支持搜索、筛选、分页与详情对话框） -->
    <v-card variant="outlined" :class="{ 'agy-stale': ctrl.monitorStale.value }">
      <v-card-item>
        <v-card-title>近期请求记录（每实例最近 20 轮）</v-card-title>
        <v-card-subtitle>
          支持按关键词、实例与状态筛选；点击「详情」查看 Token/字节分离、工具交接与 Fallback 防重放边界。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-3">
        <v-row dense>
          <v-col cols="12" sm="4">
            <v-text-field
              v-model="turnSearch"
              label="搜索模型、错误码、实例"
              variant="outlined"
              density="compact"
              hide-details
              clearable
              :prepend-inner-icon="mdiMagnify"
            />
          </v-col>
          <v-col cols="12" sm="4">
            <v-select
              v-model="turnInstanceFilter"
              :items="instanceFilterOptions"
              item-title="title"
              item-value="value"
              label="按实例筛选"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="12" sm="4">
            <v-select
              v-model="turnStatusFilter"
              :items="statusFilterOptions"
              item-title="title"
              item-value="value"
              label="按状态筛选"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
        </v-row>

        <div class="agy-table-scroll">
          <v-data-table
            v-model:page="turnPage"
            v-model:items-per-page="turnItemsPerPage"
            :headers="turnHeaders"
            :items="filteredTurnRows"
            :search="turnSearch || ''"
            :items-per-page-options="[10, 20, 50]"
            item-value="row_key"
            density="comfortable"
            hover
            no-data-text="暂无近期请求记录"
          >
            <template #item.recorded_at="{ item }">
              <div class="agy-tabular text-no-wrap">{{ formatShortTime(item.recorded_at) }}</div>
              <div class="text-caption text-medium-emphasis">
                {{ formatRelativeAgo(item.recorded_at, ctrl.nowTick.value) }}
              </div>
            </template>

            <template #item.provider_id="{ item }">
              <span class="agy-mono text-body-2">{{ item.provider_id }}</span>
            </template>

            <template #item.model="{ item }">
              <div class="agy-mono text-body-2">{{ item.model }}</div>
              <div
                v-if="item.negotiated_model && item.negotiated_model !== item.model"
                class="text-caption text-medium-emphasis agy-mono"
              >
                协商：{{ item.negotiated_model }}
              </div>
            </template>

            <template #item.status="{ item }">
              <div class="d-flex flex-wrap ga-1 align-center">
                <v-chip size="x-small" :color="statusChipColor(item.status)" variant="tonal">
                  {{ labelOf(TURN_STATUS_LABELS, item.status, '未知') }}
                </v-chip>
                <v-chip v-if="item.error_code" size="x-small" color="error" variant="outlined">
                  {{ item.error_code }}
                </v-chip>
              </div>
            </template>

            <template #item.elapsed_ms="{ item }">
              <span class="agy-tabular">{{ formatDuration(item.elapsed_ms) }}</span>
            </template>

            <template #item.usage_summary="{ item }">
              <div class="text-caption agy-tabular">{{ item.usage_summary }}</div>
              <div class="text-caption text-medium-emphasis">
                {{ item.reused ? '会话复用' : '新建会话' }}
              </div>
            </template>

            <template #item.actions="{ item }">
              <v-btn
                size="x-small"
                variant="tonal"
                color="primary"
                :prepend-icon="mdiEyeOutline"
                @click="openTurnDetail(item)"
              >
                详情
              </v-btn>
            </template>
          </v-data-table>
        </div>
      </v-card-text>
    </v-card>

    <!-- 持久化失败事件日志表（schema v2，兼容 v1 降级） -->
    <v-card variant="outlined" :class="{ 'agy-stale': ctrl.monitorStale.value }">
      <v-card-item>
        <v-card-title class="d-flex align-center flex-wrap ga-2">
          <span>插件持久化失败事件（全插件脱敏日志）</span>
          <template v-if="monitor?.failure_retention">
            <v-chip
              size="x-small"
              :color="monitor.failure_retention.storage_state === 'available' ? 'success' : 'warning'"
              variant="tonal"
            >
              存储：{{
                monitor.failure_retention.storage_state === 'available' ? '可用' : '不可用（仅内存）'
              }}
            </v-chip>
            <v-chip size="x-small" variant="outlined">
              保留 {{ formatSeconds(monitor.failure_retention.ttl_seconds) }} · 上限
              {{ monitor.failure_retention.max_events }} 条 /
              {{ formatByteSizeHuman(monitor.failure_retention.max_bytes) }}
            </v-chip>
          </template>
        </v-card-title>
        <v-card-subtitle>
          不含会话身份、模型名、聊天内容、工具参数或凭据；可通过「高级设置」导出脱敏白名单 JSON。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-3">
        <v-alert
          v-if="monitor && monitor.failure_events === null"
          type="info"
          variant="tonal"
          density="compact"
        >
          当前后端监控为 schema v{{ monitor.schema_version }}，未下发持久化失败事件列表（`failure_events` 显示为未知）。
        </v-alert>

        <template v-else>
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="failureSearch"
                label="搜索错误码、实例标签、状态"
                variant="outlined"
                density="compact"
                hide-details
                clearable
                :prepend-inner-icon="mdiMagnify"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-select
                v-model="failureCodeFilter"
                :items="failureCodeOptions"
                item-title="title"
                item-value="value"
                label="按错误码筛选"
                variant="outlined"
                density="compact"
                hide-details
              />
            </v-col>
          </v-row>

          <div class="agy-table-scroll">
            <v-data-table
              v-model:page="failurePage"
              v-model:items-per-page="failureItemsPerPage"
              :headers="failureHeaders"
              :items="filteredFailureRows"
              :search="failureSearch || ''"
              :items-per-page-options="[10, 20, 50]"
              item-value="row_key"
              density="comfortable"
              hover
              no-data-text="当前保留窗口内无持久化失败事件"
            >
              <template #item.recorded_at="{ item }">
                <div class="agy-tabular text-no-wrap">{{ formatDateTime(item.recorded_at) }}</div>
              </template>
              <template #item.provider_label="{ item }">
                <span class="agy-mono text-body-2">{{ item.provider_label }}</span>
              </template>
              <template #item.status="{ item }">
                <v-chip size="x-small" :color="statusChipColor(item.status)" variant="tonal">
                  {{ labelOf(TURN_STATUS_LABELS, item.status, item.status) }}
                </v-chip>
              </template>
              <template #item.error_code="{ item }">
                <v-chip size="x-small" color="error" variant="outlined">
                  {{ formatFaultBrief(item.error_code) }}
                </v-chip>
              </template>
              <template #item.elapsed_ms="{ item }">
                <span class="agy-tabular">{{ formatDuration(item.elapsed_ms) }}</span>
              </template>
              <template #item.fallback_allowed="{ item }">
                <v-chip
                  size="x-small"
                  :color="item.fallback_allowed === true ? 'info' : item.fallback_allowed === false ? 'warning' : 'default'"
                  variant="tonal"
                >
                  {{
                    item.fallback_allowed === true
                      ? '允许回退'
                      : item.fallback_allowed === false
                        ? '禁止重放'
                        : '未知'
                  }}
                </v-chip>
              </template>
              <template #item.actions="{ item }">
                <v-btn
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  :prepend-icon="mdiEyeOutline"
                  @click="openFailureDetail(item)"
                >
                  详情
                </v-btn>
              </template>
            </v-data-table>
          </div>
        </template>
      </v-card-text>
    </v-card>

    <!-- 统计口径帮助 Dialog -->
    <v-dialog v-model="helpDialogOpen" max-width="560">
      <v-card>
        <v-card-item>
          <v-card-title>运行监控统计口径与语义边界</v-card-title>
          <template #append>
            <v-btn icon variant="text" size="small" aria-label="关闭" @click="helpDialogOpen = false">
              <v-icon :icon="mdiClose" />
            </v-btn>
          </template>
        </v-card-item>
        <v-divider />
        <v-card-text>
          <ul class="pl-4 d-flex flex-column ga-2 text-body-1 mb-0">
            <li><strong>只读本地快照</strong>：GET 轮询不启动 CLI，不发送模型请求。</li>
            <li><strong>近 24h 窗口</strong>：单实例最多保留 100 轮内存统计，进程重启清空；持久化失败日志独立保留 7 天（最多 128 条 / 64 KiB）。</li>
            <li><strong>状态区分</strong>：<code class="agy-inline-code">active</code> 仅表示实例已初始化，不等同正在对外服务；<code class="agy-inline-code">passed</code> 仅表示上次无生成预检通过，不代表实时健康。</li>
            <li><strong>未知与 0 严格区分</strong>：未上报的 Token 用量、上下文占用与未观测到的服务时间均显示「未知/上游未报告」，绝不按 0 计；UTF-8 字节数不能替代 Token 用量。</li>
            <li><strong>路由口径</strong>：全局路由仅反映默认 profile，不代表单群/私聊覆盖；服务观测口径为 <code class="agy-inline-code">plugin_only</code>，仅统计本插件已成功完成的 ACP 回合。</li>
          </ul>
        </v-card-text>
        <v-divider />
        <v-card-actions class="px-5 py-3">
          <v-spacer />
          <v-btn color="primary" variant="flat" @click="helpDialogOpen = false">知道了</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <TurnDetailDialog v-model="detailDialogOpen" :record="selectedDetail" />
  </div>
</template>
