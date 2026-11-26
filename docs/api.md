# WebUI 后端接口

路径均相对 AstrBot 插件视图 bridge。沿用 apiGet/apiPost 的宿主 JSON 封装，下文描述 data。面板管理员认证共用现有规则，匿名 401，API key 和非面板管理员 403，新接口停用 503。原 setup/status 在停用后被直接调用仍沿用宿主 400。响应 no-store。POST 为 application/json，必须带 setup/status 当前 csrf。聊天使用独立的 AstrBot 管理员判定。

## 面板错误

插件处理器返回的所有 `setup/*`、`monitor/*` HTTP 错误均保留 HTTP 状态码，JSON 使用 `{"status":"error","message":"[AGY:CODE] 人类可读说明","data":{"code":"CODE"}}`。AstrBot 4.29.4 的 iframe bridge 仅转发 `message` 字符串。前端可用 `^\[AGY:([A-Z][A-Z0-9_]*)\] ` 从 `error.message` 开头提取稳定码，展示时去掉该前缀。宿主在分发给插件前拒绝的请求仍可能只有宿主文案。

| 稳定码 | HTTP | 含义 |
| --- | --- | --- |
| `UNAUTHENTICATED` | 401 | 缺少面板会话 |
| `FORBIDDEN` | 403 | API key 或非配置的面板管理员 |
| `CSRF_EXPIRED` | 403 | CSRF 缺失、无效或已过期 |
| `LOGIN_BUSY` | 409 | 官方登录进行中，额度刷新未启动 |
| `BUSY` | 409 | 其他并发操作冲突 |
| `CLOSED` | 503 | 插件已停用，适用于 `monitor/*`、`setup/tool-policy`、`setup/quota-refresh` |
| `CLOSED` | 400 | 原有 `setup/*` 接口的停用响应，包括 `setup/status` |
| `STORAGE_UNAVAILABLE` | 503 | 本地每日统计存储不可用 |
| `QUOTA_UNAVAILABLE` | 503 | 缺少额度服务 |
| `CONFIG` / `UNSUPPORTED` | 400 | 请求参数或当前能力不允许该操作 |
| `INTERNAL` | 500 | 本地操作失败，例如工具策略持久化失败 |

其他已知业务异常沿用各自的 AGY 代码并返回 HTTP 400。HTTP 200 的额度快照仍通过快照内的 `error.code` 表示 CLI 查询失败。

## 工具策略

GET `setup/status` 包含 `tool_policy`。POST `setup/tool-policy` 请求含 `csrf` 和至少一个工具策略字段。`read_file` 取 `deny` 或 `allow_once`，`search_web` 取 `deny` 或 `allow`，可单独保存或一同提交。例如 `{"csrf":"…","search_web":"allow"}`。只提交 `read_file` 的旧请求仍有效。成功直接返回相同结构的工具策略对象。下面是字段形状，数组按后端实际清单渲染。

```json
{"enable_tools":true,"reload_required":false,"tools":[
  {"id":"astrbot_mcp","source":"mcp","purpose":"宿主提供的工具","risk":"host","capability":"supported","choices":[],"policy":"allow_once","effective":true,"reload_required":false},
  {"id":"read_file","source":"builtin","purpose":"读取隔离工作区顶层文本文件","risk":"high","capability":"supported","choices":["deny","allow_once"],"policy":"deny","effective":false,"reload_required":false},
  {"id":"search_web","source":"builtin","purpose":"联网搜索","risk":"network","capability":"experimental","choices":["deny","allow"],"policy":"deny","effective":false,"reload_required":false,"pre_execution_approval":false,"enforcement":"post_observation","limitation":"CLI 自动执行搜索，无法在执行前审批。关闭时由模型护栏和事后中止限制，发现时搜索请求可能已发出。开启后按通知计入预算，超预算时中止本轮。"}
]}
```

`policy` 为已保存策略，`effective` 表示当前加载的全局策略在具备所需条件的工具实例是否可用。`enable_tools` 取当前生效值。两项可开启的内置工具仅适用于工具实例（非 `chat` 且本轮 `tool_choice != "none"`），要求总闸开启；开启后即使本轮没有宿主 MCP 工具也可独立激活（无需等待非空宿主工具快照）。实例 `chat` 或本轮 `tool_choice=none` 时均不可用。MCP 清单由每轮宿主快照决定。

