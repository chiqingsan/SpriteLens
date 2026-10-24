# 附近精灵 / 场景观测 / 雷达：进度审阅与功能补全清单（2026-10-24）

- 状态：审阅快照（只读结论 + 待执行清单，不是验收报告）
- 读者：接手实现的人、架构复核者、产品决策者
- 维护边界：本文只描述 2026-10-24 工作区里的附近精灵工作线；实现变更后应另起新快照，不原地改写历史结论。

## 一、结论摘要

主链路是通的：抓包帧 → `MonitorService` → `PacketEvent` → 每账号 `SceneRepository` → `/api/nearby` / WS 摘要 → Vue 列表 + 参考雷达 + 悬浮雷达，账号隔离、场景周期、战斗失效、checkpoint 原子写、雷达窗口都有实现与测试（Python 53 项相关用例、Vue 21 项）。

但**「看起来做完了」和「实机上能看到东西」之间有四条硬缺口**，其中第一条优先级最高：

1. **距离阈值与真实坐标量纲不符，实机列表/雷达几乎恒空**（详见 2.1，这是最关键的发现）。
2. `snapshot()` 读路径有副作用，移动时 0.5s 推送必然携带新版本 → 2Hz 拉取/重渲染。
3. 附近页切页即卸载，搜索/排序/选中/滚动丢失，且回到页面时可能一直空表直到下一次版本变化。
4. 悬浮雷达没有数据失效兜底，主窗口 JS 失效后静默保留旧图。

C04（目标条件）、C05（应用内告警）、C08（安全导出）仍是零实现；ROADMAP 里 C03「距离与方向待校准后展示」正是当前卡点。

## 二、关键发现（P0，均有本机实测证据）

### 2.1 距离阈值量纲错误 → 真实数据下列表几乎恒空

用真实事件日志 `%LOCALAPPDATA%\SpriteLens\eventlog\eventlog_20261024.jsonl`（300MB，当日）逐条回放 `SceneRepository.handle_packet`：

- 喂入 135,569 条相关包（`ZoneLoginRsp` 1、`ZoneEnterSceneRsp` 1、`ZoneSceneClientEnterSceneFinishNtyAck` 2、`ZoneScenePlayActsNotify` 123,314、`ZoneScenePlayActsBatchNotify` 2,753、`ZoneSceneMoveReq` 9,474、战斗 12/11、`ZoneSceneTeleportNotify` 1）；
- 结果：`phase=observing`、`scene_id=103`、`player_position=(548316, 603652, 79)` 正常，但 **`actors=0`**、`unresolved_updates=3,570`、`rejected_actors=0`；
- 把 `RADAR_DELETE_DISTANCE` 临时关闭后重放，同一份流量得到 **36 个实体**（`config_id` 10241/10242/10135/10136…），说明**解析与坐标都正确，是剪枝把实体全删了**；
- 打开剪枝时统计 840 个可解析实体与玩家的原始坐标距离：`p10=2,249 / p50=7,990 / p90=8,881 / p99=8,994 / max=14,455`；`≤2000` 占 8%、`≤3000` 占 15%。
- 结论：`RADAR_DELETE_DISTANCE=3000`（`spritelens/services/scene_repository.py:17`）与 `RADAR_DISPLAY_DISTANCE=2000`（`frontend/src/components/SceneRadar.vue:6`）比真实场景尺度小 1.6–2.7 倍，实机只在贴脸时偶尔留下实体；雷达外环 2000 更是基本画不出东西。
- 建议：两个阈值改为配置（`nearby.max_distance_raw`、`nearby.display_distance_raw`），默认取 `15000` / `10000`，文档标注「原始坐标单位、未换算米制」；并把上面的回放固化为样本驱动的回归用例（样本脱敏裁剪）。
- 样本边界：以上基于单日 300MB 裁剪分片（2026-10-24，场景 103）；10-22/10-23 的完整日志在记录保留策略（3 天/300MB）执行时被清理，无法二次复核。建议下次真实对局 15 分钟后，把裁剪样本固化为回归用例。

### 2.2 `snapshot()` 读路径推进插值并升级版本

