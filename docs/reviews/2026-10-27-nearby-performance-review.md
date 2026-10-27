# 附近精灵：性能热点与功能补全审查（2026-10-27）

- 状态：审查快照（只读审计 + 本机实测 + 补充清单），后附第十节记录 2026-10-27 第二至五轮的实施结果；第一至九节保持审查当时的结论，不原地改写
- 读者：接手实现的开发者、架构复核者、产品决策者
- 维护边界：只描述 2026-10-27 工作区（HEAD `d0b8826` + 未提交 WIP）里的附近精灵 / 雷达 / 地图工作线；实现变更后另起新快照，不原地改写历史结论。路线图状态仍以 `docs/ROADMAP.md` 为准。
- 证据标注：**[实测-本机]** = 本次 Python 基准 / 真实 Edge headless（CDP）实测；**[代码]** = 源码阅读推断；**[未验证]** = 本轮未覆盖，不能据此宣称已解决。

## 一、结论摘要

典型负载（十几个实体、雷达视图）当前链路是健康的：本机实测 12 实体 40 次连续推送，每次提交 3.4–5.3 ms，DOM 节点全部复用（cards kept 12/12），帧间隔稳定 16.1–16.8 ms，无长任务 [实测-本机]。**问题集中在四类**：

1. **每个推送节拍全量重取 + 全量重建**：只要观察版本递增（行走/插值更新时 0.5 s 一拍），前端就完整 GET 一次 `/api/nearby` 并 `parseNearby`；后端每请求重新组装整包。300 实体单次提交雷达 84 ms / 地图 153 ms（p95 140 / 235 ms），23 次推送产生 23 个长任务 [实测-本机：前端审计]；4096 实体时后端构造 + 序列化 66.7 + 21.6 ms，包体约 1.97 MB [实测-本机：本报告]。
2. **覆盖（足迹）层数据量与渲染方式不可扩展**：覆盖圆心全量随每包下发（上限 16,384），前端同一 path 在 DOM 里出现 **6 份**（地图 3 + 隐藏但常驻的雷达 3）；2,000 圆心合计 1.96 MB、5,000 圆心合计 4.9 MB 字符串，16,384 圆心理论约 15.7 MB；且 `<mask>` 强制按 4096² 底图整面光栅（雷达里被放大到约 7,344² 用户单位）[实测-本机 + 代码]。
3. **密集场景渲染没有预算**：雷达按实体 1:1 生成可聚焦 SVG 节点（约 5 节点/实体），地图按实体 1:1 生成 marker；500 实体时 DOM 14,145 个元素、雷达 SVG 2,411 节点，每次推送一个 120–150 ms 长任务 [实测-本机]；没有上限、聚合、视口裁剪或"还有 N 个未显示"的表达。
4. **覆盖数据的语义正确性与归属契约落后于计划**：coverage DTO 只有 `{radius, centers}`，没有 uid / capture_run_id / map_id / coordinate_version / version；`0x0152` 在入场位置缺失时会用残留的目标点写覆盖；停采/断流后地图与覆盖不可回看；无数据且请求失败时空态仍写"尚未观察到附近精灵"，用户会读成"这附近没精灵"。

P0 清单与最小改法见第六节；建议按"低风险止血 → 覆盖数据链路 → 渲染预算 → 语义/归属"四刀切片推进。

## 二、方法与可复现证据

本轮由 Lead + 三个并行只读审计（后端 / 前端渲染 / 功能正确性）组成，各自独立实测后交叉核对。脚本与原始数据都在 `.research/nearby-perf/`（已 gitignore，不入库）：

| 产物 | 作用 |
| --- | --- |
| `backend/bench.py`、`backend/results.json` | 后端：`nearby_payload` 构造/序列化成本、包体、prune、advance、static_data 加载 |
| `lead_bench.py` | 本报告独立复测：0/50/500/4096 实体 × 0/2000/16384 圆心的 payload 大小与耗时 |
| `lead_coverage_path2.mjs` | 覆盖 path 生成成本与字符串体积（复刻 `frontend/src/domain/mapCoverage.ts`） |
| `probe.html`、`probe-lead.html` | 挂载真实 `NearbyPage.vue` 的浏览器探针，注入符合 `parseNearby` 校验的合成快照 |
| `run.py`、`run2.py` | 前端渲染基准（300 实体、滚动、悬浮雷达） |
| `render_bench2.py`、`render_bench.json` | 本报告浏览器复测（12/500 实体、0/2000 圆心、雷达/地图视图） |

复现示例（仓库根）：

```
.venv/Scripts/python.exe .research/nearby-perf/lead_bench.py
.venv/Scripts/python.exe .research/nearby-perf/backend/bench.py
node .research/nearby-perf/lead_coverage_path2.mjs
.venv/Scripts/python.exe .research/nearby-perf/render_bench2.py
```

**方法与限制（必读）**

