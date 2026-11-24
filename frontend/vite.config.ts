import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import vuetify from 'vite-plugin-vuetify';

export default defineConfig({
  base: './',
  plugins: [
    vue(),
    vuetify({
      autoImport: true,
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  esbuild: {
    // Keep third-party notices in THIRD_PARTY_NOTICES.md; avoid bundling banner
    // comments into views/setup/assets/* where maintainer emails can trip scans.
    legalComments: 'none',
  },
  build: {
    outDir: '../views/setup',
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 1024,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/vuetify')) {
            return 'vuetify';
          }
          if (id.includes('node_modules/vue') || id.includes('node_modules/@vue')) {
            return 'vue';
          }
          return undefined;
        },
      },
    },
  },
});
