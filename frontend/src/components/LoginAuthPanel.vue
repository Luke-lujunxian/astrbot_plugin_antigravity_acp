<script setup lang="ts">
import { computed, ref } from 'vue';
import type { DashboardController } from '@/composables/useDashboardState';
import { openExternalUrlSafely } from '@/utils/copy';
import {
  mdiCancel,
  mdiConsole,
  mdiEyeOffOutline,
  mdiEyeOutline,
  mdiLogin,
  mdiOpenInNew,
  mdiShieldAlertOutline,
  mdiShieldCheckOutline,
} from '@/utils/icons';
import { actionErrorLabel, labelOf, LOGIN_STATE_LABELS } from '@/utils/labels';
import CopyField from './CopyField.vue';

const props = defineProps<{
  ctrl: DashboardController;
  compact?: boolean;
}>();

const showCodeText = ref(false);

const snapshot = computed(() => props.ctrl.setupSnapshot.value);
const report = computed(() => snapshot.value?.report ?? {});
const login = computed(() => snapshot.value?.login ?? {});
const loginBusy = computed(() => Boolean(login.value.busy));
const passed = computed(() => props.ctrl.isPreflightPassed.value);
const busy = computed(() => props.ctrl.isBusy.value);

const badgeText = computed(() => {
  if (passed.value && !loginBusy.value) return '已连接';
  return labelOf(LOGIN_STATE_LABELS, login.value.state, '等待登录');
});

const badgeColor = computed<'success' | 'error' | 'info' | 'default'>(() => {
  if (passed.value && !loginBusy.value) return 'success';
  if (login.value.state === 'failed') return 'error';
  if (loginBusy.value) return 'info';
  return 'default';
});

const loginHint = computed(() => {
  if (loginBusy.value) {
    const expires = typeof login.value.expires_in === 'number' ? login.value.expires_in : 0;
    return login.value.owned
      ? `请在浏览器完成授权并提交一次性授权码（剩余 ${expires}s）。`
      : `另一位管理员正在进行登录（剩余 ${expires}s）；仅发起管理员可查看私密授权链接或取消本次登录。`;
  }
  if (login.value.error_code) {
    return `${actionErrorLabel(login.value.error_code)}，请重试或使用终端命令登录。`;
  }
  if (passed.value) {
    return '当前官方 CLI 认证已通过无生成预检（如需切换账号可点击「重新登录」）。';
  }
  if (login.value.state === 'failed') {
    return '登录未完成，请重试或使用终端命令登录。';
  }
  return '启动官方 CLI 登录流程，在浏览器完成 Google 授权并粘贴一次性授权码。';
});

const canShowAuthorization = computed(() => Boolean(login.value.owned && login.value.url));
const canCancel = computed(() => Boolean(loginBusy.value && login.value.owned));
const canStartLogin = computed(() => !busy.value && Boolean(report.value.cli_version));
const canSubmitCode = computed(
  () =>
    !props.ctrl.actionPending.value &&
    login.value.state === 'waiting' &&
    Boolean(login.value.owned) &&
    Boolean(props.ctrl.authCode.value.trim()),
);

function handleOpenUrl(): void {
  const url = login.value.url || '';
  if (!url) return;
  if (!openExternalUrlSafely(url)) {
    props.ctrl.notify('浏览器拦截了新窗口，请使用「复制链接」手动打开', 'warning');
  }
}

async function handleSubmit(): Promise<void> {
  if (!canSubmitCode.value) return;
  await props.ctrl.submitLoginCode();
}
</script>

