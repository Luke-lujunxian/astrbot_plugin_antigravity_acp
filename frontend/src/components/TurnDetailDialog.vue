<script setup lang="ts">
import { computed } from 'vue';
import type { FailureEvent, RecentTurn } from '@/types/api';
import {
  formatBoolState,
  formatBytes,
  formatCount,
  formatDateTime,
  formatDuration,
} from '@/utils/format';
import { mdiClose, mdiFileDocumentOutline } from '@/utils/icons';
import {
  FALLBACK_REASON_LABELS,
  formatFaultBrief,
  labelOf,
  REBUILD_REASON_LABELS,
  TOOLS_MODE_LABELS,
  TURN_STATUS_LABELS,
} from '@/utils/labels';

export type DetailRecord =
  | {
      kind: 'turn';
      providerId: string;
      turn: RecentTurn;
    }
  | {
      kind: 'failure';
      providerLabel: string;
      event: FailureEvent;
    };

const props = defineProps<{
  modelValue: boolean;
  record: DetailRecord | null;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
}>();

const statusText = computed(() => {
  if (!props.record) return '未知';
  const status = props.record.kind === 'turn' ? props.record.turn.status : props.record.event.status;
  return labelOf(TURN_STATUS_LABELS, status, status || '未知');
});

const statusColor = computed<'success' | 'error' | 'warning' | 'default'>(() => {
  if (!props.record) return 'default';
  const status = props.record.kind === 'turn' ? props.record.turn.status : props.record.event.status;
  if (status === 'ok') return 'success';
  if (status === 'error') return 'error';
  if (status === 'cancelled' || status === 'short_circuited') return 'warning';
  return 'default';
});

const common = computed(() => {
  if (!props.record) return null;
  return props.record.kind === 'turn' ? props.record.turn : props.record.event;
});

function close(): void {
  emit('update:modelValue', false);
}
</script>