1. 浏览器基准跑在真实 Edge（`--headless` + `--disable-gpu`）上，加载的是 `tools/frontend.py build` 生成的真实产物；但 headless 软件光栅无 GPU/无 vsync，**帧时只能当上限参考**，真实 WebView2 + 高 DPI 未验证。
2. 探针页没有真实壳层的定高容器，虚拟列表会把全部卡片渲染出来（`clientHeight` 被撑大），所以"卡片成本"是**最坏上限**；真实壳层约渲染 7 行（`estimateSize 108 + overscan 4`）。滚动锚定行为本轮未验证。
3. 数据是合成快照（字段严格过 `parseNearby` 校验），实体分布与真实采集不同，但节点数、重算路径与真实一致；**没有真实游戏录制回放**。
4. 极端档（4096 实体 + 16,384 圆心）在 headless 软件光栅下 10 分钟未完成，未取到帧数据（renderer 工作集 888 MB）。只能说明该档位成本已超出可交互范围，真实 GPU 数值仍[未验证]。
5. 前端数字来自构建产物；若源码有未重新构建的改动，以重新 `tools/frontend.py build` 后复测为准（本次核对产物 mtime 与源码一致）。

## 三、性能热点（按实测排序）

### 3.1 后端：每请求重新组装整包

`spritelens/web/nearby.py:34-89` 的 `nearby_payload` 每次请求 `asdict(snapshot)` 深拷贝、逐实体补 static 联查（名称/图标/属性/链/标记/attention）、重建 `type_icons`，无缓存、无分页、无增量。本机实测（真实 `data/static`，1,482 条 NPC 映射）：

| 场景 | 包体 | `nearby_payload` | `json.dumps` | 其中 `asdict` |
| --- | --- | --- | --- | --- |
| 0 实体 | 1.2 KB | 0.01 ms | — | — |
| 50 实体 + 200 圆心 | 24.9 KB | 0.60 ms | 0.26 ms | 0.41 ms |
| 500 实体 + 2,000 圆心 | 242.4 KB | 7.48 ms | 1.67 ms | 3.36 ms |
| 4,096 实体 + 0 圆心 | 1.70 MB | 46.79 ms | 16.20 ms | 16.20 ms |
| 4,096 实体 + 16,384 圆心 | 1.97 MB | 66.70 ms | 21.64 ms | 33.65 ms |

- 实体约 415 B/条；coverage 圆心约 148 B/点、上限 16,384 点（`spritelens/services/scene_coverage.py:7-41`），单覆盖层最多约 2.4 MB。
- `nearby_payload` 对 actors 做了两次 `asdict`：300 实体白费约 0.87 ms（占构造总时 2.38 ms 的 37%）[实测-本机：后端审计]。
- `scene_repository.snapshot()` 的 tuple 复制只要 0.05 ms，**不是问题**（与上一次审查的猜测相反，已实测排除）。
- 真正放大器是**调用频率**：WS 摘要 `nearby.version` 随插值每拍 +1，前端 `frontend/src/composables/useNearby.ts:78-81` 见到 `next.version > data.version` 就 `void load()`。移动时约 2 次/秒，即 500 实体 ≈ 484 KB/s、4,096 实体 ≈ 3.4 MB/s 的本机回环流量，外加后端每拍 50–90 ms CPU。

### 3.2 前端：每次推送的提交成本

链路：WS → `spritelens/web/static/app.js:538-544` → `nearby-page.js:141-151` → `useNearby.update()` → `load()` → `parseNearby` → Vue 渲染。同步段（`update()` 本身）始终 ≤0.5 ms，成本全在请求、解析与提交：

| 场景（500 ms 节奏） | 页面元素 | 雷达 SVG 节点 | 单次提交 avg / p95 | 长任务 |
| --- | --- | --- | --- | --- |
| 12 实体，雷达 | 450 | 102 | 3.4–5.3 ms | 无（40 次连发） |
| 300 实体，雷达 | 8,532 | 1,464 | 84.3 / 139.5 ms | 20 次推送→20 个 65–140 ms |
| 300 实体，地图 | 9,491 | — | 152.8 / 235.2 ms | 23 次推送→23 个 66–185 ms；over33 27/765 |
| 500 实体，雷达 | 14,145 | 2,411 | 每次推送 1 个长任务 | 121–152 ms × 6 |

即使"数据没变、只递增版本"，Vue diff 只产生 2 条 `aria-busy` 变更（节点身份稳定，这点是好的），但 `parseNearby`、`rows`、`projection`、`markers`、`labels` 全部重算——**CPU 付全量、DOM 只改两笔**，说明瓶颈不在 patch，而在"每拍都重建数据与全量 computed"。

### 3.3 覆盖层：6 份同构 path + 整面 mask

- `frontend/src/domain/mapCoverage.ts:5-19` 把每个圆心拼成 `M{x-rx},{y}a…Z` 子路径；约 **163 B/圆心**。
- `frontend/src/components/MapCoverage.vue:14-16` 同一个 `paths.fill` 用在三处：`<defs><mask><path fill="black">`、`.map-coverage-fill`、`.map-coverage-border`（border 复用 fill 的 d）→ 每个实例 3 份。
- `frontend/src/pages/NearbyPage.vue:274-276` 的雷达是 `v-show` 常驻、地图激活后也常驻 → 地图视图下**两个 MapCoverage 同时存在**，实测 DOM 里 6 个 path（2 个无 class 的 mask path + fill/border 各 2）[实测-本机]。
- 体量（每份 d 字符数 / DOM 合计）：

