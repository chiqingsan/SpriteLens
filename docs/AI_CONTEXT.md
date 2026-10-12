# 协作上下文

状态：当前入口文档。读者：AI 助手与新开发者。用途：快速定位项目、边界和必读资料。

SpriteLens（小洛探探）是 Windows 本地游戏数据观测工具。当前技术栈为 Python 3.12、Npcap/scapy、aiohttp、pywebview/WebView2、SQLite 和原生 JS。采集为被动旁听，运行数据在用户数据目录；静态数据和页面资源随包分发。

开发前先检查工作区，再读 [开发指南](DEVELOPMENT_GUIDE.md) 与 [架构](ARCHITECTURE.md)。当前演进顺序以 [路线图](ROADMAP.md) 为准，文件定位见 [代码地图](CODEBASE_MAP.md)，文档导航见 [文档索引](README.md)。

当前重点是数据正确性、线程与资源生命周期、账号一致性、页面拆分和资源可复现。2026-10-12 [审查](reviews/PROJECT_REVIEW_2026-10-12.md) 发现的代码缺陷仍待修复，不能因340项既有测试通过就认定这些路径正确。

高风险区域：坏库恢复和迁移、并发批量落盘、采集启停、会话接续、账号切换、完整/历史仓库语义、资源导入与发布。修改前明确输入证据、状态所有者、失败/停止方式与验收。

`web/static/app.js`、`web/server.py`、`web/payloads.py` 是职责增长集中区。新增页面先设计独立页面模块和对应载荷/路由；纯规则放 domain，副作用由 service/repository/adapter 承接。每次抽取保持原行为可验证，避免建立平行状态或空壳抽象。

当前实现仍有 domain→MonitorService 类型依赖、domain/protocol 中的资源加载IO、VM控制抓包与安装线程等过渡边界。它们是已知债务，不能作为新增反向依赖的理由。未来目标与当前事实必须分清。

用户可见功能与启动方式维护在根 README；协议适配见 [协议笔记](PROTOCOL_NOTES.md)，UI 变更见 [UI指南](UI_GUIDE.md)。复杂业务未知项应记录为未知，历史缓存不能当本次实时确认。
