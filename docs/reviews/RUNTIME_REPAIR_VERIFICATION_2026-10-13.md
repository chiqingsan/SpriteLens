# E01–E06 运行时返修与复验

状态：当次实现及验证记录。读者：维护者、实现者与 AI 协作者。
用途：记录用户授权 Codex 直接修复后的边界和证据；持续任务状态见 [ROADMAP](../ROADMAP.md)。
基线：`477bd75` 加二次复核文档改动；这些工作区文档保留并继续同步，未回滚用户改动。

## 改动与结果

| 问题 | 最小修复 | 回归证据 |
|---|---|---|
| E01：HTTP 等待 IO 命令锁 | 录制意愿使用独立短状态锁；录制计数读取也不等待文件 IO 锁 | persist 持锁等待 Event 时，capture GET、首页、WS 初始状态仍响应；文件锁被占用时计数读取可完成 |
| E02：嗅探器提前确认退出 | 保留 stop helper、异常结果及 sniffer；同时确认 helper/thread/running；失败句柄可在后续 stop 重试 | running 已 False、socket/thread 未退时拒绝重启；stop 报错保留句柄；释放/重试成功后清理 |
| E03：monitor 阻塞停止 | 服务拥有唯一停止线程和结果，调用方限时等待（默认 12s）；线程仍持命令锁，超时保留它，不并发重复清理、不重启 | monitor 锁被旧 worker 占用时短预算返回 TimeoutError；重复停止等待同一线程；释放后重试成功 |
| E03 下游保护 | AppContext 采集停止超时不置 closed，不关闭 log/Store/DB；装配回滚与外层清理超时也保留下游 | 旧回调仍活跃时 Store.close 未调用；释放后 context 可重试正常关闭。HTTP stop 未完成返回 JSON 503/stopped=False |
| E04：HTTP stop 超时丢所有权 | loop 拥有唯一停止协程；清完 runner 才停 loop；等待超时保留 thread/loop/runner/future；收尾取消并等待 pending task | 阻塞 loop 后短预算超时，句柄保留；重复 stop 复用 future；释放后线程退出、loop 关闭、端口不可连且异常处理器无 pending task 记录 |
| E05：IO 错误误分类 | RecordingCommandError 区分 start/stop/save；HTTP 给出 error_kind、requested、recording、saved；网卡提示下次启动的选择 | 三类实际 HTTP 500 分别断言运行状态与保存事实，stop 失败仍录制、start 失败未录制、save 失败运行状态已提交 |
| E06：缺 Node 误报通过 | 缺 Node 返回失败项，完整门禁 exit=1 | main 的缺工具负例明确失败，输出不含“JS 语法通过” |

新增 `tests/test_runtime_repair.py` 的 8 个行为回归。相关旧测试补录制器清理，消除文件占用；
旧并发启停测试原先调用真实驱动、靠 sleep 交错，改为假嗅探器与 Event，验证停止期间拒绝重启。
没有引入通用线程管理器、DI 容器或新 Web 框架。

## 复验

- 新增回归及相关并发启停：9 项通过。
- 完整工程门禁：398 项 unittest、9 个 JS、HTML 引用、15 项静态清单、依赖检查通过。
- 隔离数据目录真实 build_app_context(autostart=False)：bootstrap/capture/state HTTP 均 200；
  未采集时录制意愿保存成功、actual recording=False；server/context 重复关闭安全。
- 同一隔离目录源码 `--smoke-test`（Python UTF-8 输出）通过，枚举到本机 6 个网卡。
- 文档引用、UTF-8/LF 与 `git diff --check` 检查通过。

## 保留边界

无法强制终止卡住的 Python/驱动线程：本实现返回未完成、保留所有权与下游资源，要求故障解除后重试停止；
不会声称超时代表资源已释放。外层退出仍释放单实例 guard，进程终止由系统回收未退资源。
监控 checkpoint 与录制写入仍同步 IO；PetStore/EggStore/EventLog 的最终 flush、慢盘退出与 DB 生命周期仍属于 S03b。
新建 Python 3.12 依赖环境、GUI/WebView2、真实卡死驱动、exe 发布未重新验收；不能据本机回归关闭这些任务。
Vue 工程仍未实施。下一步可以推进 F00/V01，并独立完成 S03b 与发布环境验收。
