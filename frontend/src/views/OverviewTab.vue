<script setup lang="ts">
import { computed } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import RoutingSummaryCard from '@/components/RoutingSummaryCard.vue';
import { formatCount, formatRelativeAgo } from '@/utils/format';
import {
  mdiAccountKeyOutline,
  mdiAlertCircleOutline,
  mdiChartBoxOutline,
  mdiCheckCircleOutline,
  mdiCogOutline,
  mdiRefresh,
  mdiRobotOutline,
  mdiRocketLaunchOutline,
  mdiServerNetwork,
} from '@/utils/icons';
import {
  formatFaultBrief,
  INSTALL_ERROR_LABELS,
  labelOf,
  LOGIN_STATE_LABELS,
  STAGE_LABELS,
  TOOLS_MODE_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const setup = computed(() => props.ctrl.setupSnapshot.value);
const monitor = computed(() => props.ctrl.monitorSnapshot.value);
const report = computed(() => setup.value?.report ?? {});
const login = computed(() => setup.value?.login ?? {});
const providers = computed(() => setup.value?.providers ?? []);
const instances = computed(() => monitor.value?.instances ?? []);
const passed = computed(() => props.ctrl.isPreflightPassed.value);

const cliBadgeText = computed(() => {
  if (setup.value?.busy) return labelOf(STAGE_LABELS, report.value.stage, '正在检测');
  if (passed.value) return '无生成预检通过';
  if (report.value.error_code) {
    return labelOf(INSTALL_ERROR_LABELS, report.value.error_code, report.value.error_code);
  }
  return '等待检测';
});

const cliBadgeColor = computed<'success' | 'error' | 'info' | 'default'>(() => {
  if (setup.value?.busy) return 'info';
  if (passed.value) return 'success';
  if (report.value.error_code) return 'error';
  return 'default';
});

const enabledCount = computed(() => providers.value.filter((p) => p.enabled).length);
const activeRuntimeCount = computed(
  () => instances.value.filter((inst) => inst.runtime_state === 'active').length,
);

const poolTotals = computed(() => {
  const activeInsts = instances.value.filter((i) => i.runtime_state === 'active' && i.pool);
  if (!monitor.value) return null;
  if (!activeInsts.length) {
    return { activeSessions: 0, maxSessions: 0, liveProcesses: 0, initialized: false };
  }
  return {
    activeSessions: activeInsts.reduce((sum, i) => sum + (i.pool?.active_sessions ?? 0), 0),
    maxSessions: activeInsts.reduce((sum, i) => sum + (i.pool?.max_sessions ?? 0), 0),
    liveProcesses: activeInsts.reduce((sum, i) => sum + (i.pool?.live_processes ?? 0), 0),
    initialized: true,
  };
});

const faultSummary = computed(() => {
  if (!monitor.value) return null;
  const failed24h = instances.value.reduce((sum, i) => sum + (i.summary?.failed_turns ?? 0), 0);
  const total24h = instances.value.reduce((sum, i) => sum + (i.summary?.total_turns ?? 0), 0);
  const persistentCount = Array.isArray(monitor.value.failure_events)
    ? monitor.value.failure_events.length
    : null;
  const recentFaults = instances.value
    .flatMap((i) => i.recent_turns)
    .filter((t) => Boolean(t.error_code) || t.status === 'error')
    .sort((a, b) => Date.parse(b.recorded_at || '') - Date.parse(a.recorded_at || ''));
  const latest = recentFaults[0] ?? null;
  return {
    failed24h,
    total24h,
    persistentCount,
    latestCode: latest?.error_code ?? null,
    latestAt: latest?.recorded_at ?? null,
  };
});
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <!-- 顶部四格真实状态概览（无示例数字） -->
    <v-row dense>
      <v-col cols="12" sm="6" lg="3">
        <v-card variant="outlined" class="h-100">
          <v-card-text class="d-flex flex-column ga-2 h-100">
            <div class="d-flex align-center justify-space-between ga-2">
              <span class="text-body-2 text-medium-emphasis d-flex align-center ga-1">
                <v-icon :icon="mdiServerNetwork" size="16" color="primary" />
                <span>CLI 与预检</span>
              </span>
              <v-chip size="x-small" :color="cliBadgeColor" variant="tonal">
                {{ cliBadgeText }}
              </v-chip>
            </div>
            <div class="text-h6 font-weight-bold agy-mono agy-break">
              {{ report.cli_version ? `CLI ${report.cli_version}` : '未探测到版本' }}
            </div>
            <div class="text-caption text-medium-emphasis">
              {{
                typeof report.model_count === 'number'
                  ? `目录 ${report.model_count} 个模型`
                  : '目录未读取'
              }}
              · 仅无生成预检，非实时健康
            </div>
            <v-spacer />
            <div class="d-flex ga-2 pt-1">
              <v-btn
                size="x-small"
                variant="tonal"
                color="primary"
                :disabled="ctrl.isBusy.value"
                :prepend-icon="mdiRefresh"
                @click="ctrl.runCheck()"
              >
                重新检测
              </v-btn>
              <v-btn size="x-small" variant="text" @click="ctrl.selectTab('account')">
                环境详情
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" lg="3">
        <v-card variant="outlined" class="h-100">
          <v-card-text class="d-flex flex-column ga-2 h-100">
            <div class="d-flex align-center justify-space-between ga-2">
              <span class="text-body-2 text-medium-emphasis d-flex align-center ga-1">
                <v-icon :icon="mdiAccountKeyOutline" size="16" color="primary" />
                <span>Google 认证</span>
              </span>
              <v-chip
                size="x-small"
                :color="passed && !login.busy ? 'success' : login.state === 'failed' ? 'error' : 'warning'"
                variant="tonal"
              >
                {{ passed && !login.busy ? '已连接' : labelOf(LOGIN_STATE_LABELS, login.state, '等待检查') }}
              </v-chip>
            </div>
            <div class="text-h6 font-weight-bold">
              {{ passed && !login.busy ? '认证有效' : login.busy ? '登录进行中' : '需要验证或登录' }}
            </div>
            <div class="text-caption text-medium-emphasis">
              {{
                report.auth_bridge === true
                  ? '文件桥接：开启（仅校验与链接）'
                  : report.auth_bridge === false
                    ? '文件桥接：关闭（CLI 自管）'
                    : '认证桥接状态：未知'
              }}
            </div>
            <v-spacer />
            <div class="pt-1">
              <v-btn size="x-small" variant="tonal" color="primary" @click="ctrl.selectTab('account')">
                管理登录与认证
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" lg="3">
        <v-card variant="outlined" class="h-100">
          <v-card-text class="d-flex flex-column ga-2 h-100">
            <div class="d-flex align-center justify-space-between ga-2">
              <span class="text-body-2 text-medium-emphasis d-flex align-center ga-1">
                <v-icon :icon="mdiRobotOutline" size="16" color="primary" />
                <span>ACP 实例与会话池</span>
              </span>
              <v-chip size="x-small" :color="enabledCount > 0 ? 'success' : 'default'" variant="tonal">
                启用 {{ enabledCount }} / {{ providers.length }}
              </v-chip>
            </div>
            <div class="text-h6 font-weight-bold agy-tabular">
              <template v-if="poolTotals === null">未知</template>
              <template v-else-if="poolTotals.initialized">
                {{ formatCount(poolTotals.activeSessions) }} / {{ formatCount(poolTotals.maxSessions) }} 会话
              </template>
              <template v-else>0 个已初始化实例</template>
            </div>
            <div class="text-caption text-medium-emphasis agy-tabular">
              已初始化 {{ activeRuntimeCount }} 个 · 存活进程
              {{ poolTotals === null ? '未知' : formatCount(poolTotals.liveProcesses) }}
              （active 仅表示已加载，不等同正在服务）
            </div>
            <v-spacer />
            <div class="pt-1">
              <v-btn size="x-small" variant="tonal" color="primary" @click="ctrl.selectTab('models')">
                管理模型实例
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" lg="3">
        <v-card variant="outlined" class="h-100">
          <v-card-text class="d-flex flex-column ga-2 h-100">
            <div class="d-flex align-center justify-space-between ga-2">
              <span class="text-body-2 text-medium-emphasis d-flex align-center ga-1">
                <v-icon
                  :icon="faultSummary && faultSummary.failed24h > 0 ? mdiAlertCircleOutline : mdiCheckCircleOutline"
                  size="16"
                  :color="faultSummary && faultSummary.failed24h > 0 ? 'error' : 'success'"
                />
                <span>近期异常（近 24h）</span>
              </span>
              <v-chip
                size="x-small"
                :color="faultSummary && faultSummary.failed24h > 0 ? 'error' : 'success'"
                variant="tonal"
              >
                {{
                  faultSummary === null
                    ? '未加载'
                    : faultSummary.failed24h > 0
                      ? `${faultSummary.failed24h} 次失败`
                      : '无失败记录'
                }}
              </v-chip>
            </div>
            <div class="text-h6 font-weight-bold agy-break">
              <template v-if="faultSummary === null">未知</template>
              <template v-else-if="faultSummary.latestCode">
                {{ formatFaultBrief(faultSummary.latestCode) }}
              </template>
              <template v-else>
                {{ faultSummary.total24h > 0 ? '近期无异常' : '暂无记录' }}
              </template>
            </div>
            <div class="text-caption text-medium-emphasis agy-tabular">
              <template v-if="faultSummary === null">等待监控快照…</template>
              <template v-else>
                24h 总轮数 {{ formatCount(faultSummary.total24h) }}
                <template v-if="faultSummary.persistentCount !== null">
                  · 持久失败日志 {{ formatCount(faultSummary.persistentCount) }} 条
                </template>
                <template v-if="faultSummary.latestAt">
                  · {{ formatRelativeAgo(faultSummary.latestAt, ctrl.nowTick.value) }}
                </template>
              </template>
            </div>
            <v-spacer />
            <div class="pt-1">
              <v-btn size="x-small" variant="tonal" color="primary" @click="ctrl.selectTab('monitor')">
                查看运行监控
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 全局路由与真实服务观测（#32 核心语义分区） -->
    <RoutingSummaryCard
      :routing="ctrl.combinedRouting.value"
      :schema-version="monitor?.schema_version ?? null"
      :now-tick="ctrl.nowTick.value"
    />

    <!-- 已配置实例快览与快速操作 -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiRobotOutline" color="primary" />
        </template>
        <v-card-title>已配置的 ACP 实例</v-card-title>
        <v-card-subtitle>
          查看已有实例状态，或进入对应模块完成首次设置、路由切换与深度监控。
        </v-card-subtitle>
        <template #append>
          <div class="d-flex flex-wrap ga-2">
            <v-btn
              size="small"
              variant="tonal"
              color="primary"
              :prepend-icon="mdiRocketLaunchOutline"
              @click="ctrl.selectTab('setup')"
            >
              首次设置向导
            </v-btn>
            <v-btn
              size="small"
              variant="outlined"
              :prepend-icon="mdiChartBoxOutline"
              @click="ctrl.selectTab('monitor')"
            >
              运行监控
            </v-btn>
            <v-btn
              size="small"
              variant="text"
              :prepend-icon="mdiCogOutline"
              @click="ctrl.selectTab('advanced')"
            >
              高级与导出
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <v-alert v-if="providers.length === 0" type="info" variant="tonal" density="comfortable">
          当前尚未保存任何 AGY ACP 模型实例。点击右上角「首次设置向导」完成环境预检、Google 认证与模型保存。
        </v-alert>

        <v-row v-else dense>
          <v-col v-for="row in providers" :key="row.id" cols="12" md="6">
            <div class="agy-subtle-panel d-flex flex-column ga-2 h-100">
              <div class="d-flex align-center justify-space-between flex-wrap ga-2">
                <span class="font-weight-semibold agy-mono agy-break">{{ row.id }}</span>
                <div class="d-flex flex-wrap ga-1">
                  <v-chip
                    v-if="ctrl.combinedRouting.value?.resolved_primary_id === row.id"
                    size="x-small"
                    color="primary"
                    variant="flat"
                  >
                    全局解析主项
                  </v-chip>
                  <v-chip
                    size="x-small"
                    :color="row.enabled ? 'success' : 'default'"
                    variant="tonal"
                  >
                    {{ row.enabled ? '已启用' : '已停用' }}
                  </v-chip>
                  <v-chip size="x-small" variant="outlined">
                    {{ labelOf(TOOLS_MODE_LABELS, row.tools_mode, '跟随全局') }}
                  </v-chip>
                </div>
              </div>
              <div class="text-body-2 text-medium-emphasis agy-mono agy-break">
                模型：{{ row.model || '未选择模型' }}
              </div>
              <div class="text-caption text-medium-emphasis">
                单会话切换命令：<code class="agy-inline-code">/agy use {{ row.id }}</code>
              </div>
            </div>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </div>
</template>
