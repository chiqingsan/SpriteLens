# 代码地图

文件级速查；新增文件须同步本表。测试数基线：见 `tools/run_build_tests.py` 输出。

界面形态：**只有 Web 一套**（pywebview 窗口 + 本地服务 + 原生 JS 前端）；
历史 PyQt 原生界面已于 2026-10 退役，`requirements.txt` 不再含 PyQt6。
Vue 3 + TypeScript + Vite 已确认采用，工程尚未创建；下表描述当前文件，规划见 `VUE3_MIGRATION.md`。

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
| `tools/run_build_tests.py` | 全量测试（unittest discover） |
| `tools/import_schema.py` | 导入外部 schema 全集到 data/schemas（本地目录或 GitHub） |
| `tools/import_static_data.py` | 导入基础静态表（物种/性格/系别/技能）到 data/static |
| `tools/import_assets.py` | 导入图鉴元数据 + 精灵图 + 系别图标 + 系别克制表 |
| `tools/import_egg_data.py` | 导入蛋目录（蛋组/孵化时长/公母比/身高体重/进化链）到 data/static/eggs.json |
| `tools/import_pet_details.py` | 补全静态数据：图鉴描述并入 species.json（+sum 重算修正）、补技能名、奖牌表、蛋/奖牌图标、花种等级表 |
| `tools/sync_catalog_resources.py` | 官方目录/镜像同步：保留有效值的 ID 合并、镜像校验、可重复导入并出报告（resource_sync_report.json） |
| `tools/sync_pet_media.py` | 按官方 manifest 导入头像/立绘，并派生透明边界归一的 `-fit`/`-rarity` 变体（幂等，报告 pet_media_report.json） |
| `tools/sync_ui_icons.py` | 按固定官方 Git 版本导入少量 Tabler SVG 图标并合成 sprite（开发期联网，运行期零网络） |
| `tools/analyze_recording.py` | 录制文件离线分析（帧分类/opcode 分布/宠物形状） |
| `tools/run_web_demo.py` | 带合成数据的界面实例（浏览器打开，视觉验收用） |
| `tools/make_icon.py` | 生成 `resources/app.ico` 多尺寸图标与 favicon（PIL，产物入库） |
| `resources/app.ico` | 应用图标（窗口/任务栏用，打包时随包分发） |
| `data/schemas/` | 外挂 schema：`opcodes.json` + `messages/*.json`（字段级合并） |
| `data/static/` | 静态映射：`species/natures/types/skills/type_chart/eggs/medals/flower_levels/color_cards.json` + 各 `_meta.json` |
| `spritelens/web/static/` | 前端资源：`index.html`（分组导航骨架）/ `boot.js`（启动自恢复链）/ `app.css`（布局与组件 token）/ `themes.css`（三套主题色值）/ `app.js`（数据渲染）/ `ui.css` / `ui.js`（详情抽屉、键盘与焦点）/ `appearance.js`（主题与显示偏好）/ `pet-presentation.js`（头像/色卡/标记渲染）/ `pet-filters.js`（蛋组与范围筛选）/ `backpack-controls.js`（快捷条件）/ `icons.js` + `icons/`（本地 SVG sprite）/ `favicon.png` / `pet-media/`（官方头像立绘，含 `-fit` 派生）/ `pets/`（兜底立绘）/ `type-icons/` `egg-icons/` `medal-icons/` `medals/` `rarity/` `color-cards/` |
| `data/recordings/` | 运行时录制产物（gitignore；本地回放样例不在版本库） |

## 维护与审查文档

| 文件 | 职责 |
|---|---|
| `docs/AI_CONTEXT.md` | 新开发者/AI快速上下文与当前风险导航 |
| `docs/ROADMAP.md` | 已落实范围、待办顺序与验收；唯一持续任务状态入口 |
| `docs/VUE3_MIGRATION.md` | 已确认的 Vue 前端工程/接口/状态与渐进迁移决策；不代表已实现 |
| `docs/reviews/PROJECT_REVIEW_2026-10-12.md` | 基于114be08的审查快照、复现证据与资源/文档风险；不代表已修复 |
| `docs/reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md` | 基于240b94c的改动复核、确定性复现与完成范围校正 |

路线图中的新模块路径是规划，尚未加入下面的当前源码地图。

