# 开发规范

继承姊妹项目 meow toolkit 的工程约定，新项目从第一行代码就按此执行。
（原 PyQt 原生界面已于 2026-10 退役，本文件已同步改为 Web 单形态约定。）

状态：当前维护入口。读者：开发者与 AI 协作者。本文维护开发约束；待实施改造与验收统一见
[ROADMAP](ROADMAP.md)，审查证据见 [2026-10-12 项目审查](reviews/PROJECT_REVIEW_2026-10-12.md)。

## 通用

- 所有文件读写显式 UTF-8；注释用中文，写「为什么」而不是复述代码
- 全量类型注解；文件头 `from __future__ import annotations`
- 按文末测试取舍验证；日常只检查本次改变的行为，不自动运行全套
- 不要随意回退或覆盖工作区里不是本次修改产生的变更
- 新功能优先沿用现有分层边界（见下），不新造平行结构

## 文件规模红线

以下规则适用于 Python 与 JavaScript。单文件超限时，先问"这段代码能否放进 service / repository / view_model / 页面 /
独立工具模块"，而不是顺手继续塞：

- 超过 500 行：新增代码前必须先判断拆分去向
- 超过 800 行：默认禁止新增非局部修复代码（bugfix 除外），新功能必须拆到新模块
- 超过 1200 行：高风险文件，只接受小范围 bugfix、删除、抽取或必要兼容补丁

当前复杂度关注区：`web/static/app.js`、`web/server.py`、`web/payloads_catalog.py`。
新增页面不得继续向 `app.js` 加整页状态、加载、渲染与事件绑定；先建立该页模块。
`server.py` 与 `payloads.py` 新增功能前先判断能否形成独立功能路由与载荷模块。
现有超限文件在相关任务中渐进抽取，不为满足行数单独改格式、压缩行或机械拆段。
CSS/HTML 按主题、组件与页面职责组织；超过500行时先检查新增职责归属，不机械套用Python拆分方式。

新增文件不是越多越好：只有当它能隔离职责、降低依赖、提高可测试性或减少重复时才拆。
测试优先覆盖高风险业务规则、异常分支、兼容路径与外设失败降级，不追求数量。

## 分层职责与依赖方向

```
web → view_models → services → domain / repositories / capture / protocol
app_context 是装配根；capture 可依赖 protocol，domain 不应依赖 services
```

- `web/server.py`：本地服务路由与鉴权；只做「解析请求 → 调 VM → 序列化」，
  业务逻辑一律不进路由函数；同步业务调用、载荷和 JSON 编码经服务端受控后台 runner 执行，路由不得自行创建未跟踪任务
- `web/payloads.py` / `web/payloads_catalog.py`：业务对象/VM 快照 → JSON；按功能域维护前端契约，
  不依赖 aiohttp 与 pywebview，可被测试直接驱动。当前 capture/state 载荷仍在 routes_capture mixin 中，
  后续修改该域时收口为可独立验收的转换，不继续增加隐式宿主依赖
- `view_models`：页面状态与命令；纯 Python 类，不依赖任何 UI 框架/异步运行时，
  视图数据用 frozen dataclass
- `services`：管线、运行命令与会话/账号状态编排；副作用必须有明确所有者
- `domain`：协议事件 → 业务对象的语义规则应零 IO、零线程；当前目录中的静态目录加载是已知过渡职责
- `repositories`：持久化边界；SQLite 底座 + 各域网关（适配器模式，调用方只见域对象）
- `capture`：流量接入层；TCP 重组与抓包驱动细节在此消化
- `protocol`：切帧、加解密、消息拆分和wire解码保持纯逻辑；schema/opcode加载当前含文件IO，测试与规则需区分
- `recording`：录制回放旁路；复用同一条管线

