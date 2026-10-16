# Luna 性能修复验收（2026-10-15）

状态：**整体不通过，需要返修**。读者：用户、Luna、复核者。
维护边界：本目录是本次验收快照与合成探针，不替代 ROADMAP 的持续状态，不新增统一测试门禁。

基线：`de12fca` 加验收开始时全部未提交改动。验收没有修改生产代码、现有测试或发布目录；仅新增本目录，`npm run build` 生成了被忽略的 frontend/dist 暂存产物。原有代码、文档、素材与测试改动均保留。

性能方向有效，多个原始反例已经消失；但仍有三个 P1 交付阻断项，以及草稿与新 writer 生命周期缺口，不能按“R01–R11 已完成”整体验收。

## 1. 阻断与返修项

### A01 / P1：切回正在保存的蛋，表单会沿用另一枚蛋的字段

位置：`frontend/src/components/EggBoxDetail.vue:32-44,103-108`。

保存开始后把 `state.pending` 清为 null，但没有保存该目标的当前草稿。A 保存中切到 B，再切回 A，watch 看见 A 的 `running=true`、`pending=null` 就直接返回，表单仍是 B 的值。此时只修改备注，也会把 B 的性格一起写到 A。

实际 SFC setup 复现：A 初始性格 0，编辑成 1；B 性格 9；A→B→A 后表单性格为 9，后续保存序列为 A/性格1、A/性格9/新备注。用户未对 A 选择性格9。这是数据覆盖风险。

原报告的“两次连续编辑 A 后切 B，第二次错误写 B”反例已修复，两次发送都正确绑定 uid=101、id=1；当前缺口是切回目标时草稿恢复。

返修要求：按 uid+instance_id 独立保存完整的最新草稿；正在发送的值与待发送队列分开，不能用 pending 是否非空代表是否存在草稿。增加 A→B→A 的 deferred-promise 回归。

### A02 / P1：Store.close 仍可能在显式 flush 未完成时报告关闭成功

位置：`spritelens/repositories/pet_store.py:422-433`、`egg_store.py:347-358`。

close 只等待内置 worker，再检查 pending。调用方线程已经通过 flush 取走批次时，pending 为空；被 stop 唤醒的内置 worker 会直接退出。因此 close 可以在另一个 flush 仍在途时成功返回。随后组合根正常关闭 DB，在途写入报 `ProgrammingError`，并回填一条无人再写的 pending。

两个 Store 的受控结果均为：`close_error=null`、`flush_alive_at_close_return=true`、`flush_errors=[ProgrammingError]`、`pending=1`。

HTTP 取消后等待受跟踪线程的正常关服路径已通过，能减少这个窗口；它不能替代 Store 自身对已经受理的并发 flush 的关闭契约。

返修要求：关闭成功前有界等待已经开始的 flush，并在该同步边界内确认待写状态；超时保留 DB 和清理所有权。不要恢复 join 后无界调用同步 flush 的旧实现。保留本次已通过的“内置 worker 写失败→5秒超时→恢复后由同一 worker 完成重试”行为。

### A03 / P1：运行目录还是旧 Vue 包，与新的摘要接口不兼容

位置：`spritelens/web/payloads.py:196`、`spritelens/web/static/vue/build.json`、`tools/frontend.py:check/build`。

新 Python 列表已经不返回 stats/skills/detail，当前运行目录中的 Vue 包却仍按完整 Pet 校验列表。直接从该运行包抽取实际列表解析函数，用当前 Python 生成的有效摘要载荷调用，抛出“宠物列表数据格式不正确”。因此不能因为源码构建通过就认为应用当前可用。

证据：

- `npm run build`（含 vue-tsc）通过，但只生成 frontend/dist。
- `tools/frontend.py check` 退出码 1，提示 Vue 产物过期。
- `build.py --dry-run` 同样被过期产物检查阻断。
- 运行包 source_hash 为 `abc17ad49dd95862d74ea2a3341d875b44db4e076772a96c5de390fcd0d5e595`；验收源码为 `f89845261366756b0a71499cdbfcb9870a0d15954879f112752c018caa2483f3`。
- 当前 TS 源码解析同一已知队伍摘要和详情成功；运行包解析该摘要失败。

返修要求：源码问题修完后通过 `.venv/Scripts/python.exe -B tools/frontend.py build` 发布专用运行产物，随后 check、打包 dry-run 和摘要→选中详情流程通过。不要把后端恢复为全量详情来迁就旧包。验收保留了旧运行目录，未代替实现者补发布。