`read_file` 仅在 Linux、CLI 版本探测及当前 ACP 握手均确认 `1.5.17` 或 `1.5.18`、`strict` 下开放，仅限当前私有工作区顶层普通单链接 `.txt` 文件，支持合法只读分页参数 `StartLine`、`EndLine`、`ByteOffset`（禁止 `file:///` URI 及参数篡改）。未确认时 `capability=unverified`、`choices=["deny"]`。每次授权绑定当前 prompt 的 ACP 请求并与 MCP 共用 `tool_max_calls`。

`search_web` 是由官方 CLI 自动执行的实验性联网搜索。关闭时模型护栏要求避免该工具，插件在收到调用通知时中止本轮，搜索请求可能已经发出。开启时每个新搜索调用在收到通知后计入本轮工具调用次数，并与 MCP 和 `read_file` 共用 `tool_max_calls`。检测到超预算的搜索后中止本轮，已发出的请求无法撤回，预算无法保证实际联网次数。`pre_execution_approval: false`、`enforcement: "post_observation"` 和 `limitation` 说明上述限制。`edit_file`、`write_file`、`run_command`、`read_url`、`execute_url`、`browser` 及 CLI 内部调度/子代理/工作流工具继续固定拒绝（详情见 [CLI 1.5.18 原生工具调查报告](issue41-builtin-tools-probe.md)）。

保存请求只更新所提交的全局 `builtin_read_file`、`builtin_search_web` 键，两项默认 `deny`。工具行的 `reload_required` 表示该行已保存策略与运行态不同，任一工具行待重载即令顶层 `reload_required: true`。重载后使用新策略和护栏。持久化失败会回滚本次提交并返回 HTTP 500。仅提交 `csrf`、未知字段、工具或策略返回 HTTP 400 `CONFIG`。未验证时提交 `read_file: "allow_once"` 返回 HTTP 400 `UNSUPPORTED`。总闸由宿主插件配置保存并重载，实例模式由原有 `setup/provider-update` 更新。

## 官方 CLI 额度

GET `monitor/quota` 仅读内存缓存，初始 `groups=[]`、`fetched_at=null`、`error=null`。进入监控页、从隐藏或往返缓存恢复、登录结束后，面板先读取缓存，只有缓存缺失或过期才尝试自动查询。

POST `setup/quota-refresh` 接受 `{"csrf":"…","force":false}`。省略 `force` 或传 `true` 表示手动刷新，跳过 TTL 与失败冷却。其他类型和额外字段返回 400。按需刷新和 `/agy quota` 复用 60 秒内的成功快照。已核验登录环境的暂时失败冷却 60 秒，认证失败、CLI 未安装或不支持时等待手动刷新或登录环境变化。并发刷新合并为一次官方 CLI `/usage` 查询，超时 30 秒。登录中返回 409。

额度快照仅保留在内存。登录操作、环境变化和认证失效会清除旧额度。无法观察登录环境的原生钥匙串只返回本次查询结果，既有快照与失败冷却均不跨次复用。面板的重置倒计时仅反映额度池的本地时间差。

```json
{"schema_version":1,"source":"official_cli","login_env":"匿名环境标识","cli_version":"1.5.17","capability":"supported","fetched_at":"2026-11-26T05:00:00+00:00","stale":false,"groups":[{"name":"额度组","models_shared":["模型显示名"],"buckets":[{"id":"pool-week","name":"周额度","window":"weekly","remaining_fraction":0.75,"reset_time":null}]}],"error":null}
```

同组模型共享 buckets，window 使用 CLI 原值。已知前缀解析不到模型时 models_shared=[]。UTC 重置时间为 null 时显示不适用。无绝对额度或套餐推算。capability 取 unknown/supported/unsupported；cli_version 未知为 null。错误采用同一快照（HTTP 200），error 为 {code,message} 固定脱敏说明。代码 AUTH、TIMEOUT、NOT_INSTALLED、UNSUPPORTED、QUOTA_FORMAT、QUOTA_FAILED、ENV_CHANGED。失败时同环境可保留上次成功数据，stale=true；TTL 已过同样 stale。首次未查询 stale=false。

