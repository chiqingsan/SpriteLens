# 代码地图

文件级速查；新增文件须同步本表。测试数基线：见 `tools/run_build_tests.py` 输出。

界面形态：**只有 Web 一套**（pywebview 窗口 + 本地服务 + 原生 JS 前端）；
历史 PyQt 原生界面已于 2026-10 退役，`requirements.txt` 不再含 PyQt6。

## 根目录

| 文件 | 职责 |
| --- | --- |
| `main.py` | 入口转发到 `spritelens.main:main` |
| `start.bat` | 双击启动界面（pythonw，无控制台窗口） |
| `start_debug.bat` | 前台控制台启动（看错误输出用） |
| `tools/create_shortcut.bat` + `ps1` | 创建桌面快捷方式（幂等，ps1 用 $PSScriptRoot 自定位） |
| `requirements.txt` | scapy / pycryptodome / aiohttp / pywebview（无 UI 框架之外的额外依赖） |
| `tools/run_build_tests.py` | 全量测试（unittest discover + 噪声过滤） |
| `tools/import_schema.py` | 导入外部 schema 全集到 data/schemas（本地目录或 GitHub） |
| `tools/import_static_data.py` | 导入基础静态表（物种/性格/系别/技能）到 data/static |
| `tools/import_assets.py` | 导入图鉴元数据 + 精灵图 + 系别图标 + 系别克制表 |
| `tools/analyze_recording.py` | 录制文件离线分析（帧分类/opcode 分布/宠物形状） |
| `tools/run_web_demo.py` | 带合成数据的界面实例（浏览器打开，视觉验收用） |
| `tools/make_icon.py` | 生成 `resources/app.ico` 多尺寸图标与 favicon（PIL，产物入库） |
| `resources/app.ico` | 应用图标（窗口/任务栏用，打包时随包分发） |
| `data/schemas/` | 外挂 schema：`opcodes.json` + `messages/*.json`（字段级合并） |
| `data/static/` | 静态映射：`species/natures/types/skills/type_chart.json` + 各 `_meta.json` |
| `spritelens/web/static/` | 前端资源：`index.html` / `app.css` / `app.js` / `favicon.png` / `pets/*.webp` / `type-icons/` |
| `data/recordings/` | 运行时录制产物（gitignore；本地回放样例不在版本库） |

## spritelens/

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 版本、APP_NAME、APP_DISPLAY_NAME |
| `__main__.py` | `python -m spritelens` 入口（转发到 `main:main`） |
| `paths.py` | 数据目录解析（SPRITELENS_DATA_ROOT 可覆盖）+ 打包态资源根（frozen/_MEIPASS） |
| `main.py` | CLI：--smoke-test / --list-ifaces / --replay / --diagnose-net / --web-browser / 界面启动 |
| `app_context.py` | **装配根**：管线/库/VM/清理的一次性组装（autostart 在此触发） |
| `protocol/frames.py` | GCP 21B 大端头切帧、假 magic 同步、FrameStream |
| `protocol/crypto.py` | AES-128-CBC 固定 IV 解密/加密、ACK 密钥提取 |
| `protocol/records.py` | Direction、tsf4g trailer 剥离、s2c/c2s 拆分 |
| `protocol/wire.py` | protobuf wire 字段号树（嵌套从严判定） |
| `protocol/schema.py` | schema 库加载、双路解码与降级 |
| `protocol/opcodes.py` | opcode → 名称/分类/消息名目录 |
| `capture/base.py` | CaptureSource 协议、StreamChunk、SourceError |
| `capture/reassembly.py` | TCP 流重组（乱序/重传/全零段回滚/空洞，纯逻辑） |
| `capture/npcap_source.py` | scapy AsyncSniffer 接入（轻量回调 + 队列 + worker 投递） |
| `capture/key_store.py` | 密钥文本解析与 latest.key 持久化 |
| `system/environment.py` | Npcap 检测、官方版本解析、下载、UAC 拉起安装向导 |
| `system/single_instance.py` | 单实例控制：命名互斥锁 + 唤醒事件 + Win32 强制置顶 |
| `system/net_diagnose.py` | --diagnose-net：宽抓会话统计，定位多连接的数据端口 |
| `domain/pets.py` | 宠物语义层：形状搜索提取 PacketEvent → Pet 对象（含六维/技能/外观） |
| `domain/identity.py` | 玩家身份语义层：self_info/avatar/base → PlayerIdentity（uid 归属） |
| `domain/static_data.py` | 静态映射：物种/性格/系别/技能（base_conf_id 关联，含图鉴元数据） |
| `domain/display.py` | 展示常量：系别配色、六维标签、天赋阶配色（框架无关） |
| `repositories/database.py` | SQLite 底座：连接、PRAGMA user_version 迁移（v2 含六维/外观列）、损坏自恢复 |
| `repositories/pet_store.py` | 宠物持久化网关：write-behind 批量落盘 + 读取（适配器模式） |
| `repositories/settings.py` | JSON 配置仓库（原子写、脏值归一、窗口几何） |
| `services/monitor_service.py` | 采集管线编排：字节流 → 帧 → 解密 → 解码 → PacketEvent |
| `services/session_tracker.py` | 会话表（LRU）与全局统计 |
| `services/pet_repository.py` | 宠物聚合（内存快照 + 身份归属 + 入库出口；不注入 store 时纯内存） |
| `services/event_logger.py` | PacketEvent JSONL 落盘（按天分片，复盘用） |
| `recording/recorder.py` | StreamChunk jsonl 录制/读回 |
| `recording/replay.py` | ReplaySource + CLI 回放摘要输出 |
| `logs/local_logger.py` | 双文件 RotatingFileHandler + 崩溃兜底 `install_excepthook`（crash.log） |
| `view_models/pet_vm.py` | 宠物页 VM（多维筛选/排序/聚合统计，纯 Python） |
| `view_models/capture_vm.py` | 采集页 VM（source 构造、Npcap 安装状态机、自动采集开关） |
| `view_models/events_vm.py` | 协议流页 VM（行视图/详情缓存） |
| `view_models/_shared.py` | 解码树文本渲染 |
| `web/server.py` | 本地服务：aiohttp，仅回环 + 随机端口 + token 鉴权 + WS 推送 |
| `web/run.py` | 界面入口：pywebview 窗口（系统 WebView2）+ 单实例唤醒 + 降级提示 |
| `web/payloads.py` | 业务对象 → JSON 契约（宠物/概览/图鉴三类载荷，无 UI 依赖） |