硬约束：`view_models` / `domain` / `services` / `repositories` 不 import
web（aiohttp/pywebview）；protocol 不反向依赖 services/capture；线程安全边界——
嗅探线程只做分类/重组/入队，接入层回调（on_chunk 与流关闭事件，经同一队列
**保序**）运行于投递线程，MonitorService 内部加锁，服务线程只做拉取
（drain/snapshot），不做跨线程回调。

接入层创建、录制与运行命令已由 CaptureService 承接；VM 仍控制安装/环境探测线程，
其它过渡边界见 `ARCHITECTURE.md`。新代码不得扩大例外；类型与纯规则应放无IO的下层模块
（事件类型用 `spritelens.events.PacketEvent`，不得再从 monitor_service 导入）。
命令、快照与落盘的并发保证分别验证，不能因为方法经 `to_thread` 调用就认定线程安全。

## 业务层测试方式

功能测试一律**不启动本地服务、不开窗口**：`view_models` / `domain` /
`services` / `repositories` 层的测试直接构造依赖（`Database(":memory:")`、
临时目录、合成 `PacketEvent`）。`web` 层测试（`test_web_server.py`）用最小
`AppContext` + aiohttp 测试客户端，不依赖真实抓包与浏览器。验证方式：

```powershell
# 业务层测试（无服务依赖，秒级）
.venv\Scripts\python.exe -m unittest tests.test_persistence tests.test_pets -v

# 自检：确保业务层没有反向依赖 web 框架
.venv\Scripts\python.exe -c "import sys; import tests.test_pets; assert not [m for m in sys.modules if m.split('.')[0] in {'aiohttp','webview'}], '业务层引入了 Web 依赖'"
```

## 前端约定（Vue 3 演进，现有 web/static 渐进迁移）

Vue 3 + TypeScript strict + Vite 已落地；图鉴、蛋仓、家园、色卡、产线、配对、智能配窝和宠物页已迁移，原生 JS 仅保留应用壳及采集设置。协议流页面已删除，事件日志由 `EventLogWriter` 写入本地 JSONL 供排查。
源码/demo/打包先 npm ci + tools/frontend.py build；命令与生成文件所有权见 [前端开发](FRONTEND_DEVELOPMENT.md)。
工程、导航/状态、测试和发布边界见 [VUE3_MIGRATION](VUE3_MIGRATION.md)；按路线图逐页迁移，
不要再把“零框架零构建”作为新增功能约束，也不要同时扩大原生实现和 Vue 实现。

- **UI 视觉与组件一律遵循 `docs/UI_GUIDE.md`**（token 速查/组件清单/反面清单）
- **界面颜色走 CSS 变量**（布局token在 `app.css`，三主题色值在 `themes.css`），新增样式禁止
  硬编码界面色值。系别色/天赋阶色属于业务常量，由 `domain/display.py` 经
  payloads 下发（前端不复制色表）
- **组件与类型**：新工程使用 Vue SFC / Composition API / script setup，TS strict；公共载荷与 WS 类型集中定义，
  不用 any 或强制断言跳过接口检查。当前应用共享状态由原生壳提供；Pinia 业务 store 尚未落地，
  全壳迁移前不建立第二份账号/采集状态。页面筛选/选择/详情保留局部
- **构建与分发**：npm 锁文件 + npm ci，Vite 先构建到暂存目录；校验后发布 HTML/JS/CSS。
  不清空现有图片目录，不分发 Node、node_modules 或 source map；构建前置与过期产物检查必须进入发布门禁
- **DOM 与转义**：Vue 使用模板插值/属性绑定；v-html 限于经过安全转换的明确场景。
  旧 innerHTML 路径仍须 esc()/白名单着色；Vue 挂载子树不允许旧模块继续操作
- **更新节拍**：初始数据走 `/api/bootstrap` 一次聚合；实时状态走 `/ws`
  WebSocket 推送（0.5s，内容不变不推）；列表页按需 REST 拉取
- **加页面**：归属 Vue page，渲染进 component，请求/订阅进 composable；业务计算在 Python service/domain。
  新工程尚未就绪时先做后端契约/工程前置，不默认向 app.js 添加整页逻辑；维护补丁保持局部