## spritelens/

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 版本、APP_NAME、APP_DISPLAY_NAME |
| `__main__.py` | `python -m spritelens` 入口（转发到 `main:main`） |
| `paths.py` | 数据目录解析（SPRITELENS_DATA_ROOT 可覆盖）+ 打包态资源根（frozen/_MEIPASS） |
| `main.py` | CLI：--smoke-test / --list-ifaces / --replay / --diagnose-net / --web-browser / 界面启动 |
| `app_context.py` | **装配根**：管线/库/VM/清理的一次性组装（autostart 在此触发） |
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
| `capture/key_store.py` | 密钥解析与持久化：latest.key + session.json v1（flow/密钥/身份/服务端序号，原子写，损坏即弃） |
| `system/environment.py` | Npcap 检测、官方版本解析、下载、UAC 拉起安装向导 |
| `system/webview_guard.py` | WebView2 运行时预检测（注册表/env）+ 缺失时原生对话框引导安装 |
| `system/window_geometry.py` | 初始窗口尺寸：工作区 + 系统 DPI 缩放适配（fit_window 纯函数） |
| `system/single_instance.py` | 单实例控制：命名互斥锁 + 唤醒事件 + Win32 强制置顶 |
| `system/net_diagnose.py` | --diagnose-net：宽抓会话统计，定位多连接的数据端口 |
| `domain/pets.py` | 宠物语义层：形状搜索提取 PacketEvent → Pet 对象（含六维/技能/外观/佩戴奖牌；默认排除试用与好友镜像个体） |
| `domain/identity.py` | 玩家身份语义层：登录 player_info/brief_info 与场景 self_info/avatar/base → PlayerIdentity（uid 归属） |
| `domain/static_data.py` | 静态映射：物种/性格/系别/技能/奖牌（base_conf_id 关联，含图鉴元数据与进化链成员） |
| `domain/measurements.py` | 参考范围工具：cm/g → m/kg 文案、范围位置比例与越界状态（纯函数） |
| `domain/pet_marks.py` | 紧凑标记：体型大/小、声音粗/婉（含佩戴奖牌来源），组内互斥最多两项 |
| `domain/pet_locations.py` | 真实箱位：Backpack/PetBox（30 格箱表 + 3×6 队伍 + 移动增量 + v2 快照恢复） |
| `domain/eggs.py` | 蛋目录：蛋静态数据索引（egg_conf_id / base_id 联查，孵蛋工具链底座） |
| `domain/color_cards.py` | 色卡目录：44 张卡（底色×混色）+ glass→卡号判定（赛季 s1-s4） |
| `domain/egg_box.py` | 蛋仓语义层：形状搜索提取 PacketEvent → EggBoxEntry（bagType==8 指纹） |
| `domain/home.py` | 家园语义层：0x014A 快照 → 居民/家具/产蛋窝（实证字段映射 + NEST_TYPES） |
| `domain/flowers.py` | 花种语义层：0x0375 花田帧 → 自己的花/好友花田（含宠物三维） |
| `domain/display.py` | 展示常量：系别配色、六维标签、天赋阶配色（框架无关） |
| `repositories/database.py` | SQLite 底座：连接、user_version 追加迁移至 v8（孵化槽），整组事务化 + 半迁移自修复；真损坏备份恢复，备份失败保留原文件 |
| `repositories/pet_store.py` | 宠物持久化网关：write-behind 批量落盘 + 读取（适配器模式） |
| `repositories/egg_store.py` | 蛋仓持久化网关：write-behind 批量落盘，按 uid 读取蛋与 v8 孵化槽快照 |
| `repositories/settings.py` | JSON 配置仓库（原子写、脏值归一、窗口几何） |
| `services/monitor_service.py` | 采集管线编排：字节流 → 帧 → 解密 → 解码 → PacketEvent；会话释放/空闲回收/硬上限 |
| `services/capture_service.py` | 采集运行服务：接入层创建与生命周期、录制 tee、手动密钥、副作用命令串行化（阶段1.3 自 capture_vm 抽出） |
| `services/session_tracker.py` | 会话表（LRU，支持 drop）与全局统计 |
| `services/account_tracker.py` | 账号切换判定（uid 变化才清快照；同 uid 重复帧/离线加载登录不算切换） |
| `services/pet_repository.py` | 宠物聚合、身份/切号、彩名学习与入库；consistent_snapshot 单次取齐宠物/箱位/位置/uid/version |
| `services/egg_repository.py` | 蛋仓聚合（instance_id 去重 + 版本号 + 切号清空 + 入库出口） |
| `services/home_repository.py` | 家园聚合（快照覆盖 + 切号清空 + 增量帧版本提示） |
| `services/flower_repository.py` | 花田聚合（快照覆盖 + 切号清空 + 版本号） |
| `services/event_logger.py` | PacketEvent JSONL 异步落盘（有界队列 + worker 批量写，按天分片，复盘用） |
| `recording/recorder.py` | StreamChunk jsonl 录制/读回 |
| `recording/replay.py` | ReplaySource + CLI 回放摘要输出 |
| `logs/local_logger.py` | 双文件 RotatingFileHandler + 崩溃兜底 `install_excepthook`（crash.log） |
| `view_models/pet_vm.py` | 宠物 VM + 请求级 PetView；后者持一致快照在锁外筛选/排序，不改共享条件 |
| `view_models/ui_preferences.py` | UI 偏好 VM：主题/视图/显示字段/快捷条件白名单校验与快照 |
| `view_models/capture_vm.py` | 采集页 VM（Npcap 安装状态机、自动采集开关、偏好持久化、快照组装；运行命令委托 capture_service） |
| `view_models/events_vm.py` | 协议流页 VM（行视图/详情缓存） |
| `view_models/_shared.py` | 解码树文本渲染 |
| `web/server.py` | 本地服务：aiohttp，仅回环 + 随机端口 + token 鉴权 + WS 推送；数据/偏好路由与 bootstrap，采集域路由由 routes_capture mixin 提供 |
| `web/routes_capture.py` | 采集域路由与载荷（/api/capture*、/api/state、capture/state 载荷；阶段1.4 自 server.py 拆出） |
| `web/server_helpers.py` | HTTP query 解析助手（路由模块共用） |
| `web/run.py` | 界面入口：pywebview 窗口（系统 WebView2）+ 单实例唤醒 + 降级提示 |
| `web/payloads.py` | 宠物域载荷（宠物行/列表页/概览/箱位）+ 目录域兼容重导出（无 UI 依赖） |
| `web/payloads_catalog.py` | 目录域载荷：图鉴/种公矩阵/花田/色卡/家园/蛋仓/蛋图鉴（阶段1.4 自 payloads.py 拆出） |
| `web/pet_media.py` | 物种 ID → 官方头像/立绘 URL 映射（pet_media.json，缺图回退 pets/ 兜底） |
| `web/static/pages/egg-dex.js` | 蛋图鉴页模块：该页 state/load/render/bind（阶段1.6 自 app.js 抽出；协作函数显式注入，bind 幂等 + 请求序号防旧覆新） |

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
| `test_pet_vm.py` | 宠物 VM：多维筛选、排序、聚合统计 |
| `test_static_data.py` | 静态表加载/索引/降级；base_conf_id 与 conf_id 的区分回归 |
| `test_eggs.py` | 蛋目录：加载/索引/降级、载荷筛选（蛋组/类型/孵化时长/搜索） |
| `test_egg_box.py` | 蛋仓：形状搜索提取/拒收、聚合去重、SQLite roundtrip、写-behind 落盘、跨账号隔离、载荷联查、种公矩阵 |
| `test_home.py` | 家园：居民/家具/窝提取、聚合与增量计数、载荷、花种提取与载荷 |
| `test_desktop_shell.py` | 窗口几何 fit_window（DPI/工作区 clamp）、WebView2 env 覆盖检测 |
| `test_nic_rank.py` | 活跃网卡排序（前置/保持原序/宽松匹配） |
| `test_single_instance.py` | 单实例互斥锁唯一性、唤醒事件投递与消费、close 幂等 |
| `test_persistence.py` | 身份识别（NPC 不误取）、写库/重开/加载、跨账号隔离、迁移事务/回滚/半迁移自修复、外观字段往返、彩名恢复、损坏恢复 |
| `test_view_models.py` | VM 状态与命令（Capture/Events + 自动采集开关） |
| `test_pet_locations.py` | 箱位：登录映射、空箱/部分箱、槽位匹配状态、队伍归属与槽序、切号/重启、历史与实时去重 |
| `test_pet_presentation.py` | 头像 `-fit` 派生、尺寸/声音标记边界、旧偏好迁移、类型色卡解码 |
| `test_session_resume.py` | 会话接续：服务端帧确认、流/密钥/序号不匹配、新握手与关闭失效、损坏缓存 |
| `test_ui_upgrade.py` | UI 升级：偏好鉴权/重启/并发/失败、范围与组合筛选、别名合并、sprite 完整性 |
| `test_architecture.py` | 架构边界：业务层无 Web 依赖、无反向分层、protocol 纯函数约束 |
| `test_crash_log.py` | 崩溃日志：主线程/后台线程异常落盘、Ctrl+C 不记录、写入失败静默 |
| `test_paths.py` | 打包态资源定位：源码/frozen/_MEIPASS 三分支、数据目录不受打包影响 |
| `test_smoke_assets.py` | 随包资源齐备（前端静态目录/静态表/schema），防打包漏带 |
| `test_web_server.py` | 本地服务：token 鉴权（REST/WS）、随机端口、宠物/图鉴/采集 API、载荷构造 |
| `test_environment.py` | Npcap 检测与安装引导状态机 |
| `test_event_logger.py` | 事件日志异步落盘与分片、队列满丢弃、关闭超时不跨线程关文件 |

