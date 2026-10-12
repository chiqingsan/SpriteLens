# GLM 稳定性与工程门禁交付复核

状态：带日期的审查快照，不维护后续任务状态。读者：实现者、维护者与 AI 协作者。
用途：记录本轮交付的验收证据、失败复现和返修边界；持续状态见 [ROADMAP](../ROADMAP.md)。

## 1. 范围与结论

基线：`a106044`；对比 `240b94c`，重点复核 S01、S02、S03a、S04、G01。
审查前工作区干净。本次只更新审查与维护文档，未修改生产代码，也未替 GLM 实施返修。

**本批不能整体验收：正常装配必然失败，且录制一致性、停止所有权、启动超时和 HTTP 契约仍有可复现缺口。**
已有改进可以保留：running 判定进入服务命令锁、装配资源登记、退出逐项容错、录制器失败仍尝试停源、
部分 HTTP 严格类型校验、query 助手收口，以及统一工程门禁。Vue 工程未实施。

## 2. 验证证据

所有业务数据检查使用临时目录；无真实游戏流量、无真实采集启停、无驱动/系统配置修改。
并发与启动复现使用 Event 控制顺序，检查结束后释放替身和线程。

| 检查 | 结果与边界 |
|---|---|
| `.venv\Scripts\python.exe -B tools\run_build_tests.py` | 374 项 unittest 通过；9 个 JS 递归语法、HTML 引用、15 项静态清单、依赖检查通过 |
| 隔离数据目录源码 `--smoke-test` | 设置 `PYTHONIOENCODING=utf-8` 后通过；此入口不调用真实装配，不能证明 GUI 能启动 |
| 正常 `build_app_context(autostart=False)` | 保留真实 DB/Store/log 装配，仅关闭 VM 后台环境探测；在第 216 行稳定触发 NameError |
| 两个相反录制命令 | 在首个服务调用完成、VM 缓存回写前暂停；最终 VM=True、service=False、磁盘=False |
| 配置写入失败 | 替换 `Path.write_text` 为抛 OSError；命令成功返回、内存=True，磁盘仍=False |
| worker 未退后重启 | 用阻塞回调与 0.01s worker join 预算；旧线程活着时新 worker 已创建且 running=True |
| sniffer 停止卡住 | 替身 stop 阻塞；等待超过 worker 预算仍未返回，sniffer 句柄已被清空；安装版 scapy stop 默认 join=True，调用无期限 join |
| HTTP 启动超时 | 暂停 `_run_loop` 进入点，让 start 超时，再释放；后台线程仍活着，HTTP 首页返回 200，同时 `_stopped=True` |
| 入口装配失败 | 注入 build 异常；guard.close 与 `_fatal` 均未调用 |
| 实际网卡 HTTP 命令 | `[]` / 坏 JSON 返回 500 文本；`{}` / `{"name":null}` 返回 200 并清空原有网卡 |
| G01 负例 | 临时源码 events→services、相对导入均被拦截；缺 egg-dex 文件被拦截；新增子目录坏 JS 被拦截 |

未验收：新建 Python 3.12 环境安装、GUI/WebView2、真实卡住驱动、打包 exe、慢盘退出。
未设 UTF-8 的当前 PowerShell 管道运行 smoke 会因输出 `✓` 触发 GBK 编码错误；这是既有入口问题，不能把环境覆盖后的通过描述为默认命令在所有终端都通过。

## 3. 必须返修的问题

### D01 / P0 / S02：正常装配必然 NameError

位置：`spritelens/app_context.py:216`。
`created` 是外层 `build_app_context` 的局部变量；独立定义的 `_build_app_context_inner` 无法访问它。
因此成功装配路径执行 `created.clear()` 必然抛异常，外层随后回滚资源，应用无法完成启动。

修复所有权转交的作用域；补真实成功装配→使用→关闭→重复关闭用例。
不要仅删这一行后就宣告 S02 完成：capture_vm/source 尚未登记失败回滚，autostart 之后失败也必须停源。
当前新增回滚测试只在 EggStore 构造处提前失败，没有执行正常返回路径。

### D02 / P1 / S01：VM 锁外回写仍能覆盖较新的录制意愿

位置：`spritelens/view_models/capture_vm.py:236-237`。
T1 开录制完成服务调用后暂停；T2 关录制完成服务、持久化与 VM 回写；T1 恢复，把 VM 缓存写为 True。
服务与配置为 False，页面 `/api/capture` 却返回 recording_requested=True。

录制意愿应有单一权威所有者；消除平行缓存，或让全部状态提交遵循同一完整命令顺序。
回归须暂停在服务锁释放后、VM 回写前，而非仅暂停锁内 persist；覆盖 toggle 与 start/stop。

### D03 / P1 / S01、S04：配置写失败仍报告成功

位置：`spritelens/view_models/capture_vm.py:123-124`；同类调用见 select_iface/set_autostart。
注入的是吞掉 OSError 的 `SettingsRepository.set`，服务文档声称的“异常传给 HTTP”没有发生。
显式录制、自动采集、网卡设置可返回 200，但重启后恢复旧配置，内存和磁盘也不一致。