| 圆心 | 单份 path | DOM 6 份合计 | 生成耗时（Node 复刻） |
| --- | --- | --- | --- |
| 2,000 | 326,465 B | 1.96 MB | 4.2 ms |
| 5,000 | 816,184 B | 4.90 MB | — |
| 8,000 | 1,275 KB | 7.65 MB | 8.8 ms |
| 16,384 | 2,612 KB | **15.7 MB** | 31.5 ms |

- 更重的是 mask：`maskUnits="userSpaceOnUse"` 以 4096×4096 图片坐标系定义，雷达里该组又被 `scale(7344/4096≈1.79)` 放大（`SceneRadar.vue:199-202`，侧边 408000 raw / range 10000 × 180 px）。每次覆盖更新都要重建/重光栅这张 mask；16,384 圆心时在软件光栅下不可完成 [实测-本机，见限制 4]。真实 GPU 数值[未验证]，但"每次更新重建 3 份 2.6 MB path + 一张全图 mask"的结构成本是确定的。
- 与计划一致：`docs/NEARBY_MAP_PLAN_2026-10-26.md:268` 明确「覆盖应独立接口，不能每次重发整张网格」，当前无 `/api/nearby/coverage` 路由。

### 3.4 渲染节点随实体线性增长

- `frontend/src/components/SceneRadar.vue:207-209`：每个可见目标 1 个可聚焦 `<g role="button" tabindex="0">` + `<title>` + 3 个 `<circle>`（单/双牌再多 1 环），无上限。4,096 实体上限时最多约 2 万个 SVG 节点。
- `frontend/src/components/SceneMap.vue:377-381`：每个地图范围内实体 1 个 `<button>` + 3 个 span（双牌 4 个），同样无上限/无聚合。
- `SceneRadar.vue:129-181` / `SceneMap.vue:120-194` 的投影、过滤、排序、标签贪心避让在每次 `data` 新对象时全量重算；标签本身有上限（雷达 6、地图 8），但点位没有。
- 首次渲染 300 实体雷达 415 ms（`SceneRadar` 审计实测），进入地图 `setView` 176–180 ms。

### 3.5 次要但确定的问题

- `spritelens/services/scene_repository.py:250,275`：每个移动包都 `_prune_distant_actors()` 全表 `hypot` 扫描，4,096 实体时 1.06 ms/包、且持锁 [实测-本机]。
- `spritelens/web/world_maps.py`：`/api/world-maps` 每次请求重读并校验整份 JSON（0.055 ms/次）——量级小，但和"清单在页面进入时只加载一次"的设计相比是白开销。
- `/static/*` 全量 `Cache-Control: no-store`（含 1.26 MB / 1.79 MB 的 4096 底图），每次加载或切图都重传，无法 304 [代码+后端审计]。
- `SceneMap.vue:356-363` 跟随模式下每次推送都重设 center → stage `left/top` 变化 → 整个 stage 重排；`markers`/`labels` 也随之全量重算。
- 覆盖层每张地图各自累积到 16,384 点、无全局上限；多张地图反复切换后进程内覆盖内存线性增长（10 张即约 2 MB 圆心数据）[后端审计]。

## 四、功能与正确性补充

