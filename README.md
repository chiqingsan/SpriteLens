# SpriteLens（小洛探探）

《洛克王国：世界》数据观测工具。采集游戏客户端与服务器之间的 TCP 8195 流量，
切帧、解密并解码为结构化事件，在桌面界面实时展示。

> 仅用于数据观察、研究与互操作性验证。工具只读旁听，不修改任何报文、
> 不读写游戏内存、不注入进程；是否使用由你自行评估风险。
>
> 本仓库由原 RocoPeek 项目迁移改名而来（原目录已保留作对照）；竞品解剖与架构调研
> 保留在 `docs/` 下（`DEVELOPMENT_GUIDE.md` 等已随 PyQt 退役同步更新，标注为
> 「历史文档」的评估报告保留原有结论作为决策依据）。

## 项目定位

对标蛋神助手（电脑版）的**纯本地功能**：自身不做云同步、账号体系、订阅付费与
交易市场。架构为「Python 引擎 + 本地服务 + Web UI」（pywebview + 系统 WebView2，
额外体积 ≈ 0）。**界面只有一套**：pywebview 窗口承载 Web 页面，
原生 PyQt 界面已退役（`requirements.txt` 不再含 PyQt6）。

详见 [docs/ARCHITECTURE_DECISION.md](docs/ARCHITECTURE_DECISION.md)。

## 功能

- 被动采集 8195 端口流量（Npcap 旁听，BPF 内核过滤）
- **打开即采集**：启动程序自动开始采集（采集页可关闭该开关）
- 自动捕获 0x1002 下发的会话密钥（支持 16 字节 ASCII / 32 位 hex 手动注入，重启续解）
- 实时事件流：opcode + schema 字段名解码，无 schema 时自动降级 wire 级字段号树
- **精灵图鉴**：1015 物种目录（图鉴号 / 蛋组 / 性别比 / 种族值 / 进化链），
  收集状态与筛选（全部 / 已收集 / 未收集），卡面带真实立绘（788/1015 有图）
- **蛋图鉴**：224 种精灵蛋目录（蛋组 / 孵化时长含 5/6/30 倍速换算 / 公母比环 /
  身高体重区间 / 进化链），按蛋组 / 蛋类型 / 孵化时长筛选（对标蛋神蛋图鉴）
- **蛋蛋仓库**：蛋仓快照协议帧（bagType==8 形状搜索）自动积累并持久化到 SQLite
  （重启不丢），蛋图标 / 数量徽章 / 孵化进度条 / 获得时间（对标蛋神蛋蛋仓库）
- **种公阵列**：性格 × 蛋组覆盖矩阵，行含性格修正说明，格子按性别标记展示
  宠物，点击直达精灵背包搜索（对标孵蛋管理器矩阵）
- **图鉴描述**：601 个物种的图鉴文本已并入静态表，详情面板直接展示
- **宠物仓库**：登录进入世界时服务器会主动推送全量宠物数据（无需打开盒子/面板），
  自动积累并持久化到本地 SQLite（重启不丢）
  - 卡片视图（默认，对标蛋神「点阵背包」）：真实立绘 / 性别底色 / 性格 / 系别徽章 /
    六维迷你条（含种族值参考线）/ 天赋阶 / 体型声音 / 图鉴号 / 首捕标记；支持分页
  - 表格视图：横向比对用的高密度表格（同一套筛选与排序）
  - 多维筛选：搜索、等级范围、性格多选、系别多选、天赋阶、只看首捕；按等级/天赋/六维总和等排序
  - 宠物详情面板：六维对照（实际值 vs 种族值）、性格修正、体型、技能列表
- **数据总览**：账号、宠物总量、首捕数、满级数、系别分布（条形图）一屏可见
- 原始流录制（jsonl）与离线回放，复现问题不依赖游戏在线
- 接入层可插拔：`CaptureSource` 协议预留 MITM 代理实现位（当前未实现）

**单实例运行**：重复启动不会开出第二个进程，而是把已有窗口唤到前台——
抓包与采集是独占资源，多开会导致两个进程互相干扰数据。

## 静态映射数据与资源

宠物物种（系别/种族值/进化链/图鉴号/蛋组）、性格、技能的中文名来自游戏静态表，
导入到 `data/static/`；精灵图与系别图标放在 `spritelens/web/static/`。
两个导入脚本：

```powershell
# 基础静态表（物种/性格/技能/系别）
.venv\Scripts\python.exe tools\import_static_data.py

# 图鉴元数据 + 精灵图 + 系别图标 + 系别克制表
.venv\Scripts\python.exe tools\import_assets.py
```

关联键为协议字段 `base_conf_id`（实测 105/107 命中）；名字仅作兜底，
协议直带的宠物名优先。

## 解码字段名（schema）

程序启动时加载 `data/schemas/`：内置最小集可直接使用；运行一次
`python tools/import_schema.py` 可导入完整解码库（3458 条消息定义 +
1600+ opcode 映射，来源为社区逆向数据，自动从 GitHub 下载或指定本地目录），
未收录字段自动降级 wire 级显示。