### A04 / P2：保存失败的草稿在窄屏详情关闭后丢失

位置：`frontend/src/components/EggBoxDetail.vue:28`、`frontend/src/pages/EggBoxPage.vue:277-283`。

saveStates 放在详情组件内部。窄屏关闭详情会因 aside 的 v-if 卸载组件；重新打开时 Map 已丢，未保存备注和错误/重试入口一起消失。选中项因筛选改变而使详情卸载时也有同样问题。

实际复现：保存失败前表单为 `unsaved draft` 且有错误；卸载重挂后 note 和 error 均为空。

返修要求：把按目标保存的草稿、错误与保存队列所有权放在页面/composable，详情只展示和触发命令；这样也可与 A01 共用同一份草稿状态。不要新增持久化草稿功能，范围只需覆盖当前页面生命周期。

### A05 / P2：新增 checkpoint writer 没有覆盖所有现有调用方的生命周期

位置：`spritelens/capture/key_store.py:122-125`、`spritelens/recording/replay.py:61-85`。

主应用 AppContext 已持有并关闭 KeyStore，这是正确的。但 run_replay 创建 KeyStore 后没有 close；原同步存储现在变为常驻 daemon writer，CLI 返回时可能还有 checkpoint 未写完。后台写完后也会停在 Condition.wait，缺少生命周期所有者。

用临时目录和 ACK 录制实际调用 run_replay，结果为退出码0、writer_alive_at_return=true、close_requested=false。探针随后主动释放并关闭自己创建的 writer，未泄漏真实运行资源。

现有 session_resume 回归也未适配异步保存和 close：5个用例立即 load_session 得到 None；其中4个还发生临时目录清理错误。不能把异步改动后保留的旧同步断言当作已覆盖接续/失效。

返修要求：为 CLI/replay 等创建者补齐 try/finally 排空与关闭；测试先登记 KeyStore 清理，再按新异步契约确定性等待已写边界，保留原会话恢复/失效规则覆盖，不用 sleep 碰运气，也不要把磁盘 IO重新移回采集锁内。

## 2. 性能复测

使用原报告相同 benchmark、真实静态目录、合成宠物和解码事件；构造/编码取3次中位数。下表为最终留档一轮，几轮之间有调度波动，2000只构造+编码约34–47ms。

| 场景 | 原报告基线 | 本次最终留档 |
| --- | ---: | ---: |
| 100只构造 / JSON | 10.28 / 3.58ms | 2.81 / 0.56ms |
| 1107只构造 / JSON | 74.28 / 38.57ms | 19.63 / 6.65ms |
| 2000只构造 / JSON | 178.92 / 76.74ms | 31.41 / 11.76ms |
| 2000只 UTF-8 JSON | 6,208,669字节 | 1,290,729字节 |
| 2000条×1000字段 drain | 747.53ms | 9.50ms |
| 20段录制、慢flush 20ms，append总耗时 | 409.18ms | 0.08ms；停止后20段、丢弃0 |
| 同名缺图9并发下载次数 | 9 | 1；inflight最终为空 |

额外受控验证：

- 200ms同步查询放入线程后，10ms计时器在约26ms完成，未等待整段200ms IO；这不是跨机器响应SLA。
- 慢WS挂起时健康连接在30ms观察点前收到；慢连接最终移除并关闭。
- 取消HTTP等待后关服，shutdown等待受跟踪线程实际结束，最终跟踪任务数0。
- EventsVM drain 不格式化详情；同一详情两次读取只格式化一次；原事件与缓存合计200；淘汰提示保持。
- checkpoint慢写时版本10、11、12合并为写10、12，close后writer退出。
- 精灵详情实际 Python→TS契约通过（已知队伍状态）；两笔乱序详情保持最新选择，resetAccount后旧详情不能提交，错误uid返回409。

这些改善支持继续保留 Python 技术栈。列表仍返回全部命中摘要，bootstrap也仍带全库存摘要；尚未测浏览器解析、首个可交互、真实HTTP p95或WebView2卡顿，暂不据此决定服务端分页。

## 3. 逐项结论

