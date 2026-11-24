<script setup lang="ts">
import { computed } from 'vue';
import type { RoutingSnapshot } from '@/types/api';
import { formatBoolState, formatDateTime, formatRelativeAgo } from '@/utils/format';
import { mdiAlertOutline, mdiClockOutline, mdiInformationOutline, mdiRoutes } from '@/utils/icons';
import { labelOf, RESOLUTION_REASON_LABELS } from '@/utils/labels';

const props = withDefaults(
  defineProps<{
    routing: RoutingSnapshot | null;
    schemaVersion?: number | null;
    nowTick?: number;
    compact?: boolean;
  }>(),
  {
    schemaVersion: null,
    nowTick: 0,
    compact: false,
  },
);

const invalidSet = computed(() => new Set(props.routing?.invalid_fallback_ids ?? []));

const reasonColor = computed<'success' | 'warning' | 'error' | 'info' | 'default'>(() => {
  const reason = props.routing?.resolution_reason;
  if (!reason || reason === 'unknown') return 'default';
  if (reason === 'configured_primary') return props.routing?.is_acp ? 'success' : 'info';
  if (reason === 'implicit_first_provider' || reason === 'non_local_runner') return 'warning';
  if (reason === 'missing_primary') return 'error';
  return 'default';
});

const reasonText = computed(() =>
  props.routing
    ? labelOf(RESOLUTION_REASON_LABELS, props.routing.resolution_reason, '未知')
    : '未知（后端未提供路由字段）',
);

const alertInfo = computed<{ type: 'warning' | 'error' | 'info'; text: string } | null>(() => {
  const r = props.routing;
  if (!r) {
    if (props.schemaVersion === 1) {
      return {
        type: 'info',
        text: '当前后端监控为 schema v1，未下发全局路由与服务观测字段，相关项显示为「未知」。',
      };
    }
    return null;
  }
  if (r.resolution_reason === 'implicit_first_provider') {
    return {
      type: 'warning',
      text: '配置的主模型 ID 缺失、未启用或不可解析，宿主当前隐式回退到首个可用模型实例，请检查并显式重新选定目标实例。',
    };
  }
  if (r.resolution_reason === 'missing_primary') {
    return {
      type: 'error',
      text: '宿主全局默认本地 Runner 当前没有可解析的聊天模型实例。',
    };
  }
  if (r.resolution_reason === 'non_local_runner') {
    return {
      type: 'info',
      text: '当前全局 Agent Runner 非本地 Runner（non_local_runner），本地聊天模型列表与主备解析不适用。',
    };
  }
  if (r.invalid_fallback_ids.length > 0) {
    return {
      type: 'warning',
      text: `备用模型列表中存在 ${r.invalid_fallback_ids.length} 项无效、未启用或未加载的实例 ID，请核对宿主配置。`,
    };
  }
  return null;
});

const hasObservation = computed(
  () => Boolean(props.routing?.last_observed_provider_id && props.routing?.last_observed_at),
);

const observedAgo = computed(() =>
  props.routing?.last_observed_at
    ? formatRelativeAgo(props.routing.last_observed_at, props.nowTick || Date.now())
    : '未知',
);
</script>