| 编号 | 问题 | 证据 |
| --- | --- | --- |
| F-1 | **覆盖归属契约缺失**：DTO 只有 `{radius, centers}`，无 uid / capture_run_id / map_id / coordinate_version / layer_key / version；前端无法拒绝跨账号/跨地图/跨采集代次的旧覆盖，慢响应也无法按版本回退丢弃 | `spritelens/services/scene_coverage.py:7-41`、`frontend/src/types/nearby.ts` 的 coverage 解析；计划 §6.5（L270/L274） |
| F-2 | **覆盖可能被目标点污染**：`0x0152` 入场位置解析失败时，`scene_repository.py:338` 仍用当前 `self._position` 写覆盖，而它可能是上一次 `0x0133` 的 `client_target`（移动目标）残留，违背"普通目标点不画覆盖" | `spritelens/services/scene_repository.py:318-338`；`docs/NEARBY_OBSERVATIONS.md:114` |
| F-3 | **停采/断流后覆盖与地图不可回看**：`displayMap` 只在 `data === null` 时保留 lastMap；`phase=stopped` 时 data 非空但 resource_id=null → 地图与覆盖一起消失 | `frontend/src/pages/NearbyPage.vue:150,166-168,276` |
| F-4 | **错误态与空态混淆**：无数据且请求失败时主区仍写"尚未观察到附近精灵 / 进入场景并开始采集后会自动显示"，错误只在右上角一行 countNote，空态无重试 | `NearbyPage.vue:189-204,266-270` |
| F-5 | **图例语义误导**：地图图例写"已扫描 / 未扫描"，容易被读成探索率/AOI；ROADMAP 明确"现有半径不是 AOI 证据"，计划定的文案是"本次足迹 / 有观察记录 / 未记录" | `frontend/src/components/SceneMap.vue:396-402`；`docs/ROADMAP.md:121`；计划 L140-144 |
| F-6 | **后台供数超出文档口径**：声音提醒默认开启，`feedNeeded() = floating || alert.enabled()` → 页面未打开/隐藏时也按摘要变化全量拉 `/api/nearby`；文档只描述"悬浮窗订阅时才供数" | `spritelens/web/static/nearby-page.js:40,141-151`、`nearby-alert.js:18-21`；`docs/NEARBY_OBSERVATIONS.md:54` |
| F-7 | **双底图常驻与文档相反**：文档与 ROADMAP 写"只挂载一张 4096、切回雷达即卸载"，实际 `SceneRadar` 永远渲染底图、`SceneMap` 激活后 `v-show` 常驻，单测还反向断言"保留已加载组件" | `NearbyPage.vue:274-276`、`SceneRadar.vue:199-202`、`SceneMap.vue:376`；`docs/ROADMAP.md:127`、`NEARBY_OBSERVATIONS.md:110` |
| F-8 | **切号后不知道是谁的观察**：页头只有计数与 phase，悬浮雷达标题无账号/角色；用户切号后无法从界面确认当前观察属于哪个角色 | `NearbyPage.vue:226-234`、`frontend/src/pages/FloatingRadar.vue` |
| F-9 | **地图清单无超时/abort**：页面请求有 8 s 超时，地图清单没有；`useWorldMaps` 无 AbortController | `frontend/src/composables/useWorldMaps.ts:9-26` |
| F-10 | **覆盖半径与雷达半径双源**：覆盖半径在启动时读 settings 传给仓库，`/api/nearby` 的 radar_radius_raw 每请求重读 settings；改配置不重启会不一致 | `spritelens/app_context.py:281-291`、`spritelens/web/nearby.py:78` |
| F-11 | **`aria-busy` 随后台同步翻转**：视觉上不闪（刷新按钮独立 refreshing），但读屏会在每次后台刷新时播报忙/闲 | `NearbyPage.vue:249`、`useNearby.ts:20,45` |
| F-12 | **相对时间不自动更新**：只在渲染时读 `Date.now()`，无定时器；静止时"刚刚"会一直挂着 | `NearbyPage.vue:205-213` |
| F-13 | **从雷达/地图选中会清空搜索词**：`selectActor` 先清空搜索再滚动，用户筛选状态丢失 | `NearbyPage.vue:32-38` |
| F-14 | **断流态状态层几乎盖住底图**：`SceneMap` 的"等待参考位置"层接近不透明且 `pointer-events:none`，"保留静态底图可浏览"实际观感差 | `SceneMap.vue:404-410` |

C04（目标条件）、C05 的 Toast/历史/系统通知、C06 米制与方位、C07 命中目标监控仍是零实现或部分实现，ROADMAP 已如实标注，不在此重复排期。

## 五、文档与代码矛盾（择要）

| 矛盾 | 文档 | 代码 |
| --- | --- | --- |
| "只挂载一张 4096、切回雷达即卸载" | `docs/ROADMAP.md:127`、`NEARBY_OBSERVATIONS.md:110` | 双底图 `v-show` 常驻（F-7），单测反向断言 |
| "覆盖应独立接口，不能每包重发整张网格" | `docs/NEARBY_MAP_PLAN_2026-10-26.md:268` | 每包全量下发，无 `/api/nearby/coverage` |
| 图例"本次足迹 / 有观察记录 / 未记录" | 计划 L140-144；ROADMAP L121 明确"不是 AOI 证据" | 当前是"已扫描 / 未扫描"（F-5） |
| 默认缩放 80% | 计划 / ROADMAP 口径 | `SceneMap.vue` `DEFAULT_ZOOM = MAX_ZOOM`（300%） |
| 覆盖来源口径（是否含精灵位置） | 旧口径仍留在 ROADMAP 相邻段落 | 当前来源=进场/传送/历史移动/停止位/收到的精灵位置（C13-04 实现） |
| 后台供数范围 | `NEARBY_OBSERVATIONS.md:54` 只说悬浮窗订阅 | 提醒默认开启后隐藏页也全量供数（F-6） |

这些是"文档需要同步"还是"代码需要回退"要按项决定；本报告只登记，不擅自改路线图状态。

## 六、补充清单（含最小改法与验收断言）

### P0（进入真实游戏/WebView2 验收前应处理或明确降级）

