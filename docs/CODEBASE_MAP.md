# 代码地图

文件级速查；新增文件须同步本表。必要回归与开发/发布验证范围见 [开发指南](DEVELOPMENT_GUIDE.md#测试)。

界面形态：**只有 Web 一套**（pywebview 窗口 + 本地服务 + 原生 JS 前端）；
历史 PyQt 原生界面已于 2026-10 退役，`requirements.txt` 不再含 PyQt6。
Vue 3 + TypeScript + Vite 工程与蛋图鉴已落地；构建前置见 `FRONTEND_DEVELOPMENT.md`，后续迁页见 `VUE3_MIGRATION.md`。

## 根目录

| 文件 | 职责 |
| --- | --- |
| `AGENTS.md` | 仓库协作规则与必读入口 |
| `main.py` | 入口转发到 `spritelens.main:main` |
| `start.bat` | 双击启动界面（pythonw，无控制台窗口） |
| `start_silent.vbs` | 零窗口启动（wscript 直接跑 pythonw，cmd 不闪窗） |
| `start_debug.bat` | 前台控制台启动（看错误输出用） |
| `build.bat` + `build.py` + `build_config.toml` | Nuitka 打包（配置驱动；`--dry-run` 只打印命令） |
| `requirements-build.txt` | 打包依赖（nuitka / ordered-set / zstandard），运行程序不需要 |
| `tools/create_shortcut.bat` + `ps1` | 创建桌面快捷方式（幂等，ps1 用 $PSScriptRoot 自定位） |
| `requirements.txt` | scapy / pycryptodome / aiohttp / pywebview（无 UI 框架之外的额外依赖） |
| `tools/import_schema.py` | 导入外部 schema 全集到 data/schemas（本地目录或 GitHub） |
| `tools/import_account_avatars.py` | 固定版本游戏名片头像配置与 ID 映射同步；运行时头像按需缓存 |
| `tools/import_static_data.py` | 导入基础静态表（物种/性格/系别/技能）到 data/static |
| `tools/import_assets.py` | 导入图鉴元数据 + 精灵图 + 系别图标 + 系别克制表 |
| `tools/import_egg_data.py` | 导入蛋目录（蛋组/孵化时长/公母比/身高体重/进化链）到 data/static/eggs.json |
| `tools/import_egg_icons.py` | 按道具 ID 从 wiki 资源站补缺失蛋图标（无损 webp，来源与 SHA-256 写入 resource_sync_report.json） |
| `tools/import_pet_details.py` | 补全静态数据：图鉴描述并入 species.json（+sum 重算修正）、补技能名、奖牌表、蛋/奖牌图标 |
| `tools/import_world_maps.py` | 从解包资源导入两张世界地图底图与坐标 manifest：固定来源哈希/尺寸/原点边长，暂存校验后发布，失败保留旧产物 |
| `tools/sync_catalog_resources.py` | 官方目录/镜像同步：保留有效值的 ID 合并、镜像校验、可重复导入并出报告（resource_sync_report.json） |
| `tools/sync_pet_media.py` | 按官方 manifest 导入头像/立绘并写入媒体映射；稀有标记图标由 `rarity/` 资源单独维护（幂等，报告 pet_media_report.json） |
| `tools/sync_ui_icons.py` | 按固定官方 Git 版本导入少量 Tabler SVG 图标并合成 sprite（开发期联网，运行期零网络） |
| `tools/analyze_recording.py` | 录制文件离线分析（帧分类/opcode 分布/宠物形状） |
| `tools/backfill_egg_origins.py` | 回放事件日志补录历史收蛋来源：默认只读预览，`--apply` 写库前检查应用是否已退出 |
| `tools/run_web_demo.py` | 带合成数据的界面实例（浏览器打开，视觉验收用；含一条收蛋来源链路数据） |
| `tools/make_icon.py` | 生成 `resources/app.ico` 多尺寸图标与 favicon（PIL，产物入库） |
| `resources/app.ico` | 应用图标（窗口/任务栏用，打包时随包分发） |
| `resources/icon_source.png` | 已确认的好奇版头像源图，供 `tools/make_icon.py` 派生 ICO 与 favicon |
| `spritelens/web/desktop_shell.py` | 自绘标题栏 JS 桥、WebView2原生拖动区域、保留系统动画的窗口消息回调、原生状态、最大化工作区与边缘缩放、恢复后WebView2尺寸重同步 |
| `spritelens/web/startup_cover.py` | 桌面启动唯一可见面板：静态图标与文案，首屏就绪才揭开；失败/20 秒超时原地重试，closing 释放资源 |
| `spritelens/web/static/desktop-shell.js` / `desktop-shell.css` | 桌面顶栏、窗口操作与缩放边缘；浏览器模式隐藏 |
| `data/schemas/` | 外挂 schema：`opcodes.json` + `messages/*.json`（字段级合并） |
| `data/static/` | 静态映射：`species/natures/types/skills/type_chart/eggs/medals/specialities/color_cards.json` + 各 `_meta.json`；世界地图清单见 `world_maps.json`；特性来源见 `_specialities_meta.json` |
| `spritelens/web/static/` | 前端资源：`index.html`（分组导航骨架）/ `boot.js`（启动自恢复链）/ `app.css`（布局与组件 token）/ `themes.css`（三套主题色值）/ `app.js`（数据渲染）/ `ui.css` / `ui.js`（详情抽屉、键盘与焦点）/ `appearance.js`（主题与显示偏好）/ `icons.js` + `icons/`（本地 SVG sprite）/ `favicon.png` / `pet-media/`（官方原始头像与全身图）/ `type-icons/` `egg-icons/` `medal-icons/`（奖牌及标记图标）/ `rarity/` `color-cards/` / `maps/`（世界地图底图，C13-01） |
| `spritelens/web/account_avatar_cache.py` | 游戏名片头像 ID 映射、云端按需下载与用户数据目录缓存；失败由前端回退 Logo |
| `data/recordings/` | 运行时录制产物（gitignore；本地回放样例不在版本库） |

## 维护与审查文档

| 文件 | 职责 |
|---|---|
| `docs/AI_CONTEXT.md` | 新开发者/AI快速上下文与当前风险导航 |
| `docs/HANDOFF_DEEPSEEK_2026-10-24.md` | 2026-10-24 数据库数据恢复、伙伴标记和未完成改动交接 |
| `docs/ROADMAP.md` | 已落实范围、待办顺序与验收；唯一持续任务状态入口 |
| `docs/reviews/MEMORY_PERFORMANCE_HANDOFF_2026-10-24.md` | 内存/性能审查证据与 PERF01–PERF07 修复交接；任务状态只在 ROADMAP 维护 |
| `docs/reviews/MEMORY_PERFORMANCE_VERIFICATION_2026-10-25.md` | PERF 系列独立复核、性能对照与验收限制；含 PERF05 尾批引用释放返修及复验证据 |
| `docs/archive/ROCO_RESOURCES_ANALYSIS.md` | `roco_resources` 解包/逆向报告的功能对照、参考路径和候选实施清单；不代表当前已实现 |
| `docs/HOME_IMPLEMENTATION_PLAN.md` | Luna6 家园编码规格、数据边界和逐切片验收；不代表修复已完成 |
| `docs/VUE3_MIGRATION.md` | 已确认的 Vue 前端工程/接口/状态与渐进迁移决策；不代表已实现 |
| `docs/reviews/PROJECT_REVIEW_2026-10-12.md` | 基于114be08的审查快照、复现证据与资源/文档风险；不代表已修复 |
| `docs/reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md` | 基于240b94c的改动复核、确定性复现与完成范围校正 |
| `docs/reviews/GLM_DELIVERY_REVIEW_2026-10-13.md` | 基于a106044的交付复核、启动/并发/生命周期/HTTP 返修证据与门禁边界 |
| `docs/reviews/GLM_RECHECK_2026-10-13.md` | 基于477bd75的返修复核、已修范围及事件循环/停止/失败语义剩余证据 |
| `docs/reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md` | E01–E06 的本轮实现、受控回归与真实装配复验边界 |

本表只列当前源码中的稳定入口；路线图中尚未落地的路径不会写入本表。

## spritelens/

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 版本、APP_NAME、APP_DISPLAY_NAME |
| `__main__.py` | `python -m spritelens` 入口（转发到 `main:main`） |
| `paths.py` | 数据目录解析（SPRITELENS_DATA_ROOT 可覆盖）+ 打包态资源根（frozen/_MEIPASS） |
| `main.py` | CLI：--smoke-test / --list-ifaces / --replay / --diagnose-net / --web-browser / 界面启动 |
| `app_context.py` | **装配根**：管线/库/VM/清理的一次性组装（autostart 在此触发）；蛋目录优先读用户数据目录里的快照版本，缺失时退回随包 `data/static/` |
| `events.py` | 中立叶子模块：`PacketEvent` 事件类型（无 IO 无依赖；protocol/domain/services 共用，避免层间反向引用） |
| `protocol/frames.py` | GCP 21B 大端头切帧、假 magic 同步、FrameStream |
| `protocol/crypto.py` | AES-128-CBC 固定 IV 解密/加密、ACK 密钥提取 |
| `protocol/records.py` | Direction、tsf4g trailer 剥离、s2c/c2s 拆分 |
| `protocol/wire.py` | protobuf wire 字段号树（嵌套从严判定） |
| `protocol/schema.py` | schema 库加载、双路解码与降级 |
| `protocol/opcodes.py` | opcode → 名称/分类/消息名目录 |
| `capture/base.py` | CaptureSource 协议、StreamChunk、SourceError |
| `capture/reassembly.py` | TCP 流重组（乱序/重传/全零段回滚/空洞；交付历史只留最近 256KB，纯逻辑） |
| `capture/npcap_source.py` | scapy AsyncSniffer 接入（轻量回调 + 队列 + worker 投递；FIN/RST/空闲淘汰释放流，关闭事件经队列保序） |
| `capture/nic_rank.py` | 活跃网卡识别与排序（Get-NetAdapter Status=Up → 设备列表前置） |
| `capture/key_store.py` | 密钥解析与持久化：latest.key + session.json v1 的逐连接集合（flow/密钥/身份/服务端序号/关闭标记，原子写） |
| `system/environment.py` | Npcap 检测与抓包网卡 RSC 判定（默认路由/显式选择，虚拟网卡不参与）、官方版本解析；PowerShell 首选下载、Python 回退、PE 校验、等待安装器退出 |
| `system/webview_guard.py` | WebView2 运行时预检测（注册表/env）+ 缺失时原生对话框引导安装 |
| `system/window_geometry.py` | 初始窗口尺寸：工作区 + 系统 DPI 缩放适配（fit_window 纯函数） |
| `system/single_instance.py` | 单实例控制：命名互斥锁 + 唤醒事件 + Win32 强制置顶；后台采集与主界面使用不同实例标识 |
| `system/game_process.py` | Windows 进程枚举、进程创建事件 4688 任务计划程序的安装/移除与后台启动命令 |
| `system/runtime_session.py` | 后台采集与按需主界面之间的本机运行时地址交接文件 |
| `system/tray.py` | 无第三方依赖的 Windows 通知区域图标与打开/退出动作 |
| `system/net_diagnose.py` | --diagnose-net：宽抓会话统计，定位多连接的数据端口 |
| `domain/pets.py` | 宠物语义层：形状搜索提取 PacketEvent → Pet 对象（含六维/技能/外观/佩戴奖牌；默认排除试用与好友镜像个体） |
| `domain/identity.py` | 玩家身份语义层：登录 player_info/brief_info 与场景 self_info/avatar/base → PlayerIdentity（uid 归属） |
| `domain/static_data.py` | 静态映射：物种/性格/系别/技能/奖牌（base_conf_id 关联，含图鉴元数据与进化链成员） |
| `domain/measurements.py` | 参考范围工具：cm/g → m/kg 文案、范围位置比例与越界状态（纯函数） |
| `domain/pet_marks.py` | 紧凑标记：体型大/小、声音粗/婉（含佩戴奖牌来源），组内互斥最多两项；另含蛋的声音遗传取平均（`egg_voice`）与奖牌标签（`voice_tags`） |
| `domain/pet_locations.py` | 真实箱位：Backpack/PetBox（30 格箱表 + 3×6 队伍 + 移动增量 + v2 快照恢复） |
| `domain/eggs.py` | 蛋目录：蛋静态数据索引（egg_conf_id / base_id 联查，孵蛋工具链底座）；活动蛋等变体配置按 pet_conf_id // 1000 回退同族蛋，仅补展示字段 |
| `domain/color_cards.py` | 色卡目录：44 张卡（底色×混色）+ glass→卡号判定（赛季 s1-s4） |
| `domain/egg_box.py` | 蛋仓语义层：形状搜索提取 PacketEvent → EggBoxEntry（bagType==8 指纹） |
| `domain/home.py` | 家园语义层：0x014A 双布局快照 + 0x0413/0x0414 已识别增量 → 居民/物种/家具/窝位/配对/场景蛋 |
| `domain/home_breeding.py` | 家园关系过期时，按巢穴边缘距离及已知性别/蛋组生成候选 |
| `domain/display.py` | 展示常量：系别配色、六维标签、天赋阶配色（框架无关） |
| `repositories/database.py` | SQLite 底座：schema 1 完整基线初始化与结构校验；已知 `pets.partner_mark` 单列追加走原地迁移，其余不兼容结构仅在库内无数据时按主库/WAL/SHM 成组备份后重建，库内已有数据则停止启动并保留原文件；备份失败同样保留原文件 |
| `repositories/pet_store.py` | 宠物持久化网关：write-behind 批量落盘 + 读取（适配器模式） |
| `repositories/egg_store.py` | 蛋仓持久化网关：write-behind 批量落盘，按 uid 读取蛋、孵化槽与性格/蛋窝/声音标签/手动声音标注 |
| `repositories/settings.py` | JSON 配置仓库（读取失败阻止写回、替换成功才更新缓存、字段归一、窗口几何） |
| `services/monitor_service.py` | 采集管线编排：字节流 → 帧 → 解密 → 解码 → PacketEvent；会话释放/空闲回收/硬上限 |
| `services/capture_service.py` | 采集运行服务：接入层创建与生命周期、录制 tee、手动密钥、副作用命令串行化（阶段1.3 自 capture_vm 抽出） |
| `services/game_capture_automation.py` | 游戏进程自动监听设置：保存跟随状态、安装/移除 4688 触发任务 |
| `services/session_tracker.py` | 会话表（LRU，支持 drop）与全局统计 |
| `services/account_tracker.py` | 账号切换判定；display_uid 是已加载/实时归属，写路径 uid 不变（同 uid 重复帧/离线加载登录不算切换） |
| `services/account_selection_service.py` | 账号列表与采集中切换查看；历史数据先读完，失败保留选择 |
| `services/account_sessions.py` | M01：连接身份路由、每账号业务仓库、稳定展示视图与选择所有权 |
| `services/pet_repository.py` | 宠物聚合、身份/切号、彩名学习与入库；consistent_snapshot 单次取齐宠物/箱位/位置/uid/version，声音只保留抓取值 |
| `services/egg_repository.py` | 蛋仓聚合；EggBoxSnapshot 一次取齐条目/槽/uid/version/历史来源，恢复 IO 竞争拒绝提交 |
| `services/catalog_update.py` | 目录增量更新的扩展点（游戏增量更新层 2）：CatalogStore 版本快照 + 原子指针 + 回滚，CatalogSource 协议（默认禁用、不联网），CatalogUpdater 编排 check→fetch→校验→安装，失败保留旧版本 |
| `tests/test_catalog_update.py` | 快照切换与回滚、sha256/结构校验失败时保留旧版本、更新源不可用不落半成品、未配置更新源时状态为 disabled |
| `services/egg_pickup.py` | 同账号、同连接的收蛋请求与奖励关联；保存收取前小窝、关联母本和候选父本快照 |
| `tests/test_egg_pickup.py` | 收蛋归属、并行歧义、刷新/重启与写失败重试、学院窝性格回归 |
| `services/egg_origin_backfill.py` | 事件日志回放：跨分片按 ts 归并，复用家园快照与收蛋关联规则产出历史收取来源；只读、不写库 |
| `tests/test_egg_origin_backfill.py` | 日志行解析与坏行跳过、跨分片归并、回放关联、未匹配奖励计数、pickup 只合并不覆盖 |
| `services/home_repository.py` | 家园聚合（快照覆盖 + 切号清空 + 增量帧版本提示） |
| `services/event_logger.py` | PacketEvent JSONL 异步落盘（有界队列 + worker 批量写，按天分片，复盘用） |
| `recording/recorder.py` | StreamChunk jsonl 录制/读回 |
| `recording/replay.py` | ReplaySource + CLI 回放摘要输出 |
| `logs/local_logger.py` | 双文件 RotatingFileHandler + 崩溃兜底 `install_excepthook`（crash.log） |
| `view_models/pet_vm.py` | 宠物 VM + 请求级 PetView；后者持一致快照在锁外筛选/排序/选项/统计，身份与 uid/version 同源 |
| `view_models/ui_preferences.py` | UI 偏好 VM：主题/视图/显示字段/快捷条件白名单校验与快照 |
| `view_models/capture_vm.py` | 采集页 VM（Npcap 安装状态机、自动采集开关、偏好持久化、快照组装；运行命令委托 capture_service） |
| `web/server.py` | 本地服务：aiohttp，仅回环 + 随机端口 + token 鉴权 + WS 推送；数据/偏好路由与 bootstrap，采集域路由由 routes_capture mixin 提供 |
| `web/background.py` | 受控同步后台 runner 的 AppKey 与独立路由 fallback；生产任务由 LocalServer 跟踪并在停止时等待 |
| `web/routes_capture.py` | 采集域路由与载荷（/api/capture*、/api/state、capture/state 载荷；阶段1.4 自 server.py 拆出） |
| `web/routes_accounts.py` | `/api/accounts` 与 `/api/accounts/select`：账号列表、切换查看与结果 |
| `web/server_helpers.py` | HTTP query 解析助手（路由模块共用） |
| `web/egg_icon_cache.py` | 蛋图标按需补图：安装包优先，缺图时按道具 ID 从素材站下载一次并缓存到用户数据目录；404 负缓存、失败静默降级占位 |
| `tests/test_egg_icon_cache.py` | 补图只请求一次、安装包优先、非法名不发请求、404 负缓存、异常来源不落盘 |
| `web/run.py` | 界面入口：pywebview 窗口（系统 WebView2）+ 单实例唤醒 + 降级提示；支持按需打开后台采集的远程界面 |
| `web/background_run.py` | 按需后台模式：游戏进程存在期间启动采集、托盘打开主界面、游戏退出后清理 |
| `web/close_coordinator.py` | 桌面关闭握手：等待页面保存确认、采集停止与缓存 flush；失败保留窗口或显式放弃 |
| `web/payloads.py` | 宠物域载荷（宠物行/列表页/箱位/WS 状态统计）+ 目录域兼容重导出（无 UI 依赖） |
| `web/payloads_catalog.py` | 目录域载荷：图鉴/色卡/家园/蛋仓/蛋图鉴（阶段1.4 自 payloads.py 拆出）；蛋仓行额外输出 `pickup.mother/fathers[].icon_url` 与声音推算 `voice_prediction` |
| `web/account_state.py`、`web/static/account-requests.js` | F02：state 跨域归属核对与原生账号页请求取消/代次/序号/uid/域版本校验 |
| `web/pet_media.py` | 物种 ID → 本地头像/立绘 URL（pet_media.json；缺图映射到同源图片路由） |
| `web/pet_media_cache.py` | 精灵图本地优先；缺失时按需校验、转码、缓存官方 CDN 图片并记录哈希 |
| `frontend/src/pages/EggDexPage.vue`、`pages/EggDexPage.test.ts`、`components/`、`composables/useEggDex.ts` | 蛋图鉴展示、固定分页/筛选/详情与请求生命周期；局部状态、卸载/取消与代次失效 |
| `frontend/src/pages/EggBoxPage.vue`、`components/EggBox*.vue`、`composables/useEggBox.ts`、`types/eggBox.ts` | 精灵蛋仓列表/详情、筛选/排序、数值范围展示与 REST DTO 校验；请求归属由原壳桥接 |
| `frontend/src/pages/HomePage.vue`、`pages/home.css`、`composables/useHome.ts`、`types/home.ts` | 家园居民搜索、房间/窝/家具观察视图；home DTO 运行校验与账号版本桥接 |
| `frontend/src/homeBridge.ts` | 家园 Vue 生命周期桥：挂载/暂停/恢复/切号重置；账号请求仍由旧壳拥有 |
| `tools/import_egg_inventory.py`、`data/static/egg_inventory*.json` | 蛋仓专用道具/蛋配置/随机蛋索引与导入哈希；游戏配置和 Wiki 变体分开记录，不扩充蛋图鉴展示列表 |
| `frontend/src/components/PetBasicFilters.vue`、`composables/usePetFilters.ts`、`types/petFilters.ts` | F03 第一刀：基础筛选的唯一状态/DOM 所有者、防抖与 options 运行校验；相关 Vitest 同目录 |
| `frontend/src/petFilterBridge.ts` | 原生页查询/恢复/清理/请求失效桥；卸载与重新挂载由相关轻量回归验证 |
| `frontend/src/components/PetFiltersPanel.vue`、`PetAdvancedFilters.vue`、`PetShortcuts.vue` | 完整筛选、顶部AND/OR匹配与快捷追加；扩展状态在 usePetAdvancedFilters，条件运行契约在 types/petConditions.ts |
| `frontend/src/components/DualRangeSlider.vue` | 等级、体型、声音与百分比共用双头滑动条；仅持有拖动量程，筛选状态仍在对应composable |
| `frontend/src/components/PetDetail.vue`、`PetDetailPanel.vue` | 完整详情、定位、键盘/焦点与窄屏交互；布局按需目视验收 |
| `frontend/src/composables/usePets.ts`、`types/pets.ts`、`petInventoryBridge.ts` | F03：请求与账号票据/DTO、快照/两视图/分页/箱队/选择；账号/偏好与应用壳桥 |
| `frontend/src/components/PetInventory.vue`、`PetSlots.vue`、`PetBoxNavigation.vue` | 两视图、加载/错误重试、真实箱位/队伍、分页、键盘/焦点；Vue 独占节点 |
| `frontend/src/components/PetAvatar.vue`、`PetMarks.vue`、`petDisplay.ts` | 安全模板展示本地头像/立绘、色卡/粒子、稀有/奖牌及 UI 格式；不复制 Python 业务规则 |
| `frontend/src/petTestData.ts`、`composables/usePets.test.ts` | 合成数据、异步/账号/DTO/槽位回归 |
| `frontend/src/api/client.ts`、`types/eggDex.ts` | 同源 token/取消/错误归一与页面 DTO 运行校验 |
| `frontend/src/main.ts`、工程配置/锁文件 | memory Router/Pinia 装配、蛋图鉴/蛋仓/家园页面挂载、strict TS/Vite 与必要 Vitest 回归；无 ESLint/Playwright |
| `tools/frontend.py`、`web/frontend_assets.py` | 暂存构建/专用目录发布、源指纹及运行产物清单/哈希校验 |
| `tests/test_frontend_contract.py` | JSON→JS ID 精度与构建负例 |
| `tests/test_desktop_startup.py` | 原生拖动设置、正常窗口边界保存、带桌面标识的重试 URL 与销毁后交接 |
| `tests/test_pet_snapshot_contract.py` | F01：读取后切号，列表/选项/REST/WS 与 bootstrap 的单响应同源、离线归属 |
| `tests/test_account_domain_contract.py`、`tests/test_account_requests.py`、`tests/account_requests_cases.js` | F02：切号交错、历史语义、恢复竞争与原生页请求失效 |

## tests/（unittest 平铺）

| 文件 | 覆盖 |
| --- | --- |
| `_synth.py` | 合成帧生成器（确定性 trailer、protobuf 载荷） |
| `test_frames.py` | 切帧：粘包/跨段/假 magic/超长守护 |
| `test_crypto.py` | 解密 roundtrip、key 提取、非法长度 |
| `test_records.py` | trailer 剥离、s2c 锚点、c2s 偏移 |
| `test_wire.py` | varint/嵌套/截断/二进制保留 |
| `test_schema.py` | schema 加载、双路解码、opcode 目录 |
| `test_reassembly.py` | 顺序/乱序/重复/全零段回滚/空洞/交付历史窗口裁剪 |
| `test_monitor_service.py` | 管线端到端（key 捕获、续解、隔离、统计、会话释放与回收） |
| `test_npcap_source.py` | 抓包线程逻辑（分类/入队/队列满丢弃/worker 投递/关闭事件保序/流淘汰） |
| `test_recording.py` | 录制 roundtrip、坏行跳过、回放一致性 |
| `test_pets.py` | 形状提取、仓库合并、schema→管线→聚合端到端、v2 扩展字段 |
| `test_pet_vm.py` | 宠物 VM：搜索/多维筛选组合与排序 |
| `test_static_data.py` | base_conf_id 与 conf_id 的区分、坏表不影响其它数据 |
| `test_eggs.py` | 蛋目录关联索引与蛋组/类型/孵化时长/搜索筛选 |
| `test_egg_box.py` | 蛋仓：形状搜索提取/拒收、聚合去重、SQLite roundtrip、写-behind 落盘、跨账号隔离与载荷联查 |
| `test_egg_origin_backfill.py` | 历史补录：事件日志解析/坏行跳过、跨分片按 ts 归并、回放关联母本与候选父本、未匹配奖励与 pickup 只合并不覆盖 |
| `test_home.py` | 家园：居民/家具/窝提取、聚合与增量计数 |
| `test_desktop_shell.py` | DPI/工作区适配、保存的宽高比例与多屏位置恢复 |
| `test_app_icons.py` | 窗口大小图标消息、64 位句柄与图标加载失败回归 |
| `test_single_instance.py` | 单实例互斥锁唯一性、唤醒事件投递与消费、close 幂等 |
| `test_game_automation.py` | 内置游戏进程名、4688 触发任务 XML、跟随状态配置与运行时交接文件 |
| `test_persistence.py` | 身份识别（NPC 不误取）、写库/重开/加载、跨账号隔离、schema 1 基线结构与旧库拒绝、外观字段往返、彩名恢复、损坏恢复 |
| `test_settings.py` | 配置读取失败/非法 JSON 阻止写回，原子替换失败保持磁盘与内存原值 |
| `test_view_models.py` | 手动密钥、采集/录制命令串行化、配置/录制失败与自动采集开关 |
| `test_runtime_repair.py` | 慢保存 HTTP/WS、停止所有权/下游保护、嗅探器退出与错误分类 |
| `test_pet_locations.py` | 箱位：登录映射、空箱/部分箱、槽位匹配状态、队伍归属与槽序、切号/重启、历史与实时去重 |
| `test_asset_cache_lifecycle.py` | 精灵媒体与账号头像缓存的关闭任务回收 |
| `test_pet_presentation.py` | 尺寸/声音标记边界、旧快捷偏好迁移与色卡解码 |
| `test_multi_account_capture.py` | M01：双开交替更新、未知归属拒收、采集中选择、历史读取竞态、逐连接重启/重连与单边关闭 |
| `test_session_resume.py` | 会话接续：服务端帧确认、流/密钥/序号不匹配、新握手与关闭失效、损坏缓存 |
| `test_ui_upgrade.py` | 偏好鉴权/并发/写失败、快捷迁移/校验、范围/组合筛选与资源合并 |
| `test_crash_log.py` | pythonw 主线程/后台线程崩溃落盘 |
| `test_paths.py` | 打包态资源定位：源码/frozen/_MEIPASS 三分支、数据目录不受打包影响 |
| `test_web_server.py` | REST/WS 鉴权、启动回收、请求串扰、采集输入/写失败与图鉴筛选 |
| `test_build.py` | Nuitka 发布命令包含管理员权限开关 |
| `test_world_maps.py` | C13-01 世界地图 manifest：图片尺寸/哈希/来源指纹、原点/边缘/留出点投影、负原点不钳制、坏源与改坐标失败、静态目录打包包含；C13-02 运行时清单载荷与 `/api/world-maps` 路由（200 子集、缺文件 503、no-store） |
| `test_browser_open.py` | 设置页浏览器调试入口：鉴权、当前服务 URL 与浏览器打开失败 |
| `test_environment.py` | 启动 quick 探测不调用慢 RSC 检查、RSC 只判定抓包网卡（默认路由/显式选择，虚拟网卡不误报、查不到时不谎报已关闭）、Npcap 版本数字排序、PowerShell/Python 下载回退与安装器等待 |
| `test_event_logger.py` | 异步落盘、关闭 flush、过载计数与关闭超时所有权 |

## 三主题与资源补齐（2026-10-12）

| 文件 | 责任 |
|---|---|
| `domain/measurements.py` | cm/g参考范围转m/kg、范围位置与越界状态 |
| `view_models/ui_preferences.py` | 主题/视图/显示字段白名单、非法配置降级与严格保存 |
| `web/static/themes.css` / `appearance.js` | 三套浅色主题、即时切换、显示选项与保存反馈 |
| `web/static/icons.js` / `icons/` | 本地Tabler SVG与sprite，40枚Tabler图标（sprite共44个symbol，含4个手工图标）和MIT来源清单 |
| `tools/sync_catalog_resources.py` | 保留有效值的ID合并、官方镜像校验、可重复资源导入与报告 |
| `tools/sync_ui_icons.py` | 固定官方Git版本的少量SVG导入，无运行时网络依赖 |
| `tests/test_ui_upgrade.py` | 偏好鉴权/并发/失败、快捷与筛选规则及资源合并回归 |
| `docs/archive/README.md` | 历史分析、计划、资源快照与验收记录的归档边界；不作为当前实现依据 |
| `docs/archive/RESOURCE_COVERAGE_REPORT.md` | 1060物种、646组范围、224蛋、477别名；缺图/缺字段/冲突 |
| `docs/BREEDING_PLANNER_SPEC.md` / `COLLECTION_LINES_SPEC.md` | F04-U5智能配窝规格与当前实现边界（双入口/宽容双牌/联合摆位） / 双牌产线实现与参考规则边界 |
| `domain/collection_lines.py` / `services/collection_lines_service.py` / `view_models/collection_lines_vm.py` | 产线目录与纯规则、单账号快照、进度统计 |
| `web/collection_lines.py` / `frontend/src/pages/CollectionLinesPage.vue` | 鉴权产线 API、Vue 产线列表与父母详情 |
| `domain/breeder_library.py` / `view_models/breeder_library_vm.py` | F04-U4 筛选配对纯规则、当前账号单次库存快照、双向候选与分页；无新增持久化 |
| `web/breeder_library.py` | `/api/breeder-library` 查询边界、亲本 DTO 与参考预测序列化 |
| `frontend/src/pages/BreederLibraryPage.vue` / `pages/breeder-library.css` / `components/BreederCard.vue` | 公母双列表、固定筛选／配对右栏、亲本卡及窄窗布局 |
| `frontend/src/composables/useBreederLibrary.ts` / `types/breederLibrary.ts` / `breederLibraryBridge.ts` / `web/static/breeder-library-page.js` | 筛选与选择唯一状态、请求失效／账号校验、运行时 DTO 和迁移桥 |
| `tests/test_breeder_library.py` / `frontend/src/composables/useBreederLibrary.test.ts` | 配对正确性、未知值／抓取声音、分页、鉴权、乱序／离页／切号与失败重试 |

新增API：鉴权GET/POST `/api/ui/preferences`，bootstrap新增`ui_preferences`。
`/api/pets`新增egg_groups、egg_mode和height/weight/voice_min/max；原有字段兼容。

## 背包操作与真实登录数据（2026-10-12）

| 文件 | 责任 |
|---|---|
| `domain/pet_locations.py` | Backpack/PetBox：完整30格箱表、普通3×6队伍、移动增量；区分零空格与未采集，排除客户端请求和特殊队伍，兼容旧位置快照 |
| `repositories/pet_store.py` | 当前佩戴奖牌与按账号Backpack v2快照异步落盘/恢复，沿用pet_locations表 |
| `tests/test_pet_locations.py` | 登录协议映射、真实空箱/部分箱、固定槽匹配状态、普通队伍归属/槽序、切号/重启及历史与实时位置去重、登录后WebSocket推送回归 |
| `tests/test_session_resume.py` | 原会话重启接续、服务端帧确认、流/密钥/序号不匹配、新握手/关闭失效及损坏缓存回归 |
| `docs/archive/SESSION_RESUME_VERIFICATION.md` | 会话关联保存、原始录制接续与界面状态验证；空箱隐藏/未知入口删除的后续验收 |
| `docs/archive/BACKPACK_UPGRADE_VERIFICATION.md` | 真实样本、角色更新修复、测试结果及未完成的视觉验收 |

偏好增加 `fields.positions` 与最多六组 `shortcuts` 定义；查询增加
`height_position_min/max`、`weight_position_min/max`，排序增加身高/体重/声音。
宠物载荷兼容增加 `location`、`worn_medal_id/name` 与 `is_colorful`。

### F03-U1 定稿界面落点

| 文件 | 职责 |
|---|---|
| `spritelens/domain/pet_conditions.py` | 全局AND/OR、异色炫彩/奖牌/参考快捷标记筛选，复用既有物种参考与卡片规则 |
| `spritelens/web/pet_queries.py` | 新增筛选参数的 HTTP 输入边界；无共享状态写入 |
| `spritelens/web/static/account-card.js` | 账号卡片、真实头像、UID 隐藏与本地历史账号管理浮层；切号请求交给账号 API |
| `spritelens/web/static/backpack-layout.css` | 定稿应用壳/宠物页布局、工具条与响应式几何，复用主题 tokens |
| `tests/test_pet_ui_conditions.py` | 全局 AND/OR、真实奖牌与参考标记区别、非法查询拒绝 |
| `frontend/src/components/PetShortcutSettings.vue` | 原生dialog快捷设置：分组勾选具体选项、草稿、保存和关闭；沿用现有快捷偏好边界 |
| `tests/test_pet_acquisition.py` | PetData获得字段、简略更新保留已知信息、未知日期与全局AND/OR |

新增本地 Tabler eye/eye-off/square/chevron-down 图标列入 `icons/sources.json` 与 `tools/sync_ui_icons.py`，沿用固定来源提交和MIT许可。

### F03-U3 精灵详情

| 文件 | 职责 |
|---|---|
| `frontend/src/components/PetDetailPanel.vue`、`PetDetail.vue` | 与筛选共用360px右栏、窄窗抽屉、焦点/连续浏览、正文滚动与低优先级获取信息 |
| `PetDetailHero.vue`、`PetArtwork.vue` | 详情身份叠加；独立立绘展示与同URL复用，原图按整张立绘卡片宽度70%等比居中 |
| `PetDetailStats.vue`、`PetMeasurementRow.vue` | 六维与已含加成、精灵/精灵蛋数值范围 |
| `PetDetailMedals.vue`、`PetDetailEvolution.vue`、`pet-detail.css` | 横向获得奖牌、真实头像分支进化、限定背包的主题与响应式样式 |
| `spritelens/domain/pet_medals.py` | 登录集合按获得精灵归属；未核验增量失效相关集合 |
| `spritelens/web/pet_details.py` | 既有宠物与静态资料生成详情DTO，不另读仓库 |
| `tests/test_pet_detail.py` | 获得/佩戴归属、未知/空集合、合并落库与详情契约 |

## 本地 Wiki 图鉴补充（2026-10-19）

| 文件 | 职责 |
| --- | --- |
| `tools/import_wiki_reference.py` | 从四份 Wiki Lua 数据模块生成暂存补充目录，记录来源 URL/哈希；不执行 Lua |
| `data/static/wiki_reference.json` | 离线技能、特性、进化、分布及特殊蛋来源快照 |
| `spritelens/domain/wiki_reference.py` | 游戏 ID/名称匹配与只读补充资料联查 |
| `frontend/src/types/wikiReference.ts` | 图鉴补充 DTO 与接口边界校验 |
| `frontend/src/components/WikiSkills.vue` | 技能来源/属性/文本过滤与学习资料展示 |
| `frontend/src/components/WikiAcquisition.vue` | 两个图鉴共享的分布、活动、特殊蛋来源展示 |
| `frontend/src/pages/catalog-wiki.css` | 蛋神式分页卡片、常驻详情、雷达与窄窗样式 |
| `tests/test_wiki_reference.py` | 合成数据验证身份匹配、学习来源、零能耗、按需载荷和导入数据边界 |
| `docs/WIKI_REFERENCE.md` | 当前资料来源、导入操作和维护边界 |
| `docs/prototypes/handbook/` | 图鉴视觉原型；当前收录已确认的蛋蛋图鉴清稿 |

| 图鉴共享组件 | 职责 |
| --- | --- |
| `frontend/src/components/DexPortrait.vue` | 完整源图 contain 展示及缺图占位 |
| `frontend/src/components/DexFilterMenu.vue` | 单选/多选筛选弹窗与蛋组并交集模式 |
| `frontend/src/components/DexRadar.vue` | 六维种族值雷达图 |
| `frontend/src/components/DexGender.vue` | 精灵/蛋详情共享的公母比例圆环 |
| `frontend/src/components/DexRanges.vue` | 精灵/蛋的参考范围条及物种分布展示 |

| 智能配窝文件 | 职责 |
| --- | --- |
| `domain/breeding_planner.py` / `breeding_solver.py` / `breeding_nature.py` | 准入、统一布局评估、有界联合搜索与共用性格参考 |
| `services/breeding_planner_service.py` / `view_models/breeding_planner_vm.py` / `web/breeding_planner.py` | 一致输入、目录版本、取消、账号草稿、页面DTO及鉴权API |
| `frontend/src/pages/BreedingPlannerPage.vue` / `components/BreedingCanvas.vue` / `composables/useBreedingPlanner.ts` | 双入口、模拟画布、目标/亲本选择、撤销与旧响应隔离 |
| `tests/test_breeding_planner.py` / `frontend/src/composables/useBreedingPlanner.test.ts` | 配对/迭代/搜索、共享母本、锁定、声音一致性、鉴权/保存和请求时序回归 |
| `tests/test_close_coordinator.py` | 页面确认前不销毁窗口、存储失败保留窗口与显式放弃分支 |
| `tests/test_asset_cache_lifecycle.py` | 真实 to_thread 下载未完成时关闭必须等待 |

## C01 采集向导

| 文件 | 职责 |
| --- | --- |
| `spritelens/view_models/capture_diagnostics.py` | 采集快照与环境报告的纯诊断判断，不把累计观察当成当前连接健康 |
| `frontend/src/components/CaptureDiagnostics.vue` | 完整采集设置分组：统一状态/诊断、网卡/启动/跟随/录制、内联手动密钥/会话/统计、命令互斥及卸载后响应失效 |
| `frontend/src/captureDiagnosticsBridge.ts` | 原生设置壳的 Vue 挂载/状态传递/卸载接口 |
| `frontend/src/types/captureDiagnostics.ts` | 诊断 DTO、动作及网卡响应边界校验 |
| `tests/test_capture_diagnostics.py` | 诊断语义、探测互斥/失败保留报告及鉴权接口回归 |
| `frontend/src/components/CaptureDiagnostics.test.ts` | 重复请求、失败重试、卸载后响应与非法 DTO 回归 |
| `docs/CAPTURE_DIAGNOSTICS.md` | C01 当前功能规格及维护边界 |

## C02 场景观察

| 文件 | 职责 |
| --- | --- |
| `spritelens/domain/scene.py` | 场景 NPC 字段、原始坐标、未知值及离开 ID 的纯提取 |
| `spritelens/services/scene_repository.py` | 账号/会话/场景归属、有限实体集合与一致观察快照；`reset_coverage` 清空当前地图足迹并推进版本；无持久化 |
| `spritelens/services/scene_coverage.py` | 本次运行的观察范围方格记录；人物位置采样及其雷达观察半径覆盖到的格（边长 2000 原始单位、上限 16384 格），行区间压缩，`clear(resource)` 可清指定地图或全部；战斗与换图保留记录、切账号隔离，不保存实体或 checkpoint |
| `spritelens/web/nearby.py` | 只读附近观察载荷与鉴权路由，ID 字符串化，不导出会话地址；`POST /api/nearby/coverage/reset` 清除当前地图足迹（未装配场景观察时 503） |
| `spritelens/repositories/scene_coverage_store.py` | 搜索覆盖历史的账号/地图隔离、异步原子保存与关闭等待；不保存实时实体 |
| `tests/test_scene_coverage_store.py` | 搜索覆盖历史恢复、容量、归属与写入失败重试回归 |
| `tests/test_scene.py` | 场景生命周期、契约、装配/停止和加密分段流录制回放回归 |
| `docs/SCENE_OBSERVATIONS.md` | 当前字段证据、只读接口、失败分支与待验收范围 |

## 附近精灵页面（C03）

| 文件 | 职责 |
| --- | --- |
| `frontend/src/pages/NearbyPage.vue`、`composables/useNearby.ts`、`types/nearby.ts` | 附近观察列表、搜索/排序、DTO校验、周期清空与请求失效；右侧面板在雷达与地图之间切换，共用同一选中与列表；2026-10-28 增炫彩标识（`colorful` 徽章与卡片描边，与单牌/双牌并列，后者来自本地参考线） |
| `spritelens/web/world_maps.py` | 只读世界地图清单路由：校验 manifest 后下发投影/校准子集，缺文件或坏清单 503，统一 no-store |
| `frontend/src/components/SceneMap.vue`、`SceneMap.test.ts` | 4096 底图相机（缩放/拖拽/全图/定位/跟随）、越界过滤、选中联动、标签错行与失败重试；2026-10-27 视觉重做：牛眼玩家锚点与常驻标签、分级标记与图例、图标控件列、默认 80% 街景比例；2026-10-28 炫彩点位加虚线环与图例项 |
| `frontend/src/domain/mapProjection.ts`、`frontend/src/types/worldMap.ts` | 原始坐标↔底图像素纯函数与逆变换；运行时清单严格解析、可用性判定与不可用原因 |
| `frontend/src/components/MapCoverage.vue`、`frontend/src/domain/mapCoverage.ts` | 地图/雷达共用本次足迹格网；按行区间拼成单条路径，填充、外沿与外部遮罩三个节点复用同一份 `d` |
| `frontend/src/composables/useWorldMaps.ts` | 按会话读取一次地图清单、失败显式重试、8 秒超时、损坏整块失效 |
| `frontend/src/nearbyBridge.ts`、`spritelens/web/static/nearby-page.js` | Vue装配与既有REST/单一WS摘要转发；离页暂停、周期失效、超时与悬浮请求合并 |
| `spritelens/web/static/nearby-alert.js` | 双牌重点精灵新出现提醒音（单牌只显示标记不发声）：按实体10分钟去重、默认开启并持久化；WebAudio合成双音，无外部音频资源 |
| `tools/import_scene_catalog.py`、`data/static/scene_npc_pets.json` | 裁剪并记录来源哈希的NPC配置到物种映射；StaticData只读加载 |
| `frontend/src/nearbyBridge.test.ts` | 主窗/悬浮桥接的慢请求合并、低版本切号、超时与断连失效回归 |
| `frontend/src/nearbyAlert.test.ts` | 提醒引擎首快照、单牌不响/双牌触发、10分钟去重、开关持久化与壳层端到端响铃回归 |
| `frontend/src/composables/useNearby.test.ts` | 切号/切周期/离页的晚到响应与失败保留回归 |
| `docs/NEARBY_OBSERVATIONS.md` | 当前操作、来源、所有权与观察版限制 |


| 雷达新增文件 | 职责 |
| --- | --- |
| `frontend/src/components/SceneRadar.vue`、`SceneRadar.test.ts` | 原始二维坐标雷达、缺坐标等待、按字符串ID选择与投影回归；2026-10-28 炫彩目标加虚线紫环与图例第 4 项，`title`/`aria-label` 追加「炫彩」 |
| `frontend/src/pages/FloatingRadar.vue`、`spritelens/web/static/radar.html`、`radar.js` | 独立悬浮内容、广播订阅、版本/周期校验与释放，不建WS；`radar.js` 只 import `vue/radar-entry.js` |
| `frontend/src/radar.ts`、`floatingRadarBridge.ts` | 雷达独立入口与其 Vue 桥；主窗壳经 `nearbyBridge.ts` 保留同名导出，共享同一实现 |
| `spritelens/web/radar_window.py`、`tests/test_radar_window.py` | 原生单实例置顶窗口、关闭通知、重新打开与主窗口退出生命周期 |


2026-10-24 悬浮雷达：自绘深色工具窗，标题拖动与本地关闭图标；底部固定35%–90%原生不透明度，按1%调整（默认85%）。保留置顶、不抢焦点与单一推送，正常/最小窗口/高倍缩放渲染及原生alpha验证见[附近精灵规格](NEARBY_OBSERVATIONS.md)。

## C13 世界地图资源与坐标清单（2026-10-26）

| 文件 | 职责 |
| --- | --- |
| `tools/import_world_maps.py` | 显式资源根导入两张 4096 世界地图与 desktop-data.json 参数；固定哈希/尺寸/原点边长，暂存校验后替换，失败保留旧产物 |
| `data/static/world_maps.json` | 静态 manifest：`schema_version`/`coordinate_version`、来源哈希、图片尺寸与 URL、`origin_side_normalized` 投影、支持表与 `verified`/`candidate` 校准等级 |
| `spritelens/web/static/maps/10003.webp`、`10018.webp` | 解包原图直接入库（未转码），经 `/static/maps/<id>.webp` 访问；10003 为 `supported`（8 个现场点校准后 `verified`），10018 为 `candidate` |
| `tests/test_world_maps.py` | manifest 自洽、来源指纹、投影不变量与失败分支回归；运行时清单载荷与 `/api/world-maps` 路由（200/503、no-store） |

C13-02 起地图模式在运行时读取清单：`spritelens/web/server.py` 在附近路由之后注册 `/api/world-maps`，`build_config.toml` 的 `include_data_files` 已带入 `data/static/world_maps.json`；前端只对 `availability=supported` 且 `calibration.level=verified` 的地图启用动态投影（当前仅 10003），投影公式与校准边界见 [实施计划](NEARBY_MAP_PLAN_2026-10-26.md) 与 ROADMAP C13。