## 三主题与资源补齐（2026-10-12）

| 文件 | 责任 |
|---|---|
| `domain/measurements.py` | cm/g参考范围转m/kg、范围位置与越界状态 |
| `view_models/ui_preferences.py` | 主题/视图/显示字段白名单、非法配置降级与严格保存 |
| `web/static/themes.css` / `appearance.js` | 三套浅色主题、即时切换、显示选项与保存反馈 |
| `web/static/pet-filters.js` | 蛋组any/all和m/kg/dB绝对范围，接原有筛选与重置 |
| `web/static/icons.js` / `icons/` | 本地Tabler SVG与sprite，29枚图标和MIT来源清单 |
| `tools/sync_catalog_resources.py` | 保留有效值的ID合并、官方镜像校验、可重复资源导入与报告 |
| `tools/sync_ui_icons.py` | 固定官方Git版本的少量SVG导入，无运行时网络依赖 |
| `tests/test_ui_upgrade.py` | 偏好鉴权/重启/并发/失败、范围/组合筛选、别名、合并和sprite完整性 |
| `docs/RESOURCE_COVERAGE_REPORT.md` | 1060物种、646组范围、224蛋、477别名；缺图/缺字段/冲突 |
| `docs/BREEDING_PLANNER_SPEC.md` / `COLLECTION_LINES_SPEC.md` | 下一轮配窝与产线开发规格，明确已验证规则与未知假设 |

