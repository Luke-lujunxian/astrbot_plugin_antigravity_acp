<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import CopyField from '@/components/CopyField.vue';
import { copyTextSafely } from '@/utils/copy';
import { buildSanitizedDiagnosticExport, downloadSanitizedJson } from '@/utils/diagnostics';
import { formatByteSizeHuman, formatSeconds } from '@/utils/format';
import {
  mdiCheck,
  mdiCogOutline,
  mdiConsole,
  mdiContentCopy,
  mdiDownload,
  mdiEyeOffOutline,
  mdiEyeOutline,
  mdiInformationOutline,
  mdiShieldCheckOutline,
} from '@/utils/icons';
import {
  labelOf,
  MINIMAL_TOOLS_LABELS,
  SUPERVISION_LABELS,
  TRANSPORT_LABELS,
} from '@/utils/labels';

const props = defineProps<{
  ctrl: DashboardController;
}>();

const showPreview = ref(false);
const copyExportState = ref<'idle' | 'copied' | 'manual'>('idle');
const exportTextareaRef = ref<HTMLTextAreaElement | null>(null);
const copyExportBtnRef = ref<HTMLElement | null>(null);
let copyResetTimer: ReturnType<typeof setTimeout> | null = null;

onBeforeUnmount(() => {
  if (copyResetTimer) {
    clearTimeout(copyResetTimer);
    copyResetTimer = null;
  }
});

const setup = computed(() => props.ctrl.setupSnapshot.value);
const monitor = computed(() => props.ctrl.monitorSnapshot.value);
const report = computed(() => setup.value?.report ?? {});

const effectivePolicyRows = computed<Array<[string, string]>>(() => {
  const s = setup.value;
  const r = report.value;
  const ret = monitor.value?.failure_retention;
  return [
    ['默认思考档位 (thought_level)', s?.global_effort || '未知'],
    [
      '宿主工具总闸 (enable_tools)',
      s?.global_enable_tools === true
        ? '已开启'
        : s?.global_enable_tools === false
          ? '已关闭'
          : '未知',
    ],
    ['网络代理模式 (proxy_mode)', r.proxy_mode || '未知'],
    [
      '官方认证文件桥接 (auth_bridge)',
      r.auth_bridge === true ? '开启' : r.auth_bridge === false ? '关闭' : '未知',
    ],
    ['工具组件模式 (agy_customizations_mode)', r.customizations_mode || '未知'],
    [
      '精简参数状态',
      labelOf(MINIMAL_TOOLS_LABELS, r.minimal_tools_status, '未知'),
    ],
    ['工具桥传输方式', labelOf(TRANSPORT_LABELS, r.tool_bridge_transport, '未知')],
    ['子进程托管方式', labelOf(SUPERVISION_LABELS, r.process_supervision, '未知')],
    ['CLI 更新策略', '外部手动管理（插件不检查或覆盖全局 CLI）'],
    [
      '失败日志保留策略',
      ret
        ? `${formatSeconds(ret.ttl_seconds)} · 上限 ${ret.max_events} 条 / ${formatByteSizeHuman(ret.max_bytes)} · 存储 ${ret.storage_state === 'available' ? '可用' : '不可用'}`
        : '未知（需要监控 schema v2）',
    ],
  ];
});

