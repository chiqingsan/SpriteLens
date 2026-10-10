# 开发规范

继承姊妹项目 meow toolkit 的工程约定，新项目从第一行代码就按此执行。
（原 PyQt 原生界面已于 2026-10 退役，本文件已同步改为 Web 单形态约定。）

## 通用

- 所有文件读写显式 UTF-8；注释用中文，写「为什么」而不是复述代码
- 全量类型注解；文件头 `from __future__ import annotations`
- 提交前跑 `python tools/run_build_tests.py`，全绿为准
- 不要随意回退或覆盖工作区里不是本次修改产生的变更
- 新功能优先沿用现有分层边界（见下），不新造平行结构

## 文件规模红线

单文件超限时，先问"这段代码能否放进 service / repository / view_model /
独立工具模块"，而不是顺手继续塞：

- 超过 500 行：新增代码前必须先判断拆分去向
- 超过 800 行：默认禁止新增非局部修复代码（bugfix 除外），新功能必须拆到新模块
- 超过 1200 行：高风险文件，只接受小范围 bugfix、删除、抽取或必要兼容补丁
- 测试文件超 500 行：按行为域拆分

新增文件不是越多越好：只有当它能隔离职责、降低依赖、提高可测试性或减少重复时才拆。
测试优先覆盖高风险业务规则、异常分支、兼容路径与外设失败降级，不追求数量。

## 分层职责与依赖方向

```
web (server/run/payloads/static)  →  view_models  →  services  →  domain / repositories  →  capture / protocol
```

- `web/server.py`：本地服务路由与鉴权；只做「解析请求 → 调 VM → 序列化」，
  业务逻辑一律不进路由函数；`asyncio.to_thread` 包裹同步业务调用
- `web/payloads.py`：业务对象/VM 快照 → JSON 的唯一序列化点；前端契约稳定在此模块，
  不依赖 aiohttp 与 pywebview，可被测试直接驱动
- `view_models`：页面状态与命令；纯 Python 类，不依赖任何 UI 框架/异步运行时，
  视图数据用 frozen dataclass
- `services`：管线编排与会话跟踪；持有可插拔的 `CaptureSource`
- `domain`：协议事件 → 业务对象的纯语义层（零 IO、零线程）
- `repositories`：持久化边界；SQLite 底座 + 各域网关（适配器模式，调用方只见域对象）
- `capture`：流量接入层；TCP 重组与抓包驱动细节在此消化
- `protocol`：协议纯函数层；只依赖标准库 + pycryptodome，零 IO、零线程
- `recording`：录制回放旁路；复用同一条管线

硬约束：`view_models` / `domain` / `services` / `repositories` 不 import
web（aiohttp/pywebview）；protocol 不反向依赖 services/capture；线程安全边界——
接入层回调运行于抓包线程，MonitorService 内部加锁，服务线程只做拉取
（drain/snapshot），不做跨线程回调。

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

- **颜色一律走 CSS 变量**（`app.css` 的 `:root`，teal 体系），禁止在样式里
  硬编码色值；系别色/天赋阶色属于业务常量，由 `domain/display.py` 经
  payloads 下发（前端不复制色表）
- **无构建步骤**：原生 ES5 风格 JS + 模板字符串；不引入打包器、不引入前端框架
- **DOM 渲染必须先转义**：所有插入 innerHTML 的后端文本经 `esc()`；解码树
  等需着色内容走 `colorizeDecoded()` 白名单着色，不得直接拼接原始文本
- **更新节拍**：初始数据走 `/api/bootstrap` 一次聚合；实时状态走 `/ws`
  WebSocket 推送（0.5s，内容不变不推）；列表页按需 REST 拉取
- **加页面**：`index.html` 加 `<section id="page-xxx" class="page">` 与侧栏
  `data-page="xxx"` 按钮 → `app.js` 的 `switchPage` 分发加 `loadXxx()` →
  `server.py` 加 `/api/xxx` 路由 + `payloads.py` 加载荷构造
- **图标**：内联 SVG（`index.html` 导航），24×24 viewBox、`fill=none`、
  `stroke=currentColor`、`stroke-width` 与全站一致；不依赖在线图标库