| 编号 | 问题 | 最小改法 | 验收 |
| --- | --- | --- | --- |
| P0-1 | 每拍全量 GET + 全量重建（3.1/3.2） | ① `useNearby.update()` 加 250–500 ms 合并/最小间隔（同周期内只保留最后一次），或让 WS 直接带快照由前端 `parseNearby` 后写入、免二次请求；② 后端按 `(uid, observation_id, version)` 缓存已组装的 `nearby` 摘要/整包（PERF07 手法外推）；③ actors 只 `asdict` 一次 | 500 实体连续推送：单次提交 p95 < 100 ms、无 >100 ms 长任务；`/api/nearby` 请求 ≤1 次/2 s；静止时 0 次请求；节点身份保持（cards/targets kept=全部） |
| P0-2 | 覆盖层 6 份 path + 全图 mask（3.3） | ① 覆盖拆独立接口/独立版本，按 map + coordinate_version 缓存，只在变化时推增量；② `MapCoverage` 同构 path 去重（mask 用一份 `d`、fill/border 复用或改用 `clip-path`/canvas）；③ 相邻圆合并/抽稀（如按 `spacing` 合并成团块）；④ 地图隐藏时卸载 MapCoverage 实例 | 5,000 圆心：DOM 中 path 实例 ≤2、总字符串 <1 MB；覆盖更新提交 p95 < 50 ms；`/api/nearby` 包体不随圆心数线性增长 |
| P0-3 | 密集场景无节点预算（3.4） | ① 雷达/地图设点位上限（如各 200）并按距离/attention 抽样，超出显示"还有 N 个未显示"；② 地图 marker 先做视口过滤再生成；③ `markers`/`labels` 用引用复用 + `v-memo`；④ 雷达用 `<use>`/canvas 降低单点节点数 | 500 实体：DOM < 3,000、雷达 SVG < 1,500；推送提交 p95 < 50 ms；1,000 实体仍无 >100 ms 长任务；屏幕阅读可达的焦点目标不超过上限 |
| P0-4 | 覆盖归属契约缺失（F-1） | DTO 增加 `uid / capture_run_id / map_id / coordinate_version / layer_key / version`；前端按当前账号/地图/坐标版本校验，不匹配的覆盖不画；补契约测试 | 切号/切图/重开采集后，旧覆盖不显示且不报错；坐标版本变更后旧覆盖被丢弃；测试覆盖 6 种不匹配组合 |
| P0-5 | 覆盖可能被目标点污染（F-2） | 只在本次确实解析到 teleport / scene_entry 位置时 `record`，位置为 None 不写 | 回归：`0x0133` 目标点后紧跟缺位置的 `0x0152`，centers 不增长 |
| P0-6 | 停采回看 + 错误空态（F-3/F-4） | ① "已暂停/已结束"作为合法只读态：保留最后地图+覆盖（带账号/地图/版本），清实体与玩家位置并明示；② 空态拆三态：未开始采集 / 已开始但无观察 / 读取失败（带重试） | paused/stopped 下地图与覆盖仍可见并标注来源；断网且有旧数据时显示"读取失败 + 重试"而不是"尚未观察到" |

### P1（下一批优先，收益明确、改动可控）

| 编号 | 问题 | 最小改法 |
| --- | --- | --- |
| P1-1 | 卡片 key 含 `observation_id`（`NearbyPage.vue:251`）→ 换观察周期 12/12 卡片节点重建 | key 只用 `actor_id`；观察周期变化由数据清空自然处理 |
| P1-2 | 覆盖层/底图资源无法缓存（`/static` no-store） | 对 `/static/maps/*` 与带 hash 的构建产物改用 `public, max-age` + ETag，保留 `/api/*` no-store |
| P1-3 | 隐藏页仍全量供数（F-6） | 默认开启但延迟到"首次打开附近页或显式开启声音"后才供数；或后台只拉轻量摘要供提醒 |
| P1-4 | `aria-busy` 随后台同步翻转（F-11） | 只绑首次加载与手动刷新；后台同步改 `aria-live` 静默摘要 |
| P1-5 | 图例/文案语义（F-5） | 改为"本次记录 / 有记录 / 未记录"，补"圆只表示取得过人物位置样本，不代表必有精灵"；覆盖为空不显示图例 |
| P1-6 | 覆盖半径双源（F-10） | 由一次配置快照驱动，或 DTO 同时下发半径供前端核对 |
| P1-7 | 地图清单无超时（F-9） | 复用 8 s 超时 + AbortController，失败保留上次清单并给重试 |
| P1-8 | 切号后无账号可见性（F-8） | 页头与悬浮雷达显示角色名或 uid 短码；切号时明示"附近观察已重置" |

### P2（可排期或随 C13-05 一并处理）

- 每移动包 `_prune_distant_actors` 全表扫描（`scene_repository.py:250`）→ 改为按距离分桶或每 N 包/每 X ms 一次。
- `/api/world-maps` 每请求重解析 → 启动/清单 mtime 变化时缓存。
- 覆盖层跨地图无全局上限 → 加总点数上限或 LRU。
- `SceneMap` 跟随模式每拍重排 stage → center 变化走 transform 而非 left/top，或 `will-change` 限定。
- 卸载后 detached 节点未回收（heap 12 MB）→ 用 CDP GC 后复测，确认是否只是未触发 GC。
- 相对时间不更新（F-12）、选中清空搜索（F-13）、断流态遮底图（F-14）、视图模式不持久化、悬浮窗尺寸/透明度不持久化。
- 雷达/地图缺 `aria-live` 与键盘平移；长名称/多标记行的高 DPI、窄窗（640×360 / 390×844）极限布局未验证。
- 声音提醒：启动首份快照若已有双牌会立即响（未建基线）、冷却 10 分钟不可配置、无手势时自动播放可能静音漏提醒。

## 七、建议排期（四个切片）

1. **切片 A：低风险止血**（P0-1 的前端合并节流 + P1-1/P1-2/P1-4/P1-5/P1-7）——不改变数据契约，先消掉 2 Hz 全量请求与明显的资源浪费，可独立验收。
2. **切片 B：覆盖数据链路**（P0-2 + P0-4）——独立接口、版本/归属契约、path 去重与抽稀；这一刀决定 C13-05 能否起步。
3. **切片 C：渲染预算**（P0-3）——点位上限、聚合、视口过滤、`v-memo`；与 C04 命中筛选一起设计更省事。
4. **切片 D：语义与正确性**（P0-5/P0-6 + F-8/F-9/F-10）——污染回归、停采回看、三态空态、账号可见性。