- **请求时序**：筛选请求处理乱序响应；切号/离页后的旧响应不得覆盖当前页面，初始化和事件订阅应幂等
- **接口边界**：fetch/token/错误/取消集中，应用持单一 WS；TS 类型不能替代运行时校验。
  64 位 ID 在后端按字段转十进制字符串，不能 JSON.parse 丢精度后再补救；兼容变更覆盖旧消费者
- **图标**：复用 `icons.js` 与本地 Tabler SVG sprite，新增图标更新来源清单；不依赖在线图标库

## 视觉验收

布局变化需要目视验收时，用 `tools/run_web_demo.py` 起带合成数据的实例检查受影响区域；
不要求每次修改生成截图、覆盖全部主题/窗口或维护浏览器自动化用例。
验收关注：错位/重叠/压缩、中文方框、窄窗口（<1280）响应式行为。

## 持久化约定

- 新增业务域数据：直接修改 `repositories/database.py` 的 schema 1 基线 DDL，
  并新建同构 Store（参考 `pet_store.py` / `egg_store.py`）。当前是破坏性开发，
  不为旧本地数据库追加兼容迁移；改表后启动时先备份本地数据库再重建，需保留的数据
  通过显式导出/导入处理。
- 基线初始化必须在单事务内完成，失败整体回滚；schema 版本不匹配或结构不完整时
  先完整备份主库及 WAL/SHM，再重建当前基线，不尝试迁移旧结构；备份失败必须保留原文件并报错。
- 写路径必须无 IO：抓包线程内的调用只允许并入内存待写表/队列；落盘交给
  worker 线程批量执行（登录突发实测：同步 flush 会让轮询等待 57ms）。
- 同一 Store 批次的关联表使用 `Database.execute_batches()` 在一个事务内提交；失败整体回滚并回填全部待写数据。
  配置读取错误必须向上传播，不能以空配置继续写回；原子替换成功后才更新配置缓存。
- 账号维度数据：uid 变化（真切换）才清该域内存快照；同 uid 重复身份帧与
  离线加载账号登录不算切换——判定统一走 `services/account_tracker.py`。
- 改表结构后跑 `tests.test_persistence`；损坏恢复路径已覆盖（备份重建）。

Store 并发批次顺序、坏库备份失败保护与坏行隔离已有修复及回归。
原始流录制/checkpoint 仍同步写盘，慢盘/最终 flush 失败与停止超时语义仍待验证；不能照搬这些路径当作正确模板。
新增持久化能力应验证批次顺序、失败回填、坏行隔离、账号一致性、停止超时和未写数据提示。
离线恢复统一选择展示uid，所有业务域按该uid加载；载荷应来自同一版本快照。
没有完整分页/删除事件证据时，只能声明观察集合或历史缓存，不能推断当前仓库已完整。

## 资源与打包兼容

- **只读资源**（`data/`、`resources/`）一律经 `paths.project_root()` 定位，
  禁止在模块里手写 `Path(__file__).parent.parent`——打包后 `__file__` 语义
  不同，会全部找不到。`project_root()` 已覆盖源码态 / PyInstaller `_MEIPASS` /
  Nuitka-frozen 三条分支（`tests/test_paths.py` 保留打包路径回归）
- **用户数据**（配置/日志/SQLite/录制）走 `data_root()`，与打包状态无关；
  打包后仍写 `%LOCALAPPDATA%`，绝不写进安装目录（Program Files 无写权限）。
  目录不可用必须明确报错，禁止静默切到临时目录而分裂数据。
- 包内自带的静态前端（`web/static/`）用 `Path(__file__).parent / "static"` 定位，
  打包器会把整个包目录搬走，这是唯一允许不经过 `project_root()` 的场景
