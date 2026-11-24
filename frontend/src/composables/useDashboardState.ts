import { computed, ref } from 'vue';
import {
  normalizeMonitorSnapshot,
  normalizeSetupSnapshot,
  type ModelCatalogItem,
  type MonitorSnapshot,
  type ProviderImpact,
  type RoutingSnapshot,
  type SetupSnapshot,
} from '@/types/api';
import { actionErrorLabel, INSTALL_ERROR_LABELS, hasOwn } from '@/utils/labels';
import { createThemeBridgeController } from './useThemeBridge';

export type DashboardTab = 'overview' | 'setup' | 'models' | 'account' | 'monitor' | 'advanced';

export interface SnackbarState {
  show: boolean;
  text: string;
  color: 'success' | 'warning' | 'error' | 'info';
  timeout: number;
}

export interface ApplyModelPayload {
  model: string;
  effort: string;
  tools_mode: string;
  use_default: boolean;
}

function isPermissionError(error: unknown): boolean {
  const err = error as { status?: number; statusCode?: number; status_code?: number; message?: string };
  const status = err?.status ?? err?.statusCode ?? err?.status_code;
  return (
    status === 401 ||
    status === 403 ||
    /登录|权限|管理员|unauthorized|forbidden/i.test(err?.message || '')
  );
}

function errorMessageOf(error: unknown, fallback: string): string {
  const err = error as { message?: string };
  return typeof err?.message === 'string' && err.message ? err.message : fallback;
}