| 原报告项 | 验收结果 |
| --- | --- |
| R01 | 受控倒序最终均为20；在途写入期间两个Store读取均阻塞到提交并找到数据，通过当前场景。 |
| R02 | 内置worker失败/恢复/同一worker重试通过；显式flush关闭竞态失败，见A02。 |
| R03 | 原错目标反例通过；A→B→A字段污染和卸载丢草稿失败，见A01/A04。 |
| R04 | 性能及惰性格式化/缓存/淘汰通过。 |
| R05 | 慢IO可调度、取消后线程所有权通过；路由仍直接编排Store/快照/详情构造，原计划要求的service/VM命令边界没有完整落实。 |
| R06 | 源码摘要/详情、乱序与切号保护、类型构建通过，运行包未发布导致交付失败，见A03；浏览器体验未验收。 |
| R07 | 录制旁路与checkpoint合并效果通过；调用方生命周期与会话回归未闭环，见A05。 |
| R08 | 慢连接不阻塞同批健康连接、超时移除通过。 |
| R09 | 静态确认每事件只提取一次，试用/镜像学习过滤仍保留；相关pet回归通过。未另做代表性大页profile。 |
| R10 | 9并发缺图仅下载一次，完成清理通过。 |
| R11 | build_command实际生成资源参数仅含schemas/static/Web静态目录及app.ico，无wiki候选目录；完整dry-run受A03阻断，未构建exe。 |

## 4. 现有验证结果与缺口

后端第一批：

```powershell
.venv/Scripts/python.exe -B -m unittest tests.test_persistence tests.test_egg_box tests.test_view_models tests.test_session_resume tests.test_recording tests.test_web_server -q
```

104个用例，FAILED（10 errors，来自6个用例，含4次清理错误）：

- test_failed_flush_retry_keeps_newest_value：仍断言flush失败返回0；新实现抛OperationalError，测试未适配。应保留“失败回填新值优先”规则，并明确显式flush的新异常契约。
- session_resume的 restart / other_flow / new_handshake / new_syn / new_identity 五个用例：仍立即读取异步保存结果，均在seed阶段失败；其中4个还有临时目录非空错误。

这些错误中包含契约变化引起的旧测试失配，不等于六条业务规则均已被证伪；但意味着必要回归目前没有通过，不能宣称接续/失效和失败回填已验收。

后端第二批：

```powershell
.venv/Scripts/python.exe -B -m unittest tests.test_runtime_repair tests.test_pets tests.test_pet_snapshot_contract tests.test_frontend_contract -q
```

29个用例通过。Vue usePets 与 API client 相关6个用例通过；npm run build（vue-tsc+Vite）通过；git diff --check通过。没有运行统一全套门禁、ESLint或恢复浏览器测试框架。

额外发现一个**基线已存在**的契约缺口，未归咎本轮实现：Backpack.active_team未知时后端输出null，而parsePets要求非负整数，导致无队伍快照/未知状态载荷被拒绝。已对照HEAD确认两侧原本如此。backend-contract.json与detail-results.jsonl保留该反例；完整未知/离线场景验收需单独处理。

未执行：真实账号数据写入、外网CDN、Npcap高负载/真实驱动卡死、可见WebView2或GUI交互、浏览器解析与首个可交互时间、长会话RSS、exe/onefile构建与启动。未将ROADMAP改为已验收。

## 5. 返修顺序与证据入口

先修A01/A04（同一草稿所有者切片）及A02，再补A05调用方关闭与必要回归；源码稳定后完成A03官方前端发布，重新运行相关回归、产物check和打包dry-run。R05命令边界仍需按原计划局部收口，避免向server继续加入业务编排。附发现的active_team未知契约单独标注范围，不混淆本轮新增与原有问题。

证据文件：

- [probe_backend.py](probe_backend.py)、[backend-results.jsonl](backend-results.jsonl)：批次/读取/关闭、慢IO/WS/缺图、录制/checkpoint、CLI生命周期与性能。
- [probe_frontend.cjs](probe_frontend.cjs)、[frontend-results.jsonl](frontend-results.jsonl)：实际蛋仓SFC setup的3种保存时序。
- [probe_detail.cjs](probe_detail.cjs)、[detail-results.jsonl](detail-results.jsonl)：实际TS模块与运行包解析器、详情乱序/切号。
- backend-contract*.json：由当前Python载荷生成的合成摘要/详情，区分已知与未知队伍。

在仓库根目录复跑三个探针；backend探针会重新导出detail探针使用的合成载荷：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -B output/acceptance-20261015-performance/probe_backend.py
node output/acceptance-20261015-performance/probe_frontend.cjs
node output/acceptance-20261015-performance/probe_detail.cjs
```

它们只打印受控结果，并非新增门禁；发现反例不会自动全部转换为非零退出码，验收应对照字段含义。
