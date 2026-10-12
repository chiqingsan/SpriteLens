# 架构决策：是否照搬蛋神助手重构，以及更优方案

> 新决策（2026-10-13）：已确认前端演进为 Vue 3 + TypeScript + Vite，保留 Python/aiohttp/pywebview。
> 下文“原生 JS / 无构建链”是历史选择；当前迁移边界见 [VUE3_MIGRATION](VUE3_MIGRATION.md)，任务状态见路线图。

> 阅读边界（2026-10-12）：本文保留技术选型与迁移过程，旧阶段表、测试数量、体积与性能数字均为当时快照。
> 当前实现见 [ARCHITECTURE](ARCHITECTURE.md)，新一轮健壮性与模块化演进见 [ROADMAP](ROADMAP.md)，
> 当前实测基线与风险见 [项目审查](reviews/PROJECT_REVIEW_2026-10-12.md)。Nuitka已经落地、PyQt已退役，
> 当前CLI没有`--web`参数；本地启动token实际经URL fragment传递。历史段落不作为新增开发指引。

> 历史（RocoPeek 时期）：命题是"是否照搬蛋神助手重构"，当时结论为 **不照搬**（见 §1–§7）。
> 该分析的前提是"项目定位为协议观测工具、不做商业功能"。
>
> **迁移后更新（SpriteLens 立项）**：项目已迁至 SpriteLens（小洛探探），定位改为
> 「对标蛋神助手、只做本地功能」，因此新增 **§0 阶段决策**：采用竞品的架构形态
> （pywebview + 系统 WebView2 + 本地 HTTP 服务 + 原生 JS 前端），UI 全量 Web 化；
> 但**不照搬**其云账号/订阅/交易市场等商业模块。§1–§7 保留为过程分析。

---

## 0. SpriteLens 阶段决策

### 0.1 定位

- 产品名：**SpriteLens**（中文名：**小洛探探**）
- 对标：蛋神助手电脑版 v1.1.6——实测技术栈为 Python 3.12 + PyInstaller +
  pywebview（系统 WebView2）+ aiohttp 本地服务 + 无框架 JS 前端，单进程，45 MB 单文件
- 功能范围：**只做本地功能**；不做云同步、账号体系、订阅付费、交易市场/换蛋广场
- UI 风格：配色与布局对标蛋神助手（左侧栏导航 + 顶栏状态条 + 分栏工作区）

### 0.2 Tauri 评估（结论：用不上）

| 方式 | 判断 | 理由 |
|---|---|---|
| ① 全 Rust 重写 | ❌ | 协议/采集/域层约 3,900 行 + 175 个已对真机数据验证的测试要重写为 Rust；本机无 Rust 工具链；管线余量 600×，换语言零收益 |
| ② Tauri 壳 + Python 侧车 | ❌ | 在 Python 全部体积之外再加 Rust 运行时，体积反而更大（预计 60 MB+ vs pywebview 30–45 MB）；两套构建管线 + sidecar IPC 复杂度；渲染同为系统 WebView2，用户可见零差别 |
| ③ Tauri + PyO3 内嵌 CPython | ❌ | 构建/分发最复杂，收益为零 |

Tauri 的前提是"整个应用可用 Rust/Web 重写、追求极小单二进制"。本项目核心资产是
Python 协议引擎，且体积大头是静态数据（与框架无关），目标平台仅 Windows。
**承载形态定为 pywebview + 系统 WebView2（额外体积 ≈ 0）**，即竞品已验证的路径。

### 0.3 目标架构（阶段 B）

```
单进程 Python:
  pywebview 窗口（系统 WebView2）
      ↓ 加载 http://127.0.0.1:<随机端口>/?token=...
  本地 HTTP 服务（aiohttp；仅回环 + 启动 token + compare_digest）
      ├── REST + WebSocket：宠物 / 事件 / 统计 / 设置
      └── 复用现有业务层（protocol / capture / domain / services / repositories 原样保留）
  抓包（Npcap）→ 帧解析 → 解密 → schema 解码 → SQLite
前端：HTML/CSS/原生 JS（无框架、无构建链）
```

本地服务安全组合（引入时必做）：随机端口 + 每次启动随机 token + 常量时间比较 + 仅 127.0.0.1。

