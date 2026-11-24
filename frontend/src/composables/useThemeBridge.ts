import { computed, ref } from 'vue';
import type { AstrBotBridgeContext, AstrBotPluginBridge } from '@/types/api';
import {
  DARK_THEME_NAME,
  DEFAULT_DARK_PRIMARY,
  DEFAULT_DARK_SECONDARY,
  DEFAULT_LIGHT_PRIMARY,
  DEFAULT_LIGHT_SECONDARY,
  LIGHT_THEME_NAME,
  vuetify,
} from '@/plugins/vuetify';

export type ThemeMode = 'auto' | 'light' | 'dark';

const THEME_STORAGE_KEY = 'agy-acp.setup.theme';
const HEX_COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function sanitizeHexColor(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return HEX_COLOR_RE.test(trimmed) ? trimmed : null;
}

export function getPluginBridge(): AstrBotPluginBridge | null {
  if (typeof window === 'undefined') return null;
  return window.AstrBotPluginView ?? window.AstrBotPluginPage ?? null;
}

function readStoredThemeMode(): ThemeMode {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // Sandboxed iframe without allow-same-origin blocks localStorage.
  }
  return 'auto';
}

function readInitialDocumentTheme(): 'light' | 'dark' | null {
  if (typeof document === 'undefined') return null;
  const attr = document.documentElement.dataset.theme;
  if (attr === 'light' || attr === 'dark') return attr;
  try {
    const param = new URLSearchParams(window.location.search).get('theme');
    if (param === 'light' || param === 'dark') return param;
  } catch {
    // Ignore invalid search strings.
  }
  return null;
}

function readIframeCssColor(names: string[]): string | null {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  try {
    const style = window.getComputedStyle(document.documentElement);
    for (const name of names) {
      const value = sanitizeHexColor(style.getPropertyValue(name));
      if (value) return value;
    }
  } catch {
    // Ignore computed style failure in minimal environments.
  }
  return null;
}

