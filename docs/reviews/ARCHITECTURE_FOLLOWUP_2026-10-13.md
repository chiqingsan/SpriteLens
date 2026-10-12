# 架构改动复核（2026-10-13）

状态：带日期的复核快照。读者：维护者、GLM 实现者与架构复核者。
基线：`240b94c`，开始时工作区干净。范围：复核 `114be08..240b94c` 的稳定性/架构改动，
校正完成范围与后续任务；本轮只调整文档和协作规则。持续任务状态见 [ROADMAP](../ROADMAP.md)。

## 已落实与判断

R01–R08 的修复已有实现与相应回归；事件中立化、实例 schema 注入、CaptureService、
采集路由/目录载荷拆分、宠物请求快照及蛋图鉴页面抽取方向合理。
本轮完整测试通过，但没有依据把 R09 写为全部完成，或把阶段1写为后端全部完成。
拆出模块后，需要继续检查事务范围和数据契约，不能仅比较文件行数。

| 当前文件 | 行数（含空行/注释） |
|---|---:|
| web/server.py / web/payloads.py / web/payloads_catalog.py | 510 / 240 / 437 |
| web/static/app.js / pages/egg-dex.js | 1903 / 171 |
| tests/test_persistence.py / test_egg_box.py / test_web_server.py | 1136 / 600 / 527 |

## 本轮隔离复现

以下使用临时目录、Mock、fake recorder/monitor 和 Event，未使用真实抓包、密钥或用户数据。
复现目前是本轮检查证据，尚未转入永久测试；对应任务实现时须先固化失败用例。

### C01：录制抽取后命令不再整体串行（S01，P1）

位置：`view_models/capture_vm.py:231`、`services/capture_service.py:102,138`；由 `38c3b73` 引入。
VM 先写 `_recording_requested` 和 service 意愿，再写设置，最后进入 service 命令锁；
其中 running 是调用前读取。意愿与持久化不在同一串行区间。

确定性步骤：采集状态设为运行；T1 请求 true，在写设置前由 Event 暂停；
T2 完整请求 false；恢复 T1。实测结果：

```text
requested=False  wanted=False  persisted=True  actual=True
```

页面声明不录制，实际仍录制。另按“调用方已读 running=true → stop 完成 → 提交旧值”执行，
service 可在 `running=False` 时开启录制。修复要覆盖完整命令顺序，而非只给字段赋值再加一把锁。
VM 的 `_service_note_error()` 直接改 service 私有字段，也绕过了该服务的状态边界。

### C02：装配失败与外层清理未闭环（S02，P1）

位置：`app_context.py:106`、`web/run.py:274`。
`build_app_context()` 在最终返回 context 前没有资源登记/回滚保护。
用 Mock 替代外设/资源，在 EggStore 构造处注入失败，已创建 Database、PetStore、EventLogWriter
的 close 均未调用；真实 EventLogWriter 会在构造时启动 worker。

外层 `_shutdown()` 注入 context.close 失败，调用记录只有 `[server, context]`，guard 未关闭。
AppContext 内部已经做到单项失败不跳过其它资源，但这不能覆盖外层入口。
LocalServer.start 的等待超时也缺少取消启动并清理的明确路径，需要一并验收。

### C03：非法 HTTP 输入仍产生成功副作用（S04，P1）

位置：`web/routes_capture.py:46`、`web/server.py:456`。
直接以 fake Request 驱动 handler，观察状态码及 VM 收到的参数：

| enabled 请求 / body | 状态码 | 实际传入命令 |
|---|---:|---|
| `{"enabled":"false"}` | 200 | True |
| `[]` | 200 | False |
| 坏 JSON（JSONDecodeError） | 200 | False |

这是原有问题随路由抽取保留，不能因 R09 的命令锁完成而关闭整项。
非法输入应 400 且无副作用；合法布尔值与 IO 失败分别测试。

## 源码核查发现的未完成范围

- **停止保证不完整（S03a/S03b）**：Npcap 的队列通知和 worker join 已有界，但 sniffer.stop()
  没有显式停止预算；worker 句柄在 join 前就清空，超时后仍可能执行旧回调。CaptureService.stop
  先停 recorder，异常会跳过 monitor.stop。Store close 的 join 超时后仍会同步 flush 并等待落盘锁，
  没有证明整个退出有界；失败 flush 回填不等于已保存。上述为路径检查，本轮未模拟真实卡死驱动/磁盘。
- **快照覆盖不完整（F01/F02）**：/api/pets 的 PetView 已使用同源主要快照，但 bootstrap 仍给
  pets_payload 传共享 VM；overview 和 WS 分次读取统计、身份、版本；蛋仓分别取 entries/slots/version/uid。
  PetRepoSnapshot 中 uid 尚未进入 pets 响应，依赖当前宠物的选项仍可能回读 VM。
- **门禁遗漏（G01）**：smoke 固定清单没有 `pages/egg-dex.js`；AST 收集相对导入后仍被绝对前缀判断跳过，
  根 events 模块的源层级未取到；只禁止若干 IO import 不证明零文件 IO。脚本本轮语法有效，但页面行为未重新验收。
  recorder 的细粒度层级目前只用于目标依赖判定，源模块仍按 recording 包层级处理，也需补违规样例。
- **边界抽取仍有过渡点**：routes mixin 依赖宿主状态，capture/state JSON 仍在 mixin 中；server 与 helpers
  有同名 query 函数并存。继续扩展应明确归属，避免产生更多隐式 mixin 依赖；无需立即改成框架。
- **资源与依赖工作未落实（A01–A04）**：工具仍有本机临时输入默认值，requirements 未声明 Pillow，
  全新环境安装、输入 revision/hash、分阶段暂存发布和资源发布清单仍待实现。

## 验证与限制

| 验证 | 本轮结果 |
|---|---|
| `.venv\Scripts\python.exe -B tools\run_build_tests.py` | 364 项通过，9.877 秒 |
| `node --check`，递归包含 pages | 9 个 JS 文件通过 |
| 隔离 SPRITELENS_DATA_ROOT 的源码 `--smoke-test` | 通过，scapy 枚举到 6 个网卡；不证明抓包可用 |
| C01–C03 临时复现 | 结果如上；没有改生产代码或永久测试 |
| GUI / 真实游戏 / 长期会话 / exe / 全新环境安装 | 本轮未验收 |

建议下一轮交给实现者的范围是 S01，随后 S02、S03a、S04、G01；
具体任务边界与完成标准维护在路线图，避免在本快照重复更新状态。