### 0.4 阶段划分

| 阶段 | 内容 | 状态 |
|---|---|---|
| **A. 迁移与改名** | 仓库迁至 SpriteLens；全量改名（包名/APP_NAME/数据目录/互斥名/日志/DB/文档）；PyQt6 界面保持可用；175 测试全绿 | ✅ 已完成 |
| **B1. 本地服务骨架** | aiohttp 服务（仅回环 + 随机端口 + 启动 token + `compare_digest`）+ pywebview 窗口（系统 WebView2）+ Web 前端（侧栏 + 顶栏状态条 + 宠物仓库/概览/协议流/采集四页）+ 共享装配根 `app_context.py` | ✅ 已完成 |
| **B2. 与 PyQt 版能力对等** | 概览页补齐（协议事件卡 / 当前账号 / 采集状态三栏）、系别分布条形图（真系别色）、清空快照（二次确认）、RSC 一键禁用、安装进度条、解码详情着色 | ✅ 已完成 |
| **B3. 功能扩展** | 对标蛋神本地功能。**精灵图鉴已落地**（1015 物种目录 + 收集状态 + 系别/收集筛选 + 卡片分页 + 物种详情/进化链）；顺带修正静态数据 `evolutions` 语义错误（原误取系别标记，实为物种 ID）。**打开即采集**：启动即自动开始（配置项 `capture.autostart`，默认开，可在采集页关闭）；UI 文案统一「监听」→「采集」。**宠物仓库卡片视图**：对标蛋神「点阵背包」（紧凑卡片 + 性别底色 + 六维迷你条 + 天赋徽章 + 分页），保留表格视图供横向比对；详情栏默认收起给网格让宽，选中后三栏展开 | 🔄 进行中 |
| **B4. PyQt 退役 + 资源导入**（提前执行） | **仅保留 Web 界面**：`spritelens/ui/` 全量删除、`view_models` 移出 ui 包、显示常量下沉到 `domain/display.py`；`main.py` 无参即启动界面（`--web` 兼容保留）；**PyQt6 依赖移除并已实测卸载后全绿**。**静态资源导入**（`tools/import_assets.py`）：精灵图 788/1015 张（128px WebP，7.2MB，缺图回退首字头像）、系别图标雪碧图、图鉴元数据合并进 species.json（601 物种：图鉴号/蛋组/性别比/体型区间/闪光标记）、系别克制表 | ✅ 已完成 |
| B3 后续 | 孵蛋推断 / 筛选矩阵 / 对战 HUD / 战报复盘（见 `FEATURE_MODULES.md`：M3/M4/M5/M6） | 待启动 |
| B4 收尾 | 打包（PyInstaller + 静态数据按需） | 待启动 |

B3 起每页沿用 §5.3 的量化判据（冷启动 ≤1.5 s、常驻内存 ≤250 MB、主程序打包 ≤60 MB、
单页 ≤3 人日），不达标即停。

### 0.6 PyQt 退役与资源导入（2026-10-10）

**为什么现在就退役**：Web 界面已具备旧界的全部能力（概览/宠物/协议流/采集），
且用户明确要求只保留新版。留着两套 UI 的代价是双份维护与体积，
而不是"多一个选择"——旧版没有唯一功能。执行内容：

| 项 | 处理 |
|---|---|
| `spritelens/ui/`（4,988 行 PyQt 代码） | **删除**；`view_models/` 上移到 `spritelens/view_models/`（本就零 Qt 依赖） |
| 显示常量（系别色/六维标签/天赋色） | 下沉到 `domain/display.py`（框架无关，任何前端复用） |
| `requirements.txt` | 移除 PyQt6；**已实测卸载 PyQt6 后全量测试通过**（真正的解耦验证） |
| 入口 | `main.py` 无参即启动界面；`--web` 保留为兼容别名 |
| 测试/工具 | 删 `test_ui_pages.py` 与 PyQt 截图/离屏工具；测试 202 → 189 项（净减 13，全部为 UI 专属） |

**静态资源导入**（`tools/import_assets.py`，来源均为本机解包/公开静态镜像）：
精灵图 788/1015（128×128 WebP，7.2MB，缺图自动回退首字头像）、
系别图标雪碧图、图鉴元数据（601 物种：图鉴号/蛋组/性别比/体型区间/闪光）、
系别克制表（18×18）。技能图标覆盖率仅 42/1378（不同 id 空间），**未导入**。

