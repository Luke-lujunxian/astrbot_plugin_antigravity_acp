/// <reference types="vite/client" />

import type { AstrBotPluginBridge } from './types/api';

declare global {
  interface Window {
    AstrBotPluginView?: AstrBotPluginBridge;
    AstrBotPluginPage?: AstrBotPluginBridge;
  }
}

export {};
