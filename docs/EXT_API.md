# 对外数据接口（ext API）

状态：已实现（API v2；路由仍为 `/api/ext/v1/*`），待真实游戏流量与打包桌面验收。读者：维护者、本机外部集成方（meow toolkit 等）。

v2 新增事件级 `battle` 投影：服务器下发的 `0x1316`、`0x131A`、`0x132C` 分别输出 `{"id":"<battle_id>","phase":"entered|round|ended"}`。只在对应 decoded 字段含有效整数编号时输出，ID 以字符串传输避免精度损失。投影在 decoded 容量裁剪前提取，因此 `decoded_omitted:true` 时仍可读取；超过整包大小上限被丢弃的事件仍不会输出。没有投影表示未知，不能从包名补造编号或结果。`round` 仅作为唤醒证据，不保证客户端可输入；`ended` 不代表已回世界或捕获成功。下面历史 v1 示例的 api 字段应按实际返回值 2 读取。
定位：把被动旁听得来的协议事实（原始解码事件）以只读方式提供给本机其它程序；不替代现有 Web UI 接口，不含像素/OCR 数据。

## 边界与原则

- 只读：不提供写游戏 / 改配置 / 触发抓包以外任何控制能力；唯一写操作是 `/api/capture/*` 之外的既有 UI 接口。
- 数据源是协议包：字段与 `eventlog/*.jsonl` 的 `decoded` 同源，都是协议解包结果，不是游戏状态真值；需要字节级原文时直接读事件日志。
- 与 UI 接口隔离：同一 aiohttp 服务、各自独立 token；ext 接口故障（慢客户端、超限包）不阻塞采集管线（`ExtEventHub.submit()` 只做过滤/入队）。
- 默认开启：桌面模式与 `--background` 模式随服务启动；不需要外部接口时用配置关闭。

## 启用与关闭

配置项 `ext_api.enabled`（布尔，默认 `true`），位于数据目录 `config.json` 顶层：

```json
{ "ext_api.enabled": false }
```

- 关闭后：`/api/ext/v1/*` 全部返回 403 `{"error":"external api disabled"}`，且不写发现文件。
- 修改后需重启应用生效（配置在 LocalServer 构造时读取一次）。

## 生命周期

- 与 Web UI 服务同生共死：随机回环端口（`0`，系统分配）、每次启动随机 token；窗口/后台服务停止时一并关闭并删除发现文件。
- 不提供 server-only CLI：没有 UI 进程就没有 ext API。需要长期常驻时用 `--background`（见 README）并让托盘保持运行。
- 绑定地址固定 `127.0.0.1`，非本机不可访问；不要用端口转发把该接口暴露到局域网/公网。

## 发现文件

启动成功后原子写入数据目录（默认 `%LOCALAPPDATA%\SpriteLens\ext-runtime.json`，可用 `SPRITELENS_DATA_ROOT` 覆盖）：

```json
{
  "app": "SpriteLens",
  "version": "1.1.0",
  "api": 1,
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 51234,
  "base": "http://127.0.0.1:51234",
  "token": "<ext token>",
  "endpoints": {
    "state": "/api/ext/v1/state",
    "events": "/api/ext/v1/events",
    "stream": "/api/ext/v1/stream"
  },
  "opcodes_default": ["0x0133", "..."],
  "started_at": 1793866543.5
}
```

- 写入方式 `tmp → replace`，读取方遇到坏 JSON 或缺失文件应视为「服务未运行」并重试。
- 停止时校验文件内 `token` 与当前 ext token 一致才删除，避免误删其它实例（单实例 mutex 之外的保险）。
- token 不写日志、不放进 URL fragment；发现文件权限依赖用户数据目录 ACL，不要复制、提交或上传。

## 鉴权

- 独立 ext token（`secrets.token_urlsafe(32)`），与 UI token 互不通用：
  - `X-Local-Token: <ext token>` 或查询参数 `?token=<ext token>` 访问 `/api/ext/*`；
  - 用 UI token 访问 ext 接口 → 401；用 ext token 访问 `/api/*`、`/ws` → 401。
- WebSocket 受浏览器限制无法带自定义头，统一用 `?token=`；服务端 `secrets.compare_digest` 比较，失败 401 `{"error":"unauthorized"}`。
- 每个进程启动都会换 token；客户端应每次从发现文件读取，不要缓存跨进程 token。

## 端点契约（API v1）

### `GET /api/ext/v1/ping`

```json
{
  "ok": true, "api": 1, "app": "SpriteLens", "display_name": "小洛探探",
  "version": "1.1.0", "server_time": 1793866543.5,
  "endpoints": {"state": "...", "events": "...", "stream": "..."},
  "opcodes_default": ["0x0133", "..."]
}
```

