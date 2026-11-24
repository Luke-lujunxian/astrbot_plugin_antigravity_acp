<script setup lang="ts">
import { computed } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import CopyField from '@/components/CopyField.vue';
import LoginAuthPanel from '@/components/LoginAuthPanel.vue';
import { mdiAlertOutline, mdiLanConnect, mdiRefresh, mdiServerNetwork } from '@/utils/icons';
import {
  labelOf,
  MINIMAL_TOOLS_LABELS,
  STAGE_LABELS,
  SUPERVISION_LABELS,
  TRANSPORT_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const setup = computed(() => props.ctrl.setupSnapshot.value);
const report = computed(() => setup.value?.report ?? {});
const env = computed(() => setup.value?.environment ?? {});

const diagRows = computed<Array<[string, string]>>(() => {
  const r = report.value;
  const rows: Array<[string, string]> = [];
  rows.push([
    '预检状态与阶段',
    `${r.status || '未知'} · ${labelOf(STAGE_LABELS, r.stage, '未知')}`,
  ]);
  rows.push(['CLI 版本', r.cli_version || '未探测']);
  rows.push([
    'CLI 退出码',
    Number.isInteger(r.exit_code) ? String(r.exit_code) : '未报告 / 未知',
  ]);
  if (r.protocol_version != null) rows.push(['ACP 协议版本', `v${r.protocol_version}`]);
  if (r.customizations_mode) rows.push(['组件模式', r.customizations_mode]);
  if (r.cli_flags) {
    rows.push([
      'CLI 参数探测',
      `精简组件=${r.cli_flags.include_default_customizations ? '支持' : '未探测到'} · 禁用遥测=${r.cli_flags.disable_telemetry ? '支持' : '不支持'}`,
    ]);
  }
  if (r.minimal_tools_status) {
    rows.push([
      '精简状态',
      labelOf(MINIMAL_TOOLS_LABELS, r.minimal_tools_status, r.minimal_tools_status),
    ]);
  }
  if (r.tool_bridge_transport) {
    rows.push(['工具桥传输', labelOf(TRANSPORT_LABELS, r.tool_bridge_transport, '未知')]);
  }
  if (r.process_supervision) {
    rows.push(['进程托管', labelOf(SUPERVISION_LABELS, r.process_supervision, '未知')]);
  }
  if (r.proxy_mode) {
    rows.push([
      '代理模式',
      `${r.proxy_mode}${env.value.proxy_mode_note ? `（${env.value.proxy_mode_note}）` : ''}`,
    ]);
  }
  if (r.auth_bridge !== undefined) {
    rows.push(['官方认证文件桥接', r.auth_bridge ? '开启（单文件校验链接）' : '关闭']);
  }
  if (r.cli_update_status) {
    rows.push(['CLI 更新策略', '手动外部管理，不检查或覆盖全局 CLI']);
  }
  if (r.advertised_capabilities) {
    const caps = r.advertised_capabilities;
    rows.push([
      'ACP 能力声明',
      `MCP(http=${Boolean(caps.mcpCapabilities?.http)}, sse=${Boolean(caps.mcpCapabilities?.sse)}) · 模态(img=${Boolean(caps.promptCapabilities?.image)}, audio=${Boolean(caps.promptCapabilities?.audio)}, ctx=${Boolean(caps.promptCapabilities?.embeddedContext)})`,
    ]);
  }
  rows.push([
    '是否发送模型对话',
    r.model_prompt_sent === false ? '否（仅无生成预检）' : String(r.model_prompt_sent ?? '未知'),
  ]);
  return rows;
});
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <v-row dense>
      <!-- Google 登录与账号安全边界 -->
      <v-col cols="12" lg="6">
        <v-card variant="outlined" class="h-100">
          <v-card-text>
            <LoginAuthPanel :ctrl="ctrl" />
          </v-card-text>
        </v-card>
      </v-col>

      <!-- 运行环境、容器说明与安装命令 -->
      <v-col cols="12" lg="6">
        <v-card variant="outlined" class="h-100">
          <v-card-item>
            <template #prepend>
              <v-icon :icon="mdiServerNetwork" color="primary" />
            </template>
            <v-card-title>运行环境与 CLI 发现路径</v-card-title>
            <v-card-subtitle>
              {{ env.system || '未知系统' }} · Python {{ env.python || '未知' }}
              {{ env.container ? '· 容器环境' : '' }}
            </v-card-subtitle>
            <template #append>
              <v-btn
                size="small"
                variant="tonal"
                color="primary"
                :disabled="ctrl.isBusy.value"
                :loading="Boolean(setup?.busy)"
                :prepend-icon="mdiRefresh"
                @click="ctrl.runCheck()"
              >
                重新检测
              </v-btn>
            </template>
          </v-card-item>

          <v-divider />

          <v-card-text class="d-flex flex-column ga-3">
            <v-alert
              v-if="env.container"
              type="warning"
              variant="tonal"
              density="compact"
              :icon="mdiAlertOutline"
            >
              检测到容器运行环境。宿主机安装的 CLI 或认证目录不能自动被容器访问；请在容器内以 AstrBot 同用户安装登录，并持久化官方认证目录。容器内 <code class="agy-inline-code">127.0.0.1</code> 指向容器自身。
            </v-alert>

            <div class="agy-subtle-panel d-flex flex-column ga-2">
              <div class="text-body-2 font-weight-semibold">CLI 搜索范围与 command 说明</div>
              <p class="text-body-2 text-medium-emphasis mb-0 agy-break">
                {{ env.discovery_hint || '正在读取发现策略…' }}
              </p>
              <p v-if="env.install_hint" class="text-caption text-medium-emphasis mb-0 agy-break">
                {{ env.install_hint }}
              </p>
            </div>

            <CopyField
              :model-value="env.install_command || ''"
              label="官方安装命令（手动执行）"
              button-label="复制命令"
              :is-disposed="ctrl.isDisposed"
              @notify="({ text, color }) => ctrl.notify(text, color)"
            />

            <CopyField
              :model-value="env.install_url || ''"
              label="官方文档地址"
              button-label="复制链接"
              :is-disposed="ctrl.isDisposed"
              @notify="({ text, color }) => ctrl.notify(text, color)"
            />
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 完整无生成预检技术诊断 -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiLanConnect" color="primary" />
        </template>
        <v-card-title>无生成预检与环境诊断明细</v-card-title>
        <v-card-subtitle>
          以下字段来自最近一次无生成预检，不会发送任何模型对话请求；修改 <code class="agy-inline-code">command</code> 或代理设置后需在宿主重载插件。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <dl class="agy-kv-grid">
          <div v-for="[k, v] in diagRows" :key="k" class="agy-kv-item agy-subtle-panel">
            <dt>{{ k }}</dt>
            <dd>{{ v }}</dd>
          </div>
        </dl>
      </v-card-text>
    </v-card>
  </div>
</template>