export function createDashboardController() {
  const theme = createThemeBridgeController();
  const bridge = theme.bridge;

  // Navigation
  const activeTab = ref<DashboardTab>('overview');
  let userSelectedTab = false;
  let initialLandingResolved = false;

  // Core snapshots
  const setupSnapshot = ref<SetupSnapshot | null>(null);
  const monitorSnapshot = ref<MonitorSnapshot | null>(null);
  const monitorStale = ref(false);
  const monitorPermissionDenied = ref(false);
  const monitorMessage = ref('正在读取运行快照…');
  const bridgeUnavailable = ref(false);
  const initialConnecting = ref(true);

  // Separate error channels (#28: poll recovery must not erase an action error)
  const actionErrorBanner = ref('');
  const pollErrorBanner = ref('');

  // In-flight flags
  const actionPending = ref(false);
  const monitorPending = ref(false);
  const impactPending = ref(false);

  // Independent user draft state (#28: background polls never clobber user input)
  const cachedModels = ref<ModelCatalogItem[]>([]);
  const draftModel = ref('');
  const draftEffort = ref('default');
  const draftToolsMode = ref('chat');
  const draftUseDefault = ref(false);
  const authCode = ref('');

  // Preserved UI expansion state across background polling (#28)
  const installPanelOpen = ref(false);
  const expandedMonitorDetails = ref<Record<string, boolean>>({});
  const expandedMonitorDiag = ref<Record<string, boolean>>({});

  // Relative time tick (updates "刚刚 / X 分钟前" cleanly without rebuilding state)
  const nowTick = ref(Date.now());

  // Snackbar notifications
  const snackbar = ref<SnackbarState>({
    show: false,
    text: '',
    color: 'info',
    timeout: 3000,
  });

  // Lifecycle & polling coordination (#28)
  let disposed = false;
  let suspended = false;
  let ready = false;
  let refreshEpoch = 0;
  let actionRevision = 0;
  let pollFailures = 0;
  let pollPending = false;
  let setupTimer: ReturnType<typeof setTimeout> | null = null;
  let monitorTimer: ReturnType<typeof setTimeout> | null = null;
  let clockTimer: ReturnType<typeof setInterval> | null = null;
  let previousInstallError: string | undefined;
  let previousResultSignature = '';
  let previousBusy = false;
  let lastModelCatalogSignature = '';
  let lastEffortSignature = '';

  function notify(
    text: string,
    color: SnackbarState['color'] = 'info',
    timeout = 3000,
  ): void {
    snackbar.value = { show: true, text, color, timeout };
  }

  function selectTab(tab: DashboardTab): void {
    userSelectedTab = true;
    activeTab.value = tab;
  }

  function isDisposed(): boolean {
    return disposed;
  }

  function clearSensitiveMemory(): void {
    authCode.value = '';
    if (setupSnapshot.value?.login) {
      setupSnapshot.value = {
        ...setupSnapshot.value,
        csrf: '',
        login: {
          ...setupSnapshot.value.login,
          url: '',
          ticket: '',
        },
      };
    }
  }

  function applySetupSnapshot(raw: unknown): void {
    if (disposed) return;
    const data = normalizeSetupSnapshot(raw);
    const wasBusy = previousBusy;
    setupSnapshot.value = data;
    initialConnecting.value = false;

    const report = data.report;
    const login = data.login;
    const loginBusy = Boolean(login.busy);
    const busy = actionPending.value || data.busy || loginBusy;
    previousBusy = data.busy;

    // Smart initial landing: stay on overview when configured, otherwise open setup wizard.
    if (!initialLandingResolved) {
      initialLandingResolved = true;
      if (!userSelectedTab && data.providers.length === 0) {
        activeTab.value = 'setup';
      }
    }

    // Cache models across temporary busy checks; clear when idle with no catalog.
    if (Array.isArray(report.models)) {
      cachedModels.value = report.models;
    } else if (!busy) {
      cachedModels.value = [];
    }

    // Preserve user model selection unless empty or removed from catalog.
    const modelSig = JSON.stringify(cachedModels.value);
    if (modelSig !== lastModelCatalogSignature) {
      const ids = new Set(cachedModels.value.map((m) => m.id));
      if (!draftModel.value || !ids.has(draftModel.value)) {
        const preferred = [
          report.selected_model,
          data.providers[0]?.model,
          cachedModels.value[0]?.id,
        ].find((id): id is string => typeof id === 'string' && ids.has(id));
        draftModel.value = preferred ?? '';
      }
      lastModelCatalogSignature = modelSig;
    }

    // Preserve user effort selection when valid for current model.
    const efforts =
      report.selected_model && report.selected_model === draftModel.value && Array.isArray(report.efforts)
        ? report.efforts
        : [];
    const effortSig = JSON.stringify([draftModel.value, efforts, data.global_effort]);
    if (effortSig !== lastEffortSignature && (!busy || report.selected_model === draftModel.value)) {
      const allowed = new Set(['default', ...efforts]);
      if (!allowed.has(draftEffort.value)) {
        draftEffort.value = 'default';
      }
      lastEffortSignature = effortSig;
    }

    // Auto-open install guidance only when an install-class error first appears (#28).
    const errCode = report.error_code;
    if (errCode !== previousInstallError && errCode && hasOwn(INSTALL_ERROR_LABELS, errCode)) {
      installPanelOpen.value = true;
    }
    previousInstallError = errCode;

    // Clear auth code whenever login leaves waiting state.
    if (login.state !== 'waiting') {
      authCode.value = '';
    }

    // Reset use_default checkbox only when a new non-null result arrives (#28).
    const nextResultSig = JSON.stringify(data.result ?? null);
    if (data.result && nextResultSig !== previousResultSignature) {
      draftUseDefault.value = false;
    }
    previousResultSignature = nextResultSig;

    // Surface backend action error with raw error code preserved.
    if (data.action_error) {
      actionErrorBanner.value = [actionErrorLabel(data.action_error), data.action_hint]
        .filter(Boolean)
        .join('：');
    }

    // If a background setup/provider job just finished, refresh monitor snapshot too.
    if (wasBusy && !data.busy) {
      void refreshMonitor();
    }
  }

  async function postSetupAction(
    endpoint: string,
    body: Record<string, unknown> = {},
    options: { strictFields?: boolean } = {},
  ): Promise<SetupSnapshot | null> {
    if (disposed || !bridge || !setupSnapshot.value || actionPending.value) return null;
    actionRevision += 1;
    actionPending.value = true;
    actionErrorBanner.value = '';

    const payload = options.strictFields
      ? { ...body, csrf: setupSnapshot.value.csrf }
      : { ...body, csrf: setupSnapshot.value.csrf };

    try {
      const raw = await bridge.apiPost(`setup/${endpoint}`, payload);
      if (disposed) return null;
      actionPending.value = false;
      applySetupSnapshot(raw);
      scheduleNextSetupPoll();
      return setupSnapshot.value;
    } catch (error) {
      if (disposed) return null;
      actionPending.value = false;
      actionErrorBanner.value = errorMessageOf(error, '请求失败，请刷新页面。');
      return null;
    }
  }

  async function runCheck(model?: string): Promise<void> {
    const body = model ? { model } : {};
    await postSetupAction('check', body);
  }

  async function onDraftModelChange(nextModel: string): Promise<void> {
    draftModel.value = nextModel || '';
    draftEffort.value = 'default';
    if (draftModel.value) {
      await runCheck(draftModel.value);
    }
  }

  async function startLogin(): Promise<void> {
    await postSetupAction('login');
  }

  async function submitLoginCode(): Promise<void> {
    const ticket = setupSnapshot.value?.login?.ticket || '';
    const code = authCode.value;
    // Clear auth code from memory immediately before awaiting network (#28).
    authCode.value = '';
    if (!code.trim() || !ticket) return;
    await postSetupAction('login-code', { ticket, code });
  }

  async function cancelLogin(): Promise<void> {
    const ticket = setupSnapshot.value?.login?.ticket || '';
    if (!ticket) return;
    await postSetupAction('login-cancel', { ticket });
  }

  async function applyModelConfig(override?: ApplyModelPayload): Promise<void> {
    const payload: ApplyModelPayload = override ?? {
      model: draftModel.value,
      effort: draftEffort.value || 'default',
      tools_mode: draftToolsMode.value || 'chat',
      use_default: Boolean(draftUseDefault.value),
    };
    if (!payload.model) return;
    await postSetupAction('apply', {
      model: payload.model,
      effort: payload.effort,
      tools_mode: payload.tools_mode,
      use_default: Boolean(payload.use_default),
    });
  }

  async function fetchProviderImpact(providerId: string): Promise<ProviderImpact> {
    if (!bridge || !setupSnapshot.value) {
      throw new Error('尚未连接到 AstrBot 面板。');
    }
    impactPending.value = true;
    try {
      const response = await bridge.apiPost<{ impact?: ProviderImpact }>('setup/provider-impact', {
        csrf: setupSnapshot.value.csrf,
        provider_id: providerId,
      });
      if (!response?.impact) {
        throw new Error('后端未返回实例影响范围数据。');
      }
      return response.impact;
    } finally {
      impactPending.value = false;
    }
  }

  async function setProviderDefault(providerId: string): Promise<SetupSnapshot | null> {
    return postSetupAction(
      'provider-default',
      { provider_id: providerId, confirm: true },
      { strictFields: true },
    );
  }

  async function toggleProvider(providerId: string, enabled: boolean): Promise<SetupSnapshot | null> {
    return postSetupAction(
      'provider-toggle',
      { provider_id: providerId, enabled: Boolean(enabled), confirm: true },
      { strictFields: true },
    );
  }

  async function deleteProvider(providerId: string): Promise<SetupSnapshot | null> {
    return postSetupAction(
      'provider-delete',
      { provider_id: providerId, confirm: true },
      { strictFields: true },
    );
  }

  function scheduleNextSetupPoll(): void {
    if (setupTimer) {
      clearTimeout(setupTimer);
      setupTimer = null;
    }
    if (disposed || suspended || !ready || document.hidden) return;
    const isBusy = Boolean(setupSnapshot.value?.busy || setupSnapshot.value?.login?.busy);
    const delay = pollFailures
      ? Math.min(5000 * 2 ** (pollFailures - 1), 30000)
      : isBusy
        ? 1200
        : 5000;
    setupTimer = setTimeout(() => {
      void pollSetup();
    }, delay);
  }

  async function pollSetup(): Promise<void> {
    if (setupTimer) {
      clearTimeout(setupTimer);
      setupTimer = null;
    }
    if (disposed || suspended || document.hidden || pollPending || !ready || !bridge) return;

    const epoch = refreshEpoch;
    const currentRevision = actionRevision;
    pollPending = true;
    try {
      if (!actionPending.value) {
        const raw = await bridge.apiGet('setup/status');
        if (!disposed && epoch === refreshEpoch && currentRevision === actionRevision) {
          applySetupSnapshot(raw);
          pollFailures = 0;
          pollErrorBanner.value = '';
        }
      }
    } catch (error) {
      if (!disposed && epoch === refreshEpoch && currentRevision === actionRevision) {
        pollFailures = Math.min(pollFailures + 1, 4);
        pollErrorBanner.value = errorMessageOf(error, '无法读取设置状态，正在退避重试。');
        initialConnecting.value = false;
      }
    } finally {
      if (!disposed && epoch === refreshEpoch) {
        pollPending = false;
        scheduleNextSetupPoll();
      }
    }
  }

  async function refreshMonitor(): Promise<void> {
    if (monitorTimer) {
      clearTimeout(monitorTimer);
      monitorTimer = null;
    }
    if (disposed || suspended || document.hidden || monitorPending || !ready || !bridge) return;

    const epoch = refreshEpoch;
    monitorPending = true;
    try {
      const raw = await bridge.apiGet('monitor/status');
      if (!disposed && epoch === refreshEpoch) {
        const data = normalizeMonitorSnapshot(raw);
        monitorSnapshot.value = data;
        monitorStale.value = false;
        monitorPermissionDenied.value = false;
        monitorMessage.value = data.instances.length
          ? ''
          : '尚未配置 AGY 实例，请前往「首次设置」或「模型管理」添加模型。';
      }
    } catch (error) {
      if (disposed || epoch !== refreshEpoch) return;
      const denied = isPermissionError(error);
      monitorStale.value = true;
      monitorPermissionDenied.value = denied;
      monitorMessage.value = denied
        ? '无权读取监控，请使用 AstrBot 管理员账号登录后刷新。'
        : monitorSnapshot.value
          ? '监控读取失败，以下展示的为过期快照。'
          : '暂时无法读取监控数据，请稍后刷新。';
      if (denied) {
        monitorSnapshot.value = null;
      }
    } finally {
      if (!disposed && epoch === refreshEpoch) {
        monitorPending = false;
        if (!document.hidden) {
          monitorTimer = setTimeout(() => {
            void refreshMonitor();
          }, 10000);
        }
      }
    }
  }

  function pauseRefresh(): void {
    refreshEpoch += 1;
    if (setupTimer) {
      clearTimeout(setupTimer);
      setupTimer = null;
    }
    if (monitorTimer) {
      clearTimeout(monitorTimer);
      monitorTimer = null;
    }
    pollPending = false;
    monitorPending = false;
  }

  function resumeRefresh(): void {
    if (disposed || suspended || document.hidden || !ready) return;
    pollFailures = 0;
    void pollSetup();
    void refreshMonitor();
  }

  async function refreshNow(): Promise<void> {
    if (disposed || !ready) return;
    pollFailures = 0;
    await Promise.all([pollSetup(), refreshMonitor()]);
  }

  function handleVisibilityChange(): void {
    if (document.hidden) pauseRefresh();
    else resumeRefresh();
  }

  function handlePageHide(event: PageTransitionEvent): void {
    pauseRefresh();
    if (event.persisted) {
      suspended = true;
      return;
    }
    dispose();
  }

  function handlePageShow(event: PageTransitionEvent): void {
    if (event.persisted) {
      suspended = false;
      resumeRefresh();
    }
  }

  async function init(): Promise<void> {
    theme.startListeners();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener('pageshow', handlePageShow);

    clockTimer = setInterval(() => {
      if (!document.hidden && !suspended && !disposed) {
        nowTick.value = Date.now();
      }
    }, 30000);

    if (!bridge) {
      bridgeUnavailable.value = true;
      initialConnecting.value = false;
      actionErrorBanner.value = '请从 AstrBot WebUI 侧边栏或插件详情打开 Antigravity ACP 面板。';
      monitorMessage.value = '请从 AstrBot 管理面板打开运行监控。';
      return;
    }

    try {
      const ctx = await bridge.ready();
      if (disposed) return;
      theme.syncFromContext(ctx);
      ready = true;
      void refreshMonitor();
      await pollSetup();
    } catch (error) {
      if (disposed) return;
      initialConnecting.value = false;
      actionErrorBanner.value = errorMessageOf(error, '面板连接失败，请刷新页面。');
      monitorStale.value = true;
      monitorMessage.value = '面板连接失败，请刷新页面。';
    }
  }

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    pauseRefresh();
    if (clockTimer) {
      clearInterval(clockTimer);
      clockTimer = null;
    }
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    window.removeEventListener('pagehide', handlePageHide);
    window.removeEventListener('pageshow', handlePageShow);
    theme.dispose();
    clearSensitiveMemory();
    monitorSnapshot.value = null;
  }

  // Computed helpers
  const isBusy = computed(() =>
    Boolean(
      actionPending.value ||
        setupSnapshot.value?.busy ||
        setupSnapshot.value?.login?.busy,
    ),
  );

  const isPreflightPassed = computed(() => setupSnapshot.value?.report?.status === 'passed');

  const combinedRouting = computed<RoutingSnapshot | null>(
    () => monitorSnapshot.value?.routing ?? setupSnapshot.value?.routing ?? null,
  );

  const availableEfforts = computed<string[]>(() => {
    const report = setupSnapshot.value?.report;
    if (!report || report.selected_model !== draftModel.value || !Array.isArray(report.efforts)) {
      return [];
    }
    return report.efforts;
  });

  const connectionLabel = computed(() => {
    if (bridgeUnavailable.value) return '未检测到宿主 Bridge';
    if (initialConnecting.value) return '正在连接 AstrBot…';
    if (pollErrorBanner.value) return '连接中断，正在重试…';
    if (isBusy.value) return '正在同步…';
    return '已连接 AstrBot';
  });

  const connectionColor = computed<'success' | 'warning' | 'error' | 'info'>(() => {
    if (bridgeUnavailable.value) return 'error';
    if (pollErrorBanner.value) return 'warning';
    if (initialConnecting.value || isBusy.value) return 'info';
    return 'success';
  });

  return {
    theme,
    activeTab,
    selectTab,
    setupSnapshot,
    monitorSnapshot,
    monitorStale,
    monitorPermissionDenied,
    monitorMessage,
    bridgeUnavailable,
    initialConnecting,
    actionErrorBanner,
    pollErrorBanner,
    actionPending,
    monitorPending,
    impactPending,
    cachedModels,
    draftModel,
    draftEffort,
    draftToolsMode,
    draftUseDefault,
    authCode,
    installPanelOpen,
    expandedMonitorDetails,
    expandedMonitorDiag,
    nowTick,
    snackbar,
    isBusy,
    isPreflightPassed,
    combinedRouting,
    availableEfforts,
    connectionLabel,
    connectionColor,
    notify,
    isDisposed,
    runCheck,
    onDraftModelChange,
    startLogin,
    submitLoginCode,
    cancelLogin,
    applyModelConfig,
    fetchProviderImpact,
    setProviderDefault,
    toggleProvider,
    deleteProvider,
    refreshMonitor,
    refreshNow,
    init,
    dispose,
  };
}

export type DashboardController = ReturnType<typeof createDashboardController>;