`spritelens/services/scene_repository.py:146-151` 的 `snapshot()` 在锁内调用 `_advance_motion(time.time())`，`scene_repository.py:204-206` 位置变化即 `_version += 1`。真实回放里 135,569 条包产生了 116,417 次版本递增，而 `spritelens/web/server.py:781-793` 的 0.5s 推送只在 JSON 变化时发送 → 移动期间等于 2Hz 推送，前端 `useNearby.update` 每次版本变化都 `load()`（`frontend/src/composables/useNearby.ts:40-64`）→ 行走时 2Hz 整页拉取与重渲染，违反「后台更新不得造成闪动/无谓重载」。

### 2.3 切页卸载与首屏空白

- `spritelens/web/static/nearby-page.js` 的 `leave()` 直接 `mounted.unmount()`，`enter()` 先写 `root.textContent="正在加载附近精灵…"` 再动态 `import('/static/vue/entry.js')`；搜索词、排序、选中、滚动位置全部丢失。
- 更关键：`enter()` 分支里若 `summary` 已存在，只调 `mounted.update(summary)` 不调 `load()`；`useNearby.update` 在四字段（uid/version/phase/observation_id）都未变时直接返回 → **回到页面后列表可能一直空到下一次版本变化**。

### 2.4 悬浮雷达无失效兜底

`frontend/src/pages/FloatingRadar.vue:38-56` 只被动接收 BroadcastChannel 消息；`nearby-page.js` 只在 fetch 失败时发 `error`。若主窗口进程仍在但页面 JS 挂死、WS 断开、采集停止，雷达不会清空也不会提示，会静默保留旧图。

### 2.5 文档与实现不一致（验收口径失真）

- `docs/SCENE_OBSERVATIONS.md:19-24` 与 `docs/NEARBY_OBSERVATIONS.md:15` 写「战斗结束先恢复战前雷达快照」，但 `_battle_backup` / `_battle_restored_from_cache` 从未被写成非 None（`spritelens/services/scene_repository.py:49-50,311-312`），战斗分支只清空。**2026-10-24 已按用户决策 A 定稿：删除死状态、文档统一为「清空 + 等待重发」（见 §六）。**
- `docs/NEARBY_OBSERVATIONS.md:9`（请求失败清空前端结果）与 `docs/UI_GUIDE.md:332`（同周期失败保留旧结果）互相矛盾；当前实现按前者，测试也按前者锁定。
- `docs/SCENE_OBSERVATIONS.md:32` 声称 stop 保存完整场景基线，但 `_save_checkpoint_locked` 要求 `_has_full_snapshot`（`scene_repository.py:119-120`），而该标志只在收到 `0x014A` 时置位 → **中途接入（只收到 0x0413/0x0414）的会话停止时不会写基线**，重启后无法接续场景上下文。

### 2.6 `0x014A` 的「全量实体列表」假设需要重新验证

实测当日 `0x014A`（`ZoneSceneClientEnterSceneFinishNtyAck`）只有 2 条，载荷只有 `1:ret_info` + 单个 `7:other_actors`，并不是一次进场景的全量 actor 列表；当日实体主要由 `0x0414` 的 `SpaceAct_ActorEnter`（2,010 次）携带的 `ActorInfo` 提供（当日 2,249 个 `ActorInfo` 节点中 1,231 个带身高/体重/音量测量字段）。→ 「全量快照」这一路径在当前会话里几乎不走，`_has_full_snapshot` 的语义（决定 checkpoint 与相位）应改为「收到过带测量字段的实体」而不是「见过 0x014A」。

## 三、能力矩阵

