# 协作上下文

状态：当前入口文档。读者：AI 助手与新开发者。用途：快速定位项目、边界和必读资料。

SpriteLens（小洛探探）是 Windows 本地游戏数据观测工具。当前技术栈为 Python 3.12、Npcap/scapy、aiohttp、pywebview/WebView2、SQLite 和原生 JS。采集为被动旁听，运行数据在用户数据目录；静态数据和页面资源随包分发。

前端已确认演进为 Vue 3 + TypeScript + Vite，尚未开始工程实施；后端与桌面壳保留。
按 [Vue 演进决策](VUE3_MIGRATION.md) 和路线图分任务建设，避免先大规模拆原生 JS 再重做 Vue。

开发前先检查工作区，再读 [开发指南](DEVELOPMENT_GUIDE.md) 与 [架构](ARCHITECTURE.md)。当前演进顺序以 [路线图](ROADMAP.md) 为准，文件定位见 [代码地图](CODEBASE_MAP.md)，文档导航见 [文档索引](README.md)。

当前重点是数据正确性、资源生命周期、账号/快照契约、页面边界与资源可复现。
契约还需处理 64 位 ID 的 JS 精度（家园 actor_id 已有明确样本），不能用 TS 类型断言掩盖传输错误。
2026-10-12 初审的 R01–R08 已有修复与回归；R09 部分落实，运行时异常路径仍需闭环。
[改动复核](reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md)确认录制命令一致性回归、装配/外层清理遗漏及 HTTP 输入问题；
R10–R14 的完成范围也须逐项核对。下一步顺序与验收只维护在路线图，不把一次抽取当成整阶段完成。

高风险区域：坏库恢复和迁移、并发批量落盘、采集启停、会话接续、账号切换、完整/历史仓库语义、资源导入与发布。修改前明确输入证据、状态所有者、失败/停止方式与验收。

`web/static/app.js`、`web/server.py`、`web/payloads_catalog.py` 是职责增长集中区。
新增页面先设计独立页面模块和对应载荷/路由；纯规则放 domain，副作用由 service/repository/adapter 承接。
每次抽取保持原行为与异常路径可验证，避免建立平行状态或空壳抽象。

PacketEvent 已在 events 叶子模块，domain→services 类型依赖已移除；CaptureService 已承接抓包源、录制与密钥。
PetRepoSnapshot/PetView 已覆盖 /api/pets 的主要请求读取，蛋图鉴已独立为 pages/egg-dex.js。
剩余过渡边界包括 domain/protocol 的资源加载 IO、VM 安装/探测线程、routes mixin 的宿主依赖，以及尚未统一的跨读取快照。
这些现状不能作为新增反向依赖的理由。

具体实现主要由 GLM 3.8f 承接，Codex 负责架构、路线与复核；交接使用开发指南模板，
一次推进一个可独立验收的路线图编号，完成状态附代码与验证证据。

用户可见功能与启动方式维护在根 README；协议适配见 [协议笔记](PROTOCOL_NOTES.md)，UI 变更见 [UI指南](UI_GUIDE.md)。复杂业务未知项应记录为未知，历史缓存不能当本次实时确认。
