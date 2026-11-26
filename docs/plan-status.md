# 计划与历史资料状态索引

> 核对日期 **2026-11-26**。当前版本见 [metadata.yaml](../metadata.yaml)，发布与实测证据见 [CHANGELOG](../CHANGELOG.md)、[testing.md](testing.md) 和关联 PR/Issue。

## 当前有效资料

- [AGENTS.md](../AGENTS.md)：Agent 工作入口、安全边界、开发流程。
- [architecture.md](architecture.md)、[troubleshooting.md](troubleshooting.md)、[testing.md](testing.md)：当前架构、排障和分层验收。
- [兼容补丁登记](compatibility.md)：#14、#19、#33、4.29.4 fallback 等宿主适配及协议边界。
- [WebUI 观测面板计划](webui-observability-dashboard-plan.md)：P0 已落地；未勾选的 P1/P2 是可选积压功能，不是排期发布承诺。

## 已完成或只供追溯的施工记录

| 历史文档 | 结论/当前用途 |
| --- | --- |
| [0.5.0 会话与成本任务书](next-version-task.md) | 历史设计；当前会话逻辑以源码和测试为准 |
| [Agent 文档“下一版本”计划](agent-docs-next-release-plan.md) | **已完成并纳入 v0.7.1**（#16/#17）；当时的未合并字样已标注为历史口径 |
| [LiftGate 0.6.0 加固施工书](liftgate-hardening-plan.md) | #9 相关历史设计；当前契约和已验/未验要另见 [PR #9 验收](pr9-acceptance.md) 及 CHANGELOG |
| [429 内容相关调研](429-prompt-investigation.md) | 旧阶段证据/假设；后续 #19 Safe Mode 与 #14 能力声明处理见 [兼容补丁](compatibility.md)，不能把所有 429 归为内容原因 |
| [0.5.0 实现记录](impl-notes-0.5.0.md)、[PR #9 验收](pr9-acceptance.md) | 版本固定的历史验收材料，不证明当前所有部署平台已验 |
| [旧版交接与报告](archive/HANDOFF_0.4.0.md)、[0.4.0](archive/TEST_REPORT_0.4.0.md)、[0.4.1](archive/TEST_REPORT_0.4.1.md) | 早期交接和测试证据，不作当前任务入口 |
| [review-bundle](archive/review-bundle/) | 审读快照、旧补丁材料及历史源码副本 |

历史 Issue、PR 与 CHANGELOG 仍按旧的根目录路径引用上述文件；本次只把它们归档到 `docs/archive/` 并同步本索引与安全说明，不重写旧实测数据、不把“待测”擅自改成“通过”。

## 待处理与待验证

1. **#38 / #41 只读梯队已合并（v0.8.4），写操作与跨平台实机待验证**：PR #39 与 PR #42 已合入落地工具权限独立页签、CLI 账号额度、每日用量热力图、`/agy` 命令精简、统一内置工具注册表、无 MCP 解耦及 Linux CLI `1.5.17`/`1.5.18` 受限工作区 `.txt` 只读（含按行分页）；#41 中 `write_file`/`edit_file` 等写入操作需单独评审安全配额后另案推进，Windows/macOS 及未来 CLI `>=1.5.19` 工具授权暂保留 `unverified`。
2. **#36 已合并（v0.8.3），#30/#32 实机矩阵仍待补全**：PR #37 已合并并落地三标签页、原地编辑（`provider-update`）、漂移修复（`provider-repair`）、受控默认迁移及前端缓存防护；v0.8.0 Vue 前端交接仅供历史追溯；历史图片预算、当前输入、路由与 fallback 边界由离线测试覆盖。#31 跨平台/真实宿主长期视觉与 CLI 验收待记录；#32 §5 并发争用、池锁与专用 Agent 调查延期。
2. **WebUI P1/P2**：趋势/故障筛选/复制诊断等属于非紧急可选功能，必须分项真实验收，不能由 P0 的完成状态推断。
3. **AstrBot 4.30**：仅识别部分已知模板文案，尚无完整运行兼容证据。
4. **真实环境矩阵**：Windows 工具调用、macOS 认证/环境、长期运行、QQ 生产消息路径及更多并发组合需要分层验证。
5. **兼容补丁清理**：先按 [compatibility.md](compatibility.md) 核实相应上游问题是否消失，再带回归和可回滚依据逐项移除；不把安全/协议不变量当历史补丁删除。

## 维护约定

新任务优先写当前 Issue/PR 或更新本索引，不再创建名为“下一版本”的全量施工书。历史文档保留版本标记和原始证据；有新的发布或补丁退役时只更新有效入口、此索引和具体发行日志。
