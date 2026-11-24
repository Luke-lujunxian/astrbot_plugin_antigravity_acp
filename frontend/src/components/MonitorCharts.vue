<script setup lang="ts">
import { computed } from 'vue';
import type { MonitorSummary, RecentTurn } from '@/types/api';
import { formatCount, formatDuration, formatPercent, formatRelativeAgo } from '@/utils/format';
import { labelOf, REBUILD_REASON_LABELS, TURN_STATUS_LABELS } from '@/utils/labels';

const props = defineProps<{
  summary: MonitorSummary | null;
  recentTurns: RecentTurn[];
  nowTick: number;
}>();

const CIRCUMFERENCE = 2 * Math.PI * 15;

// 24h Token composition (unknown stays unknown; never coerced to 0)
const reportedTurns = computed(() => props.summary?.reported_usage_turns ?? 0);
const unavailableTurns = computed(() => props.summary?.unavailable_usage_turns ?? 0);
const missingCacheTurns = computed(() => props.summary?.missing_cache_field_turns ?? 0);

const hasCachedBucket = computed(() => {
  const cached = props.summary?.total_input_cached;
  return (
    reportedTurns.value > 0 &&
    reportedTurns.value > missingCacheTurns.value &&
    typeof cached === 'number' &&
    Number.isFinite(cached)
  );
});

const inputOther = computed(() => {
  const value = props.summary?.total_input_other;
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
});
const inputCached = computed(() => {
  const value = props.summary?.total_input_cached;
  return hasCachedBucket.value && typeof value === 'number' ? value : 0;
});
const outputTotal = computed(() => {
  const value = props.summary?.total_output;
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
});
const tokenTotal = computed(() => inputOther.value + inputCached.value + outputTotal.value);

const stackBars = computed(() => {
  if (reportedTurns.value <= 0 || tokenTotal.value <= 0) return [];
  const width = 300;
  const parts = [
    { key: 'input', label: '非缓存输入', value: inputOther.value, color: 'var(--agy-chart-input)' },
    ...(hasCachedBucket.value
      ? [{ key: 'cached', label: '缓存读取', value: inputCached.value, color: 'var(--agy-chart-cached)' }]
      : []),
    { key: 'output', label: '输出', value: outputTotal.value, color: 'var(--agy-chart-output)' },
  ].filter((p) => p.value > 0);

  let cursor = 0;
  return parts.map((part, idx) => {
    const remaining = width - cursor;
    const w =
      idx === parts.length - 1
        ? Math.max(0, remaining)
        : Math.min(remaining, Math.max(2, Math.round((part.value / tokenTotal.value) * width)));
    const rect = { ...part, x: cursor, width: w };
    cursor += w;
    return rect;
  });
});

// Gauges
function gaugeDash(rate: number | null | undefined): string | null {
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return null;
  const clamped = Math.max(0, Math.min(1, rate));
  return `${(clamped * CIRCUMFERENCE).toFixed(2)} ${CIRCUMFERENCE.toFixed(2)}`;
}

const reuseDash = computed(() => gaugeDash(props.summary?.reuse_rate));
const cacheDash = computed(() => gaugeDash(props.summary?.cache_token_ratio));

const sentTurns = computed(() => props.summary?.request_sent_turns ?? 0);
const reuseEmptyText = computed(() => (sentTurns.value === 0 ? '暂无样本' : '未知'));
const cacheEmptyText = computed(() =>
  reportedTurns.value > 0 && reportedTurns.value === missingCacheTurns.value
    ? '未报告缓存字段'
    : '暂无样本',
);

// Latency bar chart
const timedTurns = computed(() =>
  props.recentTurns
    .slice()
    .reverse()
    .filter((t): t is RecentTurn & { elapsed_ms: number } => typeof t.elapsed_ms === 'number' && Number.isFinite(t.elapsed_ms)),
);

const latencyStats = computed(() => {
  const list = timedTurns.value;
  if (!list.length) return null;
  const maxMs = Math.max(...list.map((t) => t.elapsed_ms), 1);
  const avgMs = Math.round(list.reduce((acc, t) => acc + t.elapsed_ms, 0) / list.length);
  const latestMs = list[list.length - 1].elapsed_ms;
  const width = 300;
  const slot = width / Math.max(list.length, 6);
  const barWidth = Math.min(18, Math.max(4, slot * 0.68));
  const bars = list.map((turn, idx) => {
    const barH = Math.max(4, Math.round((turn.elapsed_ms / maxMs) * 50));
    const x = Number((idx * slot + (slot - barWidth) / 2).toFixed(1));
    const y = Number((56 - barH).toFixed(1));
    const color = turn.status === 'ok' ? 'var(--agy-chart-input)' : 'var(--agy-chart-error)';
    const title = `${formatDuration(turn.elapsed_ms)} · ${labelOf(TURN_STATUS_LABELS, turn.status, '未知')}${turn.error_code ? ` (${turn.error_code})` : ''} · ${formatRelativeAgo(turn.recorded_at, props.nowTick)}`;
    return { x, y, width: Number(barWidth.toFixed(1)), height: barH, color, title };
  });
  return { maxMs, avgMs, latestMs, bars };
});

