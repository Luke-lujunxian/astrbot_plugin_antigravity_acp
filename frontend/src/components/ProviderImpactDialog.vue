<script setup lang="ts">
import { computed } from 'vue';
import type { ProviderImpact } from '@/types/api';
import { formatBoolState } from '@/utils/format';
import {
  mdiAlertOutline,
  mdiCheckCircleOutline,
  mdiClose,
  mdiDeleteOutline,
  mdiInformationOutline,
  mdiPlayCircleOutline,
  mdiStar,
  mdiStopCircleOutline,
} from '@/utils/icons';
import { BLOCK_REASON_LABELS, labelOf } from '@/utils/labels';

export type ProviderDialogMode = 'impact' | 'default' | 'enable' | 'disable' | 'delete';

const props = defineProps<{
  modelValue: boolean;
  mode: ProviderDialogMode;
  providerId: string;
  currentPrimaryId: string | null;
  impact: ProviderImpact | null;
  loadingImpact: boolean;
  impactError: string;
  submitting: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'confirm'): void;
}>();

const dialogTitle = computed(() => {
  const titles: Record<ProviderDialogMode, string> = {
    impact: '实例引用与影响范围',
    default: '设为全局默认模型',
    enable: '启用 ACP 实例',
    disable: '停用 ACP 实例（受限）',
    delete: '删除 ACP 实例（受限）',
  };
  return titles[props.mode];
});

const dialogIcon = computed(() => {
  switch (props.mode) {
    case 'default':
      return mdiStar;
    case 'enable':
      return mdiPlayCircleOutline;
    case 'disable':
      return mdiStopCircleOutline;
    case 'delete':
      return mdiDeleteOutline;
    default:
      return mdiInformationOutline;
  }
});

const isDestructive = computed(() => props.mode === 'disable' || props.mode === 'delete');

const isBlockedByPolicy = computed(() => {
  if (!isDestructive.value) return false;
  if (!props.impact) return true;
  return props.mode === 'delete' ? !props.impact.can_delete : !props.impact.can_disable;
});

const canConfirm = computed(() => {
  if (props.mode === 'impact') return false;
  if (props.submitting || props.loadingImpact) return false;
  if (isDestructive.value) {
    return Boolean(props.impact && !isBlockedByPolicy.value);
  }
  return Boolean(props.providerId);
});

const blockReasonText = computed(() => {
  if (!props.impact) return '无法确认引用状态';
  return labelOf(BLOCK_REASON_LABELS, props.impact.block_reason, props.impact.block_reason);
});

function close(): void {
  emit('update:modelValue', false);
}
</script>

