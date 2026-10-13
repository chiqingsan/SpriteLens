# 架构

> 本文描述**当前**实现。界面为 **Web 单形态**：pywebview 窗口（系统 WebView2）
> 承载本地服务提供的页面；历史 PyQt6 原生界面已退役。
> 目标形态演进与阶段划分见 `ARCHITECTURE_DECISION.md` §0。

状态：当前架构说明。新的稳定性与模块化演进以 [ROADMAP](ROADMAP.md) 为准；
历史技术选型记录仍见 `ARCHITECTURE_DECISION.md`。当前已知缺陷及证据见
[初审](reviews/PROJECT_REVIEW_2026-10-12.md)、[改动复核](reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md)
与 [运行时修复复验](reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md)，
不要把设计约束解释为所有异常路径已验证。

2026-10-13 已落地 Vue 3 + TypeScript + Vite、蛋图鉴与宠物筛选/请求/三视图/箱位切片；其余职责仍为原生 JS，旧壳持唯一 WS。
工程/状态/发布方向见 [Vue 演进决策](VUE3_MIGRATION.md)，下文前端结构描述当前代码。

## 分层与依赖方向

```
┌─────────────────────────────────────────────────────────┐
│ web/ (前端层)  run.py(pywebview 窗口)  server.py(HTTP)  │
│                payloads.py(JSON 契约)                   │
│ web/static/    index.html / boot.js / app.css / app.js  │
│ web/static/    pets/*.webp · type-icons/（图片资源）    │
├─────────────────────────────────────────────────────────┤
│ view_models(纯 PY)  app_context.py (装配根)             │
├─────────────────────────────────────────────────────────┤
│ services: MonitorService(管线)  SessionTracker(统计)    │
│ 各域聚合(宠物/蛋仓/家园/花田)  EventLogWriter(事件日志) │
│ AccountTracker(账号切换判定)                            │
├──────────────────────┬──────────────────────────────────┤
│ domain/  应用语义层  │ protocol/  协议层(纯函数)        │
│ pets/eggs/egg_box    │ frames → crypto → records        │
│ identity/home/flowers│ wire → schema → opcodes          │
│ color_cards/display  │                                  │
│ pet_locations(箱位)  │                                  │
│ measurements/pet_marks                                  │
│ PacketEvent→业务对象 │                                  │
├──────────────────────┴──────────────────────────────────┤
│ repositories/  持久化边界（SQLite 底座 + 各域网关）     │
│ database(迁移/事务化)  pet_store/egg_store(write-behind)│
│ settings(JSON 配置)                                     │
├─────────────────────────────────────────────────────────┤
│ capture/  接入层【可插拔】                              │
│ CaptureSource 协议: npcap_source 首版 / mitm 预留       │
├─────────────────────────────────────────────────────────┤
│ recording/ (旁路: 录制 tee + 离线回放)                  │
└─────────────────────────────────────────────────────────┘
```

目标依赖方向：`web → view_models → services → domain/repositories/protocol/capture`。
协议算法与域提取规则可以被合成数据驱动（测试、回放均如此）；当前目录中的schema/opcode与静态目录加载含文件IO。
`repositories` 由 `services`、设置类ViewModel与组合根使用，不反向依赖 UI。

当前过渡边界：PacketEvent 已移入中立叶子模块 `spritelens/events.py`（2026-10-12），
domain 的5个事件提取模块改从该叶子导入，domain→services 反向依赖与包级豁免已移除；
CaptureService 已接管 source 创建、录制 tee、密钥与运行命令；CaptureViewModel 保留偏好、校验与安装/探测线程。
剩余过渡点包括资源 loader IO、VM 安装线程、routes mixin 对宿主状态的隐式依赖；
录制切换仍跨 VM/service 分步修改状态，完整串行语义待修复。新功能不得扩大这些例外。

### 当前状态与资源所有者