<template>
  <v-dialog
    :model-value="modelValue"
    max-width="720"
    scrollable
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card v-if="record && common">
      <v-card-item>
        <template #prepend>
          <v-icon :icon="mdiFileDocumentOutline" color="primary" />
        </template>
        <v-card-title class="d-flex align-center flex-wrap ga-2">
          <span>{{ record.kind === 'turn' ? '请求回合详情' : '持久化失败事件详情' }}</span>
          <v-chip size="x-small" :color="statusColor" variant="tonal">
            {{ statusText }}
          </v-chip>
          <v-chip v-if="common.error_code" size="x-small" color="error" variant="outlined">
            {{ formatFaultBrief(common.error_code) }}
          </v-chip>
        </v-card-title>
        <v-card-subtitle class="agy-mono agy-break">
          {{ record.kind === 'turn' ? record.providerId : record.providerLabel }} ·
          {{ formatDateTime(common.recorded_at) }}
        </v-card-subtitle>
        <template #append>
          <v-btn icon variant="text" size="small" aria-label="关闭" @click="close">
            <v-icon :icon="mdiClose" />
          </v-btn>
        </template>
      </v-card-item>

      <v-divider />

      <v-card-text class="d-flex flex-column ga-4">
        <!-- 基础与模型信息 -->
        <div class="agy-subtle-panel">
          <div class="text-subtitle-2 font-weight-bold mb-2">执行与耗时</div>
          <dl class="agy-kv-grid">
            <div class="agy-kv-item">
              <dt>记录时间</dt>
              <dd>{{ formatDateTime(common.recorded_at) }}</dd>
            </div>
            <div class="agy-kv-item">
              <dt>总耗时</dt>
              <dd>{{ formatDuration(common.elapsed_ms) }}</dd>
            </div>
            <div class="agy-kv-item">
              <dt>执行模式</dt>
              <dd>{{ labelOf(TOOLS_MODE_LABELS, common.mode, '未知') }}</dd>
            </div>
            <div class="agy-kv-item">
              <dt>终止原因 (stop_reason)</dt>
              <dd class="agy-mono">{{ common.stop_reason || '未知 / 未报告' }}</dd>
            </div>
            <template v-if="record.kind === 'turn'">
              <div class="agy-kv-item">
                <dt>请求模型</dt>
                <dd class="agy-mono">{{ record.turn.model || '未知' }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>ACP 协商确认模型</dt>
                <dd class="agy-mono">{{ record.turn.negotiated_model || '未知 / 未确认' }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>会话复用</dt>
                <dd>{{ record.turn.reused ? '复用已有会话' : '新建 / 重建会话' }}</dd>
              </div>
              <div class="agy-kv-item">
                <dt>重建原因</dt>
                <dd>
                  {{
                    record.turn.rebuild_reasons.length
                      ? record.turn.rebuild_reasons
                          .map((r) => labelOf(REBUILD_REASON_LABELS, r, r))
                          .join('、')
                      : '无'
                  }}
                </dd>
              </div>
            </template>
            <template v-else>
              <div class="agy-kv-item">
                <dt>实例脱敏标签 (provider_tag)</dt>
                <dd class="agy-mono">{{ record.event.provider_tag || '未知' }}</dd>
              </div>
            </template>
          </dl>
        </div>

        <!-- Token 用量与字节计数（严格区分） -->
        <div class="agy-subtle-panel">
          <div class="text-subtitle-2 font-weight-bold mb-2">
            Token 用量与适配层字节（字节数不能替代 Token）
          </div>
          <dl class="agy-kv-grid">
            <template v-if="record.kind === 'turn'">
              <div class="agy-kv-item">
                <dt>ACP 用量状态</dt>
                <dd>
                  {{
                    record.turn.usage_status === 'reported'
                      ? '上游已上报'
                      : record.turn.usage_status === 'not_sent'
                        ? '未发送请求'
                        : '上游未报告（未知）'
                  }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>非缓存输入 / 输出 Token</dt>
                <dd>
                  {{
                    record.turn.usage_status === 'reported'
                      ? `${formatCount(record.turn.input_other)} / ${formatCount(record.turn.output)}`
                      : record.turn.usage_status === 'not_sent'
                        ? '0 / 0（未发送）'
                        : '未知 / 未知'
                  }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>缓存读取 Token</dt>
                <dd>
                  {{
                    record.turn.usage_status === 'reported' &&
                    record.turn.cache_fields_present?.cachedReadTokens
                      ? formatCount(record.turn.input_cached)
                      : record.turn.usage_status === 'not_sent'
                        ? '0（未发送）'
                        : '未知 / 未报告'
                  }}
                </dd>
              </div>
              <div class="agy-kv-item">
                <dt>输入 Prompt / 历史重放 / 省略消息</dt>
                <dd>
                  {{ formatBytes(record.turn.prompt_bytes) }} /
                  {{ formatBytes(record.turn.replay_bytes) }} /
                  {{ formatCount(record.turn.omitted_messages) }}
                </dd>
              </div>
            </template>
            <div class="agy-kv-item">
              <dt>正文 UTF-8 字节 (body_bytes)</dt>
              <dd>{{ formatBytes(common.body_bytes) }}</dd>
            </div>
            <div class="agy-kv-item">
              <dt>思考 UTF-8 字节 (thought_bytes)</dt>
              <dd>{{ formatBytes(common.thought_bytes) }}</dd>
            </div>
          </dl>
        </div>

        <!-- 防重放 / 工具交接 / 告警与关联标签（schema v2） -->
        <div class="agy-subtle-panel">
          <div class="text-subtitle-2 font-weight-bold mb-2">流式交付、工具交接与 Fallback 边界</div>
          <dl class="agy-kv-grid">
            <div class="agy-kv-item">
              <dt>允许宿主回退 (fallback_allowed)</dt>
              <dd>{{ formatBoolState(common.fallback_allowed, '允许', '禁止重放') }}</dd>
            </div>
            <div class="agy-kv-item">
              <dt>回退边界原因</dt>
              <dd>
                {{
                  common.fallback_reason
                    ? labelOf(FALLBACK_REASON_LABELS, common.fallback_reason, common.fallback_reason)
                    : '不适用 / 未知'
                }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>已见分片 / 非空白正文 / 已流式交付</dt>
              <dd>
                {{ formatBoolState(common.chunk_seen) }} /
                {{ formatBoolState(common.body_seen) }} /
                {{ formatBoolState(common.body_streamed) }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>已交接工具 / 含工具结果续轮</dt>
              <dd>
                {{ formatBoolState(common.tool_handed_off) }} /
                {{ formatBoolState(common.tool_result_supplied) }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>权限拒绝次数 / 过滤 CLI 告警数</dt>
              <dd>
                {{ formatCount(common.permission_denial_count) }} /
                {{ formatCount(common.filtered_notice_count) }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>宿主 Attempt / CLI 重试计数</dt>
              <dd>
                {{ formatCount(common.attempt) }} / {{ formatCount(common.cli_retry_attempt) }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>Turn ID / Origin Turn ID</dt>
              <dd class="agy-mono">
                {{ common.turn_id || '未知' }} / {{ common.origin_turn_id || '无' }}
              </dd>
            </div>
            <div class="agy-kv-item">
              <dt>逻辑请求标签 (HMAC)</dt>
              <dd class="agy-mono">{{ common.logical_request_tag || '无 / 未知' }}</dd>
            </div>
          </dl>
        </div>

        <!-- 429 候选遥测（仅 recent_turns 存在时展示，严守语义声明） -->
        <v-alert
          v-if="record.kind === 'turn' && record.turn.content_429_candidate"
          type="warning"
          variant="tonal"
          density="compact"
        >
          <div class="font-weight-semibold mb-1">429 候选遥测（启发式特征，非根因定论）</div>
          <div class="text-caption agy-mono">
            hash={{ record.turn.content_429_candidate.system_hash8 || '未知' }} ·
            sys={{ formatBytes(record.turn.content_429_candidate.system_bytes) }} ·
            attempt={{ record.turn.content_429_candidate.attempt ?? '未知' }} ·
            has_output={{ record.turn.content_429_candidate.has_output ? '是' : '否' }}
          </div>
          <div class="text-caption mt-1">
            此标记仅为候选遥测信号，不能证明 Google 内容过滤、风控或额度根因。
          </div>
        </v-alert>
      </v-card-text>

      <v-divider />

      <v-card-actions class="px-5 py-3">
        <v-spacer />
        <v-btn variant="flat" color="primary" @click="close">关闭</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