- **图标**：源图为 `resources/icon_source.png`（好奇版头像，保留背景、大椭圆高光与眼底绿色亮面）。
  改设计后跑 `python tools/make_icon.py`，生成 16/24/32/48/64/128/256px 的
  `resources/app.ico` 与 `spritelens/web/static/favicon.png`，源图与产物随仓库提交。
  窗口标题栏、任务栏、Alt-Tab、桌面快捷方式与 exe 共用 ICO；浏览器标签页与页面品牌标识共用 PNG。
- **打包**：`build.bat` / `python build.py`（配置在 `build_config.toml`）。
  `build.bat` 无参数时进入构建菜单，可选择普通构建、dry-run 或修改项目版本号；
  版本源文件是 `spritelens/__init__.py`，也可用 `build.py --get-version` /
  `build.py --set-version VERSION` 直接操作。`build_config.toml` 保留
  `backend_c_flags = ["-mno-gfni"]`，用于规避 Nuitka onefile 外层启动器在部分
  AMD CPU 上因 GFNI 指令触发的入口非法指令崩溃；扩大到禁用 AVX/AVX2 前必须有
  目标机器的复现证据。
  发布配置启用 `uac_admin = true`，Nuitka 生成的 exe 启动时会触发 UAC，以便采集和 Npcap
  安装流程获得管理员权限；源码 `start.bat`、单元测试和开发服务器不强制提权。Npcap 安装
  首选 `powershell.exe -NoProfile -NonInteractive` 下载官方安装器，失败后回退 Python `urllib`；
  安装器退出后自动检测，不自动重启程序，两条下载路径都失败时显示官方手动安装地址。
  **不要排除 scapy 的任何子模块**——scapy 内部动态 import 多，静态排除会
  在打包产物里才暴露为运行时失败（实测排除 `as_resolvers` 让网卡枚举直接挂）
- **包内非 Python 资源必须显式附带**：`spritelens/web/static/`（前端 HTML/CSS/JS
  /精灵图）要写进 `include_data_dirs`，Nuitka 只编译 `.py`。漏带的症状是
  exe 启动即崩（服务报 `web/static does not exist`），而 `--smoke-test` 等
  非 GUI 路径测不出来——所以 `--smoke-test` 已内含静态资源检查
- **打包后必须实机验证三件事**：`--smoke-test`（三项资源齐全）→
  `--list-ifaces`（scapy 链路完好）→ **实际启动 GUI 看窗口**（前两条都过不了这个坑）
- **杀软干扰**：Nuitka 后处理调 `rc.exe` 写图标/版本资源，临时文件
  `build/RCX*.tmp` 会被部分杀软（火绒实测）误报并锁定，导致
  `Failed to add resources` 打包失败。打包前给项目目录加白名单

资源更新必须明确source参数、输入版本/哈希、导入顺序与输出差异。基础表整表重导入可能覆盖后续补齐，
须在临时输出验证后发布，不能直接在正式目录试跑。来源哈希与转码后产物哈希分别记录；本机绝对路径不进入来源清单。
缺图、未知数据和未裁定冲突保持可见，不用其它物种或猜测值补齐。发布资源依据运行引用与派生来源决定，删除前扫描调用方。
新环境应能安装声明的开发依赖并跑测试；发布记录包含依赖/资源版本、exe哈希与实测体积，旧体积数据注明日期与口径。

## 错误处理

- 捕获具体异常并降级（配置脏值归一默认；key 写失败告警不阻断采集）
- 抓包线程内的异常必须消化（`_handle_packet` 全包裹），绝不让嗅探线程死亡
- 解码异常只影响单条事件（返回空树），不影响管线
- 正常关闭时的连接重置降为debug；意外业务/服务错误在本地留下可定位信息，对外返回可读消息
- `pythonw` 启动下控制台不可见：未捕获异常由 `install_excepthook()` 落盘到
  `logs/spritelens.crash.log`，启动致命失败弹系统对话框（`web/run.py::_fatal`）——
  新增入口路径时不得绕过这两层