| 状态 / 资源 | 当前所有者 | 读取与限制 |
|---|---|---|
| 抓包源、录制器、手动密钥命令 | CaptureService；VM 提供页面命令与偏好 | 运行命令有锁，但录制意愿/持久化仍跨两层分步更新 |
| 协议会话、密钥接续、管线统计 | MonitorService / SessionTracker | monitor 锁保护管线；checkpoint 仍有同步 IO |
| 宠物、箱位、身份与域版本 | PetRepository | consistent_snapshot 一次取齐；PetView 覆盖列表/选项/概览/REST/WS，bootstrap 的宠物子载荷共享一次读取 |
| 蛋仓、槽位、家园、花田与域版本 | 各域 repository | 各域 consistent_snapshot 一次取齐；state 核对归属，失配计数保持未知；不保证跨域全局原子性 |
| SQLite 连接与最终清理 | AppContext 持有 Database，各 Store 使用连接 | AppContext.close 尝试清理每项；装配失败及外层入口仍有遗漏 |
| 页状态、请求序号与 DOM 绑定 | Vue 蛋图鉴与完整宠物页；其余主要在 app.js | 宠物请求由 usePets 管理，读取旧壳唯一账号上下文；原生其它页用 account-requests.js，宠物详情/扩展筛选/快捷条件由 Vue 管理 |

读取方不修改所有者私有字段；有界等待与资源实际退出分别判断。
下面描述的是当前链路，后续任务与验收统一在路线图。

### 应用层管线（宠物仓库为例）

```
PacketEvent → MonitorService.add_packet_listener
  → domain.identity.extract_identity（self_info→avatar→base，标记当前 uid）
  → domain.pets.extract_pets（形状搜索 + 字段号取值：六维/技能/外观/物种键）
  → PetRepository（按 gid 合并,版本号递增；带 uid 时分流到 PetStore）
  → PetStore.put（仅并入待写表，零 IO）→ worker 线程批量 upsert → SQLite
  → PetRepoSnapshot → 请求级 PetView（锁外筛选/排序/选项/统计；列表/概览/REST/WS；bootstrap 共享同一视图）
  → payloads.pets_payload（JSON 契约）→ 前端 app.js 渲染
    （点阵/卡片/表格三视图；系别/性格/六维条/天赋徽章）
  ← domain.static_data 提供物种/性格/技能中文名（base_conf_id 关联）
```

形状搜索不依赖 opcode→消息映射是否齐全：只要嵌套节点带宠物指纹字段
即可提取，抗 opcode 漂移；schema 缺失时字段为 wire 占位名、自然不命中。
命中后关键字段按**字段号**读取（六维=14、技能=12、身高=26、体重=27、
声音=93、物种键=15），schema 命名漂移不影响提取。

## 持久化（v8：宠物 / 蛋仓 / 账号 / 箱位 / 孵化槽）

**分层**：`repositories/database.py` 管连接与迁移（`PRAGMA user_version`，
追加式迁移可安全升级历史库；每个版本的多条 DDL 在单事务内执行、失败整体
回滚——不留「半迁移」状态；对历史半迁移库按「列已存在即跳过」自修复；
仅确认文件损坏时备份重建；备份失败保留原文件并报告失败）。各域网关同构（适配器模式，调用方只见
域对象）：宠物 `pet_store.py`、蛋仓 `egg_store.py`，均为 write-behind；
事件日志由 `services/event_logger.py` 有界队列 + worker 批量落盘。

**为什么异步写**：抓包回调运行在 `MonitorService` 锁内，同步 IO 会阻塞
UI 的 `drain_events` 与后续帧处理——实测事件日志每条 `flush()` 在登录突发
下净增约 14ms、UI 轮询最长等待 57ms。因此写路径统一「只入内存」：宠物/
蛋仓的 `put()` 只并入内存待写表，落盘由各自 worker 按间隔批量执行（同一
`(uid,gid)` 自动合并，百只级突发最终只产生一次 upsert）；事件日志走有界
队列 + worker 批量落盘（队列满丢新条并计数）。`close()` 做最终 flush，
正常退出尝试最终落盘。Store 批次换出、写入与失败回填由落盘锁串行化，旧批次不覆盖新值；
写库失败回填待写表留待重试。慢盘退出和最终 flush 失败尚没有“退出不丢数据”的保证。