| 能力 | 状态 | 证据 / 缺口 |
| --- | --- | --- |
| 多账号隔离、切号清空 | 已实现 | `account_sessions.py`、`test_multi_account_capture.py` 11 项 |
| 场景周期（0x0152/0x015C/0x0133） | 已实现 | `scene_repository.py:255-290` |
| 实体解析（ActorInfo → SceneActor） | 已实现但依赖测量字段 | `domain/scene.py:55-71`；当日 55% 的 ActorInfo 合格 |
| 移动插值（12/13/222） | 已实现 | `scene_repository.py:185-230`；`time.time()` 与事件 ts 混用，时钟回拨有风险 |
| 距离剪枝 / 雷达半径 | **量纲错误** | 见 2.1 |
| 战斗期间失效 | 已实现 | 4886/4908/4909 全清空，不恢复战前快照（用户决策 A，2026-10-24） |
| 重启场景上下文接续 | 部分 | checkpoint 原子写可靠；但仅 `0x014A` 后才保存（见 2.5） |
| 列表 UI（搜索/排序/虚拟滚动/空态） | 已实现 | `NearbyPage.vue`；空态文案受后台 `loading` 驱动，需拆 |
| 列表状态保持 | **缺失** | 切页卸载，见 2.3 |
| 参考雷达（SVG、标签避让、选中） | 已实现 | `SceneRadar.vue`；半径错误，无 `aria-live` |
| 悬浮雷达窗口 | 已实现 | 单实例、置顶、不抢焦点、35–90% 不透明度、位置记忆 |
| 悬浮雷达失效兜底 | **缺失** | 见 2.4 |
| WS 摘要 + 版本守卫 | 已实现 | 但受 2.2 放大 |
| 请求超时 | **缺失** | `useNearby` 无 timer，悬挂时 `loading` 常真 |
| C04 目标条件 | 未开始 | ROADMAP 未开始；需协议字段证据 |
| C05 应用内告警 | 未开始 | 依赖 C04；声音/Toast/去重/历史 |
| C06 雷达校准（米制/方位） | 部分 | 原始坐标版可用，单位未校准 |
| C07 悬浮命中监控 | 部分 | 只有置顶雷达切片 |
| C08 安全导出 | 未开始 | 脱敏、原子写、失败不覆盖 |

## 四、详细补全清单

### P0（先做，直接影响「能不能用」）

**P0-1 校准距离与雷达半径**
- 目标：真实数据下列表有实体、雷达可读；单位语义写清。
- 落点：`spritelens/services/scene_repository.py:16-17`（改为读设置）、`frontend/src/components/SceneRadar.vue:6`（从 payload/设置取 display 半径）、`spritelens/repositories/settings.py`（新增 `nearby.max_distance_raw` / `nearby.display_distance_raw`）、`docs/NEARBY_OBSERVATIONS.md`。
- 默认值：`15000` / `10000`（实测 p99≈8,994、max≈14,455）。
- 验收：真实流量回放（裁剪样本）产出实体数 > 0 且与人工抽查一致；1440/864 视口雷达可见点且不重叠；阈值越界仍不显示。
- 回归：新增回放用例（样本脱敏、只保留结构），断言实体数/坐标/剪枝计数。

**P0-2 去掉 `snapshot()` 读副作用**
- 目标：无新包时重复读取不改变版本与位置；移动时前端不被按 2Hz 拉取。
- 落点：`spritelens/services/scene_repository.py:146-151`（抽出 `_advance_motion` 到推送 tick）、`spritelens/web/routes_capture.py:210-227`、`spritelens/web/server.py:781-793`。
- 验收：无新包连续 10 次 snapshot 的 `version`/位置不变；有包时每包最多一次版本递增；移动中 `/api/nearby` 请求频率 ≤ 推送频率。

**P0-3 附近页状态保持 + 首屏不空白**
- 目标：切页回来保留搜索/排序/选中/滚动；有 summary 时首屏直接渲染现存数据。
- 落点：`spritelens/web/static/nearby-page.js`（`leave()` 改为隐藏而非卸载，或缓存实例）、`frontend/src/pages/NearbyPage.vue`、`frontend/src/composables/useNearby.ts`（`update` 在「版本未变但 data 为空」时补一次 `load()`）。
- 验收：来回切页 3 次，搜索词/排序/选中/滚动保持；切回时列表在同周期数据下立即有内容；无闪动。

**P0-4 悬浮雷达失效兜底**
- 目标：主窗口/数据源失效 ≤3s 内雷达清空或显示「数据已失效」，不展示旧图。
- 落点：`spritelens/web/routes_capture.py:227`（摘要加 `published_at`）、`spritelens/web/static/nearby-page.js`、`frontend/src/pages/FloatingRadar.vue`（超时计时器）、`spritelens/web/static/radar.js`（启动失败兜底与错误文案）。
- 验收：停采集、关主窗、页面 JS 抛错三种情况下雷达都不会保留旧图；重新恢复后自动刷新。

