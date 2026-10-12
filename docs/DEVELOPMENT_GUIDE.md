# 开发规范

继承姊妹项目 meow toolkit 的工程约定，新项目从第一行代码就按此执行。
（原 PyQt 原生界面已于 2026-10 退役，本文件已同步改为 Web 单形态约定。）

状态：当前维护入口。读者：开发者与 AI 协作者。本文维护开发约束；待实施改造与验收统一见
[ROADMAP](ROADMAP.md)，审查证据见 [2026-10-12 项目审查](reviews/PROJECT_REVIEW_2026-10-12.md)。

## 通用

- 所有文件读写显式 UTF-8；注释用中文，写「为什么」而不是复述代码
- 全量类型注解；文件头 `from __future__ import annotations`
- 按文末测试分级验证；协议、持久化、组合根与发布改动跑完整 `tools/run_build_tests.py`
- 不要随意回退或覆盖工作区里不是本次修改产生的变更
- 新功能优先沿用现有分层边界（见下），不新造平行结构

## 文件规模红线

以下规则适用于 Python 与 JavaScript。单文件超限时，先问"这段代码能否放进 service / repository / view_model / 页面 /
独立工具模块"，而不是顺手继续塞：

- 超过 500 行：新增代码前必须先判断拆分去向
- 超过 800 行：默认禁止新增非局部修复代码（bugfix 除外），新功能必须拆到新模块
- 超过 1200 行：高风险文件，只接受小范围 bugfix、删除、抽取或必要兼容补丁
- 测试文件超 500 行：按行为域拆分

当前复杂度关注区：`web/static/app.js`、`web/server.py`、`web/payloads.py`。
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
  业务逻辑一律不进路由函数；`asyncio.to_thread` 包裹同步业务调用
- `web/payloads.py`：业务对象/VM 快照 → JSON 的唯一序列化点；前端契约稳定在此模块，
  不依赖 aiohttp 与 pywebview，可被测试直接驱动
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

当前 domain 运行时导入 services.PacketEvent、VM构造抓包源与控制安装线程等例外见
`ARCHITECTURE.md` 的已知边界。新代码不得扩大例外；类型与纯规则应放无IO的下层模块。
命令、快照与落盘的并发保证分别验证，不能因为方法经 `to_thread` 调用就认定线程安全。

## 业务层无 UI 可测（强制约定）

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

## 前端约定（web/static，零框架零构建）

- **UI 视觉与组件一律遵循 `docs/UI_GUIDE.md`**（token 速查/组件清单/反面清单）
- **界面颜色走 CSS 变量**（布局token在 `app.css`，三主题色值在 `themes.css`），新增样式禁止
  硬编码界面色值。系别色/天赋阶色属于业务常量，由 `domain/display.py` 经
  payloads 下发（前端不复制色表）
- **无构建步骤**：原生现代 JS，沿用现有 IIFE 模块风格；使用系统 WebView2 已支持能力，新增依赖须有实际收益
- **DOM 渲染必须先转义**：所有插入 innerHTML 的后端文本经 `esc()`；解码树
  等需着色内容走 `colorizeDecoded()` 白名单着色，不得直接拼接原始文本
- **更新节拍**：初始数据走 `/api/bootstrap` 一次聚合；实时状态走 `/ws`
  WebSocket 推送（0.5s，内容不变不推）；列表页按需 REST 拉取
- **加页面**：`index.html` 增加必要骨架和导航；该页独立管理 state/load/render/bind，
  `app.js` 仅协调导航与启动。路由/载荷按功能归属，保留兼容契约；具体迁移次序见 `ROADMAP.md`
- **请求时序**：筛选请求处理乱序响应；切号/离页后的旧响应不得覆盖当前页面，初始化和事件订阅应幂等
- **图标**：复用 `icons.js` 与本地 Tabler SVG sprite，新增图标更新来源清单；不依赖在线图标库

## 视觉验收

改布局后用 `tools/run_web_demo.py` 起带合成数据的实例（系统浏览器打开），
对照截图检查；Web 前端也可用浏览器自动化工具做控件级校验。
验收关注：错位/重叠/压缩、中文方框、窄窗口（<1280）响应式行为。

## 持久化约定

- 新增业务域数据：在 `repositories/database.py` 的 `_MIGRATIONS` **追加**
  `(版本号, SQL 语句组)`（不得修改已发布条目，历史库需能逐级升上来），
  并新建同构 Store（参考 `pet_store.py` / `egg_store.py`）。
- 迁移语句整组单事务执行，失败必须整体回滚（不得留下「列已存在但版本号
  没推进」的半迁移库）；`ADD COLUMN` 类语句按「列已存在即跳过」容错。
- 写路径必须无 IO：抓包线程内的调用只允许并入内存待写表/队列；落盘交给
  worker 线程批量执行（登录突发实测：同步 flush 会让轮询等待 57ms）。
- 账号维度数据：uid 变化（真切换）才清该域内存快照；同 uid 重复身份帧与
  离线加载账号登录不算切换——判定统一走 `services/account_tracker.py`。
- 改表结构后跑 `tests.test_persistence`；损坏恢复路径已覆盖（备份重建）。