**身份归属**：宠物入库需要知道属于哪个账号，uid 来源是 `ZoneEnterSceneRsp`
(0x0152) 的 `self_info.avatar.base.logic_id`（实测 = 101384922，与外部工具
记录的账号一致，且先于宠物推送到达）。**必须严格走 self_info 路径**：
实测 `other_actors` 下的 NPC 也带 `logic_id`（如「护主犬」），误取会串数据。
身份未到时收到的宠物只入内存、不入库（不归错账号），界面仍可见。

**账号切换隔离**：uid 变化（真切换）清空该域内存快照（宠物/蛋仓/孵化槽/
家园/花田）；同 uid 重复身份帧与「离线加载账号登录」不算切换——判定统一
走 `services/account_tracker.py`，避免历史数据误清或新账号数据串档。

**离线可读**：组合根从 accounts 表统一选择 display uid，再分别 `load_persisted(uid)` 和 `load_account(uid)`，
载入该账号的历史宠物与蛋仓；无该域缓存时显示空态，不借其它账号补齐。
未开始采集也能看到上次的数据；历史只补缺失 gid，不覆盖本次会话的新数据，
并恢复炫彩形态 id→名字的学习表（花田载荷不退化 `#id`）。
历史恢复在 IO 前后校验账号与版本；期间切号或数据更新则失败，不发布旧数据。
蛋仓条目与槽位分别标记 observed/historical/unknown，部分条目重观测为 mixed。
历史槽位不能确认当前在孵；缺失/坏槽记录为未知，明确空槽与未保存区分，数据库读错误向上传播。
各域 `complete=null` 表示全量完整性未确认；家园有待合并增量时 `source=stale`。
账号页提交同时校验代次、请求序号、uid 与对应域版本；离页/切号取消，取消无效仍拒绝旧响应。

**迁移历史**：v2 六维/外观列（六维最终值 6 列、身高/体重/声音/变异/系别/
突破/专精/球种 8 列、物种键 `base_conf_id`，明细存 `attributes_json` /
`skills_json` 两列——避免登录突发时写入放大：百只级 × 数十字段若全部建列
会让一次 upsert 膨胀到几十个绑定参数）；v3 `eggs` 表（蛋仓快照）；
v4 炫彩外观列（`colorful_conf_id` / `glass_type` / `glass_value`）；
v5 佩戴奖牌列 + `pet_locations` 表（箱位快照）；v6 试用个体标记
（`is_trial_pet`）；v7 好友镜像标记（`is_mirror_pet`，与 v6 一起用于
修正历史误收的非自有精灵）；v8 `egg_hatch_slots` 表（孵化槽快照，
slots 帧按 uid 落「槽中蛋 id」集合，恢复标记历史状态）。追加式迁移，
v1 老库自动逐级升级、历史数据保留
（`test_persistence.py::test_v1_database_upgrades_to_v2`）。

**箱位快照（v2 JSON）**：`domain/pet_locations.py` 的 `Backpack.record()`
落 `pet_locations.snapshot_json`：完整 30 格箱表（`gid=0` 空格 / `None`
未采集，语义必须区分）+ 3 队 × 6 格出战队伍 + 当前队伍。`restore()` 兼容
上一版「已知 gid 位置列表」并标记 `historical=True`（界面提示「登录后更新」）。
箱位更新是增量语义：`PetBoxPetChange` 按槽位覆盖，跨箱/跨队移动先移除旧槽。