每片都应写明失败分支（覆盖接口失败/清单失败/切号）与验证方式；性能改动必须有连续更新的前后对照（500 实体、500 ms 节奏、至少 20 次推送），不能只用单张截图或构建通过。

## 八、未验证清单

- 真实游戏流量（本轮只有合成快照；上一次审查用 2026-10-24 真实日志回放，本次未重复）。
- 真实 WebView2 / pywebview / 打包 exe 下的帧时、内存与高 DPI（150%/200%）。
- 4096 实体与 16,384 圆心的真实 GPU 渲染成本（headless 软件光栅未完成）。
- 虚拟列表滚动锚定与"只渲染可视行"（探针页缺定高容器）。
- 真实音频输出与自动播放策略；多账号/多连接 WS 广播压力。
- 10018 地图现场校准；候选图不可用态的真实观感。
- 长名称、最多标签/徽章、空态/错误态、窄窗与字体回退的极限布局（仅有代码阅读）。
- 卸载后 detached 节点是否可由 GC 回收。

## 九、与既有文档的关系

- 与 `docs/reviews/2026-10-24-nearby-review.md`：那份的 P0-1（距离阈值）已修复，P0-2（snapshot 读路径推进插值）已被 PERF07 类缓存绕开但仍以 version 驱动前端重取；P0-3（切页卸载）已改为 pause 保留；P0-4（悬浮雷达失效兜底）已由心跳 + 3 s 清空实现。本轮是新快照，不复用其结论。
- 性能共同约束沿用 ROADMAP 的 PERF 系列：缺真实 WebView2/长期运行证据必须标"已实现待验收"；不得以展示失效附近数据或 UI 闪动换性能。
- 本报告登记但**不修改** `docs/ROADMAP.md` 的状态；路线图状态由后续实现任务按证据更新。

## 十、实施状态（2026-10-27 第二至五轮，追加记录）

本节记录按第六节清单实施后的状态。改动覆盖后端（格网覆盖、DTO、0x0152 污染）、前端（覆盖层、渲染预算、更新链路、状态语义）、应用壳（隐藏页供数与节流）、文档与回归；结论以本节为准，第一至九节保留审查当时的证据与判断。

### 10.1 覆盖层：圆心 + 半径改为固定世界方格

| 项 | 状态 | 说明与证据 |
| --- | --- | --- |
| 存储形态 | 已改 | `spritelens/services/scene_coverage.py` 为 `SceneCoverage(cell_size=2000 原始单位, radius_raw, MAX_CELLS=16384)`，绝对格 `(y//cell_size, x//cell_size)`；第五轮起每个采样写入「采样点 + 观察半径」圆的交集格（格矩形与圆相交即算），不再只写 1 格；快照按 `(gy, gx_start, run_len)` 合并成行区间并缓存，只有新增格递增 revision |
| DTO | 已改 | `{uid, map_id, layer:"visit", scope:"session", revision, cell_size, cells, rows}`，无资源或无格为 null；`rows` 为三元组数组，前端上限 16384（与 MAX_CELLS 对齐，散点最坏情况每格独占一个 run） |
| 渲染 | 已改 | `frontend/src/components/MapCoverage.vue` 只算一次 `d`，mask/fill/border 三个节点复用同一条字符串；雷达视图隐藏时 `SceneRadar` 的覆盖组随 `:visible` 卸载，不再与地图各挂一份 |
| 归属 | 部分 | 有 uid/map_id/revision/layer/scope/cell_size；缺 `capture_run_id`、`coordinate_version`、`entity_cells`、`last_sample_at`（见 10.5） |
| 污染 | 已修 | `0x0152` 没有自带落点时不再用残留 `client_target` 写足迹；新增回归断言"目标点后紧跟缺位置的场景重入，格数不增长" |
| 独立接口 | 未做 | 覆盖仍随 `/api/nearby` 全量下发，但格网 DTO 只有 467B（连续 5,000 格）到 12,733B（散点约 6,000 格），不再是包体主项 |

### 10.2 渲染预算与更新链路

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 每拍全量重取 | 部分 | `useNearby.update` 同周期只按摘要领先触发后台读取，间距 `AUTO_LOAD_INTERVAL_MS=800` 做 leading+trailing 合并；`loading`、`aria-busy`、骨架只属于首次与手动刷新。WS 直投快照（彻底免二次 GET）未做 |
| 雷达节点预算 | 已做 | `SceneRadar` `MAX_RENDERED_TARGETS=160`，选中 > 非普通 > 距离近优先，超出以"仅显示最近 N 个"表达 |
| 地图节点预算 | 已做 | `SceneMap` 同样 160，先做视口过滤再生成 marker；标签上限仍为 8/6 |
| 列表 | 已做 | 附近列表改虚拟滚动（定高容器 + 行测量），卡片 key 改为 `actor_id`，换观察周期不再整表重挂 |
| 隐藏页供数 | 已做 | 应用壳 `nearby-page.js` 在页面不可见（切走或从未打开）时按 2 s 最小间隔合并供数，首份快照与失败重试仍立即执行 |
| 资源缓存 | 已做 | `/static` 由 `no-store` 改 `no-cache`（允许 304），`/api/*` 仍 `no-store`；世界地图清单按 mtime 缓存 |