## 测试

日常收尾只做与本次改动相关的验证。已删除统一门禁脚本、AST 架构门禁、递归 JS/HTML/依赖预检、ESLint 和整套 Playwright；不另建替代统一门禁。

### 测试取舍

- 文档、文案、样式、图标和简单展示：检查 diff，布局变化按需目视验收；Vue 源码变化运行构建，不新增自动化测试。
- 普通局部行为：复用相关测试；没有现成用例时按风险人工验证，不要求为每次改动新增测试。
- 只保留关键数据规则、协议解析、持久化基线/损坏恢复、账号/快照与请求时序、鉴权、保存失败和线程/资源生命周期的回归。真实高风险缺陷缺少覆盖时才补最小用例。
- 同一行为只在合适的一层验证；不测试简单 getter、直接委托、框架保证、私有结构、固定 DOM 或像素值，不追求覆盖率和测试数量。

### 验证命令

| 改动 | 最少验证 |
| --- | --- |
| Python 业务或接口行为 | `python -B -m unittest tests.test_<相关模块> -q`；跨层风险才加相关集成测试 |
| Vue 源码 | `python -B tools/frontend.py build`（已包含类型检查）；交互变化按需运行 `npm test -- <相关.test.ts>` |
| 原生 JS 行为 | 相关已有 Node 回归或页面操作；不递归检查全部脚本 |
| 资源、启动或打包 | 本次资源引用/输出检查；受影响的启动或发布流程按需做 smoke、GUI/驱动实测 |

保留 unittest 与 Vitest。Python 使用内存库、临时目录和 `tests/_synth.py` 合成数据，不依赖真实游戏；并发回归用 Event/Barrier 控制顺序。
发布前或跨多个核心域的改动，可运行 `python -B -m unittest discover -s tests -q`；只影响单域时仍按范围选择，不因“协议/持久化/组合根”标签强制全套。
构建保留类型检查与产物校验，打包保留资源检查；发布继续验收实际 exe 启动。这些验证不在普通修改收尾时重复执行。
无法执行所需验证时，明确说明缺少的工具、未验证范围与替代检查。

## 修改前判断

动手前先问三件事：

1. 这是**用户可见行为**、**开发约束**，还是**内部实现**？
2. 涉及持久化 schema / 协议解析 / 组合根装配 / 打包入口吗？——这三类改动
   按实际影响选择相关失败路径与契约验证，不自动跑全量测试。
3. 能否用**更小的局部改动**完成，而不是继续往大文件里塞？

补充检查：输入有什么证据或未知项，谁拥有状态/线程/IO，失败和停止怎样处理，现有契约怎样保持，怎样验证和回退。
高风险副作用修复缺少覆盖时补最小失败回归；新增抽象需说明它降低了哪个具体风险或重复。

## 文档同步规则

- 功能与用法变化 → `README.md`；架构边界与分层 → `docs/ARCHITECTURE.md`
- 文件级新增/移动 → `docs/CODEBASE_MAP.md`（新增文件必须同步本表）
- 协议结论与排障 → `docs/PROTOCOL_NOTES.md`
- UI 视觉/组件规范 → `docs/UI_GUIDE.md`；蛋神对标实施状态 → `docs/DANSHEN_FEATURE_SPEC.md`
- 竞品分析与功能规划 → `docs/archive/COMPETITOR_ANALYSIS.md` / `docs/archive/FEATURE_MODULES.md`
- 开发约定（本文件）随实践更新：踩过的坑要写进来，避免重复犯
- 待办、优先级与验收 → `docs/ROADMAP.md`；带日期的审查证据 → `docs/reviews/`
- 新文档写明状态、读者、用途；当前入口不重复维护历史评估数字或多份任务状态

## 架构与实现协作

