# 2026-10-15 返修验收

状态：未通过，发现 2 项 P1、1 项 P2。读者：实现者与复核者。本文记录本轮工作区的受控验收证据，不代替真机发布验收。

基线：HEAD `de12fca` 加现有未提交改动。验收未修改生产代码或现有测试，只新增本目录的复现脚本与记录。全部探针使用合成 DTO、内存 SQLite、临时目录；未访问真实抓包、用户录制或真实密钥目录。

## 1. 需要继续返修的问题

### B01 / P1：切号清空 Map 后，旧目标的保存队列仍会与新队列并行写入

位置：`frontend/src/composables/useEggBox.ts:59-73,178-183`。

`resetAccount()` 清空 `annotationStates`，但旧 `drainAnnotations(state)` 仍持有原状态并继续发送 `pending`。切回同一账号、同一蛋后，Map 会创建另一个状态和保存队列。`saveGeneration` 仅限制最终刷新，没有限制下一笔写入或为同一目标保留唯一保存所有者。

实际 TypeScript 探针步骤：A 账号同一蛋发起 `old-1` 并挂起；继续编辑 `old-2` 进入原队列；切 B 再切 A；编辑 `new-3`；先完成新队列，再完成旧队列。

观察结果：请求顺序 `old-1 → new-3 → old-2`，最终后端保存 `old-2`，界面仍显示 `new-3`。最新编辑已经被旧队列覆盖，且界面未反映真实保存结果。

返修要求：按 `(uid, instance_id)` 保留唯一保存调度所有权，直到在途写入结束。账号展示状态失效不能让同一目标出现两个独立写队列；明确未发出的旧草稿与回到该账号后的新草稿如何合并，保证最新编辑最终落盘。只取消浏览器等待不能取消服务端已经执行的写入。

### B02 / P1：旧刷新结束后按 key 删除，会误删当前代次的新草稿状态

位置：`frontend/src/composables/useEggBox.ts:73-79`。

进入刷新前检查过 `generation`，但 `await load()` 返回后没有再次检查代次，也没有确认 Map 中仍是该 `state`。`load()` 自己会忽略过期响应，但调用者仍继续使用当前 `data.value`，随后按相同 key 删除状态。

复现：旧保存成功，其自动刷新挂起；切号失效并重新加载 A；同一蛋编辑 `new-draft`，新保存仍在途；放回旧刷新。旧 `load()` 没有提交响应，但旧 drain 的清理删除了新状态。

观察结果：表单备注从 `new-draft` 回退为 `saved-old`。接着只修改性格，新的保存把 `saved-old` 再写回，最终备注也丢失。

返修要求：异步刷新后的清理同时核对请求代次、账号及 Map 中状态对象身份；过期刷新不得清理当前代次的草稿、错误或保存队列。不能只在 await 之前校验。

### B03 / P2：仅查看过的详情也被固定为草稿，后续合法刷新无法更新标注

位置：`frontend/src/composables/useEggBox.ts:32-45,150-155`。

`annotationsFor()` 在只读展示时就创建状态，后续 `load()` 仅在本地值等于后端值时删除。没有未保存修改的状态遇到新后端标注时，反而因为不相等被永久保留。

复现：查看性格 0 的蛋但不编辑；另一客户端将其标为性格 7；本页重新加载。`data` 中的标注已为 7，表单仍为 0。随后只改备注，保存请求携带性格 0，覆盖另一客户端的性格 7。

返修要求：区分干净展示缓存与用户未保存草稿，或只在首次编辑时创建草稿。干净状态随成功快照更新；用户草稿、在途保存和失败重试状态按明确 revision 保留。

上述三项使用同一实际 composable 的 deferred promise 探针复现，见 [probe_egg_state.cjs](probe_egg_state.cjs) 与 [egg-results.jsonl](egg-results.jsonl)。这三项应分别加入必要回归，覆盖持久化最终值，不能只检查画面上的草稿。

## 2. 已通过的返修范围