**会话接续**：`capture/key_store.py` 的 `session.json`（v1）保存
`flow_id + key + identity + server_sequence`，由 `MonitorService` 在 SYN/ACK
时失效旧关联；仅当同一 flow、密钥一致且服务端序号连续时才以服务端帧确认
接续（防伪造）；详见 `docs/SESSION_RESUME_VERIFICATION.md`。

## 接入层可插拔（应用层/协议层解绑点）

`capture/base.CaptureSource` 协议只约定三件事：`start()` / `stop()` / `is_running`，
并以回调 `on_chunk(StreamChunk)` 交付**按方向重组好的有序字节流**。

- **Npcap 旁听（已实现）**：scapy AsyncSniffer + BPF `tcp port 8195`；
  TCP 重组在接入层内完成（`TcpStreamReassembler`：seq 定基准、乱序 pending、
  全零短段暂缓与冲突回滚重收、早于基准段丢弃；交付历史只保留最近
  `MAX_HISTORY_BYTES`=256KB 供重传比对）。流关闭（FIN/RST）与空闲超时
  （30min）都会释放重组器，并经同一队列**保序**向协议层投递关闭事件——
  残余数据先于会话释放处理，嗅探线程不等待协议层锁。
- **MITM 代理（预留）**：实现同一协议即可整体替换。socket 直读天然有序，
  无需重组——这正是重组放在接入层而非协议层的原因。

替换点在 `CaptureService.start()` 的 source 构造，
`MonitorService` 及其上全部复用。注意：MITM 属于写入型能力（可注入/改包），
风险等级与被动旁听不同，接入前须重新评估。

## 协议栈（实测结论）

```
TCP 8195
 └─ GCP 帧: 21B 大端头(magic 0x3366 / command / flag / seq / hdr_len / body_len)
            ├─ 0x1002 ACK: HEAD.extend[2:18] 明文下发 16B AES-128 会话密钥
            ├─ 0x1001 SYN: 扩展含 20 位账号标识
            ├─ 0x2001/0x2002 认证对: 固定 IV 可解；含登录 token 与区服号
            ├─ 0x6002 BINGO / 0x9001 心跳
            └─ 0x4013 DATA: AES-128-CBC，两种实测加密变体（按内容自适应）：
                            ├─ 固定 IV = bytes(range(16))，整 body 为密文（c2s 主流）
                            └─ 自带 IV：body 前 16B 为本次加密 IV，其余为密文（s2c 主流）
                            ├─ 明文尾部 tsf4g trailer（6~22B，"tsf4g"标记+长度字节）
                            ├─ 32B 结构头（c2s 实测，判据 [12:16]==00000001）:
                            │    [0:4]=counter1(=gcp seq) [4:6]=0x55aa
                            │    [22:24]=opcode  [28:32]=counter2(连接内递增)
                            │    payload 从 32 起
                            ├─ s2c 26B 结构头（实测）：opcode@[18:20]、55aa@[20:22]、payload 从 26 起
                            └─ 短头（s2c 实测）：opcode@[2:4] [4:6]=0x55aa 锚点 payload 从 10 起
```

解密无跨包状态：握有密钥即可从流中段续解——这是「密钥持久化 + 手动注入」
设计（`KeyStore` / `set_preset_key`）的依据。

**数据下发模型（实测）**：宠物/背包等全量业务数据由服务器在**登录进世界时
主动推送**（0x1346 ZoneGetPetInfoByPageRsp 多页连续帧，单会话约 96KB/百只规模），
无需打开任何面板；0x1345 分页请求已废弃。首推紧跟在认证序列之后。

**抓包突发保护**：登录推送会在秒级内涌入数百 KB。嗅探回调只做分类与重组
（微秒级），chunk 经有界队列（`CHUNK_QUEUE_MAX`）交给独立工作线程投递；
若在嗅探线程内同步解密解码，libpcap 内核缓冲会溢出导致整批丢包。
队列过载丢新块并计数（`dropped_chunks`），保嗅探不阻塞。流关闭事件
（FIN/RST/空闲淘汰）同样经该队列保序投递（`FlowClosed`）：**先处理残余
数据、再释放协议层会话**——否则密钥被提前清掉，残余 DATA 会丢解。