### 0.5 与 §1–§7（旧结论）的差异

| 事项 | 旧结论 | 新决策 | 变化原因 |
|---|---|---|---|
| 是否照搬竞品形态 | 不照搬；PyQt 壳 + Web 数据页混合渐进 | **采用竞品形态**（pywebview 单进程），UI 全量 Web 化 | 项目定位变更为"对标蛋神的本地数据工具"，功能表达力需求确立 |
| PyQt 角色 | 永久保留系统页 | 迁移期对照，B4 退役 | 同上；且竞品以 pywebview 单进程方案已被验证 |
| 云功能 | 不做 | 不做（保持） | 无变化 |
| 体积/性能论证 | 不该作为换栈理由 | 仍然成立（换栈理由是功能表达力） | 无变化 |

---

## 1. 结论速览

| 命题 | 判断 | 依据 |
|---|---|---|
| 照搬蛋神助手架构重构 | ❌ 不建议 | 规模差 5 倍，且竞品自身有已证实的迁移负债（§2） |
| "为了性能"重构 | ❌ 不成立 | 管线余量 600×：42,002 帧/s vs 实际 5~50 条/s（`TECH_EVALUATION.md` §1） |
| "为了体积"换 UI 框架 | ⚠️ 排最后 | 裁 Qt（−41.3 MB）、去 scapy（−16 MB）更划算且零重写（§4） |
| 迁移的**正确**理由 | ✅ 功能表达力 | M5 战报 / M4 对战 HUD / M2 筛选矩阵，PyQt 实现成本高（§5） |
| 推荐形态 | 混合渐进切片 | PyQt 壳保留系统页 + pywebview 承载数据页；先做垂直切片验证（§5） |
| 承载形态修正 | **pywebview（非 QWebEngineView）** | 见 §3，这是本次评估最大的收获 |

---

## 2. 不照搬的四条理由

### 2.1 规模不匹配（5 倍差距）

| | 蛋神助手 v1.1.6 | spritelens（当前） |
|---|---|---|
| 业务代码 | ~4.3 万行 / 1.07 MB pyc（按字节估算） | 8,880 行（实测） |
| 前端 | 8 MB / ~40 个 JS 文件 | 无 |
| 静态资源 | 26 MB | 0.4 MB `data/static` + 0.9 MB schema |
| 功能域 | 宠物/蛋/家园/繁育/交易市场/订阅/云账号 | 宠物仓库（单一业务域） |
| 复杂度来源 | 云账号体系 + 订阅付费 + 交易市场 | 无 |

它的复杂度有相当一部分是为**商业化和社交**服务的（`api.danking.cn` 云同步、
`/api/subscription/*` 订阅、`/api/market/*` 交易）。这些我们不做，
照搬等于为不存在的需求付架构成本。

### 2.2 竞品自身有已证实的迁移负债

它有 Tkinter→Web 的完整迁移史，但**没迁干净**（`DANSHEN_ASSISTANT_ANALYSIS.md` §5.1）：

```
web_runtime.py（Web 入口）
  └── from app import (..., CollectorApp, ...)   ← 只为复用几个静态方法
       └── app.py
             ├── 模块级无条件 import tkinter
             ├── 模块级无条件 import desktop_ui
             └── class CollectorApp(tk.Tk): ...   ← 12,685 行 Tkinter 旧 UI
```

后果：12,685 行死代码 + `_tkinter.pyd` + tcl/tk 数据（实测 5.6 MB）随包分发，
Web 版启动仍会初始化 Tkinter 模块。**这是缺失"架构测试"的代价**——
没有测试阻止新入口反向依赖旧 UI（补齐方案见 §6 第 5 项）。

### 2.3 我们的地基比它干净

`COMPETITOR_ANALYSIS.md` 已有评语："协议层我们更强，架构我们更干净"。本次复核确认：

- 单向分层 `ui → services → domain/repositories → capture/protocol`；业务层 Qt 零依赖
  （全仓 grep，仅 `main.py:4` 一处注释提及 PyQt6）
