# F01 宠物响应同源验证

状态：2026-10-13 实施与本机验收快照。读者：实现者、维护者、架构复核者。
维护边界：本文保留本轮证据，持续状态在 ROADMAP；不代替 F02 跨域与前端账号请求失效验收。

## 任务与边界

- 任务：F01；前置是既有 PetRepoSnapshot/PetView 与已落地的 F00/V01/V02。
- 目标：宠物条目、箱位、筛选选项、统计、身份、uid/version 来自相应单次锁内快照。
- 状态所有者：PetRepository / AccountTracker 为账号与库存权威；PetView 持锁外读副本。
- 范围：列表/概览/REST state/WS 共享读契约；bootstrap 的相关子载荷复用同一个 PetView。
- 失败分支：读取后发生切号/更新，继续序列化完整旧快照并附旧 uid/version；后续请求读新快照。
  查询筛选不写共享 VM；空快照不退回当前仓库重新取数据。读取/序列化失败按既有失败机制暴露，不吞错。
- 不修改：协议、存储/退出、账号切换命令与前端页面结构；F02 的其它域一致性与旧账号请求失效单列。

## 修复内容

先写 6 项受控用例，旧实现出现 4 个失败、2 个错误：
bootstrap/WS 没使用一致性快照，PetView 的筛选选项回读新仓库，离线载荷缺 uid。

PetView 的统计和性格/系别/蛋组/天赋上限只消费已捕获宠物，复用既有计算，不复制业务规则。
`pets_payload` 收到旧 VM 调用时也先转一次 PetView；HTTP 的请求视图保持不可变筛选。
`pet_summary_payload` 供概览和 state 共用，分别附 `uid/version` 与兼容的 `uid/pets_version`。
bootstrap 创建默认筛选视图一次，列表/概览/state 复用；默认 bootstrap 不继承共享 VM 的筛选命令。

`AccountTracker.display_uid` 表示数据归属（实时 uid 或已加载 uid），只用于读取快照。
写路径仍用 `uid`，离线加载不会触发写入归属或冒充实时身份：identity 保持 None，cached_identity 独立。
未知身份且无加载归属仍为 uid=0。历史账号列表是全局历史索引，可独立读取，不参与本次宠物统计。

## 验证

- 6 项新回归通过：快照后切 A→B、旧 VM 列表捕获一次、筛选选项/箱位不回读 live 数据、
  bootstrap 的列表/概览/state 单次快照、WS/REST 共用 state、离线归属与筛选互不污染。
- 受控挂钩在 consistent_snapshot 返回前切号；明确统计、身份、uid/version 属于 A，下一响应属于 B。
  用禁止 live snapshot 的替身抓住选项回读，不靠 sleep 或真实抓包。
- 全量门禁 407 Python（5 既有跳过）、5 Vitest、类型/ESLint、JS/资源/产物检查通过。
- 5 Playwright 用例通过，真实 HTTP bootstrap 的 uid/version/count 对齐，并复验 Vue 页面交互与主题。
- 临时数据目录源码 smoke 通过；未验收真实驱动或 exe/WebView2，本轮不改变桌面壳。

## 后续

F01 保证一个响应内部同源，不能让多个请求自动拥有同一版本，也不保证多域组合快照。
state 顶层 uid 明确表示宠物快照归属；egg_box/home/flower 的版本仍须 F02 各自取齐并检查账号。
原生账号页尚需落实旧 uid 请求失效；不据此宣称账号相关 UI 全部完成。
保存、录制功能仍需 S03b 的慢盘/最终落盘失败策略。