显式命令使用可观测保存结果，明确运行状态已生效但保存失败的语义；HTTP 返回可读错误。
现有 set_checked 可供实现选择，但不能只替换调用而不处理运行/意愿状态提交与失败响应。
补录制器 start/stop 失败与配置失败，检查页面意愿、下次启动意愿、实际状态、磁盘和响应。

### D04 / P1 / S03a：保存 stale 句柄后仍允许新旧投递并存

位置：`spritelens/capture/npcap_source.py:93-104`、`:215-230`；`spritelens/services/capture_service.py:77-86`。
start 未检查 stale，reap/diagnostic 无运行调用方。阻塞旧回调后 stop 超时，再 start 仍创建新 worker。
同实例共享 queue，新的 worker 可能抢走旧哨兵；服务重启则直接覆盖旧 source 引用，迟退回调仍指向同一 monitor/recorder。

服务层保留未退 source 的所有权，明确拒绝重启或隔离采集代次的策略；旧回调不得污染新会话。
回归必须真的重启并释放旧回调，验证线程/队列/回调归属；当前测试只查看 stale 列表，没有执行 restart。

### D05 / P1 / S03a：sniffer 停止没有预算且提前丢句柄

位置：`spritelens/capture/npcap_source.py:177-183`。
调用 `sniffer.stop()` 的默认 join 没有超时；只给投递 worker join 设预算不能限制整个 stop。
卡住时命令锁一直被占用，后续采集命令及退出被阻塞；同时 `_sniffer=None`，诊断也看不到尚未退出的嗅探器。

审查实际 scapy 停止接口，保留嗅探器句柄和超时状态，给停止流程明确预算；预算需包含相关流锁/monitor 清理。
用可释放的 sniffer、下游回调替身验证，而非仅用没有 sniffer 的 worker 用例。

### D06 / P1 / S02：启动超时仍可能晚到后运行服务

位置：`spritelens/web/server.py:139-147`、`:168-187`。
超时时若后台还未建立 loop，`_stopped=True` 只是标记；线程稍后进入 `_run_loop`，仍绑定并 run_forever。
已用 Event 稳定复现超时后首页 200、线程存活。
loop 已运行时直接 stop 也未保证已创建 runner/site、待启动任务被清理；`_run_loop` finally 仅 close loop。

用明确取消/停止握手覆盖超时发生在 loop 创建前、启动中、绑定后的路径，清理 runner/site 和任务后才退出。
检查重复 stop；关闭的 loop 不得再次 call_soon_threadsafe。
当前超时测试依赖 1ms 概率，最终只断言 timed_out 为 bool；成功分支甚至不停止新建 server，无法证明回收。

### D07 / P1 / S02：入口装配仍在清理保护区之外

位置：`spritelens/web/run.py:53-55`。
guard 获取后，WebView2 检查、build_app_context、LocalServer 构造并未被统一 finally 覆盖。
装配抛异常时 guard.close 和启动错误提示都未调用；server 构造失败时已建 context 也不会关闭。
open_browser 的打开动作同样位于等待段 try 之外。

资源获得后立即进入覆盖后续步骤的清理保护，支持只创建部分资源的退出；验证每个入口节点失败。
`_shutdown` 的逐项容错可以保留，但单独测试它不能证明 run_web 一定调用它。

### D08 / P1 / S04：网卡命令未覆盖新的 JSON 异常契约

位置：`spritelens/web/routes_capture.py:34-40`。
`_json_body` 已改成抛 ValueError，iface handler 未捕获，数组/坏 JSON 变成 500。
缺 name/null 又被默认成空字符串，200 清除原网卡，违反必填字符串与非法输入零副作用的目标。

统一 name 必填/类型校验及可读 400；清空网卡若仍被支持，应要求明确空字符串。
实际 HTTP 回归覆盖全部修改命令的数组、坏 JSON、缺字段、null、错类型与合法值，并覆盖 IO 失败。

## 4. 后续实施与验收边界

1. 先修 D01 并补成功装配；随后完成 D07/D06 及 autostart 后回滚，重新验收 S02。
2. 修 D02/D03，明确失败状态与保存语义，再验收 S01。
3. 修 D04/D05，验证旧回调释放后的行为，再验收 S03a。
4. 修 D08 和相关 IO 错误响应，再验收 S04；复用 S01 的保存失败证据。
5. G01 的本机门禁与主要负例已验证；补可重复的成功装配、确定性超时/重启回归及全新环境安装证据。
   新环境需声明 Node 前置；缺 Node 的当前检查会抛 FileNotFoundError，函数注释中的“报告跳过”并未实现。

以上按单个编号提交，不打包重构。下一步 F00/V01/V02 的顺序保持；本轮没有 frontend/package.json、TS 或 Vue 组件，
不能把 Vue 决策文档记成 MVVM 前端工程已经落地。S03b 与资源/发布任务按原路线继续。