### 10.3 功能与语义补全

- 停采/断流改为合法只读回看态：保留最后一份底图、覆盖与足迹，状态与计数行注明"不再实时"，切场景/切号仍立即失效（F-3）。
- 空态拆三态：未开始采集 / 已开始但无观察 / 读取失败；失败态给重试按钮，不再用"尚未观察到附近精灵"掩盖错误（F-4）。
- 图例改为"本次足迹 / 未记录"，并在 `title` 中写明足迹格只表示取得过位置采样，不代表 AOI 或探索率（F-5）。
- 页头新增当前观察账号短码（完整 uid 在 `title`），切号后随之更新（F-8/P1-8）。
- 地图清单读取加 8 s 超时与失败重试，避免按钮一直停在"正在读取地图清单…"（F-9/P1-7）。
- 覆盖半径单源：`nearby.radar_radius_raw` 同时供雷达显示与覆盖格计算（装配时读取，改配置需重启），不再有两份半径（F-10/P1-6）。
- 后台同步不再翻转 `aria-busy`（F-11/P1-4）；"已扫描"类图例与 ROADMAP 冲突的文案已同步（P1-5）。
- 手动清除足迹（用户新需求）：地图工具条新增「清除足迹」，点击乐观清空覆盖层后 `POST /api/nearby/coverage/reset`；服务端 `SceneCoverage.clear(resource)` + `SceneRepository.reset_coverage()` 清空当前地图格网并推进版本，失败恢复原覆盖并提示重试。只动覆盖层，不动列表、观察周期与相机。
- 覆盖范围按雷达半径外扩（第五轮，用户复核要求）：用户指出「看得到这么远的精灵，探索范围却只有一个方格」，`SceneCoverage._cells_for` 改为记录采样点与观察半径圆的交集格，做到看得见多远的精灵就记多少格；候选矩形超过 `MAX_CELLS` 时退回中心格，`record` 到上限时整次采样都不写入（不产生半个圆）。半径经 `SceneRepository(coverage_radius_raw=…)`、`AccountSessions(scene_coverage_radius_raw=…)` 与 `build_app_context` 从 `nearby.radar_radius_raw`（默认 10,000、500–200,000）装配，`DEFAULT_RADAR_RADIUS_RAW` 移到 `scene_repository.py` 由 `nearby.py` 复用。`/api/nearby` 的覆盖 DTO 形状未变，仍随整包下发；`mapCoverage.ts`、`types/nearby.ts` 与地图图例 `title` 同步改为「采样点 + 观察半径覆盖到的格」。

### 10.4 验证与实测（本机，Edge headless 1440×1000）

浏览器基准用 `.research/nearby-perf/render_bench2.py` + 探针页（页高固定 976px，修复了探针未定高导致虚拟列表全渲染的测量偏差）；探针的 `load` 是本地 mock，不含 HTTP 往返与真实 WebView2 合成，帧与提交时间只作上限参考。

| 场景 | 元素 / 卡片 / 雷达点位 | 覆盖 path | 帧 p95 | 长任务 | 推送提交 |
| --- | --- | --- | --- | --- | --- |
| 12 实体、雷达 | 443 / 12 / 12 | 无 | 16.7 ms | 0 | 平均 0.6 ms，最大 2.9 ms |
| 500 实体、无覆盖 | 1,247 / 15 / 160 | 无 | 16.7 ms | 0 | 平均 1.2 ms，最大 6.3 ms |
| 500 实体、2,000 格 | 1,254 / 15 / 160 | 3 × 1,710B | 16.8 ms | 0 | 平均 0.8 ms，最大 4.5 ms |
| 500 实体、2,000 格、地图 | 1,254 / 15 / 160 点位 + 8 标签 | 3 × 1,710B | 16.7 ms | 0 | 平均 2.0 ms，最大 7.6 ms；切视图 38.1 ms |
| 500 实体、5,000 散点格 | 1,254 / 15 / 160 | 3 × 178,600B（合计 514 KiB） | 16.8 ms | 0 | 平均 3.1 ms，最大 11.8 ms |
| 4,096 实体、16,384 格、地图 | 1,254 / 15 / 160 点位 + 8 标签 | 3 × 4,980B | 33.3 ms | 0 | 平均 8.9 ms，最大 17.6 ms；切视图 31.9 ms |
| 4,096 实体、16,384 格、雷达 | 1,254 / 15 / 160 | 3 × 4,980B | 16.8 ms | 0 | 平均 4.9 ms，最大 14.6 ms |

对照审查时的实测：500 实体雷达 14,145 元素 / 2,411 SVG / 6 个 120–150 ms 长任务，现为 1,247 元素 / 160 点位 / 0 长任务；2,000 圆心覆盖 1.96 MB、5,000 圆心 4.9 MB 且 DOM 出现 6 份，现为 3 个节点、5,000 散点格合计约 514 KiB；地图切视图由 176.5 ms 降为 31.9–38.1 ms；4,096 实体 + 16,384 格在旧探针下无法在 10 分钟内完成首帧，现在能正常测完（仍是 headless 软件光栅）。

