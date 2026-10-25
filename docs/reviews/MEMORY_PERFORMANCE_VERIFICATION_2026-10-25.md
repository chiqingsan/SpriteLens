# PERF 系列改动验收（2026-10-25）

状态：PERF01/PERF02 首轮、PERF04/PERF07 补验及 PERF05 尾批释放返修复验通过，具体范围见各轮证据；真实桌面整机性能及长期运行仍待验收。第 7 节的 P2 已由第 8 节关闭。
读者：维护者、后续实现模型与复核者。
用途：核验 [内存优化交接](MEMORY_PERFORMANCE_HANDOFF_2026-10-24.md) 中已实施的切片，记录各轮独立复测、返修项与完成边界。后续提交的 PERF04/PERF05/PERF07 补验见第 7 节。
维护边界：本文是日期验收证据；持续状态只维护在 [ROADMAP](../ROADMAP.md#perf-系列内存与性能优化2026-10-24)。本轮未修改业务代码。

## 1. 基线与结论

- 验收 HEAD 为 `bffa7a0`；PERF01 实现提交为 `10318ea`。PERF02 的启动脚本调整已经包含在 `9970853`。
- 开始时已有 `docs/README.md` 的打包研究索引改动，以及未跟踪的 `docs/reviews/BUILD_TIME_RESEARCH_2026-10-25.md`，本轮保留。
- PERF01 的缓存关闭没有改变独立回放的事件内容、顺序或最终业务快照，内存下降在新样本中复现。
- PERF02 的重复调用路径已移除，启动脚本层的排队/挂载交接与正常事件均只交付一次。
- 未发现这两项的阻断性代码问题；可以继续推进后续编号的测量。PERF03–PERF07 尚未实施，不能据此宣布整个优化系列完成。

## 2. PERF01 源码复核

检查位置：

- `spritelens/services/monitor_service.py`：`keep_event_history` 默认关闭；关闭时不分配历史 deque；事件仍进入监听器。显式开启时保留原 2,000 条容量与 drain 行为。
- `spritelens/app_context.py`：桌面装配显式传 `keep_event_history=False`，没有关闭事件日志或业务仓库监听器。
- `spritelens/recording/replay.py`：CLI 显式传 `keep_event_history=True`，继续通过 `drain_events()` 输出事件。
- 停止日志使用独立累计事件计数，不再依赖当前 deque 长度；关闭历史时 drain 返回空并提示一次。
- 扫描当前生产代码的 `drain_events()` 调用，只有 CLI 回放需要事件历史；相关测试调用已按需显式开启。

改动保持局部，没有修改 wire/schema、账号分流、数据库结构、后台写入和关闭所有权。

## 3. PERF01 独立同输入对照

### 方法

两个独立新进程运行同一份当前代码，仅 `keep_event_history=True/False` 不同。固定同一本地录制的字节边界，流式读入，不输出录制、密钥、账号身份或本机路径。

使用真实 schema、opcode 目录与 MonitorService，注册真实 AccountSessions 和无持久化的宠物/蛋仓/家园/场景仓库。KeyStore 只用于读取恢复信息，传给管线的保存方法是内存替身；不写真实密钥、配置、数据库或事件日志，不启停在线实例。

为比较业务时间字段，每段按录制时间提供确定的事件墙钟。每条事件经规范化后累积 SHA-256 摘要，包含字段树与归属；全部账号四域最终快照也生成摘要，只输出摘要比较结果和聚合计数。记录回调异常数量，防止错误被监听器隔离机制掩盖。

### 等价性

| 指标 | 保留历史 | 关闭历史 |
| --- | ---: | ---: |
| 输入段数 | 57,478 | 57,478 |
| 监听器收到的事件数 | 55,103 | 55,103 |
| 解密失败 / 缺密钥 | 0 / 0 | 0 / 0 |
| 业务回调错误 | 0 | 0 |
| 最终账号数 | 1 | 1 |
| 最终宠物 / 蛋条目数 | 928 / 615 | 928 / 615 |

事件内容及顺序摘要一致；全部账号的宠物、蛋仓、家园、场景最终快照摘要一致。计数只描述本次录制，不表示数据库总量或完整游戏仓库。

### 内存

单位 MiB；结束指标在释放比较用的临时快照并执行 GC 后读取 Windows ProcessMemoryCountersEx。

| 指标 | 保留历史 | 关闭历史 |
| --- | ---: | ---: |
| 结束工作集（含共享映射） | 151.93 | 54.52 |
| 进程峰值工作集（含共享映射） | 201.19 | 78.22 |
| 结束私有提交 | 141.25 | 44.91 |

这里的工作集不是私有工作集，不与原实施记录的私有工作集直接对比。本次关闭历史后的结束私有提交降低约 96 MiB，证明收益可以复现；它包含回放与无持久化业务仓库，不包含桌面宿主、WebView2、真实 Npcap、SQLite 和事件日志积压，不能按该比例推算整机收益。

本次没有启用 tracemalloc。两组运行约 39.44/37.24 秒，但包含完整事件摘要和业务提取成本，仅作为实验背景，不宣称吞吐提升。诊断脚本在临时目录执行后清理，原始录制和密钥不入库。

## 4. PERF02 启动脚本交接核验

当前 `web/static/radar.js` 的临时 listener 只在未挂载时排队；挂载完成后移除临时 listener，再将排队事件交给组件 `onmessage`。正常消息不再由启动脚本手动调用 `onmessage`。

独立 Node 运行当前启动脚本，只将其动态模块导入替换为可控制的模块替身；模拟 DOM/桌面桥，用 EventTarget 事件分发同时保留 listener 与 onmessage 的独立注册语义，因此可检出旧版的重复调用。

通过的检查：

- 导入完成前排队两条消息，挂载后各交付一次且顺序不变。
- 挂载后继续分发两条消息，各交付一次。
- 创建第二个独立启动实例，以上行为不累积旧 listener。
- 模块加载失败显示可见错误。
- 慢加载触发超时提示后，模块完成加载仍能正常挂载并单次消费后续消息。

这验证了启动脚本的消息交接，不代表真实 WebView2 的关闭/重开和主窗最小化已在本轮操作验证。组件侧断线、失效、透明度与数据归属由以下现有 Vitest 覆盖。

## 5. 本轮运行的检查

| 范围 | 命令/方式 | 结果 |
| --- | --- | --- |
| 解析、回放、恢复、账号、日志、业务 | `.venv/Scripts/python.exe -B -m unittest tests.test_monitor_service tests.test_recording tests.test_session_resume tests.test_multi_account_capture tests.test_event_logger tests.test_pets tests.test_scene tests.test_view_models -q` | 93 项通过 |
| 前端资源、雷达生命周期、关闭保存 | `.venv/Scripts/python.exe -B -m unittest tests.test_frontend_contract tests.test_radar_window tests.test_close_coordinator -q` | 19 项通过 |
| 悬浮组件与附近请求时序 | 在 frontend 执行 `npm test -- src/pages/FloatingRadar.test.ts src/composables/useNearby.test.ts` | 24 项通过 |
| 已发布资源与源码指纹 | `.venv/Scripts/python.exe -B tools/frontend.py check` | 通过 |
| 雷达启动脚本 | 上述 Node 隔离事件交接检查 | 通过 |
| 差异 | `git diff --check` | 检查时通过 |

Python 日志中的 disk full、关闭超时及录制坏行是已有用例注入的失败分支，测试结果为通过。本轮没有修改 Vue/业务源码，没有重新构建覆盖运行资源，也没有恢复统一门禁或运行全套测试。

## 6. 首轮保留的验收缺口

- 用同一构建、相同账号数据、窗口/DPI、页面、雷达与日志/录制开关，测真实桌面进程树的修改前后私有工作集与私有提交。当前在线实例不能直接当作相同条件的旧版对照。
- 真实 WebView2 中的雷达关闭/重开、主窗最小化、断线恢复及持续更新；本轮仅源码、启动脚本隔离和组件回归通过。
- 真实登录大包、Npcap 连续采集、退出保存和长时内存曲线；无长期数据时不能宣称不存在泄漏。
- 本次隔离实验没有真实持久化或日志写入，不覆盖其慢盘积压；PERF05 继续保持待测量。
- PERF03 的页面分摊、PERF04 的独立入口、PERF06 的解码分配与 PERF07 的摘要构造尚未实施或测量，不追加完成标记。

建议下一步按 ROADMAP 推进 PERF03 的页面驻留分摊；PERF06 可以在 PERF01 基础上重新测量，但不因本轮解析对照通过就直接改动解码契约。

## 7. 第二轮：PERF04 / PERF05 / PERF07 补验

### 7.1 基线与结论

基线：`42f107b`；新增实现为 `a58d1ce`（日志批次）、`2d2fdc3`（推送摘要）、`42f107b`（雷达双入口）。保留首轮未提交的验收文档、索引和打包研究文件，本轮只更新文档。

| 编号 | 本轮结论 | 完成边界 |
| --- | --- | --- |
| PERF04 | 源码、发布产物依赖检查和相关回归通过 | 雷达独立入口成立；本轮未复测真实 WebView2/冻结 EXE，不能单凭静态包体推算进程内存收益 |
| PERF05 | 批次上限回归通过，但整体需要返修 | 已写尾批在空闲期仍被 worker 局部变量持有，未满足“写完即释放” |
| PERF07 | 源码、摘要等价/失效及相关回归通过 | 静止状态复用与无订阅者跳过构造成立；本轮没有重新测量真实桌面 CPU 或长期运行 |

PERF03/PERF06 仍未实施，不改变其状态；首轮 PERF01/PERF02 的结论保持。

### 7.2 P2：日志写完后仍持有尾批与最后一条事件

位置：`spritelens/services/event_logger.py::_run`，行 149、166–174。队列暂时为空时，worker 执行末尾的 `_write_batch(batch)`，随后直接进入下一轮阻塞的 `_queue.get()`，尚未重置 `batch`；失败的 `get_nowait()` 也没有覆盖 `item`。因而队列为空、文件已 flush 后，线程栈仍持有已处理事件。

不足一批的尾批最多保留 `batch_max_events - 1` 条；即使刚好写满一批并重置列表，`item` 仍可保留最后一条。大事件携带完整 decoded 树，空闲期不能释放这些对象，会抵消一部分事件历史取消后的收益。这是本切片的剩余问题，不据此声称是新增的无限泄漏。

独立复现（临时日志目录、合成数据，不操作在线实例）：

1. 创建 `EventLogWriter(batch_max_events=8)`，入队一条带 1 MiB 合成 bytes 字段的 PacketEvent，并只保留其 weakref，删除外部强引用。
2. 等待 `writer.count == 1` 且队列为空，不主动调用 `flush()`；此时文件写入已经完成。执行 GC 后 weakref 仍存活。
3. 再调用 `writer.flush()` 并执行 GC，weakref 消失。这个 barrier 会清理尾批，因此不能在验证“自然空闲释放”前调用它，否则掩盖问题。

本轮输出：`written_count=1`、`queue_empty=true`、`event_retained_after_write_while_idle=true`；显式 flush 后 `event_retained_after_explicit_flush=false`。

修复方向：在再次阻塞等待之前明确释放已完成批次和逐项变量持有的事件引用，保留 barrier、sentinel、写失败、丢弃计数与关闭重试语义。不要通过定时 flush、强制 GC 或缩小业务数据绕过；修复后用“自然排空后无外部强引用”的用例证明事件可回收，覆盖不足一批和恰好一批两种情况。

当前仍只有条数边界，尚无解码树实际字节预算；本轮不把批次上限称为完整内存上限。后续预算策略仍需按 PERF05 规格结合实测选择，不凭 payload_len 或平均日志行字节数估算硬上限。

### 7.3 PERF04 独立检查

- `radar.js` 已改为加载 `radar-entry.js`，独立挂载点只依赖 FloatingRadar 及共享组件。
- 对当前 manifest 从 `src/radar.ts` 遍历静态/动态依赖，未到达 `src/main.ts`。可达的 JS/CSS 共 3 个文件、95,679 字节，全部存在；此数字不含加载器、app.css、themes.css、HTML 和 sprite，不能与原交付的整页字节量直接相减。
- 稳定加载器只注入雷达可达 CSS。发布哈希、双入口及源码指纹检查通过。
- `tools/frontend.py` 和 `web/frontend_assets.py` 当前分别声明相同的 ENTRY_LOADERS，属于两份清单，并非字面上的共用对象；当前内容一致，没有据此扩大本轮重构。

### 7.4 PERF07 独立检查

在临时 AppContext 中使用 926 只合成宠物，预热一次摘要后连续调用 200 次 `_state_payload()`：宠物一致快照新增读取次数为 0；缓存结果与传入新 PetView 的直接构造结果逐字段一致。仓库 clear 推进版本后总数立即变为 0，账号代次推进后响应 account_epoch 立即更新。

本机此次合成环境每次缓存状态约 0.018 ms，传入新快照的直接构造约 0.397 ms；无静态目录、真实抓包或 WS 传输，不与交付记录的真实数据耗时直接比较，不宣称整机 CPU 降低同样比例。

已复核无订阅者仍推进场景插值，bootstrap 的显式快照路径不使用缓存；采集、安装、环境和附近摘要继续每次读取。相关账号/快照契约和推送回归通过。

### 7.5 本轮验证与后续动作

- Python：`tests.test_event_logger`、`tests.test_retention`、`tests.test_close_coordinator`、`tests.test_web_server`、`tests.test_pet_snapshot_contract`、`tests.test_account_domain_contract`、`tests.test_frontend_contract`、`tests.test_radar_window`，108 项通过。
- Vitest：`src/pages/FloatingRadar.test.ts`，13 项通过。
- `.venv/Scripts/python.exe -B tools/frontend.py check` 通过；独立雷达依赖图、200 拍摘要对照、尾批 weakref 复现完成。
- 测试输出的存储错误和关闭超时为既有注入用例；本轮未修改业务源码或重建覆盖运行资源。

下一步先修复第 7.2 节的 PERF05 引用释放问题并复验，再推进 PERF03 的分摊测量；PERF04/PERF07 继续保留真实桌面、长期运行及冻结 EXE 的具体验收缺口。

## 8. 第三轮：PERF05 尾批释放返修复验

基线：`a55414c`。本轮只复核上轮 P2 的修复，不重新扩大到已验收的前端及摘要缓存，也不修改业务代码。

### 8.1 修复与独立验证

`EventLogWriter._run()` 在末尾 `_write_batch(batch)` 返回后清空 `batch` 与 `item`，再进入关闭分支或下一次阻塞等待。释放的是已处理事件的局部强引用，barrier、sentinel、计数和关闭所有权保持原路径。

除了新增的 `test_written_tail_batch_is_released_while_worker_idles`，本轮使用临时日志目录做独立边界验证：批上限设为 8，先以 Event 阻塞第一次写入，随后分别排入 1、7、8、9、16 条合成事件，再解除阻塞。等所有事件写入、队列自然排空后，删除外部强引用并检查 weakref；观察前不调用 flush 或 close。

| 第一批之后排队的事件数 | 总写入数 | 空闲时队列 | 仍被持有的事件数 |
| --- | ---: | --- | ---: |
| 1 | 2 | 空 | 0 |
| 7 | 8 | 空 | 0 |
| 8 | 9 | 空 | 0 |
| 9 | 10 | 空 | 0 |
| 16 | 17 | 空 | 0 |

不足一批、恰好一批、跨批与多批场景均可自然回收已写对象；上轮“显式 flush 才释放”的复现条件不再成立。

### 8.2 相关回归与结论

`.venv/Scripts/python.exe -B -m unittest tests.test_event_logger tests.test_retention tests.test_close_coordinator -q`：53 项通过，覆盖批次上限、尾批回收、日志失败、过载、分片与关闭保存相关路径。测试中的存储错误/超时日志是既有注入场景，不是本轮执行失败。

结论：**第 7.2 节的 P2 已修复，PERF05 的批次限制及空闲引用释放通过本轮验收，未发现该局部修复引入的新问题。** 本轮没有重新测量整机内存，也没有给出解码树字节硬上限；真实慢盘/长期采集和桌面整机收益仍按原缺口保留。PERF03/PERF06 不追加完成标记。