<template>
  <v-card variant="outlined">
    <v-card-item>
      <template #prepend>
        <v-icon :icon="mdiRoutes" color="primary" />
      </template>
      <v-card-title class="d-flex align-center flex-wrap ga-2">
        <span>全局路由与 ACP 服务观测</span>
        <v-chip size="x-small" color="primary" variant="tonal">
          范围：全局（{{ routing?.scope || 'global' }}）
        </v-chip>
        <v-chip size="x-small" :color="reasonColor" variant="tonal">
          {{ reasonText }}
        </v-chip>
      </v-card-title>
      <v-card-subtitle class="agy-break">
        全局默认路由仅反映默认 profile（空 UMO），不代表任意具体群聊或私聊的会话覆盖路由。
      </v-card-subtitle>
    </v-card-item>

    <v-divider />

    <v-card-text class="d-flex flex-column ga-4">
      <v-alert
        v-if="alertInfo"
        :type="alertInfo.type"
        variant="tonal"
        density="compact"
        :icon="alertInfo.type === 'info' ? mdiInformationOutline : mdiAlertOutline"
      >
        {{ alertInfo.text }}
      </v-alert>

      <v-row dense>
        <!-- 配置与解析路由 -->
        <v-col cols="12" :md="compact ? 12 : 7">
          <div class="agy-subtle-panel h-100 d-flex flex-column ga-3">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <span class="text-subtitle-2 font-weight-bold">配置路由（宿主本地 Runner 解析）</span>
              <v-chip
                v-if="routing && routing.is_acp !== null"
                size="x-small"
                :color="routing.is_acp ? 'success' : 'default'"
                variant="outlined"
              >
                {{ routing.is_acp ? '解析为 ACP 实例' : '解析为非 ACP 实例' }}
              </v-chip>
              <v-chip v-else size="x-small" variant="outlined">解析类型：未知</v-chip>
            </div>

            <dl class="agy-kv-grid">
              <div class="agy-kv-item">
                <dt>配置主模型 ID</dt>
                <dd class="agy-mono">{{ routing?.configured_primary_id || '未知 / 未配置' }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>宿主实际解析主 ID</dt>
                <dd class="agy-mono font-weight-medium">
                  {{ routing?.resolved_primary_id || '未知 / 无' }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>主配置行存在 / 启用</dt>
                <dd>
                  {{ formatBoolState(routing?.primary_exists, '存在', '缺失') }} /
                  {{ formatBoolState(routing?.primary_enabled, '已启用', '已停用') }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>解析原因</dt>
                <dd>{{ reasonText }}</dd>
              </div>
            </dl>

            <div>
              <div class="text-caption text-medium-emphasis mb-1">显式备用链（按配置顺序）</div>
              <div
                v-if="routing && routing.explicit_fallback_ids.length > 0"
                class="d-flex flex-wrap ga-1"
              >
                <v-chip
                  v-for="(fid, idx) in routing.explicit_fallback_ids"
                  :key="`${fid}-${idx}`"
                  size="small"
                  :color="invalidSet.has(fid) ? 'error' : 'default'"
                  :variant="invalidSet.has(fid) ? 'tonal' : 'outlined'"
                >
                  <span class="agy-mono">{{ idx + 1 }}. {{ fid }}</span>
                  <span v-if="invalidSet.has(fid)" class="ml-1">（无效/未加载）</span>
                </v-chip>
              </div>
              <div v-else class="text-body-2 text-medium-emphasis">
                {{
                  !routing || routing.resolution_reason === 'unknown'
                    ? '未知'
                    : routing.resolution_reason === 'non_local_runner'
                      ? '不适用（非本地 Runner）'
                      : '未配置显式备用模型'
                }}
              </div>
            </div>
          </div>
        </v-col>

        <!-- 真实服务观测（独立语义，绝不混同配置主项） -->
        <v-col cols="12" :md="compact ? 12 : 5">
          <div class="agy-subtle-panel h-100 d-flex flex-column ga-3">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <span class="text-subtitle-2 font-weight-bold d-flex align-center ga-1">
                <v-icon :icon="mdiClockOutline" size="16" color="primary" />
                <span>最近 ACP 服务观测</span>
              </span>
              <v-chip size="x-small" color="info" variant="tonal">
                口径：{{
                  routing?.last_observed_scope === 'plugin_only'
                    ? '仅本插件 (plugin_only)'
                    : '未知 (unknown)'
                }}
              </v-chip>
            </div>

            <dl class="agy-kv-grid">
              <div class="agy-kv-item">
                <dt>最近成功完成的 ACP 实例</dt>
                <dd class="agy-mono font-weight-medium">
                  {{ hasObservation ? routing?.last_observed_provider_id : '未知' }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>观测时间</dt>
                <dd>
                  <template v-if="hasObservation">
                    {{ formatDateTime(routing?.last_observed_at) }}
                    <span class="text-caption text-medium-emphasis">（{{ observedAgo }}）</span>
                  </template>
                  <template v-else>未知</template>
                </dd>
              </div>
            </dl>

            <p class="text-caption text-medium-emphasis mb-0">
              仅记录插件启动后已发送 prompt 并成功完成的 ACP 回合（可含管理员真实生成）；无法观测其他非 ACP Provider 的服务状态或单会话实际路由。未观测为「未知」，不等于故障。
            </p>
          </div>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>