后端基准（`.research/nearby-perf/lead_bench_grid.py`）：4,096 实体 + 5,000 格时 payload 1,702,548B、构造 15.4 ms、序列化 14.5 ms（旧：1,965,304B、66.7 ms、21.6 ms）；12 实体时 payload 6,434B、构造 0.088 ms。覆盖 DTO 与实体数无关，只随格数/行区间增长。第五轮按雷达半径外扩后（`.research/nearby-perf/bench_radius.py`）：默认半径 10,000 / 格 2,000 时一处采样约 100 格；沿 1,500 原始单位一步走 200 步（约 3 km）累计 1,742 格但只有 11 行区间，覆盖 DTO 仅 270B，`record` 0.05 ms、行区间重算 0.3 ms；payload 12 实体 6,225B、4,096 实体 1,702,946B（构造 17.9 ms、序列化 16.1 ms），与只记单格时基本一致。

回归与构建（第五轮收尾时复跑）：`tests.test_scene` 33 项、`tests.test_scene tests.test_web_server tests.test_frontend_contract` 64 项通过（更早批次另有 31/46/48/60/33 项）；前端 `npx vitest run` 33 个文件 234 通过、1 跳过，`vue-tsc --noEmit` 通过；`tools/frontend.py build` 通过（main 375.17 kB / gzip 119.36 kB、CSS 197.15 kB、floatingRadarBridge 91.89 kB、回执 8 个文件）。

清除足迹按钮极限布局（`.research/nearby-perf/layout_check.py`，Edge headless + CDP）：1440/1024/900/640/480/360 六档，含声音提醒按钮与 2,000 格覆盖，空态与有足迹态、地图视图分别测量；无横向滚动、无控件重叠、无裁切，工具条 2–4 行正常换行；清除前后按钮矩形完全一致（x1186 y48.5 w98 h34），清除后按钮禁用且图例只余「未记录」；像素对比确认覆盖层真实绘制并在清除后消失（平均亮度差 10.8）。

第五轮观察半径覆盖的渲染抽查（`.research/nearby-perf/radius_visual.py`，探针按后端语义生成路线足迹带）：200 个采样点（每步 1,500 原始单位、半径 10,000、格 2,000）得到 1,768 格，页面仍只有 3 个覆盖节点、`d` 各 1,027 字符，图例显示「本次足迹 · 1768 格」，无横向溢出，与后端基准的 1,742 格/11 行一致（说明 JS 与 Python 的圆格判定口径一致）。覆盖包围盒在底图坐标下为 3,212 × 281 图像像素（约 3.2 km × 0.28 km 原始坐标，即 200 个采样点的直径 200 m 圆带），300% 缩放下已占满可视高度；`setCoverage(0)` 后覆盖节点与填充消失、「清除足迹」回到禁用态，说明清除链路与渲染同步。

### 10.5 仍未完成或未验证

- `/api/nearby` 仍是"一次请求整包"：4,096 实体时约 1.7 MB，前端解析与提交已压到 8.9 ms 均值，但传输与 JSON 解析在大包下仍是主要成本；免二次 GET 的 WS 直投、分页或按需裁剪都未做。
- 覆盖 DTO 仍缺 `capture_run_id`、`coordinate_version`、`entity_cells`、`last_sample_at`：跨采集代次/跨坐标版本的旧覆盖只能靠 uid + map_id + revision 粗校验，跨重启历史（C13-05）仍不能安全起步。
- P2 未做：`_prune_distant_actors` 每包全表扫描（4,096 实体约 1.06 ms/包且持锁）、跟随模式每拍重设 stage `left/top`、覆盖跨地图无全局上限、卸载后 detached 节点未做 GC 复测、相对时间不自动刷新、悬浮雷达尺寸/透明度不持久化。
- 覆盖连续性取决于真实采样密度：现在一处采样记录「采样点 + 半径 10,000 原始单位」的圆内格（约 78 格、直径约 200 m 游戏内距离），游戏多久推一次位置、断包时轨迹是否连续都未用真实流量验证；16,384 格上限触顶后静默停记（没有提示，只能靠「清除足迹」重置），跨重启历史（C13-05）仍未开始。
- 手动清除足迹只在 headless mock 下做完布局与状态目视（含清除后图例与禁用态），真实 WebView2 下的写请求时序、并发采样与失败提示未验证；服务端清空会推进快照版本，同账号其他页面在下一拍摘要后自动重拉并清空，但没有专门的广播事件，两页同时操作时的时序未验证。
- 文档矛盾 F-7 只做口径对齐、不改实现：SceneRadar/SceneMap 仍 v-show 双常驻（各自保留缩放、拖拽、滚动位置，共享选中与列表状态），已在本报告第十节与 docs/ROADMAP.md 第三轮段落注明 C13-02「切回雷达即卸载」为当轮口径。
- 未验证：真实游戏流量与采样密度、真实 WebView2/pywebview 与真实 GPU 合成、150%/200% 高 DPI、640×360/390×844 窄窗下的极限布局与连续更新目视闪动、打包 exe、真实音频自动播放策略。按仓库约束，这些项只能标"已实现待验收"，不能算 C13 阶段完成。

