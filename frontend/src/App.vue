<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue';
import { createDashboardController, type DashboardTab } from '@/composables/useDashboardState';
import AccountEnvTab from '@/views/AccountEnvTab.vue';
import AdvancedTab from '@/views/AdvancedTab.vue';
import ModelsTab from '@/views/ModelsTab.vue';
import MonitorTab from '@/views/MonitorTab.vue';
import OverviewTab from '@/views/OverviewTab.vue';
import SetupWizardTab from '@/views/SetupWizardTab.vue';
import {
  mdiAccountKeyOutline,
  mdiChartBoxOutline,
  mdiRefresh,
  mdiRobotOutline,
  mdiRocketLaunchOutline,
  mdiThemeLightDark,
  mdiTuneVariant,
  mdiViewDashboardOutline,
  mdiWeatherNight,
  mdiWeatherSunny,
} from '@/utils/icons';

const ctrl = createDashboardController();

const tabModel = computed<DashboardTab>({
  get: () => ctrl.activeTab.value,
  set: (value: DashboardTab) => ctrl.selectTab(value),
});

const themeIcon = computed(() => {
  if (ctrl.theme.themeMode.value === 'light') return mdiWeatherSunny;
  if (ctrl.theme.themeMode.value === 'dark') return mdiWeatherNight;
  return mdiThemeLightDark;
});

const navTabs: Array<{ value: DashboardTab; label: string; icon: string }> = [
  { value: 'overview', label: '概览', icon: mdiViewDashboardOutline },
  { value: 'setup', label: '首次设置', icon: mdiRocketLaunchOutline },
  { value: 'models', label: '模型管理', icon: mdiRobotOutline },
  { value: 'account', label: '账号与环境', icon: mdiAccountKeyOutline },
  { value: 'monitor', label: '运行监控', icon: mdiChartBoxOutline },
  { value: 'advanced', label: '高级设置', icon: mdiTuneVariant },
];

onMounted(() => {
  void ctrl.init();
});

onBeforeUnmount(() => {
  ctrl.dispose();
});
</script>

<template>
  <v-app>
    <!-- 紧凑顶栏：贴合 AstrBot 原生插件视图 iframe，不重复宿主侧边栏与大标题 -->
    <div class="agy-header-strip">
      <div class="agy-shell py-2">
        <div class="d-flex align-center justify-space-between flex-wrap ga-2">
          <div class="d-flex align-center flex-wrap ga-2">
            <span class="text-subtitle-1 font-weight-bold">Antigravity ACP</span>
            <v-chip size="x-small" variant="outlined">Gemini CLI</v-chip>
            <v-chip
              size="x-small"
              :color="ctrl.connectionColor.value"
              variant="tonal"
              role="status"
            >
              {{ ctrl.connectionLabel.value }}
            </v-chip>
          </div>

          <div class="d-flex align-center ga-2">
            <v-btn
              size="small"
              variant="text"
              :disabled="ctrl.bridgeUnavailable.value || ctrl.initialConnecting.value"
              :loading="ctrl.monitorPending.value"
              :prepend-icon="mdiRefresh"
              @click="ctrl.refreshNow()"
            >
              刷新
            </v-btn>
            <v-btn
              size="small"
              variant="outlined"
              :prepend-icon="themeIcon"
              @click="ctrl.theme.cycleTheme()"
            >
              {{ ctrl.theme.themeButtonLabel.value }}
            </v-btn>
          </div>
        </div>

        <v-tabs
          v-model="tabModel"
          color="primary"
          align-tabs="start"
          density="comfortable"
          show-arrows
          class="mt-1"
        >
          <v-tab
            v-for="tab in navTabs"
            :key="tab.value"
            :value="tab.value"
            :prepend-icon="tab.icon"
          >
            {{ tab.label }}
          </v-tab>
        </v-tabs>
      </div>
    </div>

    <v-main>
      <div class="agy-shell d-flex flex-column ga-4">
        <!-- 双通道全局错误告警：轮询恢复不清除操作错误（#28） -->
        <v-alert
          v-if="ctrl.actionErrorBanner.value"
          type="error"
          variant="tonal"
          density="comfortable"
          closable
          role="alert"
          @click:close="ctrl.actionErrorBanner.value = ''"
        >
          {{ ctrl.actionErrorBanner.value }}
        </v-alert>

        <v-alert
          v-if="ctrl.pollErrorBanner.value && ctrl.pollErrorBanner.value !== ctrl.actionErrorBanner.value"
          type="warning"
          variant="tonal"
          density="compact"
          role="status"
        >
          {{ ctrl.pollErrorBanner.value }}
        </v-alert>

        <!-- 六大功能视图：使用 v-window 保留各 Tab 内筛选、分页与草稿状态（#28） -->
        <v-window v-model="tabModel" :touch="false">
          <v-window-item value="overview">
            <OverviewTab :ctrl="ctrl" />
          </v-window-item>
          <v-window-item value="setup">
            <SetupWizardTab :ctrl="ctrl" />
          </v-window-item>
          <v-window-item value="models">
            <ModelsTab :ctrl="ctrl" />
          </v-window-item>
          <v-window-item value="account">
            <AccountEnvTab :ctrl="ctrl" />
          </v-window-item>
          <v-window-item value="monitor">
            <MonitorTab :ctrl="ctrl" />
          </v-window-item>
          <v-window-item value="advanced">
            <AdvancedTab :ctrl="ctrl" />
          </v-window-item>
        </v-window>

        <v-divider class="mt-2" />
        <footer class="d-flex justify-space-between align-center flex-wrap ga-2 text-caption text-medium-emphasis">
          <span>AGY ACP · 官方 CLI 本地直连 · 全量本地静态打包</span>
          <span>通信通道：AstrBot Plugin View Bridge</span>
        </footer>
      </div>
    </v-main>

    <v-snackbar
      v-model="ctrl.snackbar.value.show"
      :color="ctrl.snackbar.value.color"
      :timeout="ctrl.snackbar.value.timeout"
      location="bottom center"
    >
      {{ ctrl.snackbar.value.text }}
    </v-snackbar>
  </v-app>
</template>
