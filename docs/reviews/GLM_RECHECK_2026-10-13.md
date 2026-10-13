# GLM 返修二次复核

状态：带日期的审查快照。读者：实现者、维护者与 AI 协作者。
用途：核验 D01–D08 返修及其新增风险；持续状态见 [ROADMAP](../ROADMAP.md)。
基线：`477bd75`，对比 `a106044`；审查前工作区干净。本次只更新文档，未修改生产代码。

## 1. 验证与结论

**P0 启动阻断已修复；本批仍不能整体验收，剩余问题主要在慢操作、停止超时及失败语义。**

| 检查 | 结果 |
|---|---|
| 完整 `tools/run_build_tests.py` | 390 项 unittest 通过，9 JS、HTML 引用、15 项静态清单、依赖检查通过；测试输出含录制文件未关闭的 ResourceWarning |
| D01：真实装配→HTTP→关闭 | 隔离数据目录，仅关闭 VM 后台环境探测；真实 DB/Store/log 装配成功，`/api/bootstrap` 返回 200，server/context 重复关闭安全 |
| D02：服务调用后暂停再反向切换 | VM、服务、配置均为 False，旧平行缓存回归已消除 |
| D03：真实配置写入失败 | 替换 Path.write_text 抛 OSError；recording/autostart/iface 均返回 JSON 500，已不吞错误；录制器失败分类另见 E05 |
| D04：服务层旧 worker 未退 | 保留旧 source，拒绝创建新 source，错误可读；同实例拒绝与释放后重启有门禁回归；嗅探器分支另见 E02 |
| D05：sniffer.stop 预算 | 独立停止线程已加入；超时返回存在，停止确认与整体停止预算仍不完整，见 E02/E03 |
| D06：启动超时 | 新增 loop 创建前、启动中、绑定后三路径用例通过；正常启停通过。普通 stop 超时仍丢所有权，见 E04 |
| D07：入口保护 | run_web 的 finally 已覆盖预检/装配/构造/浏览器/窗口；装配与构造失败清理回归通过 |
| D08：网卡非法体 | 实际 HTTP 的数组、坏 JSON、缺字段、null、错类型均返回 400，原网卡不变 |
| G01 缺 Node | 不再抛 FileNotFoundError，但跳过后仍输出“JS 语法通过”并返回 0，见 E06 |

补充检查使用临时数据和可释放的 Event/替身；无真实磁盘破坏或系统配置修改。
未验收 GUI/WebView2、真实卡住驱动、exe、新建依赖环境、慢盘持久化退出。
生命周期新增测试仍有固定 sleep/Timer，并非全部由 Event 确定到达顺序。

## 2. 剩余返修

### E01 / P1 / S01：录制意愿读取把命令锁带入 HTTP 事件循环

位置：`spritelens/services/capture_service.py:149-152`，调用链为
`CaptureRoutesMixin._capture_payload → vm.recording_requested → service.recording_wanted`。

意愿单一所有者是正确改进，但 getter 同步等待包含磁盘 IO、采集启停等待的 `_command_lock`。
`GET /api/capture` 和 bootstrap 在 aiohttp loop 内直接调用；慢保存/停止期间一旦 GET 进入，整个 loop 被阻塞，
首页、其它 API、WS、退出协程均不能处理。

确定性复现：让录制 persist 在持锁状态等待 Event，再让 GET 到达 getter；随后访问首页超时。
释放 persist 后两个请求恢复。该等待没有 getter 超时。

保留意愿单一所有者，使用短状态锁/已提交快照，或明确将阻塞读取移出事件循环；
不要让页面快照等待完整 IO 命令。回归须在慢保存、慢停止时证明独立 HTTP/WS 仍可响应。

### E02 / P1 / S03a：嗅探器停止确认仍会丢失活跃所有权

位置：`spritelens/capture/npcap_source.py:235-274`。

两个缺口已复现：

1. `sniffer.stop()` 抛异常时只记录 warning，返回 True，不保存句柄。
   替身保持 running=True 并抛 OSError 后，has_unfinished_sniffer=False，旧嗅探器不在 stale 中。
2. 超时句柄仅按 running 判定退出。当前安装版 scapy 的 `_run` 先置 running=False，随后关闭 socket，
   最后才退出 thread；独立 stop helper 此时仍在 join。模拟这个实际顺序，旧 thread 仍活着、
   helper 未返回时，has_unfinished_sniffer 清掉句柄，start 允许创建新 worker 并置 running=True。