| 项目 | 本轮证据与结论 |
| --- | --- |
| A01 原切蛋字段污染 | 现有 A→B→A（不切账号）延迟保存回归通过；跨账号代次仍受 B01/B02 阻断。 |
| A02 Store 关闭 | 两个 Store 的显式 flush 被挂起时，close 均约 5 秒报 TimeoutError，数据库仍可查询；释放写入后重试成功，最终 1 行、无 flush 异常、worker 已退出。原在途读屏障也通过。 |
| A03 Vue 运行包 | `tools/frontend.py check` 通过，源码类型检查/Vite 构建通过，打包 dry-run 通过。源码摘要接口与本机运行产物已同步。 |
| A04 失败草稿与重试 | 保存失败后清除并重新选择详情，备注和错误仍保留；重试成功后后端备注正确，错误清空。由 composable 保留状态；本轮未做真实浏览器 SFC 挂载/卸载。 |
| A05 KeyStore 生命周期 | 慢 writer 下 flush、close 均按设定期限超时；保留同一个 writer，释放后 close 成功并写入 sequence 10。回放入口在 writer 完成前保持等待，返回 0 时 writer 已退出且 store 已关闭。 |
| HTTP 手工命令 | 标注、收藏和声音修正已调用 services 下的 repository 方法，完整同步调用仍由受跟踪线程池任务执行。快照到载荷的组装仍在 server helper，属于已披露的剩余边界。 |
| active_team 未知契约 | null 运行校验回归通过，保留未知语义。 |

关闭与 writer 探针见 [probe_lifecycle.py](probe_lifecycle.py)、[lifecycle-results.jsonl](lifecycle-results.jsonl)。

## 3. 验证与性能

本轮重新执行：

- Python：`tests.test_session_resume tests.test_recording tests.test_persistence tests.test_egg_box tests.test_monitor_service tests.test_pets tests.test_web_server`，122 项通过。
- Vitest：`src/composables/useEggBox.test.ts src/composables/usePets.test.ts`，7 项通过。
- `npm run build`、`tools/frontend.py check`、`build.py --dry-run`、`git diff --check` 通过。

测试全绿没有覆盖 B01–B03。现有蛋仓测试只覆盖同一页面代次内的目标切换和 composable 选择清除，未覆盖切号后旧队列、过期刷新收尾或干净状态刷新。

同一合成数据探针重测（本机结果，不作为真实 HTTP/WebView2 SLA）：

| 指标 | 初审基线 | 本轮 |
| --- | --- | --- |
| 2000 只列表构造 + JSON | 255.66 ms | 41.68 ms（29.24 + 12.44） |
| 2000 只 JSON 大小 | 6,208,669 字节 | 1,290,729 字节 |
| 2000 事件 × 1000 字段 drain | 747.53 ms | 7.07 ms |
| 20 段录制、慢 flush 20 ms 的 append 合计 | 409.18 ms | 0.04 ms；停止后 20 段、丢弃 0 |

惰性事件详情：drain 格式化 0 次，同一详情两次读取共格式化 1 次，合计保留 200 条，淘汰提示正确。checkpoint 10/11/12 合并为写 10/12，close 后 writer 退出。

性能改善保持。当前阻断来自前端保存状态的所有权和失效规则，证据不支持引入高性能语言来处理这些问题。

未执行真实 Npcap 采集、WebView2 GUI、浏览器首个可交互时间或实际 exe 编译；打包结果仅是 dry-run。

## 4. 最小返修顺序

1. 先统一跨账号代次的目标保存调度，解决 B01，补 A→B→A 最终持久化值回归。
2. 修复 await 后清理的代次与状态身份核对，解决 B02，补过期刷新不得移除新状态的回归。
3. 区分干净展示与未保存草稿，解决 B03，补外部标注更新后只改备注不得覆盖其它字段的回归。
4. 源码稳定后运行相关 Vitest、官方前端 build/check 与打包 dry-run，保留本轮已通过的后端生命周期修复。