## 解码双路

`schema.py`：opcode → 消息名映射命中时按 `data/schemas/messages/*.json`
渲染字段名；未命中或字段缺失自动降级 `wire.py` 的字段号树（`field_N`）。
schema 为外挂数据文件，游戏版本更新只换文件不改代码。

**合并策略是字段级而非消息级**（实测教训）：多文件对同一消息做定义时，
后加载的只覆盖它显式列出的字段号。早期手写文件整体替换同名消息，导致
`PetBriefInfo` 从 38 字段缩到 11 字段、六维/身高体重全部退化成 `field_N`。

**形状搜索的字段号兜底**：`domain/pets.py` 的关键字段一律按字段号（`no`）
取值而非字段名——schema 命名会随导入来源漂移，字段号与 raw 值稳定。

## 静态映射数据（data/static/）

协议只有数字 ID；物种/性格/系别/技能的中文名与数值来自游戏静态表，
由 `tools/import_static_data.py` 从解包数据转制（来源与生成时间记录在
`_meta.json`）。

**关键关联键（实测确立，勿用错）**：
- `pet.base_conf_id`（协议字段 15） → `species.json`（1060 物种），
  且名字与协议直带一致；
- 反例：`pet.conf_id`（字段 2）是实例级 ID，用它查物种表会得到错误物种
  （conf_id=2000671 实为「波波拉」，旧索引却指向「水蓝蓝」）——有回归测试
  `test_static_data.py::test_species_index_is_not_conf_id` 锁死这条约束。

命中率可经 `StaticData.stats()` 观测；名字字段仅作兜底（协议直带优先），
系别/种族值/技能名等版本稳定字段直接使用。

## 前端层（Web 单形态）

与竞品（蛋神助手）同型的形态：单进程，pywebview 用系统 WebView2 开窗，
内容由本地 aiohttp 服务提供。历史 PyQt 原生界面已退役，`requirements.txt`
不再含 PyQt6（见 `ARCHITECTURE_DECISION.md` §0.6）。

```
入口（spritelens/main.py；无参即启动界面）
  → spritelens/web/run.py    pywebview 窗口（系统 WebView2，额外体积 ≈ 0）
  → spritelens/web/server.py LocalServer：aiohttp，仅 127.0.0.1 + 随机端口
       ├─ 静态资源 /static/*（HTML/CSS/原生 JS/精灵图，无框架无构建）
       ├─ REST：/api/bootstrap（一次聚合）/api/pets /api/handbook /api/eggs
       │        /api/egg-box /api/home /api/flowers /api/colors /api/male-matrix
       │        /api/ui/preferences（主题/显示偏好，与其余接口同为 token 鉴权）
       │        /api/capture/*（启停/录制/密钥/网卡/安装）
       │        /api/events /api/state
       └─ WebSocket /ws：状态增量推送（每 0.5s，内容不变则不推）
  → web/payloads.py + payloads_catalog.py 按功能域转换 JSON
    capture/state JSON 当前仍在 routes_capture mixin 中
  → spritelens/app_context.py  装配根（管线/库/VM/自动采集）
```

**前端结构**（`frontend/` + `web/static/` 渐进迁移，构建说明见 [前端开发](FRONTEND_DEVELOPMENT.md)）：

