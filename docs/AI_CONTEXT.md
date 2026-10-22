# 协作上下文

状态：当前入口文档。读者：AI 助手与新开发者。用途：快速定位项目、边界和必读资料。

2026-10-15 已精简测试与开发约束：统一门禁、ESLint、Playwright 与结构/展示类冗余测试已删除。
日常仅验证本次行为，Vue 构建已含类型检查；必要回归与发布检查按 [开发指南](DEVELOPMENT_GUIDE.md#测试) 选择。
下文测试数量与门禁结果是历史交付证据，不代表当前执行要求。

SpriteLens（小洛探探）是 Windows 本地游戏数据观测工具。当前技术栈为 Python 3.12、Npcap/scapy、aiohttp、pywebview/WebView2、SQLite，以及 Vue 3/TypeScript/Vite 与少量原生 JS 壳。采集为被动旁听，运行数据在用户数据目录；静态数据和页面资源随包分发。

前端已落地 Vue 3 + TypeScript + Vite，当前图鉴、蛋仓、家园、色卡、产线、配对、智能配窝和宠物页由 Vue 页面承载；原生 JS 保留应用壳、导航、账号与采集设置。协议流页面已删除，排查依赖本地事件日志。
按 [Vue 演进决策](VUE3_MIGRATION.md) 和路线图分任务建设，避免先大规模拆原生 JS 再重做 Vue。

开发前先检查工作区，再读 [开发指南](DEVELOPMENT_GUIDE.md) 与 [架构](ARCHITECTURE.md)。当前演进顺序以 [路线图](ROADMAP.md) 为准，文件定位见 [代码地图](CODEBASE_MAP.md)，文档导航见 [文档索引](README.md)。

当前重点是数据正确性、资源生命周期、账号/快照契约、页面边界与资源可复现。
当前数据库只有 schema 1 基线 DDL，不维护旧迁移链；桌面关闭等待页面保存确认和缓存 flush，失败可保留窗口。
planner 保存采用 base_revision 冲突检查；图片缓存关闭等待实际下载线程，事件日志写失败在采集页可见。
2026-10-23 补齐配置读取失败禁止写回、Store 内关联表原子提交、退出保存等待预算与串行重试；数据目录不可用明确报错。
退出预算覆盖 JS 派发本身与窗口几何保存；明确放弃使用进程终止，避免解释器继续等待阻塞的请求线程。
2026-10-23 已用 Playwright 连接真实 WebView2 复验正常退出、28 秒 JS 阻塞后的超时恢复、窗口几何保存阻塞后的重试，以及阻塞请求下明确放弃后的进程退出；72 项相关回归通过。
确认框选择使用测试替身，未覆盖原生按钮点击；物理慢盘、断电及打包态仍未验收，不能据本轮结果宣布发布完成。
家园 actor_id 已按字符串传输并验证 JSON→JS 精度；迁页 DTO 做运行校验，不能用 TS 断言掩盖错误。
2026-10-22 复核已补齐 R01–R12 中确认的库恢复、快照/flush、命令串行、关闭重试、后台任务和草稿顺序问题；慢盘、真实 WebView2、真实多账号抓包仍需实机证据。
[运行时修复复验](reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md)：装配与前轮回归保留，
E01–E06 已修（HTTP 短状态读取、嗅探器退出确认、可重试停止所有权与下游保护、错误分类、缺 Node 门禁）。
历史 review 中的测试数量和门禁结果只代表当次快照，不作为当前完成度。当前验证命令和任务状态只维护在 [路线图](ROADMAP.md) 与 [开发指南](DEVELOPMENT_GUIDE.md#测试)。

高风险区域：坏库恢复和迁移、并发批量落盘、采集启停、会话接续、账号切换、完整/历史仓库语义、资源导入与发布。修改前明确输入证据、状态所有者、失败/停止方式与验收。

`web/static/app.js`、`web/server.py`、`web/payloads_catalog.py` 是职责增长集中区。
新增页面先设计独立页面模块和对应载荷/路由；纯规则放 domain，副作用由 service/repository/adapter 承接。
每次抽取保持原行为与异常路径可验证，避免建立平行状态或空壳抽象。

PacketEvent 已在 events 叶子模块，domain→services 类型依赖已移除；CaptureService 已承接抓包源、录制、密钥与运行命令。
PetRepoSnapshot/PetView 已覆盖列表/选项、REST/WS 的宠物字段，bootstrap 共享一次快照；
F01 的快照契约已覆盖列表、选项、REST、WS 与 bootstrap；离线 uid 表示归属且不冒充实时 identity。
蛋图鉴由 frontend/src/pages/EggDexPage.vue 独占，旧页面脚本已退出。
剩余过渡边界包括 domain/protocol 的资源加载 IO、VM 安装/探测线程、routes mixin 的宿主依赖，
F02 已补齐蛋仓/家园单次快照、跨域归属核对与原生页旧请求失效；历史孵化与未知明确区分，真实多账号抓包仍待实机。
F03 已迁完整宠物页，Vue 独占筛选、请求、两视图、箱队、详情与快捷管理状态和 DOM；统一人工验收见 [F03 清单](reviews/F03_ACCEPTANCE_2026-10-13.md)。
这些现状不能作为新增反向依赖的理由。

构建前置与本轮证据见 [前端开发](FRONTEND_DEVELOPMENT.md) 和 [Vue 实施验证](reviews/VUE_EGG_DEX_VERIFICATION_2026-10-13.md)。

具体实现主要由 GLM 3.8f 承接，Codex 负责架构、路线与复核；交接使用开发指南模板，
一次推进一个可独立验收的路线图编号，完成状态附代码与验证证据。

用户可见功能与启动方式维护在根 README；协议适配见 [协议笔记](PROTOCOL_NOTES.md)，UI 变更见 [UI指南](UI_GUIDE.md)。复杂业务未知项应记录为未知，历史缓存不能当本次实时确认。
