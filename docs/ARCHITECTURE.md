# 架构

> 本文描述**当前**实现。界面为 **Web 单形态**：pywebview 窗口（系统 WebView2）
> 承载本地服务提供的页面；历史 PyQt6 原生界面已退役。
> 目标形态演进与阶段划分见 `ARCHITECTURE_DECISION.md` §0。

## 分层与依赖方向

```
┌──────────────────────────────────────────────────────┐
│ web/ (前端层)  run.py(pywebview 窗口)  server.py(HTTP) │
│                payloads.py(JSON 契约)                 │
│ web/static/    index.html / app.css / app.js / 图片     │
├──────────────────────────────────────────────────────┤
│ view_models(纯 PY)  app_context.py (装配根)            │
├──────────────────────────────────────────────────────┤
│ services: MonitorService(管线)  SessionTracker(统计)  │
│           PetRepository(状态聚合,订阅事件流)           │
├──────────────────────┬───────────────────────────────┤
│ domain/  应用语义层    │ protocol/  协议层(纯函数)      │
│ pets: 形状搜索提取     │ frames → crypto → records     │
│ identity: 账号归属     │ wire → schema → opcodes       │
│ static_data/display    │                               │
│ PacketEvent→业务对象  │                               │
├──────────────────────┴───────────────────────────────┤
│ repositories/  持久化边界（SQLite 底座 + 各域网关）      │
│ database(连接/迁移)  pet_store(write-behind)  settings │
├──────────────────────────────────────────────────────┤
│ capture/  接入层【可插拔】                              │
│ CaptureSource 协议: npcap_source 首版 / mitm 预留      │
├──────────────────────────────────────────────────────┤
│ recording/ (旁路: 录制 tee + 离线回放)                │
└──────────────────────────────────────────────────────┘
```

依赖单向：`ui → services → domain/repositories/protocol/capture`。`protocol` 与
`domain` 不依赖任何上层、零 IO 零线程，可被合成数据驱动（测试、回放均如此）。
`repositories` 只被 `services` 与组合根使用，不反向依赖 UI。

### 应用层管线（宠物仓库为例）

```
PacketEvent → MonitorService.add_packet_listener
  → domain.identity.extract_identity（self_info→avatar→base，标记当前 uid）
  → domain.pets.extract_pets（形状搜索 + 字段号取值：六维/技能/外观/物种键）
  → PetRepository（按 gid 合并,版本号递增；带 uid 时分流到 PetStore）
  → PetStore.put（仅并入待写表，零 IO）→ worker 线程批量 upsert → SQLite
  → PetViewModel.filtered_pets（多维筛选/排序）→ PetTableModel
  → PetCellDelegate 富绘制（系别/性格/六维条/天赋徽章）
  ← domain.static_data 提供物种/性格/技能中文名（base_conf_id 关联）
```

形状搜索不依赖 opcode→消息映射是否齐全：只要嵌套节点带宠物指纹字段
即可提取，抗 opcode 漂移；schema 缺失时字段为 wire 占位名、自然不命中。
命中后关键字段按**字段号**读取（六维=14、技能=12、身高=26、体重=27、
声音=93、物种键=15），schema 命名漂移不影响提取。

## 持久化（v2：宠物与账号）

**分层**：`repositories/database.py` 管连接与迁移（`PRAGMA user_version`，
追加式迁移可安全升级历史库；文件损坏自动备份重建，不阻断启动）；
`repositories/pet_store.py` 管宠物读写（适配器模式，调用方只见 `Pet` 对象）。

**为什么异步写**：抓包回调运行在 `MonitorService` 锁内，同步 IO 会阻塞
UI 的 `drain_events` 与后续帧处理——实测事件日志每条 `flush()` 在登录突发
下净增约 14ms、UI 轮询最长等待 57ms。因此 `put()` 只并入内存待写表，
落盘由独立 worker 按间隔批量执行（同一 `(uid,gid)` 自动合并，百只级突发
最终只产生一次 upsert）；`close()` 做最终 flush，退出不丢数据。
写库失败整批回滚回待写表留待下轮重试。

**身份归属**：宠物入库需要知道属于哪个账号，uid 来源是 `ZoneEnterSceneRsp`
(0x0152) 的 `self_info.avatar.base.logic_id`（实测 = 101384922，与外部工具
记录的账号一致，且先于宠物推送到达）。**必须严格走 self_info 路径**：
实测 `other_actors` 下的 NPC 也带 `logic_id`（如「护主犬」），误取会串数据。
身份未到时收到的宠物只入内存、不入库（不归错账号），界面仍可见。

