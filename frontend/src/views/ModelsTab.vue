<script setup lang="ts">
import { computed, ref } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import type { MonitorInstance, ProviderImpact } from '@/types/api';
import CopyField from '@/components/CopyField.vue';
import ProviderImpactDialog, { type ProviderDialogMode } from '@/components/ProviderImpactDialog.vue';
import RoutingSummaryCard from '@/components/RoutingSummaryCard.vue';
import {
  mdiAlertOutline,
  mdiCheckCircleOutline,
  mdiDeleteOutline,
  mdiInformationOutline,
  mdiPlayCircleOutline,
  mdiRefresh,
  mdiRobotOutline,
  mdiStarOutline,
  mdiStopCircleOutline,
} from '@/utils/icons';
import {
  actionErrorLabel,
  EFFORT_LABELS,
  labelOf,
  TOOLS_MODE_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const setup = computed(() => props.ctrl.setupSnapshot.value);
const monitor = computed(() => props.ctrl.monitorSnapshot.value);
const providers = computed(() => setup.value?.providers ?? []);
const routing = computed(() => props.ctrl.combinedRouting.value);
const busy = computed(() => props.ctrl.isBusy.value);
const passed = computed(() => props.ctrl.isPreflightPassed.value);
const models = computed(() => props.ctrl.cachedModels.value);

const monitorByProviderId = computed(() => {
  const map = new Map<string, MonitorInstance>();
  for (const inst of monitor.value?.instances ?? []) {
    map.set(inst.provider_id, inst);
  }
  return map;
});

const fallbackSet = computed(() => new Set(routing.value?.explicit_fallback_ids ?? []));

// Provider management dialog state
const dialogOpen = ref(false);
const dialogMode = ref<ProviderDialogMode>('impact');
const dialogProviderId = ref('');
const dialogImpact = ref<ProviderImpact | null>(null);
const dialogImpactError = ref('');

async function openProviderDialog(mode: ProviderDialogMode, providerId: string): Promise<void> {
  dialogMode.value = mode;
  dialogProviderId.value = providerId;
  dialogImpact.value = null;
  dialogImpactError.value = '';
  dialogOpen.value = true;

  try {
    dialogImpact.value = await props.ctrl.fetchProviderImpact(providerId);
  } catch (error) {
    const err = error as { message?: string };
    dialogImpactError.value =
      err?.message || '当前后端未返回实例影响范围（可能为旧版后端或操作竞争，请刷新后重试）。';
  }
}

async function handleDialogConfirm(): Promise<void> {
  const id = dialogProviderId.value;
  if (!id) return;

  if (dialogMode.value === 'default') {
    const snap = await props.ctrl.setProviderDefault(id);
    dialogOpen.value = false;
    if (snap) props.ctrl.notify(`已提交设 ${id} 为全局默认任务，正在校验回读…`, 'info');
  } else if (dialogMode.value === 'enable') {
    const snap = await props.ctrl.toggleProvider(id, true);
    dialogOpen.value = false;
    if (snap) props.ctrl.notify(`已提交启用 ${id} 任务…`, 'info');
  } else if (dialogMode.value === 'disable') {
    if (!dialogImpact.value?.can_disable) return;
    await props.ctrl.toggleProvider(id, false);
    dialogOpen.value = false;
  } else if (dialogMode.value === 'delete') {
    if (!dialogImpact.value?.can_delete) return;
    await props.ctrl.deleteProvider(id);
    dialogOpen.value = false;
  }
}

// Last provider management task feedback
const manageResult = computed(() => {
  const res = setup.value?.result;
  if (!res || typeof res.applied !== 'boolean') return null;
  return res;
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
  { value: 'chat', title: '纯聊天（推荐）' },
  { value: 'inherit', title: '跟随全局开关' },
  { value: 'tools', title: '工具模式' },
];

function handleModelSelect(val: unknown): void {
  void props.ctrl.onDraftModelChange(typeof val === 'string' ? val : '');
}
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <!-- 顶部全局路由视图 -->
    <RoutingSummaryCard
      :routing="routing"
      :schema-version="monitor?.schema_version ?? null"
      :now-tick="ctrl.nowTick.value"
      compact
    />

    <!-- 管理操作结果反馈（严格区分 applied=true 与 REFERENCE_BLOCKED / ROUTE_MISMATCH） -->
    <v-alert
      v-if="manageResult && !setup?.busy && !setup?.action_error && manageResult.applied"
      type="success"
      variant="tonal"
      density="compact"
      :icon="mdiCheckCircleOutline"
    >
      实例 <code class="agy-inline-code">{{ manageResult.provider_id }}</code> 管理操作已完成并经宿主校验确认。
    </v-alert>

    <v-alert
      v-else-if="manageResult && !setup?.busy && setup?.action_error"
      type="warning"
      variant="tonal"
      density="compact"
      :icon="mdiAlertOutline"
    >
      实例 <code class="agy-inline-code">{{ manageResult.provider_id }}</code> 操作未完成：
      {{ actionErrorLabel(setup.action_error) }}
      <template v-if="setup.action_hint">（{{ setup.action_hint }}）</template>
    </v-alert>

    <!-- 已有 ACP 实例管理 -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiRobotOutline" color="primary" />
        </template>
        <v-card-title class="d-flex align-center flex-wrap ga-2">
          <span>已有 ACP 实例管理</span>
          <v-chip size="x-small" color="primary" variant="tonal">
            {{ providers.length }} 个实例
          </v-chip>
        </v-card-title>
        <v-card-subtitle>
          精确按实例 ID 操作。停用与删除在 AstrBot v4.29.4 受会话扫描边界保护，需先查看影响范围，不能通过二次确认绕过阻止。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <v-alert v-if="providers.length === 0" type="info" variant="tonal">
          尚未配置 ACP 模型实例。可在下方表单添加实例，或前往「首次设置」完成引导。
        </v-alert>

        <div v-else class="d-flex flex-column ga-3">
          <v-card
            v-for="row in providers"
            :key="row.id"
            variant="outlined"
            rounded="lg"
          >
            <v-card-text class="d-flex flex-column ga-3">
              <div class="d-flex align-start justify-space-between flex-wrap ga-2">
                <div class="d-flex flex-column ga-1">
                  <div class="d-flex align-center flex-wrap ga-2">
                    <span class="text-subtitle-1 font-weight-bold agy-mono agy-break">
                      {{ row.id }}
                    </span>
                    <v-chip
                      v-if="routing?.configured_primary_id === row.id"
                      size="x-small"
                      color="primary"
                      variant="tonal"
                    >
                      全局配置主项
                    </v-chip>
                    <v-chip
                      v-if="routing?.resolved_primary_id === row.id"
                      size="x-small"
                      color="success"
                      variant="flat"
                    >
                      宿主当前解析主项
                    </v-chip>
                    <v-chip
                      v-if="fallbackSet.has(row.id)"
                      size="x-small"
                      color="info"
                      variant="outlined"
                    >
                      全局备用链
                    </v-chip>
                    <v-chip
                      v-if="routing?.last_observed_provider_id === row.id"
                      size="x-small"
                      color="secondary"
                      variant="outlined"
                    >
                      最近 ACP 观测
                    </v-chip>
                  </div>
                  <div class="text-body-2 text-medium-emphasis agy-mono agy-break">
                    模型：{{ row.model || '未指定模型' }}
                  </div>
                </div>

                <div class="d-flex flex-wrap ga-1">
                  <v-chip
                    size="small"
                    :color="row.enabled ? 'success' : 'default'"
                    variant="tonal"
                  >
                    {{ row.enabled ? '配置已启用' : '配置已停用' }}
                  </v-chip>
                  <v-chip
                    size="small"
                    :color="monitorByProviderId.get(row.id)?.runtime_state === 'active' ? 'info' : 'default'"
                    variant="outlined"
                  >
                    {{
                      monitorByProviderId.get(row.id)?.runtime_state === 'active'
                        ? '运行时：已初始化'
                        : '运行时：未初始化'
                    }}
                  </v-chip>
                  <v-chip size="small" variant="outlined">
                    {{ labelOf(TOOLS_MODE_LABELS, row.tools_mode, '跟随全局') }}
                    （实际{{ row.effective_tools ? '含工具' : '纯聊天' }}）
                  </v-chip>
                </div>
              </div>

              <CopyField
                :model-value="`/agy use ${row.id}`"
                label="单会话切换命令（仅切换当前聊天会话，不改全局默认）"
                button-label="复制命令"
                :aria-label="`切换模型命令 ${row.id}`"
                :is-disposed="ctrl.isDisposed"
                @notify="({ text, color }) => ctrl.notify(text, color)"
              />

              <div class="d-flex flex-wrap ga-2 align-center">
                <v-btn
                  size="small"
                  variant="tonal"
                  color="primary"
                  :disabled="busy || !row.enabled"
                  :prepend-icon="mdiStarOutline"
                  @click="openProviderDialog('default', row.id)"
                >
                  设为全局默认
                </v-btn>

                <v-btn
                  v-if="!row.enabled"
                  size="small"
                  variant="tonal"
                  color="success"
                  :disabled="busy"
                  :prepend-icon="mdiPlayCircleOutline"
                  @click="openProviderDialog('enable', row.id)"
                >
                  启用并加载
                </v-btn>

                <v-btn
                  size="small"
                  variant="outlined"
                  :disabled="busy"
                  :prepend-icon="mdiInformationOutline"
                  @click="openProviderDialog('impact', row.id)"
                >
                  查看影响范围
                </v-btn>

                <v-btn
                  v-if="row.enabled"
                  size="small"
                  variant="outlined"
                  color="warning"
                  :disabled="busy"
                  :prepend-icon="mdiStopCircleOutline"
                  @click="openProviderDialog('disable', row.id)"
                >
                  停用（受限）
                </v-btn>

                <v-btn
                  size="small"
                  variant="outlined"
                  color="error"
                  :disabled="busy"
                  :prepend-icon="mdiDeleteOutline"
                  @click="openProviderDialog('delete', row.id)"
                >
                  删除（受限）
                </v-btn>
              </div>
            </v-card-text>
          </v-card>
        </div>
      </v-card-text>
    </v-card>

    <!-- 新增 / 保存实例表单 -->
    <v-card variant="outlined">
      <v-card-item>
        <v-card-title>新增 / 保存 ACP 模型实例</v-card-title>
        <v-card-subtitle>
          使用官方 CLI 无生成预检读取可用模型目录与思考档位；如需修改自定义扩展字段，请前往 AstrBot 原生模型页。
        </v-card-subtitle>
        <template #append>
          <v-btn
            size="small"
            variant="outlined"
            :disabled="busy"
            :prepend-icon="mdiRefresh"
            @click="ctrl.runCheck()"
          >
            刷新目录（无生成预检）
          </v-btn>
        </template>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <v-form @submit.prevent="ctrl.applyModelConfig()">
          <v-row dense>
            <v-col cols="12" md="6">
              <v-autocomplete
                :model-value="ctrl.draftModel.value || null"
                :items="models"
                item-title="name"
                item-value="id"
                label="Gemini 模型"
                :placeholder="models.length ? '请选择模型' : '请先执行无生成目录预检'"
                variant="outlined"
                density="comfortable"
                hide-details="auto"
                :disabled="busy || !models.length"
                @update:model-value="handleModelSelect"
              />
            </v-col>
            <v-col cols="12" sm="6" md="3">
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
            <v-col cols="12" sm="6" md="3">
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
            <v-col cols="12" class="d-flex flex-wrap align-center justify-space-between ga-2 mt-2">
              <v-switch
                v-model="ctrl.draftUseDefault.value"
                color="primary"
                density="compact"
                hide-details
                :disabled="busy"
                label="保存后尝试设为全局默认模型"
              />
              <v-btn
                type="submit"
                color="primary"
                variant="flat"
                :disabled="busy || !passed || !ctrl.draftModel.value"
                :loading="Boolean(setup?.busy && setup?.operation === 'apply')"
              >
                保存并启用实例
              </v-btn>
            </v-col>
          </v-row>
        </v-form>
      </v-card-text>
    </v-card>

    <ProviderImpactDialog
      v-model="dialogOpen"
      :mode="dialogMode"
      :provider-id="dialogProviderId"
      :current-primary-id="routing?.configured_primary_id ?? null"
      :impact="dialogImpact"
      :loading-impact="ctrl.impactPending.value"
      :impact-error="dialogImpactError"
      :submitting="ctrl.actionPending.value"
      @confirm="handleDialogConfirm"
    />
  </div>
</template>