具体实现主要交给 GLM 3.8f，Codex 维护架构与路线、拆解任务、复核改动和验收证据。
实现者按路线图的单个编号推进；涉及新的依赖方向、持久化语义或前端契约时，先写明取舍及兼容方式。
这套约定用于交接与复核，不要求每次局部修改都等待额外批准。

### 任务交接模板

```text
任务：ROADMAP 编号与目标（一次只做一个可独立验收的切片）
基线：commit、git status；保留哪些已有改动
假设：输入证据、已知/未知；存在多种语义时写明选择
范围：涉及模块、状态所有者、依赖方向、对外契约
实现边界：最小改动；不扩大大文件职责/架构豁免；兼容与迁移条件
失败分支：启动、运行、停止、写失败、并发/切号（按实际相关性列出）
验收：按风险选择已有测试、必要回归用例或人工/静态检查；缺陷回归应能复现原问题
交付：改动摘要、验证结果、未验证项、遗留编号、回退条件
```

### 实现时守住的边界

- **状态与命令**：同一状态只有一个权威所有者；跨层不写对方私有字段。
  串行化覆盖完整命令，而非仅包住最后一次副作用；命令锁可包含必要 IO，必须说明等待与失败策略。
  快照状态锁保持短小，序列化/渲染在锁外；不得把“锁内零 IO”误用于所有类型的锁。
- **资源生命周期**：创建即登记释放，成功装配后转交唯一所有者；生命周期改动按实际影响复用失败回滚、退出或重试回归。
  超时返回不代表 worker 已退；没有清理证据不能丢掉句柄或宣告数据保存成功。
  采集停止默认等待预算 12s，HTTP 服务停止 5s；超时保留唯一清理线程/任务并允许重试。
  旧采集回调或 HTTP 服务尚未确认退出时，下游日志/Store/DB 延后关闭，不能以逐项容错为由关闭仍在使用的资源。
- **数据读契约**：返回同域的 uid/version/业务数据快照，静态配置独立；跨域检查归属，保留历史、不完整与未知。
  frozen 外壳不保护内层 dict，读取方不得修改；不靠多次带锁 getter 拼响应。
- **页面与请求**：页面自持状态、加载与绑定；导航/推送只分发。绑定幂等，账号相关请求能失效，旧响应不能覆盖新账号。
  Vue 逐页承接状态/组件，临时桥接不共享 DOM 所有权；共享模块须有真实调用方，先锁行为再迁移。
- **资源与发布**：输入可追溯，暂存输出验证后发布；缺图与数据缺失分开处理，未裁定冲突保持可见。

### 复核与完成

复核看状态所有权、事务范围、线程停止、账号归属、依赖与兼容契约；不以“测试变多”“文件拆小”单独判断完成。
按改动范围选择必要验证，不为凑覆盖率写镜像实现的测试；修复并发风险使用 Event/Barrier。
实现者提交证据后，路线图才从“已实现待验收”改为“已验收”；缺 GUI/驱动/新环境验证须保留具体待验收项。
单次审查写入带日期的 review，只有路线图维护持续任务状态。

## 删除和归档规则

- 不按文件年龄删除文档或代码
- 删除前先做引用扫描（README / 文档 / 代码），确认无引用
- 有价值的事故经验、阈值、回滚条件先迁入维护文档，再删旧文档
- 生成物（日志、截图、临时诊断脚本）默认不进版本库——
  `.guishot/`、`data/recordings/`、`data/keys/`、`/logs/` 已在 .gitignore
- **忽略规则一律锚定仓库根**：写 `/logs/` 而不是 `logs/`。无前导斜杠会匹配
  任意层级同名目录，曾把源码包 `spritelens/logs/` 一起忽略（首次提交实测漏文件）
- 新增 Git 忽略规则后，用 `git status --ignored --porcelain` 复查一遍，
  确认没有源码文件被误伤

## 安全边界

- 日志与录制文件含会话密钥与本机地址：/logs/、data/recordings/、data/keys/ 均已 gitignore
- 不把本机绝对路径写进代码与文档
