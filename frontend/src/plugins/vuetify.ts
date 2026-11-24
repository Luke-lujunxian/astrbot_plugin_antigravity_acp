import { createVuetify, type ThemeDefinition } from 'vuetify';
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg';

export const LIGHT_THEME_NAME = 'AstrBotLight';
export const DARK_THEME_NAME = 'AstrBotDark';

export const DEFAULT_LIGHT_PRIMARY = '#3c96ca';
export const DEFAULT_LIGHT_SECONDARY = '#2f86bd';
export const DEFAULT_DARK_PRIMARY = '#5ba4d4';
export const DEFAULT_DARK_SECONDARY = '#4a95c4';

// Theme palette aligned with AstrBot v4.29.4 (6133541443) native Dashboard themes.
const AstrBotLight: ThemeDefinition = {
  dark: false,
  variables: {
    'border-color': '#1e88e5',
    'border-opacity': 0.16,
  },
  colors: {
    primary: DEFAULT_LIGHT_PRIMARY,
    secondary: DEFAULT_LIGHT_SECONDARY,
    info: '#03c9d7',
    success: '#00c853',
    accent: '#FFAB91',
    warning: '#ffc107',
    error: '#f44336',
    lightprimary: '#eef2f6',
    lightsecondary: '#e8f3fa',
    lightsuccess: '#b9f6ca',
    lighterror: '#f9d8d8',
    lightwarning: '#fff8e1',
    primaryText: '#1b1c1d',
    secondaryText: '#000000aa',
    darkprimary: '#1565c0',
    darksecondary: '#236b99',
    borderLight: '#d0d0d0',
    border: '#d0d0d0',
    inputBorder: '#787878',
    containerBg: '#fffffff4',
    surface: '#ffffff',
    'on-surface-variant': '#525866',
    background: '#ffffff',
    gray100: '#fafafacc',
    primary200: '#90caf9',
    secondary200: '#8cc4e1',
    codeBg: '#ececec',
    preBg: '#f9f9f9',
    code: '#0d0d0d',
    mcpCardBg: '#ecf2fa',
  },
};

const AstrBotDark: ThemeDefinition = {
  dark: true,
  variables: {
    'border-color': '#3c96ca',
    'border-opacity': 0.22,
  },
  colors: {
    primary: DEFAULT_DARK_PRIMARY,
    secondary: DEFAULT_DARK_SECONDARY,
    info: '#03c9d7',
    success: '#52c41a',
    accent: '#FFAB91',
    warning: '#faad14',
    error: '#ff4d4f',
    lightprimary: '#1a2e3d',
    lightsecondary: '#1a2e3d',
    lightsuccess: '#1a3a1a',
    lighterror: '#3d1a1a',
    lightwarning: '#3d351a',
    primaryText: '#e8eaed',
    secondaryText: '#ffffffdd',
    darkprimary: '#3a8ab8',
    darksecondary: '#3a8ab8',
    borderLight: '#3a3a3a',
    border: '#333333ee',
    inputBorder: '#787878',
    containerBg: '#1a1a1a',
    surface: '#242424',
    'on-surface-variant': '#c8cdd5',
    background: '#1a1a1a',
    gray100: '#cccccccc',
    primary200: '#84c9ea',
    secondary200: '#8cc4e1',
    codeBg: '#282833',
    preBg: '#171717',
    code: '#ffffffdd',
    mcpCardBg: '#2a2a2a',
  },
};

export const vuetify = createVuetify({
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi,
    },
  },
  theme: {
    defaultTheme: LIGHT_THEME_NAME,
    themes: {
      [LIGHT_THEME_NAME]: AstrBotLight,
      [DARK_THEME_NAME]: AstrBotDark,
    },
  },
  defaults: {
    VBtn: {},
    VCard: {
      rounded: 'lg',
    },
    VSnackbar: {
      elevation: 6,
      rounded: 'lg',
    },
    VTextField: {
      rounded: 'lg',
    },
    VSelect: {
      rounded: 'lg',
    },
    VAutocomplete: {
      rounded: 'lg',
    },
    VTooltip: {
      location: 'top',
    },
  },
});

export default vuetify;