- `protocol/` 纯函数零 IO 零线程，可被合成数据驱动（测试与回放均如此）
- `CaptureSource` 三方法协议，MITM 预留
- **175 项测试全绿**（`unittest`，2026-10-10 本次实测）

唯一偏差：`domain/identity.py:18`、`domain/pets.py:16` 反向 import
`services.monitor_service.PacketEvent`（纯 dataclass，无行为耦合）。
建议下沉到独立 types 模块——§6 的架构测试会把它变成红灯。

### 2.4 当初的迁移理由已经失效

既有文档把迁移动机归为"三大短板"：① 无持久化 ② 无静态数据 ③ 宠物页无全字段展示。
**这三项现已全部补齐**（SQLite v2 + `data/static` + 高密度宠物表，175 测试锁定）。
现在做迁移，理由必须重新论证——见 §5。

---

## 3. 关键修正：承载形态选错了（本次最大收获）

既有推荐方案 B 写的是 `QWebEngineView`（`STACK_EVALUATION.md` §3、
`TECH_EVALUATION.md` §4.2），但**从未量化它的体积代价**。本次实测：

| 承载形态 | 内核来源 | 额外体积 | 说明 |
|---|---|---|---|
| `QWebEngineView` | **自带完整 Chromium** | **+132.4 MB**（wheel 实测） | `PyQt6-WebEngine-Qt6` win_amd64 wheel = 132,370,879 B |
| **pywebview + WebView2** | 复用系统 WebView2 | **≈ 0** | 本机已装 154.0.4258.62（Win10/11 预装）；另需 pythonnet（数 MB 级） |
| 现状（纯 PyQt6 原生） | — | 0 | `.venv` 248 MB，其中 PyQt6 目录 214 MB（本次实测） |

换算参考（估算口径）：`PyQt6-Qt6` wheel 78 MB → 安装后 214 MB，膨胀比 ~2.7×；
据此 QWebEngineView 安装后约 **250–350 MB**（**估算**，未实测）。
即使打包裁剪，其增量也在 **100 MB 量级**（估算）——量级上向 Electron 靠拢。

**结论**：方案 B 若用 QWebEngineView 承载，等于在我们的体积账上再加一个
"Chromium"。**要 Web 化，选 pywebview。**

旁证：蛋神助手（45 MB 单文件，含 26 MB 静态资源）选了 pywebview 路线，且**用的是系统 WebView2 后端**——
其解包产物 `webview_guard.py` 内直接引用 pywebview 的 `edgechromium` 渲染器名，并有
`Microsoft.Web.WebView2.Core` / `GetAvailableBrowserVersionString` 的运行时探测代码。
45 MB 的包体也装不下"26 MB 静态资源 + 自带 Chromium"。
（参考：`DANSHEN_ASSISTANT_ANALYSIS.md` §1.1、§10）

---

## 4. 体积账：换 UI 框架是最不划算的一项

### 4.1 可削减项对照

| 优化项 | 削减量 | 方式 | 成本 |
|---|---|---|---|
| ① Qt 未用模块 | **−41.3 MB** | 打包时排除（opengl32sw 19.7 / avcodec 13.4 / Qt6Quick+Qml 11.4 / Designer 5.0 / Pdf 4.4 等） | 1–2 天，零重写 |
| ② scapy | **−16 MB** | ctypes 直调 `wpcap.dll`（学竞品；只保留用到的抓包/网卡子集） | 中，需重测抓包路径 |
| ③ 静态数据 | 视规模 | 引入全量社区数据（26 MB）时按需裁剪/下载 | 低，后置 |
| ④ 换 UI 框架 | ≈0 ~ −10 MB（估算） | PyQt6 裁剪后 ~30–35 MB 与 pywebview 形态大致持平 | **4,250 行 UI 重写** |

### 4.2 正确顺序

```
① 裁剪 Qt 未用模块（−41.3 MB，零重写）      ← 收益最大、成本最低
② 去 scapy 改 ctypes 直调 wpcap（−16 MB）   ← 顺带省掉 scapy 的导入开销
③ 静态数据按需化（引入全量数据时再做）
④ 换 UI 框架                                 ← 只有①②③做完且功能需要时才做
```