const hostManagedConfigGroups = [
  {
    group: 'CLI 与网络',
    keys: 'command, setup_auto_check, auth_bridge, proxy_mode, proxy_url',
    note: '控制可执行文件绝对路径、启动自动无生成预检、文件桥及代理设置（修改后须重载插件）。',
  },
  {
    group: '并发与会话池',
    keys: 'max_concurrent, max_sessions, max_pending, idle_ttl, session_reuse_mode',
    note: '控制每实例并发上限、常驻进程会话池大小、空闲回收及会话复用模式（strict / structured）。',
  },
  {
    group: '超时与字节预算',
    keys: 'startup_timeout, request_timeout, queue_timeout, history_bytes, max_output_bytes',
    note: '控制握手/单轮/排队超时及历史重放、单轮输出字节上限。',
  },
  {
    group: '上下文压缩与稳定性',
    keys: 'context_compaction_min_peak, context_compaction_drop_percent, empty_dedupe_ttl, quota_cooldown, cost_log_enabled',
    note: '控制疑似上下文压缩启发式阈值、EMPTY 去重、QUOTA/RATE_LIMIT 冷却及每轮成本日志开关。',
  },
  {
    group: '工具桥与多模态图片',
    keys: 'enable_tools, agy_customizations_mode, tool_max_calls, tool_max_concurrent, tool_approval_timeout, tool_execution_timeout, tool_result_bytes, enable_images, media_roots, image_max_*',
    note: '工具模式总闸、实验性精简模式、工具调用预算及 PNG/JPEG 媒体白名单根目录。',
  },
];

const sanitizedJsonText = computed(() =>
  JSON.stringify(buildSanitizedDiagnosticExport(monitor.value, setup.value), null, 2),
);

async function handleCopyExport(): Promise<void> {
  const text = sanitizedJsonText.value;
  if (!showPreview.value) {
    // Allow fallback selection if manual copy is needed.
    showPreview.value = true;
  }
  const outcome = await copyTextSafely(text, {
    sourceInput: exportTextareaRef.value,
    returnFocusEl: copyExportBtnRef.value,
    isDisposed: props.ctrl.isDisposed,
  });
  if (outcome === 'empty' || outcome === 'stale') return;
  copyExportState.value = outcome === 'copied' ? 'copied' : 'manual';
  props.ctrl.notify(
    outcome === 'copied' ? '已复制脱敏诊断 JSON' : '已选中下方预览文本，请按 Ctrl+C / ⌘C 复制',
    outcome === 'copied' ? 'success' : 'warning',
  );
  if (copyResetTimer) clearTimeout(copyResetTimer);
  copyResetTimer = setTimeout(() => {
    copyExportState.value = 'idle';
    copyResetTimer = null;
  }, 2000);
}