### `GET /api/ext/v1/state`

`capture` 为现有 `/api/state` 中抓包域快照（采集状态/会话/计数/错误），`ext` 为接口自身统计：

```json
{
  "api": 1, "app": "SpriteLens", "version": "1.1.0", "server_time": 1793866543.5,
  "capture": {"running": true, "iface": "...", "sessions": [{"session_id": "...", "uid": 123}], "...": "..."},
  "ext": {"ring": 200, "ring_max": 200, "subscribers": 1, "seq": 40213, "dropped_oversize": 0, "dropped_queue": 0}
}
```

排障时看 `ext.dropped_*`：持续增长说明客户端消费过慢或订阅了洪峰 opcode（见「容量与上限」）。

2026-11-07：`state` 增加可选 `navigation`，用于 Meow 等客户端晚连接时恢复当前场景交互 NPC。仅采集中且存在唯一可解密连接时返回该连接的内存快照，否则为 `null`。字段为 `uid`（字符串）、`session`、`seq`（快照截点）、`position_seq`（最近位置事件序号）、`scene_id`、`scene_generation`（最近一次场景重建的事件序号，用于识别同地图重新进入）、`position`、`in_battle`、`source: observed_partial` 和 `actors`。每个 actor 只包含字符串 `actor_id`、`config_id`、`creator_id`、`position` 及 `options: [{id, enabled}]`；不含精灵详情。场景聚合由 `domain/navigation_scene.py` 维护，hub 在锁内按事件顺序更新，读接口在后台复制与编码；保留最多 16 个连接、每连接最多 4096 个交互实体，超限移除对应快照。关闭 hub 清空，不从磁盘恢复。

2026-11-08：快照增加 `self_actor_id`（字符串或 `null`），actor 增加 `creator_id`（字符串或 `null`）。`self_actor_id` 是本连接自身 avatar 的 `actor_id`，`creator_id` 是实体创建者的 avatar `actor_id`（取自 `npc_base.create_avatar_id`，`0` 或无字段时为 `null`）。

2026-11-09 修订：`self_actor_id` 由 `0x0152` 进场响应（`self_info`，field 11）与 `0x015C` 传送通知（`self_info`，field 21）共同提供，任一到达即可用。奇遇归属判据改为 `creator_id`：它与游戏界面「拥有者 XXX」（同节点 `create_avatar_name`）同源，而 `ActorInfo_Base.owner_id` 实测恒为当前账号自身，不能用于判归属。因此消费方规则是「`creator_id` 非空且不等于 `self_actor_id`」即别人拥有；自身身份未知时，可用快照新增的 `player_actor_ids`（场景里可见的其他玩家 avatar 的 `actor_id` 列表）兜底——`creator_id` 命中该集合即为别人的奇遇。任一判据都拿不到时不能下结论，应保持原有接纳行为。`0x0152`/`0x015C` 都是大包，ext 通道常把它们标为 `decoded_omitted`，但 `ExtEventHub` 在校验前已交给 `NavigationScene`，快照仍可用。

2026-11-10：快照增加 `heading`（整数或 `null`），主控朝向，单位 0.1°，0° 指向 +x、顺时针为正，取自 `0x0133` 移动请求的 `to_rot.z`（`ctrl_rot.z` 作为兜底，实测两者一致）；与同包 `position` 同一坐标系，客户端可直接用它旋转自己的箭头。只有位置有效的移动请求才会更新，站立不动时保持最后一次移动方向；`0x0102`、`0x0152`、`0x015C` 重建场景后清空，战斗中不更新。旧版本没有该字段时按 `null` 处理，不要臆造方向。

快照在场景切换、移除及已确认入战时更新，不受 200 条事件回看覆盖；大 AOI 包先提取精简坐标再裁剪原始事件。它只表示当前采集观察到的部分场景，未采集到的实体不能补造，也不能把停止采集期间的旧点位当作当前完整场景。客户端必须校验 uid/session、按 seq 拒绝迟到快照，随后继续应用更晚的实时事件。旧版本没有此字段时，客户端只能等待新的实体事件，不能仅用历史战斗事件补启动。

### `GET /api/ext/v1/events?since=&limit=&opcodes=`

环形回看（只保留默认 opcode 集，200 条）。

- `since`：浮动秒级时间戳（Unix epoch，同事件 `ts`），只返回 `ts > since`；缺省不过滤。
- `limit`：1–200，缺省 200。
- `opcodes`：逗号/空格分隔，`0x1316` 或十进制均可；缺省=默认订阅集；`all`=不过滤；非法 → 400。

