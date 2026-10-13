# F02 账号与各域快照验证

状态：2026-10-13 实施与本机验收快照。读者：实现者、维护者、架构复核者。
维护边界：保留本轮证据；持续状态由 ROADMAP 维护，不替代真实抓包、WebView2/exe 与 S03b 验收。

## 目标与范围

单任务 F02：蛋仓、家园、花田响应的状态与 uid/version 同源；state 跨域核对归属；
账号页拒绝切号、离页和同页乱序产生的旧请求。沿用原生页，仅增加迁移期请求桥接，未展开 F03/F04。

各 repository/AccountTracker 是域状态与账号的权威；DTO 消费锁内一次捕获的只读副本。
页面缓存与选择仍在原页面，account-requests.js 仅保存 state 归属、域版本与请求票据，不存业务数据。
原生壳沿用唯一 WS；没有新增全局锁、跨域事务或状态管理库。

## 数据与失败语义

- EggBoxSnapshot 一次取齐 entries/slots/uid/version/historical_ids/source/slots_source。
  恢复条目为历史，逐条重观测后可为 mixed；历史槽只提供历史证据，当前 hatching=null。
  本次槽帧确认当前在孵；明确空槽确认当前没有槽中蛋，不用时间字段冒充槽证据。
- HomeRepoSnapshot 取齐 data/uid/version/pending_deltas，FlowerRepoSnapshot 取齐 data/uid/version。
  未观察状态为 unknown；有未合并家园增量为 stale；全量完整性统一 complete=null。
- 图鉴收集、种公/母矩阵和色卡附单次宠物快照的 uid/version，便于页面提交校验。
- state 各域附 consistent/source/complete；归属不符时蛋计数为 null，不拿另一账号的数据拼统计。
  域版本仍保留用于后续刷新，不承诺跨域拥有同一时刻的全局原子快照。
- 蛋/宠物恢复在 IO 前后核对 uid/version。期间切号、A→B→A 或更新则抛错，保留当前数据。
  缺失/坏孵化槽记录返回 None；有效空槽返回空集合；实际 SQLite 读取异常向上传播。
  Store flush/最终退出策略沿用现状，未声称解决 S03b。
- 原生账号页提交校验账号代次、同页序号、响应 uid 与相应域最新版本；离页/切号取消，
  即使取消无效也禁止旧响应提交。过期 state 不回滚归属；有效当前请求错误仍提示。
  切号清旧条目、详情和账号派生筛选选项，再刷新活动页；静态 Vue 蛋图鉴不因账号清理被关闭。

## 验证证据

- 新增 10 项门禁测试：三域读取后切号、跨域失配、家园 stale/unknown、空域未知、
  历史槽与逐条重观测、缺槽、恢复期间 A→B→A、宠物恢复切号、坏槽/读错、Node 请求时序。
  Node 受控网络包含 A→B→A、同页乱序、错 uid、响应版本过期、旧 state、离页、坏 DTO 与真实错误。
- 全量 run_build_tests.py：417 Python（5 既有跳过）、11 JS、16 静态清单、HTML 引用、
  Vue 类型/ESLint、5 Vitest、既有 Vue 产物指纹/哈希检查通过。
- 7 Playwright 通过：2 项新用例验收历史在孵显示与切号清理；用取消无效的真实 HTTP 交错，
  先显示 B 再释放 A 响应，列表保持 B。其余 5 项复验蛋图鉴筛选、错误重试、主题/焦点与 ID 精度。
- 临时数据目录源码 smoke 通过；合成 demo 三域与宠物使用同一 uid，无真实账号、录制或密钥样本。

## 后续边界

F02 的受控与浏览器范围完成；真实游戏多账号交错、驱动、桌面 WebView2/exe 仍须实机。
F03 宠物页按单切片迁 Vue；F04 其它页面逐页推进。保存/录制相关需求先明确 S03b 慢盘与最终落盘失败语义。
素材审计仍是独立候选方案，本轮未压缩或替换正式资源。