function handleDownloadExport(): void {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const ok = downloadSanitizedJson(`agy-acp-diagnostics-${stamp}.json`, sanitizedJsonText.value);
  props.ctrl.notify(
    ok ? '已触发脱敏诊断 JSON 下载' : '当前环境拦截了下载，请使用「复制脱敏 JSON」',
    ok ? 'success' : 'warning',
  );
}
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <!-- 明确入口边界，不提供假开关 -->
    <v-alert type="info" variant="tonal" :icon="mdiInformationOutline">
      <div class="font-weight-semibold mb-1">插件主配置修改入口说明</div>
      <div class="text-body-2">
        当前插件后端未暴露主配置写入 API。如需修改代理、超时、会话池、工具总闸或图片白名单，请前往 AstrBot Dashboard 左侧菜单
        <strong>「插件管理 → Antigravity ACP → 配置」</strong> 修改并保存重载。本页仅如实展示当前可观测的生效策略与只读参考，不提供无效开关。
      </div>
    </v-alert>

    <!-- 当前生效运行时策略（真实读回） -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiCogOutline" color="primary" />
        </template>
        <v-card-title>当前可观测生效策略（只读）</v-card-title>
        <v-card-subtitle>
          数据来自 <code class="agy-inline-code">setup/status</code> 与 <code class="agy-inline-code">monitor/status</code> 实时快照，缺失项显示「未知」。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <dl class="agy-kv-grid">
          <div
            v-for="[label, value] in effectivePolicyRows"
            :key="label"
            class="agy-kv-item agy-subtle-panel"
          >
            <dt>{{ label }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>
      </v-card-text>
    </v-card>

    <!-- 脱敏诊断导出（严格白名单） -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiShieldCheckOutline" color="primary" />
        </template>
        <v-card-title>脱敏诊断导出（白名单投影）</v-card-title>
        <v-card-subtitle>
          仅导出 monitor 失败事件、保留参数、全局路由投影与非敏感环境摘要；绝不包含 CSRF、登录票据、授权链接/授权码、代理密码、会话身份或聊天正文。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-3">
        <div class="d-flex flex-wrap ga-2 align-center">
          <span ref="copyExportBtnRef">
            <v-btn
              color="primary"
              variant="flat"
              size="small"
              :prepend-icon="copyExportState === 'copied' ? mdiCheck : mdiContentCopy"
              @click="handleCopyExport"
            >
              {{
                copyExportState === 'copied'
                  ? '已复制 ✓'
                  : copyExportState === 'manual'
                    ? '请手动复制'
                    : '复制脱敏 JSON'
              }}
            </v-btn>
          </span>

          <v-btn
            variant="tonal"
            color="primary"
            size="small"
            :prepend-icon="mdiDownload"
            @click="handleDownloadExport"
          >
            下载 JSON 文件
          </v-btn>

          <v-btn
            variant="outlined"
            size="small"
            :prepend-icon="showPreview ? mdiEyeOffOutline : mdiEyeOutline"
            @click="showPreview = !showPreview"
          >
            {{ showPreview ? '收起预览' : '预览导出内容' }}
          </v-btn>
        </div>

        <v-expand-transition>
          <div v-show="showPreview">
            <textarea
              ref="exportTextareaRef"
              :value="sanitizedJsonText"
              readonly
              aria-label="脱敏诊断 JSON 预览"
              class="agy-pre w-100"
              rows="12"
            />
          </div>
        </v-expand-transition>
      </v-card-text>
    </v-card>

    <!-- 宿主插件配置参数速查（只读） -->
    <v-card variant="outlined">
      <v-card-item>
        <v-card-title>宿主插件配置项分类速查（只读 · 到宿主插件配置修改）</v-card-title>
        <v-card-subtitle>
          以下参数定义于 <code class="agy-inline-code">_conf_schema.json</code>，由 AstrBot 宿主统一持久化管理。
        </v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-2">
        <div
          v-for="item in hostManagedConfigGroups"
          :key="item.group"
          class="agy-subtle-panel d-flex flex-column ga-1"
        >
          <div class="d-flex align-center justify-space-between flex-wrap ga-2">
            <span class="font-weight-semibold text-body-1">{{ item.group }}</span>
            <v-chip size="x-small" variant="outlined">宿主插件配置修改</v-chip>
          </div>
          <div class="text-caption agy-mono text-medium-emphasis agy-break">{{ item.keys }}</div>
          <div class="text-body-2 text-medium-emphasis">{{ item.note }}</div>
        </div>
      </v-card-text>
    </v-card>

    <!-- 管理员聊天命令速查 -->
    <v-card variant="outlined">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiConsole" color="primary" />
        </template>
        <v-card-title>管理员诊断与维护命令</v-card-title>
        <v-card-subtitle>仅 AstrBot 管理员可在聊天窗口调用，均不泄露凭据或聊天内容。</v-card-subtitle>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-3">
        <CopyField
          model-value="/agy doctor"
          label="完整脱敏无生成自检（含全局路由投影）"
          button-label="复制"
          :is-disposed="ctrl.isDisposed"
          @notify="({ text, color }) => ctrl.notify(text, color)"
        />
        <CopyField
          model-value="/agy cost"
          label="查看 24h 成本、Token 与会话复用统计"
          button-label="复制"
          :is-disposed="ctrl.isDisposed"
          @notify="({ text, color }) => ctrl.notify(text, color)"
        />
        <CopyField
          model-value="/agy setup"
          label="查看当前设置摘要与已配置实例列表"
          button-label="复制"
          :is-disposed="ctrl.isDisposed"
          @notify="({ text, color }) => ctrl.notify(text, color)"
        />
      </v-card-text>
    </v-card>
  </div>
</template>