新增API：鉴权GET/POST `/api/ui/preferences`，bootstrap新增`ui_preferences`。
`/api/pets`新增egg_groups、egg_mode和height/weight/voice_min/max；原有字段兼容。

## 背包操作与真实登录数据（2026-10-12）

| 文件 | 责任 |
|---|---|
| `domain/pet_locations.py` | Backpack/PetBox：完整30格箱表、普通3×6队伍、移动增量；区分零空格与未采集，排除客户端请求和特殊队伍，兼容旧位置快照 |
| `web/static/backpack-controls.js` | 命名快捷条件、性格更多和折叠摘要，共用原有查询 |
| `repositories/pet_store.py` | 当前佩戴奖牌与按账号Backpack v2快照异步落盘/恢复，沿用pet_locations表 |
| `tests/test_pet_locations.py` | 登录协议映射、真实空箱/部分箱、固定槽匹配状态、普通队伍归属/槽序、切号/重启及历史与实时位置去重、登录后WebSocket推送回归 |
| `tests/test_session_resume.py` | 原会话重启接续、服务端帧确认、流/密钥/序号不匹配、新握手/关闭失效及损坏缓存回归 |
| `docs/SESSION_RESUME_VERIFICATION.md` | 会话关联保存、原始录制接续与界面状态验证；空箱隐藏/未知入口删除的后续验收 |
| `docs/BACKPACK_UPGRADE_VERIFICATION.md` | 真实样本、角色更新修复、测试结果及未完成的视觉验收 |

偏好增加 `fields.positions` 与最多六组 `shortcuts` 定义；查询增加
`height_position_min/max`、`weight_position_min/max`，排序增加身高/体重/声音。
宠物载荷兼容增加 `location`、`worn_medal_id/name` 与 `is_colorful`。