## 安装

1. **Npcap 抓包驱动（必需）**：程序启动时会自动检测，未安装时采集页顶部会出现
   引导横幅，点「一键安装 Npcap」即可（自动从 npcap.com 官方下载最新安装器并
   提权打开安装向导；向导中保持默认勾选 *Install Npcap in WinPcap API-compatible
   Mode*，装完点「重新检测」并重启小洛探探）。也可到 [npcap.com](https://npcap.com) 手动安装。
2. Python 3.12+（开发基线 3.12）
3. 安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 使用

双击 `start.bat` 即可启动界面（无控制台窗口）；或运行 `tools\create_shortcut.bat`
创建桌面快捷方式「小洛探探」。

命令行方式（调试用）：

```powershell
# 启动界面（pywebview 窗口 + 本地服务；等价于双击 start.bat）
.venv\Scripts\python.exe main.py

# 仅起本地服务并用系统浏览器打开（调试方便用 DevTools）
.venv\Scripts\python.exe main.py --web-browser

# 带控制台窗口启动，可直接看到错误输出
start_debug.bat

# 列出可用网卡
.venv\Scripts\python.exe main.py --list-ifaces

# 网络诊断：按会话统计 TCP 流量分布（排障用，游戏开着时运行）
.venv\Scripts\python.exe main.py --diagnose-net 20

# 离线回放录制文件
.venv\Scripts\python.exe main.py --replay data\recordings\capture_xxx.jsonl

# 组件自检（不打开窗口）
.venv\Scripts\python.exe main.py --smoke-test
```

### 本地服务与安全

界面内容由本机 HTTP 服务提供：只绑 `127.0.0.1`，端口由系统随机分配；
每次启动生成随机 token，经 URL fragment 交给页面（不进日志、不发 Referer），
API 与 WebSocket 均校验。数据只在本机流动，不对外发送。

### 留档与复盘

- 原始流录制：`data\recordings\`（勾选「自动录制原始流」，可 --replay 回放）
- 事件日志：`data\eventlog\eventlog_YYYYMMDD.jsonl`（每条消息含完整解码字段树，
  采集页状态行会显示当前文件名）

界面操作顺序：选择游戏实际使用的网卡（不确定就保持「默认路由网卡」）→ 默认「打开即采集」已自动开始（也可手动点「开始采集」）
→ 再进入游戏。若在游戏已登录后才开始采集，请退出到登录界面重新进入（会话密钥只在
连接建立时下发一次）。

**状态行怎么读**：`采集中 | 原始流 N 段 / M | 密钥 ✓ | 解密成功 …`

- 原始流一直是 0 → 抓包层没工作（网卡选错或 Npcap 问题）
- 原始流在涨但密钥「未获取」→ 连接建立早于采集启动，退回登录界面重新进入
- 密钥 ✓ 且解密成功在涨 → 正常工作，事件流页实时滚动

## 数据目录

运行时数据（配置 / 日志 / SQLite / 密钥 / 录制）默认写入
`%LOCALAPPDATA%\SpriteLens`，可用环境变量 `SPRITELENS_DATA_ROOT` 覆盖。

## 测试

```powershell
python tools\run_build_tests.py
```

协议层测试使用合成帧生成器（`tests/_synth.py`），全链路不依赖游戏客户端。

## 打包（Nuitka）

生成单文件 exe（含静态数据与图标，用户机无需装 Python）：

```powershell
# 首次先装打包依赖
.venv\Scripts\pip install -r requirements-build.txt

# 打包（首次会下载 MinGW 编译器，耗时较长）
.venv\Scripts\python.exe build.py
# 或双击 build.bat

# 只打印命令不编译
.venv\Scripts\python.exe build.py --dry-run
```

产物在 `build\SpriteLens_<版本>.exe`（约 22 MB）。打包选项（含带哪些资源、
排除哪些库）都在 `build_config.toml` 里改，不写死在脚本中。

> **杀毒软件会干扰打包**：Nuitka 后处理阶段用微软 `rc.exe` 写 exe 图标与
> 版本信息，产生 `build/RCX*.tmp`。部分杀软（实测火绒）会把该临时文件误报
> 为病毒并锁住它，导致打包以 `Failed to add resources` 失败。打包前把项目
> 目录加入杀软白名单，或临时关闭实时防护。产物可用 Windows Defender 独立
> 复检（本机对 0.1.0 产物零检出）。

用户数据仍写 `%LOCALAPPDATA%\SpriteLens`，与源码运行共用同一份；
exe 放在哪都不影响配置与历史数据。

## 文档

- [docs/README.md](docs/README.md) 文档索引（全部文档的阅读顺序与用途）
- [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) 开发规范
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 架构与协议说明
- [docs/ARCHITECTURE_DECISION.md](docs/ARCHITECTURE_DECISION.md) 架构决策（含 Tauri 评估与 Web 化路线）
- [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md) 代码地图