```
index.html   侧栏（14 页，分组导航）+ 顶栏（角色/状态胶囊/启停）+ 各页面骨架
app.css      design token 体系（间距/字号/圆角/阴影/表面分层）+ 布局 + 组件样式
themes.css   三套浅色主题（喵喵/火花/水蓝蓝）的色值覆盖，data-theme 切换
app.js       导航、REST 调用、WebSocket 消费、尚未迁出的各页状态/渲染
vue/              专用生成目录（暂存校验后发布，不清空其它静态资源）
frontend/src/pages/EggDexPage.vue 蛋图鉴页面（独占子树、局部状态、取消与代次校验）
frontend/src/components/PetBasicFilters.vue 宠物基础筛选（独占根与两个 Teleport 子树；原生脚本不写这些控件）
frontend/src/petFilterBridge.ts mount/查询/恢复/清理接口；基础与扩展状态分别在 usePetFilters/usePetAdvancedFilters
frontend/src/composables/usePets.ts 请求/缓存/加载错误/三视图/分页/箱队/选择；不另建 WS 或账号版本权威
frontend/src/components/PetInventory.vue 及 Cards/Table/Slots/BoxNavigation 子组件，独占列表和导航；petInventoryBridge 连接账号、偏好与应用壳
appearance.js      主题/显示字段/图片模式偏好（GET/POST /api/ui/preferences）
pet-presentation.js 其它原生页资源渲染；Vue 宠物页使用 PetAvatar/PetMarks 模板，不注入旧 HTML
frontend/src/components/PetAdvancedFilters.vue 蛋组、绝对范围与位置筛选
frontend/src/components/PetDetailPanel.vue + PetDetail.vue 详情、键盘与焦点
frontend/src/components/PetShortcuts.vue + PetFilterSummary.vue 快捷条件（≤6 组）与已应用条件标签
icons.js     本地 SVG sprite 图标装饰（Tabler MIT，零运行时网络）
pet-media/<id>-<variant>.webp  官方头像/立绘（原图 + 透明边界归一派生图）
pets/<id>.webp        精灵图（128×128 兜底，缺图回退首字头像）
type-icons/  系别图标雪碧图（来自 roco-helper 素材）
```

**三主题**：颜色变量在 `themes.css` 按 `:root[data-theme]` 覆盖，布局变量仍在
`app.css`；`appearance.js` 只切根属性与显示类，不重建数据。偏好经
`ui_preferences.py` 白名单校验后原子写 config.json，非法提交 400、非法本地
配置降级为默认（`docs/UI_GUIDE.md` §主题）。

**页面**（侧栏分组：仓库与图鉴 / 孵蛋工具 / 家园信息 / 炫彩 / 系统）：
概览（统计卡 + 系别分布条形图 + 账号/采集状态）、精灵背包（点阵/卡片/表格
三视图 + 筛选栏 + 详情面板 + 分页）、精灵图鉴（物种目录 + 收集状态 + 立绘 +
蛋组/性别比/进化链）、蛋图鉴（蛋目录 + 蛋组/类型/孵化时长筛选）、蛋蛋仓库
（蛋仓快照 + 孵化进度 + 数量徽章）、种公阵列（性格×蛋组矩阵）、种公母库、
我的家园（居民/家具/产蛋窝）、炫彩色卡（底色×混色矩阵）、炫彩花种（自己的花 +
好友花田）、协议流（事件表 + 解码详情着色）、采集与设置（环境引导/启停/录制/
密钥/会话表）、智能配窝与产线收集（占位页，待协议帧与长期积累）。

**安全组合**（本地服务的必备项）：只绑 `127.0.0.1`；端口 `port=0`
由系统分配（避免固定端口被探测/占用）；每次启动随机 token
（`secrets.token_urlsafe`），经 URL fragment 交给前端（fragment 不进
服务端日志、不发 Referer），请求带 `X-Local-Token` 头，WebSocket 因浏览器
限制改用 `?token=` 查询参数；服务端 `compare_digest` 常量时间比较。

**静态资源禁用缓存**：本地加载代价可忽略，`Cache-Control: no-store` 避免
改前端后刷新不生效（实测 WebView2/浏览器缓存会命中旧 CSS）。

