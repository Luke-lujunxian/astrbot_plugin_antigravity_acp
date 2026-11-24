# Third-party references

The Python implementation was authored for this repository. ACP transport, isolated custom-agent configuration and usage accounting were informed by:

- [lili-luo/dsh-plugin-bundle](https://github.com/lili-luo/dsh-plugin-bundle), commit `b8989f976fed7ab84fba267853a6dc92bf7c64e4`, `dsh-llm-antigravity-acp/src/{acp-process,preflight,conversation,runtime}.ts`.
- [AstrBot](https://github.com/AstrBotDevs/AstrBot/tree/v4.29.4) provider APIs and plugin lifecycle (runtime dependency; not bundled).

No DSH runtime or compiled JavaScript is bundled.

The 0.4.0 onboarding implementation additionally consulted
`lili-luo/dsh-plugin-bundle` commit
`0a90ec37c69430608084e33ebc2f891e328c9e89`, especially
`dsh-llm-antigravity-acp/src/{preflight,runtime,remote,conversation}.ts` and
`model-selection.js`. Windows discovery, official CLI login orchestration,
and bounded streaming-notice recognition were adapted in Python. The view
uses AstrBot's own plugin-view bridge; DSH UI and runtime dependencies are
not bundled. The upstream license retained below covers these adaptations.
OAuth credential readers/refreshers, internal Cloud Code requests, account
pools, client-identity substitution, and binary patches were not imported.

Host integration follows AstrBot v4.29.4's
`docs/zh/dev/star/guides/plugin-pages.md`, `astrbot/api/web.py`, and
`astrbot/core/provider/manager.py`. CLI install/login guidance was checked
against the official getting-started and ACP documentation on 2026-11-12.

M0 protocol/design review additionally consulted ACP v1 schema at
[`7ec5185c18ca928b48e457d2d8a163800be013c8`](https://github.com/agentclientprotocol/agent-client-protocol/tree/7ec5185c18ca928b48e457d2d8a163800be013c8),
the official AGY documentation repository at
[`e186eb5819bc33ce2d9e26420f30f30ae289b1a5`](https://github.com/google-antigravity/antigravity-cli/tree/e186eb5819bc33ce2d9e26420f30f30ae289b1a5),
and AstrBot v4.29.4 at
[`61335414433db721b3f7ecc93f90deafe0a59d78`](https://github.com/AstrBotDevs/AstrBot/tree/61335414433db721b3f7ecc93f90deafe0a59d78).
These are linked references only; their source, schemas, binaries and account data
are not vendored. No new runtime dependency is introduced.

## Native Dashboard UI refactor (#30) design baseline & frontend packages

The `frontend/` source tree (compiled into static assets under `views/setup/` at
build time; end users do not need Node.js) aligns its visual tokens, typography,
spacing, and Plugin Views Bridge integration with AstrBot v4.29.4 at
[`61335414433db721b3f7ecc93f90deafe0a59d78`](https://github.com/AstrBotDevs/AstrBot/tree/61335414433db721b3f7ecc93f90deafe0a59d78)
(`dashboard/package.json`, `dashboard/src/plugins/vuetify.ts`,
`dashboard/src/theme/{LightTheme,DarkTheme}.ts`, `dashboard/src/scss/*`,
`astrbot/dashboard/plugin_page_bridge.js`, and
`dashboard/src/views/PluginViewPage.vue`). Theme palettes and CSS rules in
`frontend/src/plugins/vuetify.ts` and `frontend/src/styles/astrbot-theme.css`
were independently written for this MIT-licensed repository; no AstrBot AGPL
dashboard source files are vendored.

Frontend packages declared in `frontend/package.json` (installed and bundled into
`views/setup/` during build):

- `vue` (`3.3.4`): MIT License — Vue.js runtime compiled into `views/setup/assets/`.
- `vuetify` (`3.7.11`): MIT License — UI component library tree-shaken into `views/setup/assets/`.
- `@mdi/js` (`^7.4.47`): Apache-2.0 License (JS wrapper) / Pictogrammers Free License (Material Design Icons SVG paths) — tree-shaken minimal SVG path subset only; full icon fonts are not bundled.
- `@fontsource/outfit` (`^5.0.0`): MIT License (packaging) & SIL Open Font License 1.1 (Outfit font weights 400/500/600/700 bundled locally as static woff2 assets; no CDN requests). CJK glyphs use local system font fallbacks.
- Build-time devDependencies (`vite` 6.4.1, `@vitejs/plugin-vue` 5.2.4, `vite-plugin-vuetify` 2.1.3, `typescript` 5.1.6, `vue-tsc` 1.8.8, `@types/node` ^20.5.7): MIT / Apache-2.0 Licenses; excluded from plugin release archives via `.gitattributes`.

The DSH reference project's copyright and MIT license are retained below for the
adapted configuration and protocol patterns:

```text
MIT License

Copyright (c) 2026 lili-luo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