**P0-5 文档口径对齐（验收前必须做）**
- 删除「战斗后恢复战前快照」未实现陈述；统一 `NEARBY_OBSERVATIONS.md:9` 与 `UI_GUIDE.md:332` 的失败/清空口径；修正 `SCENE_OBSERVATIONS.md` 的 0x0133「仅匹配当前场景时保存」与 `0x014A` 全量假设。

### P1
- **P1-1 切场景兜底**：只收到 0x0413/0x0414 时的旧实体混入（`scene_repository.py:326-356`）；需要录制复现后再决定守卫。
- **P1-2 `/api/nearby` 缓存头**：`spritelens/web/server.py:464-472` 的 `_no_cache_middleware` 扩到 `/api/*` GET。
- **P1-3 checkpoint 精简 + 版本化**：`scene_checkpoint_store.py:17-29` 只存 uid/flow/scene/resource/instance/position_source/updated_at，删 actors/position，加 `format_version`。
- **P1-4 空态与后台同步解耦**：`NearbyPage.vue:115-127` 的「正在读取」只在首次加载显示。
- **P1-5 请求超时**：`useNearby` 加 AbortSignal.timeout（如 8s），超时按失败处理且不影响已展示数据。
- **P1-6 attention 单一来源**：payload 输出分类结果，前端不再按中文牌名推导（`spritelens/web/nearby.py:29-31`、`frontend/src/types/nearby.ts`）。
- **P1-7 长名称与标记行**：`NearbyPage.vue:172` 补 `title`、`:180` 标记行允许换行或滚动；补极限布局用例。
- **P1-8 映射缺失可观测**：`data/static/scene_npc_pets.json` 缺失时页面提示「映射表不可用」，payload 计数。

### P2
- 拆分 nearby 展示映射到 `spritelens/domain/nearby_view.py`（web 层只做 HTTP）。
- 移除 `_battle_backup` / `_battle_restored_from_cache` 死字段。
- 观测计数：`pruned_by_distance` / `stale_removed` / `mapping_missing`。
- 雷达 `aria-live` 更新宣告、键盘可达性补齐。
- 测试补齐：TTL、stop-without-014A、0413-only 切场景、store 并发/关闭、缓存头、nearby-page 桥、radar stale、双 update 去重、`FloatingRadar.test.ts:11` 的过期断言。

### 后续 C 系列（需单独立项，不在本轮）
C04 目标条件 → C05 应用内告警 → C06 雷达校准（米制/方位）→ C07 悬浮命中监控 → C08 安全导出。C04/C05 需要先补协议字段证据（条件字段来源、触发消息），不猜。

## 五、决策结论（2026-10-24 已定）

1. **坐标单位**：用户决定「暂时先用原始单位」→ 已实现 `nearby.max_distance_raw`（默认 15000）与 `nearby.radar_radius_raw`（默认 10000），不换算米制。
2. **失败语义**：用户决定「保留同周期」→ 请求失败保留同周期已有结果并标注「可能已过期」，切号/切场景/观察周期变化清空；文档与测试同步改。
3. **战斗恢复**：已用回放证据说明（11 个战斗窗口，结束后 120 秒内服务器重新下发 0–142 个实体），采用「清空 + 等待重发」，删除「恢复战前快照」的叙述；不实现内部快照。用户 2026-10-24 明确确认采用此选项 A，死状态 `_battle_backup` / `_battle_restored_from_cache` 已删除。

## 六、实施状态（2026-10-24，P0 全部落地，未提交）

