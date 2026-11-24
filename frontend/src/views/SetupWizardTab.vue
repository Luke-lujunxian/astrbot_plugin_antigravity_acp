<script setup lang="ts">
import { computed, ref } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import CopyField from '@/components/CopyField.vue';
import LoginAuthPanel from '@/components/LoginAuthPanel.vue';
import {
  mdiAlertOutline,
  mdiCheckCircleOutline,
  mdiChevronDown,
  mdiChevronUp,
  mdiHelpCircleOutline,
  mdiInformationOutline,
  mdiRefresh,
} from '@/utils/icons';
import {
  actionErrorLabel,
  EFFORT_LABELS,
  INSTALL_ERROR_LABELS,
  labelOf,
  STAGE_LABELS,
  TOOLS_MODE_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const activeStep = ref(1);
const showModelHelp = ref(false);

const setup = computed(() => props.ctrl.setupSnapshot.value);
const report = computed(() => setup.value?.report ?? {});
const env = computed(() => setup.value?.environment ?? {});
const busy = computed(() => props.ctrl.isBusy.value);
const passed = computed(() => props.ctrl.isPreflightPassed.value);
const models = computed(() => props.ctrl.cachedModels.value);

const checkBadgeText = computed(() => {
  if (setup.value?.busy) return labelOf(STAGE_LABELS, report.value.stage, '正在检测');
  if (passed.value) return '无生成预检通过';
  if (report.value.error_code) {
    return labelOf(INSTALL_ERROR_LABELS, report.value.error_code, report.value.error_code);
  }
  return '等待检测';
});

const checkBadgeColor = computed<'success' | 'error' | 'info' | 'default'>(() => {
  if (setup.value?.busy) return 'info';
  if (passed.value) return 'success';
  if (report.value.error_code) return 'error';
  return 'default';
});

const checkHint = computed(() => {
  if (setup.value?.busy) {
    return `正在${labelOf(STAGE_LABELS, report.value.stage, '检查环境')}…`;
  }
  if (passed.value) {
    return report.value.minimal_tools_status === 'unsupported' ? setup.value?.hint || '' : '';
  }
  return setup.value?.hint || '';
});

const envSummaryText = computed(() => {
  const sys = env.value.system || '未知系统';
  const py = env.value.python || '未知';
  return `${sys} · Python ${py}${env.value.container ? ' · 容器环境' : ''}`;
});

const preflightFacts = computed(() => {
  const items: string[] = [];
  if (report.value.cli_version) items.push(`CLI ${report.value.cli_version}`);
  if (report.value.model_count != null) items.push(`${report.value.model_count} 个可用模型`);
  if (Number.isInteger(report.value.exit_code)) items.push(`CLI 退出码：${report.value.exit_code}`);
  if (report.value.error_code && report.value.stage && STAGE_LABELS[report.value.stage]) {
    items.push(`失败阶段：${STAGE_LABELS[report.value.stage]}`);
  }
  return items;
});

const modelPlaceholder = computed(() => {
  if (models.value.length) return '请选择 Gemini 模型';
  if (passed.value) return '环境已就绪，但未读取到模型目录';
  return '请先完成环境检测';
});

const effortOptions = computed(() => {
  const globalLabel = setup.value?.global_effort || '默认';
  return [
    { value: 'default', title: `跟随全局（${globalLabel}）` },
    ...props.ctrl.availableEfforts.value.map((effort) => ({
      value: effort,
      title: labelOf(EFFORT_LABELS, effort, effort),
    })),
  ];
});

const toolsModeOptions = [
  { value: 'chat', title: '纯聊天（推荐，禁用工具调用节省上下文）' },
  { value: 'inherit', title: '跟随全局开关（受插件 enable_tools 控制）' },
  { value: 'tools', title: '工具模式（需插件开启 enable_tools）' },
];

const lastApplyResult = computed(() => {
  const res = setup.value?.result;
  if (!res || !res.provider_id || typeof res.applied === 'boolean') return null;
  return res;
});

const hasRouteMismatchPartialSave = computed(() =>
  Boolean(
    lastApplyResult.value &&
      setup.value?.action_error &&
      !lastApplyResult.value.default_selected,
  ),
);

function handleModelSelect(nextModel: unknown): void {
  void props.ctrl.onDraftModelChange(typeof nextModel === 'string' ? nextModel : '');
}

async function handleApplySubmit(): Promise<void> {
  await props.ctrl.applyModelConfig();
}
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <v-alert type="info" variant="tonal" density="compact" :icon="mdiInformationOutline">
      首次设置按「环境检测 → 官方登录 → 模型配置」顺序引导。环境预检仅做无生成检查，不发送模型对话，也不代表实时健康。CLI 安装仅提供官方命令复制，不会在后台自动执行 shell 安装。
    </v-alert>

    <v-stepper v-model="activeStep" flat border rounded="lg">
      <v-stepper-header>
        <v-stepper-item
          :value="1"
          title="1. 环境检测"
          :subtitle="checkBadgeText"
          :complete="passed"
          :error="Boolean(!passed && report.error_code)"
          editable
        />
        <v-divider />
        <v-stepper-item
          :value="2"
          title="2. 官方认证"
          :subtitle="passed ? '已通过' : 'Google 登录'"
          :complete="passed"
          :error="setup?.login?.state === 'failed'"
          editable
        />
        <v-divider />
        <v-stepper-item
          :value="3"
          title="3. 模型配置"
          :subtitle="setup?.providers?.length ? `已有 ${setup.providers.length} 个实例` : '选择并保存'"
          :complete="Boolean(setup?.providers?.length)"
          editable
        />
      </v-stepper-header>

      <v-stepper-window>
        <!-- Step 1: 环境检测 -->
        <v-stepper-window-item :value="1">
          <div class="pa-2 pa-sm-4 d-flex flex-column ga-4">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <div>
                <div class="text-subtitle-1 font-weight-semibold">运行环境与官方 CLI 预检</div>
                <div class="text-body-2 text-medium-emphasis">{{ envSummaryText }}</div>
              </div>
              <v-chip size="small" :color="checkBadgeColor" variant="tonal">
                {{ checkBadgeText }}
              </v-chip>
            </div>

            <div v-if="preflightFacts.length" class="d-flex flex-wrap ga-2">
              <v-chip
                v-for="fact in preflightFacts"
                :key="fact"
                size="small"
                variant="outlined"
                class="agy-mono"
              >
                {{ fact }}
              </v-chip>
            </div>

            <v-alert
              v-if="checkHint"
              :type="passed ? 'warning' : report.error_code ? 'error' : 'info'"
              variant="tonal"
              density="compact"
            >
              {{ checkHint }}
            </v-alert>

            <div class="d-flex flex-wrap ga-2 align-center">
              <v-btn
                color="primary"
                variant="flat"
                :disabled="busy"
                :loading="Boolean(setup?.busy)"
                :prepend-icon="mdiRefresh"
                @click="ctrl.runCheck()"
              >
                {{ setup?.busy ? '检测中…' : '重新检测' }}
              </v-btn>
              <v-btn
                variant="outlined"
                :append-icon="ctrl.installPanelOpen.value ? mdiChevronUp : mdiChevronDown"
                @click="ctrl.installPanelOpen.value = !ctrl.installPanelOpen.value"
              >
                CLI 安装命令与路径说明
              </v-btn>
              <v-spacer />
              <v-btn variant="tonal" color="primary" @click="activeStep = 2">
                下一步：官方认证
              </v-btn>
            </div>

            <!-- 折叠安装指引：保持手动开关状态不被轮询覆写（#28） -->
            <v-expand-transition>
              <div v-show="ctrl.installPanelOpen.value" class="agy-subtle-panel d-flex flex-column ga-3">
                <p v-if="env.install_hint" class="text-body-2 text-medium-emphasis mb-0 agy-break">
                  {{ env.install_hint }}
                </p>
                <p v-if="env.discovery_hint" class="text-caption text-medium-emphasis mb-0 agy-break">
                  {{ env.discovery_hint }}
                </p>
                <CopyField
                  :model-value="env.install_command || ''"
                  label="官方安装命令（请手动在目标运行环境执行，插件不自动安装）"
                  button-label="复制命令"
                  aria-label="官方 CLI 安装命令"
                  :is-disposed="ctrl.isDisposed"
                  @notify="({ text, color }) => ctrl.notify(text, color)"
                />
                <CopyField
                  :model-value="env.install_url || ''"
                  label="官方安装与教程文档"
                  button-label="复制文档地址"
                  aria-label="官方文档地址"
                  :is-disposed="ctrl.isDisposed"
                  @notify="({ text, color }) => ctrl.notify(text, color)"
                />
                <p class="text-caption text-medium-emphasis mb-0">
                  自定义路径请在 AstrBot 插件配置中填写 <code class="agy-inline-code">command</code>（Windows 指向 <code class="agy-inline-code">agy.exe</code>）；自定义代理设 <code class="agy-inline-code">proxy_mode=custom</code> 并保存重载。
                </p>
              </div>
            </v-expand-transition>
          </div>
        </v-stepper-window-item>

        <!-- Step 2: 官方认证 -->
        <v-stepper-window-item :value="2">
          <div class="pa-2 pa-sm-4 d-flex flex-column ga-4">
            <LoginAuthPanel :ctrl="ctrl" />
            <div class="d-flex flex-wrap ga-2 justify-space-between">
              <v-btn variant="text" @click="activeStep = 1">上一步：环境检测</v-btn>
              <v-btn variant="tonal" color="primary" @click="activeStep = 3">
                下一步：模型配置
              </v-btn>
            </div>
          </div>
        </v-stepper-window-item>

        <!-- Step 3: 模型配置 -->
        <v-stepper-window-item :value="3">
          <div class="pa-2 pa-sm-4 d-flex flex-column ga-4">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <div class="d-flex align-center ga-2">
                <span class="text-subtitle-1 font-weight-semibold">选择 Gemini 模型并保存为 ACP 实例</span>
                <v-btn
                  size="x-small"
                  variant="text"
                  :icon="mdiHelpCircleOutline"
                  aria-label="模型与模式说明"
                  @click="showModelHelp = !showModelHelp"
                />
              </div>
              <v-chip size="small" :color="passed && models.length ? 'success' : 'default'" variant="tonal">
                {{ models.length ? `${models.length} 个可用模型` : modelPlaceholder }}
              </v-chip>
            </div>

            <v-expand-transition>
              <v-alert
                v-show="showModelHelp"
                type="info"
                variant="tonal"
                density="compact"
                closable
                @click:close="showModelHelp = false"
              >
                <ul class="pl-4 mb-0 text-body-2">
                  <li><strong>思考强度</strong>：选「跟随全局」时沿用插件主配置的 <code class="agy-inline-code">thought_level</code>；切换模型会重置为默认并刷新档位。</li>
                  <li><strong>纯聊天</strong>：禁用工具调用以节省输入上下文（推荐默认）。</li>
                  <li><strong>跟随全局 / 工具模式</strong>：受插件全局总闸 <code class="agy-inline-code">enable_tools</code> 控制。</li>
                </ul>
              </v-alert>
            </v-expand-transition>

            <v-form @submit.prevent="handleApplySubmit">
              <v-row dense>
                <v-col cols="12">
                  <v-autocomplete
                    :model-value="ctrl.draftModel.value || null"
                    :items="models"
                    item-title="name"
                    item-value="id"
                    label="Gemini 模型"
                    :placeholder="modelPlaceholder"
                    variant="outlined"
                    density="comfortable"
                    hide-details="auto"
                    :disabled="busy || !models.length"
                    @update:model-value="handleModelSelect"
                  >
                    <template #item="{ props: itemProps, item }">
                      <v-list-item v-bind="itemProps" :subtitle="item.raw.id" />
                    </template>
                  </v-autocomplete>
                </v-col>

                <v-col cols="12" sm="6">
                  <v-select
                    v-model="ctrl.draftEffort.value"
                    :items="effortOptions"
                    item-title="title"
                    item-value="value"
                    label="思考强度"
                    variant="outlined"
                    density="comfortable"
                    hide-details="auto"
                    :disabled="busy || !passed || !ctrl.draftModel.value"
                  />
                </v-col>

                <v-col cols="12" sm="6">
                  <v-select
                    v-model="ctrl.draftToolsMode.value"
                    :items="toolsModeOptions"
                    item-title="title"
                    item-value="value"
                    label="实例模式"
                    variant="outlined"
                    density="comfortable"
                    hide-details="auto"
                    :disabled="busy || !passed || !ctrl.draftModel.value"
                  />
                </v-col>

                <v-col cols="12">
                  <v-switch
                    v-model="ctrl.draftUseDefault.value"
                    color="primary"
                    density="compact"
                    hide-details="auto"
                    :disabled="busy"
                    label="保存后尝试设为全局默认模型（仅更新默认 profile 本地 Runner，不影响已有群会话覆盖）"
                  />
                </v-col>
              </v-row>

              <div class="d-flex flex-wrap ga-2 align-center mt-4">
                <v-btn variant="text" @click="activeStep = 2">上一步：官方认证</v-btn>
                <v-spacer />
                <v-btn
                  type="submit"
                  color="primary"
                  variant="flat"
                  :disabled="busy || !passed || !ctrl.draftModel.value"
                  :loading="Boolean(setup?.busy && setup?.operation === 'apply')"
                >
                  保存并启用
                </v-btn>
              </div>
            </v-form>

            <!-- 保存结果与 #32 ROUTE_MISMATCH 部分保存提醒（绝不给假绿勾） -->
            <v-alert
              v-if="hasRouteMismatchPartialSave && lastApplyResult"
              type="warning"
              variant="tonal"
              :icon="mdiAlertOutline"
            >
              <div class="font-weight-semibold mb-1">
                实例已保留，但全局默认选择未完成（{{ actionErrorLabel(setup?.action_error || 'ROUTE_MISMATCH') }}）
              </div>
              <p class="text-body-2 mb-2">
                实例 <code class="agy-inline-code">{{ lastApplyResult.provider_id }}</code>
                （状态：{{ lastApplyResult.provider_state === 'created' ? '已新建保留' : '已存在' }}）已保存，
                但宿主全局 Runner 回读校验未确认匹配（<code class="agy-inline-code">default_selected=false</code>）。请前往「模型管理」查看路由诊断并显式重新选择。
              </p>
              <CopyField
                :model-value="`/agy use ${lastApplyResult.provider_id}`"
                label="当前会话手动切换命令"
                button-label="复制命令"
                :is-disposed="ctrl.isDisposed"
                @notify="({ text, color }) => ctrl.notify(text, color)"
              />
            </v-alert>

            <v-alert
              v-else-if="lastApplyResult && !setup?.action_error"
              type="success"
              variant="tonal"
              :icon="mdiCheckCircleOutline"
            >
              <div class="font-weight-semibold mb-1">
                {{
                  lastApplyResult.provider_state === 'created'
                    ? '已新建并启用 ACP 实例'
                    : '已保存并启用 ACP 实例'
                }}
                <code class="agy-inline-code">{{ lastApplyResult.provider_id }}</code>
              </div>
              <p class="text-body-2 mb-2">
                模型：{{ lastApplyResult.model || '已配置' }} · 模式：
                {{ labelOf(TOOLS_MODE_LABELS, lastApplyResult.tools_mode, '跟随全局') }}
                <template v-if="lastApplyResult.default_selected">
                  · <strong>已通过宿主回读校验并设为全局默认模型</strong>。
                </template>
                <template v-else> · 未更改全局默认模型。</template>
              </p>
              <CopyField
                :model-value="`/agy use ${lastApplyResult.provider_id}`"
                label="单会话切换命令"
                button-label="复制命令"
                :is-disposed="ctrl.isDisposed"
                @notify="({ text, color }) => ctrl.notify(text, color)"
              />
            </v-alert>
          </div>
        </v-stepper-window-item>
      </v-stepper-window>
    </v-stepper>
  </div>
</template>