上面的规则是新代码要求；审查发现原始流录制/checkpoint仍同步写盘、Store并发flush存在顺序风险，
坏库备份失败与单条坏数据隔离也未充分覆盖，不能照搬这些路径当作正确模板。
新增持久化能力应验证批次顺序、失败回填、坏行隔离、账号一致性、停止超时和未写数据提示。
离线恢复统一选择展示uid，所有业务域按该uid加载；载荷应来自同一版本快照。
没有完整分页/删除事件证据时，只能声明观察集合或历史缓存，不能推断当前仓库已完整。

## 资源与打包兼容

- **只读资源**（`data/`、`resources/`）一律经 `paths.project_root()` 定位，
  禁止在模块里手写 `Path(__file__).parent.parent`——打包后 `__file__` 语义
  不同，会全部找不到。`project_root()` 已覆盖源码态 / PyInstaller `_MEIPASS` /
  Nuitka-frozen 三条分支（`tests/test_paths.py` 锁死）
- **用户数据**（配置/日志/SQLite/录制）走 `data_root()`，与打包状态无关；
  打包后仍写 `%LOCALAPPDATA%`，绝不写进安装目录（Program Files 无写权限）
- 包内自带的静态前端（`web/static/`）用 `Path(__file__).parent / "static"` 定位，
  打包器会把整个包目录搬走，这是唯一允许不经过 `project_root()` 的场景
- **图标**：改设计后跑 `python tools/make_icon.py` 重新生成，
  产物（`resources/app.ico`、`web/static/favicon.png`）随仓库提交
- **打包**：`build.bat` / `python build.py`（配置在 `build_config.toml`）。
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

## 架构边界测试

`tests/test_architecture.py` 用 AST 静态解析校验分层约束（不导入模块，无副作用）：
业务层不得 import aiohttp/pywebview、不得反向依赖上层、protocol 保持纯函数、
业务层不得依赖装配根。违规立即红灯。已批准的例外（`protocol → logs`、
`domain → services.PacketEvent`）在文件头部记录，**只减不增**。

当前测试把domain→services按整个包豁免，且未完整解析相对导入；它不能证明所有上述约束已被执行。
后续收紧时按模块/符号登记例外及删除条件，不以增加包级白名单让测试变绿。

## 测试

- unittest（非 pytest），tests/ 平铺 `test_<模块>.py`
- 协议行为测试优先用 `tests/_synth.py` 合成帧，禁止依赖真实游戏流量
- Web 服务测试使用最小AppContext、临时/内存数据和可注入依赖；当前集成测试监听随机回环端口，
  新的请求级校验可用aiohttp测试客户端，均不得依赖真实驱动或游戏
- 不写依赖时序/网络的 flaky 断言；随机数据一律用确定种子
- 并发故障优先用Event/Barrier控制顺序，避免靠sleep碰运气；外部驱动/磁盘/下载用可注入替身
- JavaScript纯规则与请求时序可用原生Node测试；语法与资源检查不能替代浏览器交互验收

### 测试分级（按改动范围选命令）

| 改动范围 | 需要跑 |
| --- | --- |
| 文档 / 注释 | diff 与引用检查即可 |
| 单一 domain / repository / view_model | 对应测试文件 + `compileall` |
| 协议层（frames/crypto/records/wire/schema） | `tools/run_build_tests.py`（协议是全链路地基） |
| Web 前端 / 路由 / 组合根 | `run_build_tests.py` + `python -m spritelens --smoke-test` + 浏览器过一遍 |
| 持久化 schema / 打包入口 / 发布前 | 上面全部 |
| 资源导入 / 映射 | 对应工具与资源测试、JSON/图片/引用校验、覆盖/冲突差异；涉发布再做exe验收 |

发布前统一用 `python tools/run_build_tests.py`（内部跑完整 unittest discover）。

环境缺测试工具或依赖时，要在最终说明里明确写清楚"跳过什么、为什么"。

## 修改前判断

动手前先问三件事：

1. 这是**用户可见行为**、**开发约束**，还是**内部实现**？
2. 涉及持久化 schema / 协议解析 / 组合根装配 / 打包入口吗？——这三类改动
   影响面最大，必须跑全量测试。
3. 能否用**更小的局部改动**完成，而不是继续往大文件里塞？

补充检查：输入有什么证据或未知项，谁拥有状态/线程/IO，失败和停止怎样处理，现有契约怎样保持，怎样验证和回退。
副作用修复应先补失败用例；新增抽象需说明它降低了哪个具体风险或重复。

## 文档同步规则

- 功能与用法变化 → `README.md`；架构边界与分层 → `docs/ARCHITECTURE.md`
- 文件级新增/移动 → `docs/CODEBASE_MAP.md`（新增文件必须同步本表）
- 协议结论与排障 → `docs/PROTOCOL_NOTES.md`
- UI 视觉/组件规范 → `docs/UI_GUIDE.md`；蛋神对标实施状态 → `docs/DANSHEN_FEATURE_SPEC.md`
- 竞品分析与功能规划 → `docs/COMPETITOR_ANALYSIS.md` / `docs/FEATURE_MODULES.md`
- 开发约定（本文件）随实践更新：踩过的坑要写进来，避免重复犯
- 待办、优先级与验收 → `docs/ROADMAP.md`；带日期的审查证据 → `docs/reviews/`
- 新文档写明状态、读者、用途；当前入口不重复维护历史评估数字或多份任务状态

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