<template>
  <v-dialog
    :model-value="modelValue"
    max-width="580"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card>
      <v-card-item>
        <template #prepend>
          <v-icon :icon="dialogIcon" :color="isDestructive ? 'warning' : 'primary'" />
        </template>
        <v-card-title>{{ dialogTitle }}</v-card-title>
        <v-card-subtitle class="agy-mono agy-break">{{ providerId }}</v-card-subtitle>
        <template #append>
          <v-btn icon variant="text" size="small" aria-label="关闭" @click="close">
            <v-icon :icon="mdiClose" />
          </v-btn>
        </template>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-3">
        <!-- 默认切换确认说明 -->
        <v-alert v-if="mode === 'default'" type="info" variant="tonal" density="compact">
          将更新默认 profile 下本地 Runner 的全局主模型 ID，并校验宿主回读与解析结果匹配。当前配置主项：
          <span class="agy-mono">{{ currentPrimaryId || '未配置' }}</span>。
          此操作不会改写已有群聊/私聊的会话覆盖、备用链顺序或辅助引用。
        </v-alert>

        <!-- 启用说明 -->
        <v-alert v-if="mode === 'enable'" type="info" variant="tonal" density="compact">
          将在宿主资源锁内启用此 ACP 实例配置并触发加载；仅在加载确认后报告成功，不会自动修改全局默认主模型。
        </v-alert>

        <!-- 影响检查加载态 -->
        <div v-if="loadingImpact" class="d-flex align-center ga-3 py-4 justify-center">
          <v-progress-circular indeterminate color="primary" size="24" />
          <span class="text-body-1">正在扫描已加载配置与观测引用…</span>
        </div>

        <v-alert v-else-if="impactError" type="error" variant="tonal" density="compact">
          {{ impactError }}
        </v-alert>

        <!-- 影响范围详细数据 -->
        <template v-else-if="impact">
          <div class="agy-subtle-panel d-flex flex-column ga-2">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <span class="text-subtitle-2 font-weight-bold">可见引用计数（非零引用证明）</span>
              <v-chip size="x-small" variant="outlined">
                已扫描 Profile：{{ impact.profiles_scanned }}
              </v-chip>
            </div>

            <dl class="agy-kv-grid">
              <div class="agy-kv-item">
                <dt>主模型引用 (primary)</dt>
                <dd>{{ impact.references.primary }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>备用链引用 (fallback)</dt>
                <dd>{{ impact.references.fallback }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>辅助配置引用 (auxiliary)</dt>
                <dd>{{ impact.references.auxiliary }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>已观测会话覆盖</dt>
                <dd>{{ impact.references.observed_session_overrides }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>当前全局实际解析</dt>
                <dd>{{ formatBoolState(impact.references.global_resolved, '是', '否') }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>配置启用状态</dt>
                <dd>{{ impact.enabled ? '已启用' : '已停用' }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>会话覆盖扫描边界</dt>
                <dd class="agy-mono">{{ impact.session_scan }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>辅助字段扫描范围</dt>
                <dd class="agy-mono">{{ impact.auxiliary_scan }}</dd>
              </div>
            </dl>
          </div>

          <!-- 停用 / 删除拦截提示：绝不提供绕过按钮 -->
          <v-alert
            v-if="isBlockedByPolicy"
            type="warning"
            variant="tonal"
            :icon="mdiAlertOutline"
          >
            <div class="font-weight-semibold mb-1">
              操作已被安全边界阻止（{{ blockReasonText }}）
            </div>
            <div class="text-body-2">
              AstrBot v4.29.4 无法在资源锁内完整枚举历史会话覆盖、未加载 profile 及其他插件私有引用（<code class="agy-inline-code">session_scan={{ impact.session_scan }}</code>），因此可见命中数为 0 也不能证明零引用。后端返回
              <code class="agy-inline-code">can_disable={{ String(impact.can_disable) }}</code>、
              <code class="agy-inline-code">can_delete={{ String(impact.can_delete) }}</code>，无法通过二次确认绕过。如需强制调整，请先在 AstrBot 原生模型页面核对引用后自行操作（本面板后续会自动检测悬空主 ID）。
            </div>
          </v-alert>

          <v-alert
            v-else-if="mode === 'impact'"
            type="info"
            variant="tonal"
            density="compact"
            :icon="mdiInformationOutline"
          >
            以上计数仅反映默认配置、已加载 profile 与插件生命周期内观测到的会话偏好变更（最多 1024 条 HMAC 标签），不包含启动前偏好或未加载配置。
          </v-alert>
        </template>
      </v-card-text>

      <v-divider />

      <v-card-actions class="px-5 py-3">
        <v-spacer />
        <v-btn variant="text" @click="close">
          {{ mode === 'impact' || isBlockedByPolicy ? '关闭' : '取消' }}
        </v-btn>
        <v-btn
          v-if="mode !== 'impact'"
          :color="isDestructive ? 'error' : 'primary'"
          variant="flat"
          :disabled="!canConfirm"
          :loading="submitting"
          :prepend-icon="mdiCheckCircleOutline"
          @click="emit('confirm')"
        >
          {{
            mode === 'default'
              ? '确认设为全局默认'
              : mode === 'enable'
                ? '确认启用并加载'
                : mode === 'disable'
                  ? '已阻止停用'
                  : '已阻止删除'
          }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