## tests/（unittest 平铺）

| 文件 | 覆盖 |
| --- | --- |
| `_synth.py` | 合成帧生成器（确定性 trailer、protobuf 载荷） |
| `test_frames.py` | 切帧：粘包/跨段/假 magic/超长守护 |
| `test_crypto.py` | 解密 roundtrip、key 提取、非法长度 |
| `test_records.py` | trailer 剥离、s2c 锚点、c2s 偏移 |
| `test_wire.py` | varint/嵌套/截断/二进制保留 |
| `test_schema.py` | schema 加载、双路解码、opcode 目录 |
| `test_reassembly.py` | 顺序/乱序/重复/全零段回滚/空洞/历史段 |
| `test_monitor_service.py` | 管线端到端（key 捕获、续解、隔离、统计） |
| `test_npcap_source.py` | 抓包线程逻辑（分类/入队/队列满丢弃/worker 投递） |
| `test_recording.py` | 录制 roundtrip、坏行跳过、回放一致性 |
| `test_pets.py` | 形状提取、仓库合并、schema→管线→聚合端到端、v2 扩展字段 |
| `test_pet_vm.py` | 宠物 VM：多维筛选、排序、聚合统计 |
| `test_static_data.py` | 静态表加载/索引/降级；base_conf_id 与 conf_id 的区分回归 |
| `test_single_instance.py` | 单实例互斥锁唯一性、唤醒事件投递与消费、close 幂等 |
| `test_persistence.py` | 身份识别（NPC 不误取）、写库/重开/加载、多账号隔离、迁移与损坏恢复 |
| `test_view_models.py` | VM 状态与命令（Capture/Events + 自动采集开关） |
| `test_architecture.py` | 架构边界：业务层无 Web 依赖、无反向分层、protocol 纯函数约束 |
| `test_crash_log.py` | 崩溃日志：主线程/后台线程异常落盘、Ctrl+C 不记录、写入失败静默 |
| `test_paths.py` | 打包态资源定位：源码/frozen/_MEIPASS 三分支、数据目录不受打包影响 |
| `test_web_server.py` | 本地服务：token 鉴权（REST/WS）、随机端口、宠物/图鉴/采集 API、载荷构造 |
| `test_environment.py` | Npcap 检测与安装引导状态机 |
| `test_event_logger.py` | 事件日志落盘与分片 |