const rebuildReasons = computed(() => {
  const reasons = props.summary?.rebuild_reasons;
  return Array.isArray(reasons) ? reasons.slice(0, 8) : [];
});

const rebuildTotal = computed(() =>
  rebuildReasons.value.reduce((acc, [, n]) => acc + (Number.isFinite(n) ? n : 0), 0),
);
</script>

<template>
  <div class="d-flex flex-column ga-3">
    <!-- 24h Token 构成 -->
    <div class="agy-subtle-panel d-flex flex-column ga-2">
      <div class="d-flex align-center justify-space-between flex-wrap ga-2">
        <span class="text-body-2 font-weight-semibold">24h Token 构成</span>
        <span class="text-caption text-medium-emphasis agy-tabular">
          {{ reportedTurns > 0 ? `已上报 ${reportedTurns} 轮` : '近 24h' }}
        </span>
      </div>

      <p v-if="reportedTurns <= 0" class="text-caption text-medium-emphasis mb-0">
        {{
          unavailableTurns > 0
            ? `暂无已上报用量（${unavailableTurns} 轮上游未报告；未知不按 0 计）`
            : '暂无已上报 Token 用量'
        }}
      </p>
      <p v-else-if="tokenTotal <= 0" class="text-caption text-medium-emphasis mb-0">
        已上报轮次用量为 0
      </p>
      <template v-else>
        <svg
          class="agy-token-stack-svg"
          role="img"
          viewBox="0 0 300 14"
          preserveAspectRatio="none"
          :aria-label="`24h Token 构成：非缓存输入 ${formatCount(inputOther)}，输出 ${formatCount(outputTotal)}`"
        >
          <rect
            v-for="bar in stackBars"
            :key="bar.key"
            :x="bar.x"
            y="0"
            :width="bar.width"
            height="14"
            :fill="bar.color"
          />
        </svg>
        <div class="d-flex flex-wrap ga-3 text-caption text-medium-emphasis agy-tabular">
          <span class="d-inline-flex align-center ga-1">
            <span class="agy-legend-dot agy-legend-dot--input" />
            非缓存输入 {{ formatCount(inputOther) }} ({{ ((inputOther / tokenTotal) * 100).toFixed(1) }}%)
          </span>
          <span class="d-inline-flex align-center ga-1">
            <span class="agy-legend-dot agy-legend-dot--cached" />
            <template v-if="hasCachedBucket">
              缓存读取 {{ formatCount(inputCached) }} ({{ ((inputCached / tokenTotal) * 100).toFixed(1) }}%)
            </template>
            <template v-else>缓存读取 上游未报告</template>
          </span>
          <span class="d-inline-flex align-center ga-1">
            <span class="agy-legend-dot agy-legend-dot--output" />
            输出 {{ formatCount(outputTotal) }} ({{ ((outputTotal / tokenTotal) * 100).toFixed(1) }}%)
          </span>
        </div>
      </template>
    </div>

    <!-- 双环形指标：会话复用率 / 缓存读取占比 -->
    <v-row dense>
      <v-col cols="12" sm="6">
        <div class="agy-subtle-panel d-flex align-center ga-3 h-100">
          <svg class="agy-gauge-svg" viewBox="0 0 40 40" aria-hidden="true">
            <circle
              cx="20"
              cy="20"
              r="15"
              fill="none"
              stroke="var(--agy-chart-track)"
              stroke-width="4.5"
              :stroke-dasharray="reuseDash ? undefined : '3 3'"
            />
            <circle
              v-if="reuseDash"
              cx="20"
              cy="20"
              r="15"
              fill="none"
              stroke="var(--agy-chart-input)"
              stroke-width="4.5"
              stroke-linecap="round"
              :stroke-dasharray="reuseDash"
              transform="rotate(-90 20 20)"
            />
          </svg>
          <div class="d-flex flex-column">
            <span class="text-caption text-medium-emphasis">会话复用率 (24h)</span>
            <span class="text-subtitle-1 font-weight-bold agy-tabular">
              {{ reuseDash ? formatPercent(summary?.reuse_rate) : reuseEmptyText }}
            </span>
            <span v-if="sentTurns > 0" class="text-caption text-medium-emphasis agy-tabular">
              基于 {{ formatCount(sentTurns) }} 次实际发送
            </span>
          </div>
        </div>
      </v-col>

      <v-col cols="12" sm="6">
        <div class="agy-subtle-panel d-flex align-center ga-3 h-100">
          <svg class="agy-gauge-svg" viewBox="0 0 40 40" aria-hidden="true">
            <circle
              cx="20"
              cy="20"
              r="15"
              fill="none"
              stroke="var(--agy-chart-track)"
              stroke-width="4.5"
              :stroke-dasharray="cacheDash ? undefined : '3 3'"
            />
            <circle
              v-if="cacheDash"
              cx="20"
              cy="20"
              r="15"
              fill="none"
              stroke="var(--agy-chart-cached)"
              stroke-width="4.5"
              stroke-linecap="round"
              :stroke-dasharray="cacheDash"
              transform="rotate(-90 20 20)"
            />
          </svg>
          <div class="d-flex flex-column">
            <span class="text-caption text-medium-emphasis">缓存读取占比 (24h)</span>
            <span class="text-subtitle-1 font-weight-bold agy-tabular">
              {{ cacheDash ? formatPercent(summary?.cache_token_ratio) : cacheEmptyText }}
            </span>
            <span v-if="missingCacheTurns > 0" class="text-caption text-medium-emphasis agy-tabular">
              {{ formatCount(missingCacheTurns) }} 轮缺缓存字段
            </span>
          </div>
        </div>
      </v-col>
    </v-row>

    <!-- 最近请求耗时分布 -->
    <div class="agy-subtle-panel d-flex flex-column ga-2">
      <div class="d-flex align-center justify-space-between flex-wrap ga-2">
        <span class="text-body-2 font-weight-semibold">
          最近请求耗时{{ timedTurns.length ? `（近 ${timedTurns.length} 轮）` : '' }}
        </span>
        <span v-if="latencyStats" class="text-caption text-medium-emphasis agy-tabular">
          最新 {{ formatDuration(latencyStats.latestMs) }} · 均值 {{ formatDuration(latencyStats.avgMs) }}
        </span>
      </div>

      <p v-if="!latencyStats" class="text-caption text-medium-emphasis mb-0">暂无耗时采样</p>
      <template v-else>
        <svg
          class="agy-latency-svg"
          role="img"
          viewBox="0 0 300 60"
          preserveAspectRatio="none"
          :aria-label="`最近 ${timedTurns.length} 轮请求耗时，峰值 ${formatDuration(latencyStats.maxMs)}`"
        >
          <line x1="0" y1="29" x2="300" y2="29" stroke="var(--agy-chart-track)" stroke-dasharray="2 3" stroke-width="1" />
          <line x1="0" y1="56" x2="300" y2="56" stroke="var(--agy-chart-track)" stroke-width="1" />
          <rect
            v-for="(bar, idx) in latencyStats.bars"
            :key="idx"
            :x="bar.x"
            :y="bar.y"
            :width="bar.width"
            :height="bar.height"
            rx="2"
            :fill="bar.color"
          >
            <title>{{ bar.title }}</title>
          </rect>
        </svg>
        <div class="d-flex justify-space-between text-caption text-medium-emphasis agy-tabular">
          <span>较早</span>
          <span>峰值 {{ formatDuration(latencyStats.maxMs) }}</span>
          <span>最新</span>
        </div>
      </template>
    </div>

    <!-- 会话重建原因 -->
    <div class="agy-subtle-panel d-flex flex-column ga-2">
      <div class="d-flex align-center justify-space-between flex-wrap ga-2">
        <span class="text-body-2 font-weight-semibold">会话重建原因 (24h)</span>
        <span v-if="rebuildReasons.length" class="text-caption text-medium-emphasis agy-tabular">
          合计 {{ formatCount(rebuildTotal) }} 次
        </span>
      </div>
      <div v-if="rebuildReasons.length" class="d-flex flex-wrap ga-1">
        <v-chip
          v-for="[reason, count] in rebuildReasons"
          :key="reason"
          size="x-small"
          variant="outlined"
        >
          {{ labelOf(REBUILD_REASON_LABELS, reason, reason) }} × {{ formatCount(count) }}
        </v-chip>
      </div>
      <p v-else class="text-caption text-medium-emphasis mb-0">暂无会话重建记录</p>
    </div>
  </div>
</template>