## 近 24 小时运行统计

GET `monitor/status` 沿用 schema v2。每个运行实例的 `summary` 和 `recent_turns` 包含窗口内的历史和实时样本，`/agy cost` 使用相同统计来源。每个实例最多 100 轮，接口返回最近 20 轮明细。复用率按实际发出的轮次计算。缺失用量保留为 `null`。

`instances[].history_storage` 为 `available` 或 `memory_only`。实例未加载时为 `null`。恢复的样本带 `historical: true`，时间和模型仍为采样时的值。`pool`、`latest_context` 和当前运行状态来自本次加载后的运行时。每日用量与失败诊断继续使用独立存储，额度查询不进入请求统计。 [存储与实例归属](architecture.md#监控明细存储)

## 每日用量

GET `monitor/daily/30`、`monitor/daily/90`、`monitor/daily/365`，默认展示 90 天。每次返回区间内全部模型，前端可本地筛选、切换指标。宿主本地日历含今日，日期无需转换。仅返回实际有终结轮次的日期，区间内缺行表示无记录。

```json
{"schema_version":1,"timezone":"host_local","range":{"days":90,"start":"2026-08-29","end":"2026-11-26"},"models":["model-id"],"days":[{"date":"2026-11-26","requests":2,"success":1,"failed":1,"input_tokens":100,"cached_tokens":20,"output_tokens":10,"total_tokens":110,"usage_unknown_turns":1,"by_model":{"model-id":{"requests":2,"success":1,"failed":1,"input_tokens":100,"cached_tokens":20,"output_tokens":10,"total_tokens":110,"usage_unknown_turns":1}}}]}
```

requests 含失败、取消及本地短路，success 只计 ok，其余计 failed。按完成时宿主日期入账。input_tokens 包含可观测缓存，cached_tokens 为其中的缓存读取，total_tokens 为已知输入和输出之和。部分缺字段时各列为已知和，全未知的列为 null，未发出请求的已知零保留为 0。usage_unknown_turns 统计已发出但缺可用 usage 的轮。只存日/模型汇总，无旧数据回填。今天取 range.end，活跃天数为有记录的日期数，日均按有记录天数计算。存储故障返回 HTTP 503。模型键来自本地轮次，配置映射沿用 setup/status.providers[].id/model、monitor/status.instances[].provider_id/model。CLI 共享组的显示名独立，不猜测 Provider 对应额度池。

## 聊天管理员指令

| 指令 | 功能与范围 |
| --- | --- |
| /agy help | 列出指令与参数 |
| /agy setup | 设置入口及已有实例 |
| /agy use <provider_id> | 切换当前会话 |
| /agy cost | 现有本地成本与复用统计 |
| /agy doctor | 无生成自检 |
| /agy quota | 官方 CLI 额度 |
| /agy status | 已加载实例及运行状态 |
| /agy models | 已配置模型与实例 ID |
| /agy usage [30&#124;90&#124;365] | 本地每日统计摘要及最近 28 天文本热力图，默认 90 天 |

上述指令在插件启用且宿主将消息分发给插件的私聊、群聊中使用。管理员发送裸 `/agy` 时显示同 `/agy help` 的帮助。非管理员发送裸 `/agy` 或已注册子指令时只收到 `AGY [FORBIDDEN] 仅管理员可使用此指令。`。额度服务在查询时停用，`/agy quota` 会提示 `AGY [CLOSED] 插件已停用。`。

## 变更记录

- 2026-11-26 生产根因调查返回后，setup/status 新增可空字符串 command_scope_warning。默认配置显式排除本插件时返回修复提示。会话单独绑定的配置仍需管理员核对。
- 2026-11-26 14:04 CST 收紧 read_file 能力范围至实测的 Linux，并在每次启动时核对实际 ACP agentInfo，以覆盖 wrapper 目标热替换。macOS 与 Windows 返回 unverified。
- 2026-11-26 14:13 CST 补充 /agy usage 聊天输出中的 28 天文本热力图。HTTP 统计字段和区间保持原契约。
- 2026-11-26 14:20 CST 按已注册路由的实测响应补记登录中 409 和原 setup/status 的停用状态码，便于前端处理迟到请求。