**体积不是 UI 框架问题**：将来体积主因是静态数据与玩家 SQLite 数据（与框架无关）。
PyQt6 裁剪+打包后约 30–35 MB（`TAURI_SIZE_EVALUATION.md` §4），
与 pywebview 形态的差距在同一量级——**不值 4,250 行重写**。

---

## 5. 更优方案：混合渐进切片

### 5.1 形态

```
阶段 1 原型（独立进程，完全不侵入现有 PyQt 程序）:
    pywebview 窗口  ← 系统 WebView2（额外体积 ≈ 0）
        ↓ HTTP（127.0.0.1 随机端口 + 启动 token）
    本地服务（只读现有 SQLite / 回放数据）

最终形态（若阶段 1 判据达标再设计）:
    PyQt6 壳（永久保留：采集控制 / 事件流 / 诊断 / 单实例）
  + pywebview 数据页（宠物 / 战报 / 筛选矩阵 / 地图）
  + 共享同一套 services / repositories（同进程或 sidecar，阶段 2 定）
```

保留 PyQt 的理由（沿用 `TECH_EVALUATION.md` §4.2）：桌面工具的核心价值是
双击即用、无浏览器、无端口管理；低频交互页（采集控制/诊断）留在 Qt 更省事。

### 5.2 三阶段

| 阶段 | 内容 | 门槛 |
|---|---|---|
| **1. 垂直切片（3–5 天，先验证不承诺迁移）** | pywebview + 本地服务，**只做「宠物表」一页**（筛选+排序+详情）；PyQt 主程序不动，双壳并行对照 | 四判据达标（§5.3） |
| 2. 迁移高价值页 | 战报（M5，图表/时间轴）、筛选矩阵（M2）、对战 HUD（M4） | 每页独立评估 |
| 3. 按需扩展 | 其余数据页；系统页永久留 PyQt | 单页验收 |

### 5.3 垂直切片的量化判据（建议阈值，切片前先测现状基线）

| 指标 | 阈值（达标才继续） | 测法 |
|---|---|---|
| 冷启动 | 双击→宠物页可交互 **≤ 1.5 s**（相对 PyQt 版增量 ≤ 400 ms） | 秒表 5 次取中位 |
| 常驻内存 | 空载+打开宠物页 **≤ 250 MB**（增量 ≤ 120 MB） | 任务管理器 / psutil 汇总进程树 |
| 打包体积 | 双壳形态主程序 **≤ 60 MB**（全量迁移后目标 ≤ 40 MB） | PyInstaller onedir + Qt 裁剪 |
| 功能开发工时 | 宠物表一页 **≤ 3 人日**（对照 PyQt 版 624+518 行） | 实做计时 |

**这四个数字是决策闸门**：先测基线、再做切片、对比后定去留。
切片的价值在于把"要不要大重构"从赌博变成有数据支撑的决策——
不达标就停，沉没成本仅 3–5 天。

### 5.4 若真要全量迁移：成本清单（实测行数）

| 类别 | 规模 | 说明 |
|---|---|---|
| 必须重写/丢弃 | **~4,250 行** | pages 1,362 / widgets 845 / styles 592 / pet_table 518 / app.py 446 / themes 305 / common 182 |
| 其中最难移植 | `pet_table.py` ~300 行手绘 | 六维条+种族值参考线+徽章（`PetCellDelegate`） |
| 会直接作废 | `widgets.py` ~260 行 | `FrostedBackdrop`/`TitleBar` 无边框壳（pywebview 用原生边框） |
| 连带重写 | `test_ui_pages.py` 253 行 | 控件属性名是文档化契约（`pet_page.py:8-9`） |
| 小改可留 | `view_models/` 约 700 行 | Qt 无关；`capture_vm` 例外（直接 new `NpcapCaptureSource`，需上移） |
| **完全不动** | **~3,892 行** | 全部非 UI 代码：protocol/capture/domain/services/repositories 等 |

---

## 6. 无条件工程前置（与是否迁移无关，都该做）

推进状态见末尾「处理记录」列；已完成项保留原始判据作为决策依据。

