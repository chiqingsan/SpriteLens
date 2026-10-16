# 2026-10-15 标注保存修复与复验

状态：B01–B03 修复完成，本轮受控验收通过。读者：实现者与复核者。维护边界：本目录记录本轮工作区证据，不代替真实桌面、抓包或发布验收；后续代码变化需要重新验证。

基线：HEAD `de12fca` 加原有未提交改动。本轮仅修改 `frontend/src/composables/useEggBox.ts`、对应回归测试，并通过官方构建更新忽略的 Vue 运行产物；没有回滚或清理原有改动。历史失败快照保留在 [上一轮验收](../acceptance-20261015-repair/README.md)。

## 修复范围与失败分支

| 问题 | 实现与结果 |
| --- | --- |
| B01 / P1：切号后同一目标出现两个保存队列 | 切号保留按 `(uid, instance_id)` 组织的保存状态；当前在途写入结束后发送最新待保存值。A→B→A 探针现在只发送 `old-1 → new-3`，后端与界面最终均为 `new-3`。 |
| B02 / P1：旧刷新收尾删除新草稿 | 保存队列在刷新前释放，异步刷新返回后不再执行删除；清理由通过请求代次校验的 load 负责，跳过正在保存、待重试和未保存草稿。旧响应返回后仍显示 `new-draft`，随后只改性格也保留该备注。 |
| B03 / P2：只读详情阻挡合法刷新 | 只读 getter 不创建草稿，首次编辑才建立状态；成功保存的干净状态随后端快照更新。外部性格由 0 变 7 后，本页显示 7，随后修改备注仍保存性格 7。 |

状态由页面 composable 持有。账号/离页请求失效与保存队列分别管理：暂停或切号使旧展示请求失效，在途保存继续按原目标完成；只有当前视图代次发起的保存会主动刷新。保存失败保留最新草稿、待保存值和可见错误，由用户重试；成功提交时若仍有未提交编辑，不清除该草稿。

## 验收证据

- Vitest：`npm test -- src/composables/useEggBox.test.ts src/composables/usePets.test.ts`，2 个文件、13 项通过。其中蛋标注 7 项，新增 6 项覆盖切号串行、旧刷新、只读刷新、切号失败重试、在途保存期间未提交编辑、离页后返回。
- 新增回归在修复前有 4 项失败，修复后全部通过。
- 独立实际 TypeScript composable 探针：[probe_egg_state.cjs](probe_egg_state.cjs)，4 个场景的断言通过，最终持久化值与显示值见 [egg-results.jsonl](egg-results.jsonl)。使用合成 DTO 和 deferred 请求，无真实账号数据。
- Python：`tests.test_session_resume tests.test_recording tests.test_persistence tests.test_egg_box tests.test_monitor_service tests.test_pets tests.test_web_server`，122 项通过。测试中的预期故障注入日志不代表验收失败。
- 重跑 [生命周期探针](../acceptance-20261015-repair/probe_lifecycle.py)：两个 Store 在显式 flush 被挂起时 close 约 5 秒超时，数据库保留；释放后重试成功、各 1 行、worker 退出。KeyStore 超时保留同一个 writer，恢复后 sequence 10 落盘；回放等待 writer 完成后返回。结果见 [lifecycle-results.jsonl](lifecycle-results.jsonl)。
- 官方 `tools/frontend.py build` 通过（含 vue-tsc、Vite、4 个文件发布）；`tools/frontend.py check`、`build.py --dry-run`、`git diff --check` 均通过。运行资源为 `main-DVDP3ywt.js` / `main-CY0hCW1w.css`。

## 性能与原修复复测

复用 [初审基准脚本](../review-20261015-performance/probe_backend.py) 的 benchmark，以及 [原验收探针](../acceptance-20261015-performance/probe_backend.py) 的 read_barrier、lazy_event_detail、recorder_and_checkpoint。结果见 [performance-results.jsonl](performance-results.jsonl)。这些是本机合成数据结果，不是 HTTP 或 WebView2 时延承诺。

| 指标 | 本轮结果 |
| --- | --- |
| 2000 只宠物载荷构造 + JSON | 37.78 ms（27.26 + 10.52）；另有快照构造 2.51 ms |
| 2000 只 JSON 大小 | 1,290,729 字节 |
| 2000 条事件 × 1000 字段 drain | 7.30 ms |
| 惰性详情 | drain 格式化 0 次，同一详情读取两次共格式化 1 次，保留 200 条 |
| 20 段录制，flush 注入 20 ms | append 合计 0.03 ms；停止后 20 段、丢弃 0 |
| 两个 Store 读屏障 | 读取均等待在途 flush 完成，最终找到数据 |
| checkpoint 合并 | 写入 sequence 10、12；关闭后 writer 退出 |

本轮生产改动集中在前端保存状态，没有新增后端性能改动。原先披露的快照到载荷组装仍在 server helper 的边界事项没有扩大到本轮。

## 验证边界

未执行真实 Npcap 抓包、WebView2 GUI 点击、浏览器首个可交互时间测量或实际 exe 编译。前端验证基于真实 composable、合成载荷、类型检查与构建，未覆盖浏览器 SFC 挂载/卸载；打包仅验证 dry-run。当前结论是上述问题和受控场景通过，不能替代完整真机发布验收。