```json
{
  "api": 1, "server_time": 1793866543.5, "count": 1,
  "events": [{
    "seq": 40213, "ts": 1793866521.239, "session": "192.168.3.71:63757",
    "direction": "s2c", "opcode": "0x131A", "name": "BattleRoundStartNotify",
    "payload_len": 11962, "account_uid": 134509467,
    "decoded": [{"no": 1, "name": "state_info", "type": "BattleStateInfo", "value": "<5 字段>"}]
  }]
}
```

事件记录 schema 与事件日志单行一致，另加进程内递增 `seq`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seq` | int | 进程内单调递增，从 1 开始；WS 断线重连去重/补齐用 |
| `ts` | float | 收包时间（Unix epoch 秒，毫秒级小数） |
| `session` | str | 抓包会话 `ip:port` |
| `direction` | str | `c2s` / `s2c` |
| `opcode` | str | 4 位十六进制，如 `0x131A` |
| `name` | str | 事件名（来自 `data/schemas`） |
| `payload_len` | int | 原始载荷字节数 |
| `account_uid` | int | 账号 uid（未识别时为 0） |
| `decoded` | list | 解码字段树；超尺寸时为 `[]` 并带 `decoded_omitted: true`（大包如 `0x015C` decoded 可到 MB 级） |

### `WS /api/ext/v1/stream?opcodes=&uid=`

- `opcodes` 语义同 `/events`；`uid` 缺省 0=不过滤，非 0 时只推该账号事件。
- 连接后先收 `hello`：

```json
{"type": "hello", "api": 1, "app": "SpriteLens", "version": "1.1.0", "opcodes": ["0x1316", "..."], "uid": 0, "server_time": 1793866543.5}
```

- 之后批量推送 `{"type":"events","data":[<事件记录>...]}`：单批最多 64 条、单条消息最多 512 KiB；超限时丢弃该批的 `decoded` 只保元数据（`decoded_omitted`）。
- 无事件 5 秒发一次 `{"type":"heartbeat","ts":...}` 保活；`ping/pong` 由 aiohttp 心跳兜底。
- 发送超时 0.1 秒即断开该连接（慢客户端不影响采集与其它连接）；断开后请重新读发现文件重连并用 `seq`/`since` 补齐。

## 默认 opcode 白名单

默认订阅集见 `spritelens/web/ext_api.py` 的 `DEFAULT_EXT_OPCODES`，按用途分组：

- 战斗：`0x1316` 进入战斗、`0x131A` 回合开始（`battle_id`/`round`/`battle_start_time`）、`0x1324` 表现开始（技能 `skill_cast`、伤害 `damage_info`、buff、`pet_sync_info`）、`0x132C` 战斗结束（`seen_monster_id`/`battle_conf_type`/`real_pve`/`pet_info`）、`0x132D`/`0x13F3`/`0x13F4`、`0x1305` 加载完成、`0x130B`/`0x130C` 指令回撤、`0x1313`/`0x1314` 回合流程、`0x1322` 指令同步、`0x1339` 退出战斗。
- 捕获/丢球：`0x0200`/`0x0201`/`0x0202`/`0x0203` 开始/结束丢球、`0x1982`/`0x1983` 捕获结束（含 `is_catch_success`/`shake_times`/`glass_info`/`is_quick_catch`）。
- 场景/移动：`0x0133` 移动请求、`0x0152`、`0x015C`/`0x015D`/`0x015E` 传送、`0x0413`/`0x0414` 场景 act 通知。
- 访客/奖励/星灵/图鉴：`0x02E3`/`0x02E6`、`0x0243`、`0x15E0`、`0x01DF`、`0x0220`、`0x039D`、`0x1492`/`0x1493`、`0x159D`。

需要其它 opcode 时在客户端用 `?opcodes=` 显式指定即可，无需改服务端。

## 容量与上限（实测约 17 事件/秒，含登录突发）

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `RING_MAX_EVENTS` | 200 | REST 回看环形上限（默认集合） |
| `RING_MAX_FULL_PAYLOAD` | 8192 字节 | 超过则环形里只留元数据 |
| `EXT_MAX_PAYLOAD` | 256 KiB | 超过整包丢弃并计入 `dropped_oversize` |
| `EXT_MAX_BATCH_BYTES` | 512 KiB | 单条 WS 消息上限，超限丢 `decoded` |
| `SUB_QUEUE_MAX` | 1024 | 每连接积压上限，满则存入 `dropped_queue` |
| `STREAM_BATCH_MAX` | 64 | 单批事件数 |
| `STREAM_HEARTBEAT_SECONDS` | 5.0 | 空闲心跳间隔 |

`0x0414`（场景 act）实测占全部事件约 83%（约 14 事件/秒）。外部集成方若不关心附近实体逐帧变化，建议订阅时排除它或单独节流；否则 WS 带宽/客户端 CPU 会被它主导。

## 安全红线

- `keys/latest.key`、`keys/session.json` 是游戏解密密钥：绝不经 ext API、日志、发现文件或错误信息外泄；接口只暴露解码后的字段树，不暴露原始载荷字节及密钥。
- 事件含 `uid`/`name`/`uin` 等账号与好友信息：外部程序应按最小化原则只取需要的字段，不得二次上传或跨用户共享。
- 发现文件里的 token 等同于本机读写 UI 的凭据：不要提交进仓库、不要打印到公开日志；调试截图前先确认不含 token。

## meow toolkit 接入清单（本次不合并 meow 代码）

目标：用协议事实替换/补充 meow 现有的像素推断，降低误判与响应延迟（实测同一场战斗，meow 日志比协议流晚 0.3–3.1 秒）。

1. 客户端形态：meow 无 asyncio/websockets，建议独立守护线程（`requests` 或标准库 `urllib`）：先读 `ext-runtime.json` → `GET /events?since=seq&opcodes=<子集>` 增量轮询（1 秒级足够），需要低延迟时再评估 WS（QtWebSockets 或 `websocket-client`）。不要在 Qt 主线程或判据内发网络请求。
2. 快照与判据：后台线程把事件归并成「战斗/捕获/场景」快照（加锁），判据只读快照；候选替换点：`AutomationEngine.is_enter_combat()`（engine.py:1293）、`is_capture_available()`（engine.py:2143）、`_observe_bloodline(session)`（engine.py:3066）、`_wait_for_capture_result(ball_name)`（engine.py:2856）、`is_it_in_normal_condition()`（engine.py:1378）、`manual_tasks.py:133 _is_mining_assist_context_ready()`。不建议替换 `ScreenRecognitionService.match`（像素识别仍是场景/UI 兜底）。
3. 生命周期与降级：在 `engine.start()` 之前初始化（`ui/app.py:354` 附近），启动失败/发现文件缺失/连续 N 次请求失败 → 记录一次告警并整体回退到现有视觉判据，不得阻塞启动；恢复后按 `seq` 补齐，缺失则重新拉 `/events`。
4. 去重与时钟：以 `seq` 单调递增去重（auto-fighting 与 bloodline-observer 双线程观测同一事件时只处理一次）；`ts` 是收包墙钟，跨进程比较前先与本地时钟对齐（RTT/2 修正），不要直接混用 meow 日志的秒级时间。
5. 数据映射：战斗进入 `0x1316`；回合/`battle_id` `0x131A`；技能/伤害/聚能 `0x1324`（`perform_info.type` 1=技能、3=buff、4=伤害，`skill_cast.skill_id`、`damage_info`、`pet_sync_info.energy_result`）；结算 `0x132C`；丢球/捕获 `0x0200`–`0x0203`、`0x1982`/`0x1983`；场景/传送 `0x0133`、`0x015C`–`0x015E`；访客 `0x02E6`；奖励 `0x0243`；星灵 `0x15E0`。
6. 协议没有「血脉」字段（血脉只存在于战斗表现与 OCR 文本中）：血脉判定继续用 meow 的视觉/OCR，不要用协议事件替代。

## 实现位置

- `spritelens/web/ext_api.py`：`ExtEventHub`（环形缓冲 + 订阅队列 + 统计）、`ExtRoutesMixin`（4 个端点与编码/上限）、默认 opcode 白名单。
- `spritelens/web/server.py`：独立 ext token、鉴权中间件分支、发现文件读写、`monitor.add_packet_listener` 挂载/解绑。
- `spritelens/services/monitor_service.py`：新增 `remove_packet_listener`（停止/启动失败时解绑）。
- `spritelens/web/run.py`、`spritelens/web/background_run.py`：传入 `ext_runtime_path`。
- `tests/test_ext_api.py`：hub 过滤/上限、REST/WS 契约、双 token 隔离、发现文件与禁用分支。

## 未覆盖与后续

- 未做语义聚合层（battle/capture 对象、回合与伤害归并、事件重放）；目前只提供原始事件，语义由消费方自建。
- 未做限速/配额/多客户端审计；慢客户端只靠有界队列与发送超时保护。
- 未在真实游戏流量 + 打包 exe（Nuitka/WebView2）下验收；真实吞吐与长期运行内存待验证。
- 未开放 CORS：仅供本机原生程序调用；浏览器页面跨源访问需另行评审。

## 维护约定

- 新增对外字段/端点属协议变更：必须 bump `API_VERSION`，同步更新本文件与 `tests/test_ext_api.py`。
- 调整默认 opcode 集时同步本文件「默认 opcode 白名单」，并在实测中确认不会放大洪峰。
- 文档用 LF、不写本机绝对路径；新增文档需在 `docs/README.md` 索引登记。