export function createThemeBridgeController() {
  const bridge = getPluginBridge();
  const themeMode = ref<ThemeMode>(readStoredThemeMode());
  const bridgeContext = ref<AstrBotBridgeContext | null>(null);
  const hostAccentApplied = ref(false);
  const resolvedDark = ref(false);

  let offContext: (() => void) | null = null;
  let mediaQuery: MediaQueryList | null = null;
  let mediaListener: ((event: MediaQueryListEvent) => void) | null = null;

  function detectOptionalHostColors(ctx: AstrBotBridgeContext | null): {
    primary: string | null;
    secondary: string | null;
  } {
    const primary =
      sanitizeHexColor(ctx?.theme?.primary) ??
      sanitizeHexColor(ctx?.theme?.colors?.primary) ??
      sanitizeHexColor(ctx?.colors?.primary) ??
      sanitizeHexColor(ctx?.primaryColor) ??
      readIframeCssColor(['--astrbot-theme-primary', '--astrbot-primary']);

    const secondary =
      sanitizeHexColor(ctx?.theme?.secondary) ??
      sanitizeHexColor(ctx?.theme?.colors?.secondary) ??
      sanitizeHexColor(ctx?.colors?.secondary) ??
      sanitizeHexColor(ctx?.secondaryColor) ??
      readIframeCssColor(['--astrbot-theme-secondary', '--astrbot-secondary']);

    return { primary, secondary };
  }

  function applyHostAccentIfPresent(ctx: AstrBotBridgeContext | null): void {
    const { primary, secondary } = detectOptionalHostColors(ctx);
    const themes = vuetify.theme.themes.value;
    const light = themes[LIGHT_THEME_NAME];
    const dark = themes[DARK_THEME_NAME];

    if (light?.colors) {
      light.colors.primary = primary ?? DEFAULT_LIGHT_PRIMARY;
      light.colors.secondary = secondary ?? DEFAULT_LIGHT_SECONDARY;
    }
    if (dark?.colors) {
      dark.colors.primary = primary ?? DEFAULT_DARK_PRIMARY;
      dark.colors.secondary = secondary ?? DEFAULT_DARK_SECONDARY;
    }
    hostAccentApplied.value = Boolean(primary || secondary);
  }

  function resolveTheme(): 'light' | 'dark' {
    if (themeMode.value === 'light' || themeMode.value === 'dark') {
      return themeMode.value;
    }
    let hostIsDark: boolean | undefined;
    if (typeof bridgeContext.value?.isDark === 'boolean') {
      hostIsDark = bridgeContext.value.isDark;
    } else {
      try {
        const ctx = bridge?.getContext?.();
        if (typeof ctx?.isDark === 'boolean') hostIsDark = ctx.isDark;
      } catch {
        // Host context may not be ready yet.
      }
    }
    if (typeof hostIsDark === 'boolean') {
      return hostIsDark ? 'dark' : 'light';
    }
    const docTheme = readInitialDocumentTheme();
    if (docTheme) return docTheme;
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return 'light';
  }

  function applyTheme(): void {
    const resolved = resolveTheme();
    resolvedDark.value = resolved === 'dark';
    vuetify.theme.global.name.value = resolved === 'dark' ? DARK_THEME_NAME : LIGHT_THEME_NAME;
    applyHostAccentIfPresent(bridgeContext.value);

    if (typeof document !== 'undefined') {
      const root = document.documentElement;
      if (themeMode.value === 'auto' && typeof bridgeContext.value?.isDark !== 'boolean') {
        const initial = readInitialDocumentTheme();
        if (initial) root.dataset.theme = initial;
        else delete root.dataset.theme;
      } else {
        root.dataset.theme = resolved;
      }
    }
  }

  function cycleTheme(): void {
    const next: Record<ThemeMode, ThemeMode> = {
      auto: 'light',
      light: 'dark',
      dark: 'auto',
    };
    themeMode.value = next[themeMode.value];
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themeMode.value);
    } catch {
      // Storage blocked in sandboxed iframe: keep selection in memory for this session.
    }
    applyTheme();
  }

  function syncFromContext(ctx: AstrBotBridgeContext | null): void {
    if (ctx && typeof ctx === 'object') {
      bridgeContext.value = ctx;
    }
    applyTheme();
  }

  function startListeners(): void {
    applyTheme();
    if (bridge?.onContext) {
      try {
        offContext = bridge.onContext((ctx) => {
          syncFromContext(ctx);
        });
      } catch {
        offContext = null;
      }
    }
    if (typeof window !== 'undefined' && window.matchMedia) {
      mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      mediaListener = () => {
        if (themeMode.value === 'auto') applyTheme();
      };
      if (typeof mediaQuery.addEventListener === 'function') {
        mediaQuery.addEventListener('change', mediaListener);
      }
    }
  }

  function dispose(): void {
    if (offContext) {
      try {
        offContext();
      } catch {
        // Ignore unsubscribe error on unload.
      }
      offContext = null;
    }
    if (mediaQuery && mediaListener && typeof mediaQuery.removeEventListener === 'function') {
      mediaQuery.removeEventListener('change', mediaListener);
    }
    mediaQuery = null;
    mediaListener = null;
  }

  const themeButtonLabel = computed(() => {
    const labels: Record<ThemeMode, string> = {
      auto: '主题：跟随宿主',
      light: '主题：浅色',
      dark: '主题：深色',
    };
    return labels[themeMode.value];
  });

  const hostLocale = computed(() => bridgeContext.value?.locale || bridge?.getLocale?.() || 'zh-CN');

  return {
    bridge,
    themeMode,
    resolvedDark,
    bridgeContext,
    hostAccentApplied,
    hostLocale,
    themeButtonLabel,
    applyTheme,
    cycleTheme,
    syncFromContext,
    startListeners,
    dispose,
  };
}