| # | 项 | 现状证据 | 为什么 | 处理记录 |
|---|---|---|---|---|
| 1 | `paths.py` frozen 适配 | `project_root()` 假定源码树（`paths.py:64-76`），无 `sys._MEIPASS` 分支 | **PyInstaller 打包必炸**；任何打包动作的前置 | ✅ 已适配（2026-10-10）：覆盖 `_MEIPASS` / Nuitka-frozen / 源码态三分支，`tests/test_paths.py` 锁死 |
| 2 | DPI 感知 | 全项目 `Dpi/HighDpi` 零命中 | 高分屏渲染只靠 Qt6 默认兜底，无显式声明 | ⛔ 已失效：PyQt 退役后渲染全在 WebView2，pywebview 自带 DPI 处理，应用层无需声明 |
| 3 | `excepthook` + 启动日志 | 无 `sys.excepthook`/`faulthandler`/`startup-error.log` | `start.bat` 用 pythonw，未捕获异常**静默消失** | ✅ 已实现（2026-10-10）：`logs/spritelens.crash.log` + 启动致命失败弹对话框，`tests/test_crash_log.py` 覆盖 |
| 4 | `setWindowIcon` | `app.ico` 只被标题栏 logo 用（`widgets.py:705`） | 任务栏图标未设置 | ✅ 已实现（2026-10-10）：`tools/make_icon.py` 生成多尺寸 `resources/app.ico`，接 `webview.start(icon=...)` 与 favicon |
| 5 | 架构测试 | 文档承诺"业务层无 Qt"但只有手工命令（`TECH_EVALUATION.md` 列为待办） | 竞品的 import 图污染正是缺此测试；建议仿 innovationb1ue `test_architecture.py`，同时把 §2.3 的反向 import 变红灯 | ✅ 已实现（2026-10-10）：`tests/test_architecture.py`，约束改为「业务层无 Web 依赖 + 无反向分层 + protocol 纯函数」 |
| 6 | 本地服务安全组合 | 尚无 HTTP 服务 | 一旦引入：随机端口 + 每次启动随机 token + `compare_digest` + 仅 127.0.0.1（约 30 行） | ✅ 已实现（B1 阶段） |

打包仍剩的实质工作：PyInstaller/Nuitka spec（含 `data/` 与 `resources/` 附带清单）、
体积与冷启动实测（§5.3 判据）。

---

## 7. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| `TECH_EVALUATION.md` | **强化**：性能结论（600× 余量）、两热点、推荐方向不变。**修正**：§4.2 承载形态 `QWebEngineView` → pywebview（§3） |
| `STACK_EVALUATION.md` | **强化**：B≫C>A>D 排序、不该换 Python 协议层。**修正**：方案 B 承载形态（文首已加指针）；"测试基线 110 项"已过期（实际 175 项） |
| `TAURI_SIZE_EVALUATION.md` | **强化**："体积大头是静态数据不是框架"；**补入** QWebEngineView 132.4 MB 新数据点 |
| `DANSHEN_ASSISTANT_ANALYSIS.md` | **强化**：本文件是其启示⑫"UI 迁移路径已验证"的决策化落地 |
| `FEATURE_MODULES.md` | **强化**：M5/M4/M2 是迁移的唯一正当理由 |
| `COMPETITOR_ANALYSIS.md` | **强化**："架构我们更干净"的判断被本次复核确认 |

### 本文件的边界

这是一份**决策记录**，不是排期。执行与否、何时执行，由 §5.3 的垂直切片判据决定。
在此之前，优先级最高的是 §6 的工程前置——成本低、收益确定、不依赖任何架构选择。

---

## 8. 打包（Nuitka，2026-10-11 落地）

**为什么 Nuitka 而非 PyInstaller**：与姊妹项目 meow toolkit 同款工具链，构建
配置可复用；Nuitka 编译为 C 后启动更快、内存更省。代价是首次构建需下载
MinGW 编译器，且单次打包约 20 分钟（增量构建快得多）。

**产物**：`build/SpriteLens_0.1.0.exe`，单文件 **22.3 MB**
（源码态 12MB 是静态数据 + 精灵图 7.2MB，编译后运行时约 15MB）。

**构建入口**：`build.bat` / `build.py`（配置驱动，选项在 `build_config.toml`）：

```powershell
.venv\Scripts\pip install -r requirements-build.txt   # 一次性
.venv\Scripts\python.exe build.py                     # 打包
.venv\Scripts\python.exe build.py --dry-run           # 只看命令
```

**打包踩坑记录**（都是实测，改配置前务必先读）：