保存嗅探器及停止 helper 的完成/异常状态，验证实际 thread 退出与资源释放；
running=False 不能代替 join 完成。异常但未确认退出时也保留所有权并拒绝重启。
测试至少覆盖 stop 异常、running 已 False 但 socket/thread 仍在关闭、以及释放后恢复重启。

### E03 / P1 / S03a：source 的等待预算没有覆盖 MonitorService.stop

位置：`spritelens/services/monitor_service.py:105-113`，入口为 `CaptureService.stop`。

source 的 worker join 超时返回后，monitor.stop 立即无期限等待 `_lock`。
真实 chunk 处理及 packet listener 就在这个锁内执行；只要旧回调/同步 checkpoint 持锁阻塞，
服务仍一直占有命令锁，退出无法到达后续资源清理。

复现：worker 持有 monitor._lock 等待 Event，source 的短 join 预算已结束并发出 stopped，
服务 stop 线程仍不返回；释放后才退出。现有 stuck worker 测试未覆盖真正的 monitor 锁。

定义从 service→source→monitor 的完整停止结果与预算；旧回调未退出时保留所有权和未完成状态，
不能继续关闭其仍可能调用的 Store/DB。checkpoint 慢盘可以关联 S03b，但不得据 source 返回就宣布 S03a 已有界。

### E04 / P1 / S02：LocalServer.stop 超时仍清空活跃线程和 runner

位置：`spritelens/web/server.py:171-191`。

`future.result` 与 thread.join 超时后，无条件把 `_thread/_loop/_runner` 清空；
而 `_abort_start` 已有保留未退线程逻辑，普通 stop 没有采用同一所有权原则。
运行线程的 finally 读取共享 `_runner`，提前清空会让兜底清理找不到资源。

复现：让真实 HTTP loop 在受控回调内等待，调用 stop(timeout=0.02)；旧线程仍活着，三个句柄均已清空。
释放回调后产生 pending task 被销毁、shutdown 未 await 的警告；再次 stop 因 `_thread=None` 无法重试。
E01 是实际业务中可以触发这种 loop 阻塞的路径。

超时保留 thread/loop/runner 与清理结果，由拥有线程确认退出后转交/释放；
覆盖运行中 stop 超时、后续释放、重试 stop、pending task 回收和端口不可连接。
当前成功 stop 与启动超时测试不能替代普通 stop 超时验收。

### E05 / P2 / S04：录制器 IO 错误被误报为“已生效但保存失败”

位置：`spritelens/web/routes_capture.py:68-75`。

捕获整个录制命令的 OSError，却统一描述为配置保存失败。
让 recorder.start 抛 OSError 后，实际 recording=False、配置写入根本未执行，HTTP 却说“录制设置已生效，但保存失败”。
recorder.stop 失败也会被同样误分类，用户无法知道是否仍在录制。

区分运行命令失败与偏好保存失败，响应明确 requested/actual/saved 或等价的可读事实；
保存失败保持现有已提交运行状态语义。补 start、stop、persist 三类错误的 HTTP 用例，不能仅检查 error 字段存在。
网卡偏好是下次启动生效，保存失败文案不宜描述成当前运行网卡已经切换。

### E06 / P2 / G01：缺 Node 后仍宣称完整门禁通过

位置：`tools/run_build_tests.py:53-56`、`:157-165`。

缺 Node 返回空 failures，main 输出“跳过”后又输出“JS 语法通过: 9 个文件”和最终“通过”，exit=0。
已用 shutil.which 替身验证实际 main 输出；unittest 替身仅避免重复运行 390 项测试。

完整工程/发布门禁应对必需工具缺失返回失败；若允许局部检查，显式报告不完整，不能将 skip 记为通过。
当前本机有 Node，9 个 JS 实际已检查；此缺陷影响新环境和发布信任度。

## 3. 交接顺序

优先 E01（事件循环阻塞）及 E04（超时后清理所有权），随后 E02/E03，最后 E05/E06。
按对应 ROADMAP 编号独立提交，不扩成通用锁、线程管理器或错误框架。
D01/D02/D03/D07/D08 的已验证改进保留，旧 review 不修改成当前事实。
F00/V01 的独立前置可以按原路线开展；运行命令页面与发布仍需通过相关稳定性门禁。