**服务运行方式**：aiohttp 跑在专属线程的独立事件循环（桌面壳占主线程），
阻塞命令经 `asyncio.to_thread` 调用，部分同步快照/载荷仍在事件循环中构造；停止时
`run_coroutine_threadsafe` 优雅收尾。
CaptureService 的运行副作用已有命令锁，Store flush 批次已串行化；录制意愿/偏好/立即启停仍未形成完整命令顺序。
PetView 已让列表选项、bootstrap、概览与 WS 的宠物字段使用对应单次快照；
display_uid 表示已加载/实时数据归属，identity 与 cached_identity 继续区分。
state 顶层 uid 属于宠物快照；蛋仓/家园/花田的单域及跨域归属一致性仍待 F02。
不能把线程池调用本身当作线程安全保证，或把局部快照推广成所有接口保证。

## 单实例控制

单实例的理由：抓包引擎与采集会话是独占资源，多开会两个进程同时抓同一网卡、
写同一份 SQLite 与事件日志，数据互相干扰。实现在 `system/single_instance.py`：

- **唯一性**：`CreateMutexW` 命名互斥锁（`SpriteLens.SingleInstance.Mutex`），
  返回 `ERROR_ALREADY_EXISTS` 即判定已有实例；
- **唤醒**：已有实例创建命名事件（`SpriteLens.SingleInstance.Activate`）并由
  守护线程每 250ms 轮询消费（WebView2 主循环不感知 Win32 事件）；
  重复启动的进程 `SetEvent` 后静默退出（返回码 0，不是报错）；
- **前台**：`SetForegroundWindow` 在 Windows 前台锁下可能被忽略（实测窗口
  不置顶），因此被唤醒时按进程 ID 枚举找到自己的窗口，再调 Win32
  `ShowWindow(SW_RESTORE)` + `SetForegroundWindow` + `BringWindowToTop` 三重兜底。

检查位置在 `run_web()` 的**最开头**——必须在数据库/抓包/事件日志初始化之前，
否则第二个进程已经把库打开了才判断，等于没拦住。非 Windows 平台整体降级
为不做限制（不影响开发与测试）。

## 线程模型

- scapy 嗅探线程：`_handle_packet` 只做分类 + 重组 + 入队（见「抓包突发保护」）
- chunk 投递线程：从队列取出 `StreamChunk` / 流关闭事件 → `MonitorService.on_chunk`
  / `close_session`（锁内解密/解码；关闭事件与数据同队列保序）
- 事件日志 worker：从有界队列批量 JSONL 落盘（文件句柄由其独占）
- WebView2 主线程：pywebview 开窗；页面数据全部经本地服务
- 本地服务线程：aiohttp 事件循环，0.5s 推送状态；业务调用经 `asyncio.to_thread`
  回到同步世界，绝不跨线程回调
- 录制器与解析器共享 tee 入口（`CaptureService._tee_chunk`）；append 仍同步写盘，慢盘影响待测

## 当前健壮性债务与演进入口

R01–R08 已有修复及回归：坏库备份保护、Store 批次顺序、启动失败 worker 回滚与满队列通知、
坏行隔离、统一离线 uid、v8 孵化槽持久化、schema 实例递归与请求级宠物筛选。
R09 已落实 Database 所有权与 AppContext 内部容错关闭，但装配失败回滚、外层清理和 HTTP 校验未闭环；
采集服务抽取后录制切换产生一致性回归。队列通知/join 有界也不代表整个 source/Store 停止有界。

下一阶段保护三项边界：资源由组合根明确持有并按逆序释放；业务返回单一uid/version快照；页面和请求状态按功能隔离。
`app.js`、`server.py`、`payloads_catalog.py` 是优先控制职责增长的位置；原始流录制与checkpoint的同步IO需要实际慢盘验证。
资源流水线先明确来源、版本、临时输出验证和发布清单，再处理体积，保留当前兜底资源与可追溯原图。