| 现象 | 原因 | 处理 |
|---|---|---|
| `Conflict between user and plugin decision for module 'webview.platforms.android'` | Nuitka 4.x 内置 `pywebview` 插件且**强制启用**，自行决定只收 Windows 平台分支；手动 `--enable-plugin=pywebview` 或 `--include-package=webview` 都会与之冲突 | 两者都不加，交给插件自动处理 |
| exe 里网卡枚举失败：`Module 'scapy.as_resolvers' was actively excluded` | 曾把 `scapy.as_resolvers` 当无用模块排除，实际它在 `scapy.arch.windows` 的调用链上（scapy 动态 import 多，静态排除极易误伤） | **不要排除 scapy 任何子模块** |
| **exe 能通过 smoke 却启动即崩**：`ValueError: '...\spritelens\web\static' does not exist` | 只把 `data/`、`resources/` 加进 `include_data_dirs`，漏了**包内资源** `spritelens/web/static/`（前端 HTML/CSS/JS/精灵图）。Nuitka 只编译 `.py`，非 Python 文件必须显式附带。而 `--smoke-test`/`--replay` 等非 GUI 路径不加载前端，测不出来 | 把 `spritelens/web/static` 加入 `include_data_dirs`；**并把静态资源检查并入 `--smoke-test`**（缺目录/缺文件直接返回非 0），`tests/test_smoke_assets.py` 锁死 |
| `Failed to add resources to file ...exe`（重试 5 次后失败） | **杀毒软件实时扫描锁住 Nuitka 后处理写入的临时文件**；本机火绒会报 `build/RCX*.tmp` 为病毒。`RCX*.tmp` 是微软 `rc.exe` 资源编译器的标准临时文件，用于给 exe 写入图标与版本信息——属**误报** | 打包前给项目目录加杀软白名单；或临时关闭实时防护。成品可用 `Start-MpScan` 独立复检：本机 Defender 对产物零检出 |

**打包后必须验的三件事**（按顺序，缺一不可）：

1. `SpriteLens_x.y.z.exe --smoke-test` → 应含前端静态目录/静态表/schema 三项 ✓
2. `--list-ifaces` → 应枚举出网卡（scapy 链路完好）
3. **实际启动 GUI**：看窗口是否出现、侧栏各页是否渲染（前两条都过不了这个坑）

**产物指纹**（0.1.0，供比对）：26.4 MB，
SHA256 见 `build/SpriteLens_0.1.0.exe` 现状（每次构建会变）。

### §8.1 启动体验（2026-10-11）

用户实测反馈三个问题，根因与修复：

| 现象 | 根因（实测数据） | 修复 |
|---|---|---|
| 启动弹黑色控制台窗口 | 窗口子系统的 GUI 进程调 `subprocess` 会给子进程分配新控制台——启动路径上的 RSC 检测每次启动都跑一次 PowerShell（实测 1.8s，黑窗一闪 1.8s） | `environment.py::_no_window_kwargs`：所有子进程调用带 `STARTUPINFO(SW_HIDE)` + `CREATE_NO_WINDOW` |
| 启动慢（双击后 ~4.4s 才见窗口） | RSC 检测同步阻塞在装配路径（占 1.8s）；onefile 每次解包 ~2.2s 是硬底 | `check_npcap(quick=True)` 毫秒级先拿 installed 结论（autostart 不等探测），RSC 结果由后台探测线程异步补齐，经 WS 推送刷新横幅 |
| 窗口出现后先白屏再出内容 | WebView2 渲染前的空窗默认白色，与前端深青启动遮罩（`#074f5d→#053b48`）形成割裂 | `create_window(background_color=SPLASH_BG)`，空窗与遮罩同色，视觉无缝 |

测试基线变化：构造 `CaptureViewModel` 不再同步跑 PowerShell——测试套件
20s → 4.3s；`probe_environment=False` 可关闭后台探测（测试注入用），
`environment_probe` 参数可注入假探针。

**尚未做**：主程序体积/冷启动的正式实测（§5.3 判据：≤60MB / ≤1.5s）——
26.4MB 已满足体积判据，冷启动待正式计时（§5.3 的 1.5s 不含 onefile 解包，
如需达标可改 standalone 目录分发）。
