# Issue #38 后端接口

路径均相对 AstrBot 插件视图 bridge。沿用 apiGet/apiPost 的宿主 JSON 封装，下文描述 data。面板管理员认证共用现有规则，匿名 401，API key 和非面板管理员 403，新接口停用 503。原 setup/status 在停用后被直接调用仍沿用宿主 400。响应 no-store。POST 为 application/json，必须带 setup/status 当前 csrf。聊天使用独立的 AstrBot 管理员判定。

## 工具策略

GET `setup/status` 新增 `tool_policy`，POST `setup/tool-policy` 请求为 `{"csrf":"…","read_file":"deny"}` 或 allow_once，成功直接返回相同结构的 tool_policy（无外层同名字段）。失败走宿主错误，保持编辑内容。下面是字段形状，数组按后端实际清单渲染。

```json
{"enable_tools":true,"reload_required":false,"tools":[
  {"id":"astrbot_mcp","source":"mcp","purpose":"宿主提供的工具","risk":"host","capability":"supported","choices":[],"policy":"allow_once","effective":true},
  {"id":"read_file","source":"builtin","purpose":"读取隔离工作区的普通文本文件","risk":"high","capability":"supported","choices":["deny","allow_once"],"policy":"deny","effective":false},
  {"id":"search_web","source":"builtin","purpose":"联网搜索","risk":"network","capability":"unsupported","choices":["deny"],"policy":"deny","effective":false}
]}
```

policy 为已保存策略，effective 为当前加载的全局策略在具备所需条件的工具实例是否可用。enable_tools 取当前生效值。实例 chat、缺少工具快照或宿主未启用 tool_use 时均不可用。MCP 清单由每轮宿主快照决定。read_file 仅在 Linux、CLI 版本探测及当前 ACP 握手均确认 1.5.17、strict 下开放，仅限当前私有工作区顶层普通单链接 .txt 文件；未确认时 capability=unverified、choices=["deny"]。每次绑定当前 prompt 的 ACP 请求并与 MCP 共用 tool_max_calls。其余内置项只读 deny。无身份条件授权。搜索可能在 CLI 发出通知之前已启动，插件不能提供执行前拦截保证。

保存只写插件全局 `builtin_read_file`（默认 deny），重载插件后生效。总闸由宿主插件配置保存并重载，实例模式由原有 setup/provider-update 更新。两者独立。未知字段、工具或策略拒绝 400，持久化失败 500，未授权或 nonce 过期 403。

## 官方 CLI 额度

GET `monitor/quota` 仅读内存缓存，初始 groups=[]、fetched_at=null、error=null。POST `setup/quota-refresh` 请求仅含 csrf，主动查询并返回额度快照。/agy quota 同服务，60 秒内复用成功，面板手动刷新跳过 TTL，并发合并。无后台轮询。登录进行中返回 409，不启动子进程。超时 30 秒。环境变更或面板登录使缓存失效；无法通过文件元数据观察登录环境的原生钥匙串只返回本次查询结果。跨环境或认证失效清空旧值。

```json
{"schema_version":1,"source":"official_cli","login_env":"匿名环境标识","cli_version":"1.5.17","capability":"supported","fetched_at":"2026-11-26T05:00:00+00:00","stale":false,"groups":[{"name":"额度组","models_shared":["模型显示名"],"buckets":[{"id":"pool-week","name":"周额度","window":"weekly","remaining_fraction":0.75,"reset_time":null}]}],"error":null}
```

同组模型共享 buckets，window 使用 CLI 原值。已知前缀解析不到模型时 models_shared=[]。UTC 重置时间为 null 时显示不适用。无绝对额度或套餐推算。capability 取 unknown/supported/unsupported；cli_version 未知为 null。错误采用同一快照（HTTP 200），error 为 {code,message} 固定脱敏说明。代码 AUTH、TIMEOUT、NOT_INSTALLED、UNSUPPORTED、QUOTA_FORMAT、QUOTA_FAILED、ENV_CHANGED。失败时同环境可保留上次成功数据，stale=true；TTL 已过同样 stale。首次未查询 stale=false。

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

上述指令在插件启用且宿主将消息分发给插件的私聊、群聊中使用。非管理员只收到固定拒绝提示。

## 变更记录

- 2026-11-26 生产根因调查返回后，setup/status 新增可空字符串 command_scope_warning。默认配置显式排除本插件时返回修复提示。会话单独绑定的配置仍需管理员核对。
- 2026-11-26 14:04 CST 收紧 read_file 能力范围至实测的 Linux，并在每次启动时核对实际 ACP agentInfo，以覆盖 wrapper 目标热替换。macOS 与 Windows 返回 unverified。
- 2026-11-26 14:13 CST 补充 /agy usage 聊天输出中的 28 天文本热力图。HTTP 统计字段和区间保持原契约。
- 2026-11-26 14:20 CST 按已注册路由的实测响应补记登录中 409 和原 setup/status 的停用状态码，便于前端处理迟到请求。