**离线可读**：启动即 `load_last_account()` 载入最近账号的历史宠物，
未开始采集也能看到上次的数据；历史只补缺失 gid，不覆盖本次会话的新数据。

**v2 迁移**（六维与外观）：`pets` 表追加列——六维最终值 6 列（可排序/筛选）、
身高/体重/声音/变异/系别/突破/专精/球种 8 列、物种键 `base_conf_id` 1 列，
以及 `attributes_json` / `skills_json` 两列存明细（避免登录突发时写入放大：
百只级 × 数十字段若全部建列会让一次 upsert 膨胀到几十个绑定参数）。
迁移为追加式，v1 老库自动升级、历史数据保留（`test_persistence.py::test_v1_database_upgrades_to_v2`）。

**已知边界**：当前未持久化背包/图鉴等域，扩展方式是在 `_MIGRATIONS`
追加表 + 新增同构 Store。

## 接入层可插拔（应用层/协议层解绑点）

`capture/base.CaptureSource` 协议只约定三件事：`start()` / `stop()` / `is_running`，
并以回调 `on_chunk(StreamChunk)` 交付**按方向重组好的有序字节流**。

- **Npcap 旁听（已实现）**：scapy AsyncSniffer + BPF `tcp port 8195`；
  TCP 重组在接入层内完成（`TcpStreamReassembler`：seq 定基准、乱序 pending、
  全零短段暂缓与冲突回滚重收、早于基准段丢弃）。
- **MITM 代理（预留）**：实现同一协议即可整体替换。socket 直读天然有序，
  无需重组——这正是重组放在接入层而非协议层的原因。

替换点只在 `CaptureViewModel.start()` 的 source 构造，
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
队列过载丢新块并计数（`dropped_chunks`），保嗅探不阻塞。

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
- `pet.base_conf_id`（协议字段 15） → `species.json`，实测 105/107 命中，
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
       ├─ REST：/api/bootstrap（一次聚合）/api/pets /api/handbook
       │        /api/capture/*（启停/录制/密钥/网卡/安装）
       │        /api/events /api/state
       └─ WebSocket /ws：状态增量推送（每 0.5s，内容不变则不推）
  → spritelens/web/payloads.py 业务对象 → JSON 契约（唯一序列化点）
  → spritelens/app_context.py  装配根（管线/库/VM/自动采集）
```

**前端结构**（`web/static/`，零框架零构建）：

```
index.html   侧栏（5 页）+ 顶栏（角色/状态胶囊/启停）+ 各页面骨架
app.css      主题变量（teal 体系）+ 布局 + 卡片/图鉴/表格样式
app.js       导航、REST 调用、WebSocket 消费、各页渲染
pets/<id>.webp        精灵图（128×128，788/1015 有图，缺图回退首字头像）
type-icons/  系别图标雪碧图（来自 roco-helper 素材）
```

**页面**：概览（统计卡 + 系别分布条形图 + 账号/采集状态）、
宠物仓库（卡片视图为主 + 表格视图可切 + 筛选栏 + 详情面板 + 分页）、
精灵图鉴（物种目录 + 收集状态 + 筛选 + 立绘 + 蛋组/性别比/进化链）、
协议流（事件表 + 解码详情着色）、采集与设置（环境引导/启停/录制/密钥/会话表）。

**安全组合**（本地服务的必备项）：只绑 `127.0.0.1`；端口 `port=0`
由系统分配（避免固定端口被探测/占用）；每次启动随机 token
（`secrets.token_urlsafe`），经 URL fragment 交给前端（fragment 不进
服务端日志、不发 Referer），请求带 `X-Local-Token` 头，WebSocket 因浏览器
限制改用 `?token=` 查询参数；服务端 `compare_digest` 常量时间比较。

**静态资源禁用缓存**：本地加载代价可忽略，`Cache-Control: no-store` 避免
改前端后刷新不生效（实测 WebView2/浏览器缓存会命中旧 CSS）。

**服务运行方式**：aiohttp 跑在专属线程的独立事件循环（桌面壳占主线程），
业务层均为线程安全的同步代码，经 `asyncio.to_thread` 调用；停止时
`run_coroutine_threadsafe` 优雅收尾。

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
- chunk 投递线程：从队列取出 `StreamChunk` → `MonitorService.on_chunk`（锁内解密/解码）
- WebView2 主线程：pywebview 开窗；页面数据全部经本地服务
- 本地服务线程：aiohttp 事件循环，0.5s 推送状态；业务调用经 `asyncio.to_thread`
  回到同步世界，绝不跨线程回调
- 录制器与解析器共享一个 tee 入口（`CaptureViewModel._tee_chunk`），各自线程安全