<template>
  <div class="d-flex flex-column ga-3">
    <div class="d-flex align-center justify-space-between flex-wrap ga-2">
      <div class="d-flex align-center ga-2">
        <v-icon
          :icon="passed ? mdiShieldCheckOutline : mdiShieldAlertOutline"
          :color="passed ? 'success' : 'warning'"
        />
        <span class="text-subtitle-1 font-weight-semibold">Google 官方 CLI 认证</span>
      </div>
      <v-chip size="small" :color="badgeColor" variant="tonal">
        {{ badgeText }}
      </v-chip>
    </div>

    <p class="text-body-1 text-medium-emphasis mb-0 agy-break">
      {{ loginHint }}
    </p>

    <div class="d-flex flex-wrap ga-2 align-center">
      <v-btn
        color="primary"
        :variant="passed ? 'tonal' : 'flat'"
        :disabled="!canStartLogin"
        :loading="loginBusy && login.state === 'starting'"
        :prepend-icon="mdiLogin"
        @click="ctrl.startLogin()"
      >
        {{ passed ? '重新登录' : '开始官方登录' }}
      </v-btn>

      <v-btn
        v-if="canCancel"
        color="error"
        variant="outlined"
        :disabled="ctrl.actionPending.value"
        :prepend-icon="mdiCancel"
        @click="ctrl.cancelLogin()"
      >
        取消登录
      </v-btn>
    </div>

    <v-alert
      v-if="loginBusy && !login.owned"
      type="warning"
      variant="tonal"
      density="compact"
    >
      检测到其他管理员会话持有当前登录票据（non-owner）。为防止凭据串用，本页面不会展示其授权 URL，且禁止提交授权码或取消其流程；等待过期或由原发起者操作。
    </v-alert>

    <!-- 仅登录发起者可见的私密授权区，全部仅驻留内存 -->
    <div v-if="canShowAuthorization" class="agy-subtle-panel d-flex flex-column ga-3">
      <CopyField
        :model-value="login.url || ''"
        label="1. 打开 Google 授权链接（仅驻内存，关闭页面即清除）"
        button-label="复制链接"
        aria-label="Google 授权链接"
        :is-disposed="ctrl.isDisposed"
        @notify="({ text, color }) => ctrl.notify(text, color)"
      >
        <template #append>
          <v-btn
            size="small"
            variant="outlined"
            color="primary"
            :prepend-icon="mdiOpenInNew"
            @click="handleOpenUrl"
          >
            在新标签打开
          </v-btn>
        </template>
      </CopyField>

      <v-form autocomplete="off" @submit.prevent="handleSubmit">
        <div class="text-body-2 font-weight-medium text-medium-emphasis mb-1">
          2. 粘贴浏览器返回的一次性授权码
        </div>
        <div class="d-flex flex-wrap ga-2 align-start">
          <v-text-field
            v-model="ctrl.authCode.value"
            :type="showCodeText ? 'text' : 'password'"
            variant="outlined"
            density="compact"
            hide-details="auto"
            autocomplete="off"
            spellcheck="false"
            maxlength="4096"
            placeholder="粘贴一次性授权码（提交后立即清空）"
            class="flex-grow-1"
            style="min-width: 220px"
            :append-inner-icon="showCodeText ? mdiEyeOffOutline : mdiEyeOutline"
            @click:append-inner="showCodeText = !showCodeText"
          />
          <v-btn
            type="submit"
            color="primary"
            variant="flat"
            :disabled="!canSubmitCode"
            :loading="login.state === 'verifying'"
          >
            提交授权码
          </v-btn>
        </div>
      </v-form>
    </div>

    <div v-if="!compact" class="agy-subtle-panel">
      <div class="d-flex align-center ga-2 mb-1">
        <v-icon :icon="mdiConsole" size="16" color="primary" />
        <span class="text-body-2 font-weight-medium">终端命令行兜底登录</span>
      </div>
      <p class="text-caption text-medium-emphasis mb-2">
        若远程无浏览器、登录票据超时（300s）或弹窗受限，请在运行 AstrBot 的同一用户下执行：
      </p>
      <CopyField
        model-value="agy acp --login"
        button-label="复制命令"
        aria-label="终端登录命令"
        :is-disposed="ctrl.isDisposed"
        @notify="({ text, color }) => ctrl.notify(text, color)"
      />
      <p class="text-caption text-medium-emphasis mt-2 mb-0">
        认证完全由官方 CLI 管理；插件文件桥仅校验元数据并链接官方认证文件，不读取或复制 OAuth 内容。完成后点击「重新检测」。
      </p>
    </div>
  </div>
</template>