- **P0-1 已实现**：删除阈值/雷达半径改为可配置原始单位。`spritelens/services/scene_repository.py` 新增 `DEFAULT_MAX_DISTANCE_RAW=15000` 与 `max_distance_raw` 构造参数；`spritelens/web/nearby.py` 载荷新增 `radar_radius_raw`（默认 10000，`nearby.radar_radius_raw` 可调）；`spritelens/app_context.py` 装配 `nearby.max_distance_raw`；`SceneRadar.vue` 用 `radius` prop，`NearbyPage.vue`/`FloatingRadar.vue` 从 payload 取值。
- **P0-2 已实现**：`snapshot()` 只读，推进改由写路径（`SceneRepository.advance()`，WS 推送循环 `_push_payload()` 调用）；`GET /api/nearby` 不再自激；连续两次 `snapshot()` 的版本与实体一致（单测锁定）。
- **P0-3 已实现**：`nearby-page.js` 切页保持挂载（复用壳 `.page-cached`），`enter()` 有摘要时原位 `update()`、无摘要或数据缺失时补 `load()`；离开页面不卸载 Vue 实例，搜索/排序/选中/滚动保留。
- **P0-4 已实现**：主窗口每 1 秒广播心跳，悬浮雷达 3 秒无消息即清空并提示「数据已失效（采集连接断开或主窗口未响应）」，恢复后自动重订阅；`radar.js` 启动流程加 8 秒超时与失败可见文案，不再永久隐形。
- **失败语义已统一**：页面与悬浮雷达都「保留同周期已有数据 + 标注可能过期」，仅切号/周期变化/清空指令/无数据失败才清空；文档 `docs/NEARBY_OBSERVATIONS.md` 与 `docs/UI_GUIDE.md` 口径一致。
- **P0-5 文档口径已改**：删除「战斗后恢复战前快照」；0x014A「全量实体列表」假设改为实测描述（当日仅 2 条、实体主要来自 0x0414 `SpaceAct_ActorEnter`）。
- **战斗语义已定稿（选项 A）**：`spritelens/services/scene_repository.py` 删除从未写入的 `_battle_backup` / `_battle_restored_from_cache`，4908/4909 分支加注释「不恢复战前快照，保持空态等新观察周期重发」；0x014A 分支只判断 checkpoint 恢复。`docs/SCENE_OBSERVATIONS.md:23-24,46` 与 `docs/NEARBY_OBSERVATIONS.md:9,15` 统一为「清空 + 等待重发」，并注明 2026-10-24 用户决策。现有回归 `tests/test_scene.py:217,239` 已锁定该行为（战后实体/位置为空、phase=awaiting_scene，收到新 0x0414 后 phase=observing）。

### 验收证据（2026-10-24）

- 真实事件日志回放（`eventlog_20261024_p02.jsonl`，6,658 个相关包、457 秒）：`phase=observing`、场景 103、玩家 (548741,603243,79)、**实体 36**（旧默认 3000 时为 0）、两次 `snapshot()` 完全一致。
- 真实数据 + 动态推送（每 300ms 重放真实事件包）经 Edge headless CDP 验收：1440×900 与 864×672 均渲染 36 只、雷达 79 个点、无横向溢出；连续 8 次采样期间计数、文案、卡片数与 `scrollTop=120` 全部不变（无闪动、无回顶）。
- 悬浮雷达 360×460 与最小 280×380：36 只、79 个点、重点胶囊 3 个、无错误提示；关闭主页面 4.5 秒后自动清空并显示失效文案（心跳兜底成立）。
- 自动化：`tests.test_scene/test_scene_checkpoint/test_radar_window/test_multi_account_capture/test_web_server` → 65 项 OK；`npx vitest run` → 152 passed / 1 skipped；`tools/frontend.py build`（vue-tsc + vite）通过。

### 仍未验证

- 真实桌面 WebView2 进程内的失效/恢复时序、WS 断开 1.5 秒重连窗口不闪动的端到端表现（仅单测与 headless 验证）。
- stale 提示在 640×360 最小窗口与 150% 缩放下的换行/高度目检。
- 真实游戏实时增量（非回放）下的长时观察与内存占用。

## 七、建议执行顺序（后续）

1. P1：`position_source` 文案、`attention` 前后端单源、请求超时、长名称 `title` 与标记行换行（`_battle_backup` 死状态已于 2026-10-24 清理）。
2. C04 目标条件 → C05 应用内告警 → C06 雷达校准（米制/方位）→ C07 悬浮命中监控 → C08 安全导出；C04/C05 需要先补协议字段证据，不猜。
3. 提交：当前附近线仍全部未提交，建议按「后端阈值/只读快照」「壳层与前端状态」「文档」拆分提交，避免混入雷达/采集诊断工作线。