## 视觉验收

改布局后用 `tools/run_web_demo.py` 起带合成数据的实例（系统浏览器打开），
对照截图检查；Web 前端也可用浏览器自动化工具做控件级校验。
验收关注：错位/重叠/压缩、中文方框、窄窗口（<1280）响应式行为。

## 持久化约定

- 新增业务域数据：在 `repositories/database.py` 的 `_MIGRATIONS` **追加**
  `(版本号, SQL 语句组)`（不得修改已发布条目，历史库需能逐级升上来），
  并新建同构 Store（参考 `pet_store.py`）。
- 写路径必须无 IO：抓包线程内的调用只允许并入内存待写表；落盘交给
  worker 线程批量执行（登录突发实测：同步 flush 会让轮询等待 57ms）。
- 改表结构后跑 `tests.test_persistence`；损坏恢复路径已覆盖（备份重建）。

## 错误处理

- 捕获具体异常并降级（配置脏值归一默认；key 写失败告警不阻断采集）
- 抓包线程内的异常必须消化（`_handle_packet` 全包裹），绝不让嗅探线程死亡
- 解码异常只影响单条事件（返回空树），不影响管线
- 服务端错误不进日志堆栈（连接重置属正常收尾）；对外只回可读消息
- `pythonw` 启动下控制台不可见：未捕获异常由 `install_excepthook()` 落盘到
  `logs/spritelens.crash.log`，启动致命失败弹系统对话框（`web/run.py::_fatal`）——
  新增入口路径时不得绕过这两层

## 架构边界测试

`tests/test_architecture.py` 用 AST 静态解析校验分层约束（不导入模块，无副作用）：
业务层不得 import aiohttp/pywebview、不得反向依赖上层、protocol 保持纯函数、
业务层不得依赖装配根。违规立即红灯。已批准的例外（`protocol → logs`、
`domain → services.PacketEvent`）在文件头部记录，**只减不增**。

## 测试

- unittest（非 pytest），tests/ 平铺 `test_<模块>.py`
- 协议行为测试优先用 `tests/_synth.py` 合成帧，禁止依赖真实游戏流量
- Web 服务测试用 aiohttp 测试客户端 + 内存库，不监听真实端口（除随机端口专项）
- 不写依赖时序/网络的 flaky 断言；随机数据一律用确定种子

### 测试分级（按改动范围选命令）

| 改动范围 | 需要跑 |
| --- | --- |
| 文档 / 注释 | diff 与引用检查即可 |
| 单一 domain / repository / view_model | 对应测试文件 + `compileall` |
| 协议层（frames/crypto/records/wire/schema） | `tools/run_build_tests.py`（协议是全链路地基） |
| Web 前端 / 路由 / 组合根 | `run_build_tests.py` + `python -m spritelens --smoke-test` + 浏览器过一遍 |
| 持久化 schema / 打包入口 / 发布前 | 上面全部 |

发布前统一用 `python tools/run_build_tests.py`（内部跑完整 unittest discover）。

环境缺测试工具或依赖时，要在最终说明里明确写清楚"跳过什么、为什么"。

## 修改前判断

动手前先问三件事：

1. 这是**用户可见行为**、**开发约束**，还是**内部实现**？
2. 涉及持久化 schema / 协议解析 / 组合根装配 / 打包入口吗？——这三类改动
   影响面最大，必须跑全量测试。
3. 能否用**更小的局部改动**完成，而不是继续往大文件里塞？

## 文档同步规则

- 功能与用法变化 → `README.md`；架构边界与分层 → `docs/ARCHITECTURE.md`
- 文件级新增/移动 → `docs/CODEBASE_MAP.md`（新增文件必须同步本表）
- 协议结论与排障 → `docs/PROTOCOL_NOTES.md`
- 竞品分析与功能规划 → `docs/COMPETITOR_ANALYSIS.md` / `docs/FEATURE_MODULES.md`
- 开发约定（本文件）随实践更新：踩过的坑要写进来，避免重复犯

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
