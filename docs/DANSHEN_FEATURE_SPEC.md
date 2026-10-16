# 蛋神助手本地功能规格（v1.1.6 解剖结论 · 实施对照）

> 本文是对标实施的**工作文档**：记录蛋神助手（电脑版 v1.1.6）本地功能的
> 模块结构、数据模型与算法要点，以及 SpriteLens 侧的实施状态。
> 云端 / 账号 / 订阅 / 交易市场 / 更新服务不在范围（项目定位纯本地）。
>
> 解剖方法：PyInstaller 解包 → Python 3.12 marshal 反汇编（pyc 无源码级
> 反编译工具，靠字节码 + 常量表还原）→ 前端 JS 通读。
> 解包产物：`蛋神助手解包目录`。
> 研究过程产物（pyc 反汇编 dump 等）在 `.research/`（不入库）。
> 架构层结论见 [DANSHEN_ASSISTANT_ANALYSIS.md](DANSHEN_ASSISTANT_ANALYSIS.md)（历史文档，仍有效）。

## 1. 业务模块全景（PYZ 反汇编确认）

蛋神本地业务模块 → SpriteLens 实施对照：

| 蛋神模块 | 规模 | 职责 | SpriteLens 状态 |
|---|---:|---|---|
| `roco_collector` | 7,117 行 | 协议采集器（可独立 CLI） | 已有等价且更强（schema 双路降级） |
| `egg_types` | 小 | 蛋类型判定（普通/特殊/异色/神奇/炫彩 + 玻璃信息） | 🟡 协议字段已提取（special/appearance/extension）；动态判定未做（类型名暂用静态目录） |
| `egg_inventory` | 757 行 | 蛋仓快照解析 + 分页 + SQLite | ✅ 已实装（蛋蛋仓库页：形状搜索累积 + SQLite 持久化） |
| `egg_evidence` | 小 | 孵蛋证据链（性格预测/声音/标注来源） | ⬜ 待做 |
| `nest_egg_inference` | 1,454 行 | **孵蛋推断引擎**（窝×父本→子代概率） | ⬜ 待做（算法在 §3.4；智能配窝页已占位） |
| `home_scene` | 737 行 | 家园场景解码（居民/家具/产蛋窝/场景蛋） | 🟡 已有解析；场景/主人归属与增量过滤待修，见 F04-U2 |
| `home_breeding_range` | 295 行 | 繁育范围（楼层×距离×蛋组兼容） | 🟡 家园页用于过期关系候选；智能配窝的全量规划仍待做 |
| `color_cards` | 小 | 炫彩色卡（glass→卡号/粒子映射） | ✅ 已实装（炫彩色卡页：底色×混色矩阵） |
| `flower_seeds` / `flower_state` | 小 | 炫彩花种（协议帧 + 按天合并） | ✅ 已实装（炫彩花种页：0x0375 快照 + 宠物名学习表） |
| `pet_medals` | 4,710 行 | 体型/声音奖牌富化（种群内极值 + 内嵌种群名录） | ⬜ 富化未做（medals.json 静态表已导入） |
| `desktop_catalog` | 小 | 静态目录加载（技能/勋章/特长/体型声音名） | 部分已有（static_data） |
| `desktop_preferences` | 小 | WebView2 leveldb 旧偏好迁移 | 不适用（无历史包袱） |
| `collection_accounts` | 小 | 产线收集的账号维度（本地 gameIds ≤100 / 云端 gating） | ⬜ 本地部分待做（产线收集页已占位） |
| `webview_guard` / `window_geometry` / `window_close` | 小 | 桌面壳三件套 | ✅ 前两者已抄（见 §3.9） |
| `delta_update` / `remote_release` / `update_launcher` | 1,700+ 行 | 增量更新链（Ed25519+bsdiff4） | ⬜ 跳过（属分发服务） |
| 云端（app 内 market/subscription/sync 部分） | — | 交易市场/订阅/云同步 | ⛔ 明确不做 |

前端页面（webui/ 40 个 JS 文件）：侧栏分组 = 精灵背包 / 蛋蛋仓库 / 家园信息 /
孵蛋工具（种公阵列、种公母库、智能配窝、产线收集、交易市场）/ 精灵图鉴
（精灵图鉴、蛋图鉴）/ 炫彩色卡 / 炫彩花种 / 换蛋广场 / 赞赏作者。
其中交易市场、换蛋广场、赞赏作者、账号体系为云端功能，不抄。

## 2. UI 布局（index.html 实测）

```
app-shell
├── sidebar（品牌块 + 分组导航 + 底部"本地安全模式"）
│     概览
│     仓库与图鉴：精灵背包 / 精灵图鉴 / 蛋图鉴
│     孵蛋工具：蛋蛋仓库 / 种公阵列 / 种公母库 / 智能配窝 / 产线收集
│     家园信息：我的家园
│     炫彩：炫彩色卡 / 炫彩花种
│     系统：协议流 / 采集与设置        ← SpriteLens 自有页归入系统组
└── main-shell
      ├── topbar：角色块 | 状态 pill（握手/采集/密钥/录制）| 主按钮（开始采集）
      └── pages：每页 section#page-*；背包为中间网格 + 右侧筛选/详情共用栏（加全局导航构成三栏）
modal-layer + toast-layer
```

SpriteLens 已按此骨架重构（保留自有"概览/协议流/采集与设置"页）。
蛋神特有的交互资产，后续页面直接复用：

- **点阵背包 / 属性卡片 / 对比表格**（segmented 切换；点击或 Enter 打开详情，悬停不放大）
- **矩阵视图**（种公阵列：性格×蛋组覆盖矩阵；色卡：底色×混色矩阵）
- **分页器 + 右侧详情面板**（Master-Detail 范式，SpriteLens 已有）
- **孵化时间倍率表**（原始/5 倍/6 倍/30 倍）——蛋图鉴已实现

## 3. 关键数据模型与算法（反汇编还原）

### 3.1 蛋类型（egg_types）

蛋条目字段 → 类型判定：
- `appearance` / `extensions`：外观扩展（`mutation_type`、`glass_info`、`precious_egg_type`、`extension_type`）
- 类型名：普通蛋 / 特殊蛋（special_egg_conf_id）/ 异色蛋（is_shiny）/ 神奇蛋（is_mystery_egg，随机 randomEgg）/ 炫彩蛋（is_colorful，rainbow）
- 玻璃信息：`glass_type` / `glass_value`（炫彩色卡与粒子的数据源）
- 孵化状态：`hatching`（startHatchTime / hatchedSeconds / hatchUpdatedAt）

### 3.2 蛋仓（egg_inventory）

- 自带 protobuf varint 解析（read_varint / parse_protobuf_fields / iter_length_delimited_messages）
- 蛋条目字段：`itemConfId`（道具 ID）、`petConfId`（detail.conf_id → 蛋目录 egg_conf_id）、`category`（获取来源）、`preciousEggType`、`obtainedAtUnix`、`bagType`、`instanceId`、`quantity`。2026-10-15 已纠正两类 ID 混用；field17 是随机蛋配置，不等于特殊蛋类型。
- 分页聚合：`EggInventoryPages.feed(payload)`（多页快照合并）
- 静态联查：egg_static_config.json（我们用 data/static/eggs.json 的 egg_conf_index）
- "智能标注"：对每枚蛋挂证据与推断结论（见 3.4）

### 3.3 孵蛋证据（egg_evidence）

蛋的标注来源三级：`localAnnotation`（本地推断）> `manualOverride`（手改）> `cloudAnnotation`（云标）。
性格预测结构：`{nature, status: certain/possible/missing, probabilities: {nature: percent}, distribution, evidenceSource, ruleVersion}`；
声音证据：父本 `parent_sound` dB 值 → 蛋声音候选（`plus100/minus100` 规则，"dB" 单位）。

### 3.4 孵蛋推断引擎（nest_egg_inference）——蛋神最核心算法

`NestEggInference(db)` 按 uid 存状态，流程状态机：

```
begin(uid, occurred)           开始孵蛋（窝占用）
pet(uid, pet_id, occurred)     父本信息入库（fathers 列表）
home(uid, data, occurred)      家园快照 enrich（窝位置/居民）
scene_predictions(home)        按窝 × 父本算预测
write_prediction(uid, egg_id, result, occurred, reason)
collected(uid, binding, occurred)   收蛋对账（蛋→实际物种回填证据）
recalculate / reconcile        快照对账（snapshot-species 规则）
```

概率核心 `probability(mother, fathers)`：按候选父本的**性格对目标性格的加成**
计分（add(nature, amount)），输出 `{probabilities, unknownPercent}`；
多父本等概率时走 `equal-father-probability` 规则；`natureCertain` 表示唯一可能性格。
结论写回蛋条目（annotate_entry），收蛋后 reconcile 校准。

> SpriteLens 实施：数据依赖 = 家园窝数据（谁在哪个窝）+ 宠物库（父本性格/蛋组）
> + 蛋仓（子代）；三者齐备前只能先实现"蛋组 × 性格"静态覆盖矩阵（种公阵列）。

### 3.5 家园场景（home_scene / home_breeding_range）

- 场景结构：`residents`（居民宠物）、`furniture`（家具：furnitureGuid/configId/position/roomId/floor）、`nests`（产蛋窝：nestType/nestName + `layEggCouples`[{femaleActorId, maleActorIds}]）、`sceneEggs`（场景蛋）
- v1.2.0 家园页请求本地 `/api/home/info?gameId=...`。采集运行时该路由读取本地 `home-capture` 缓存，结果仍放在 `remote` 字段；停止采集后在线更新才使用云端服务。前端按 `resident/isHomeResident` 筛成员，再以 instance/gid 合并本地个体资料。
- 楼层：`_home_position` 的 signed x/y/z → 一楼/二楼/地下室（`home_floor`）
- 请求/响应配对：`pending_home_collection` 用于 0x0137/0x0243 家园拾蛋请求/响应关联，不是主动查询家园成员的机制。
- 繁育范围：`in_range(a, b, home)`——两窝距离判定 + `compatible(a, b)`（性别不同 + 蛋组交集）
- opcode（已确认）：0x014A 是通用进场景应答，需通过 home_info 主人 UID 与 0x0152/0x015C 场景资源确认目标家园；蛋神排除30002场景。场景记录提供 `instanceId`→宠物个体、`baseId`→物种、`actorId`→场景实体，以及 `layEggCouples` 配对。
- SpriteLens 嵌套解析已能从真实字段树读出11居民/11窝/6条母本配对，核心数据无需蛋神 API；旧分支误读 actor 类型为房间等级，场景/主人/会话过滤及0x0413/0x0414增量判断仍待修。实施规格见 [家园开发计划](HOME_IMPLEMENTATION_PLAN.md)，状态以 ROADMAP 的 F04-U2 为准。
- 蛋神家园主关系面板使用场景配对，未开启范围候选选项；SpriteLens 已有明确标记的过期关系候选。性格概率、均值声音和范围规则属于工具预测，不代表游戏内产物已实测。

### 3.6 炫彩色卡（color_cards）与花种（flower_seeds/flower_state）

- 色卡从蛋/宠物的 **glass 信息**派生：`card_id = glass_type × glass_value`（" × " 组合）、
  `particle`（四角星/爱心/方块/镂空五角星，pattern_*.png）、赛季粒子（season）
- UI：底色（横轴）× 混色（纵轴）矩阵；个人色卡 / 色卡图鉴预览双 tab
- 花种：`handle_flower_message(flow, opcode, payload)` 协议驱动（opcode 线索 0x375/0x39D），
  list/detail 两种消息；`flower_state.merge_flowers(previous, update, occurred)` 按 `day_key`（天）合并，
  记录 baseId/pet/endTime，登录（login 域）拉全量、增量更新
- 花种等级静态表：assets/catalog/flowerLevels.json（source: client-config-reference）

### 3.7 炫彩形态 id 体系与名字来源（重要结论）

宠物帧 field58 = 炫彩形态 conf_id（130xxx/140xxx/5400xxx 系，实测 210/214 覆盖；
roco_helper 同款字段名 caught_camp）。花种帧（0x0375 field13）按这套 id 引用宠物，
**图鉴静态表（3001-5061 系）不含它，蛋神与 roco_helper 的发行包里也没有
这套 id 的静态名字表**——两边都靠协议现场学习（宠物帧的 field58 + field3 名字
成对出现）。SpriteLens 用 Pet.colorful_conf_id + PetRepository.colorful_name()
学习表实现同款；未学到的 id 显示 "#id"（用户在游戏里获得该炫彩宠后自动补全）。

宠物帧 glass 的正确位置是 **field86 子消息 {field1: type, field2: value}**
（decode_handbook_glass；162/266 只携带；field87 是 cheer_point 加油点，先前
误认已纠正）。卡号判定（color_cards.card_id_from_glass）：type=2 且 value 低
20 位 ∈{1..4} → 赛季卡 "s1".."s4"；否则 str(value & 0xFFFFF) 查 CARDS_BY_ID
（44 张色卡目录：id/底色名/混色名/颜色 hex，已导出 data/static/color_cards.json）。
真实帧验证：42 只宠物入矩阵、零未收录。

### 3.8 体型/声音奖牌（pet_medals）

四种奖牌 = 种群内极值：大块头（体型最大）/ 小不点（最小）/ 粗嗓门（声音最低）/ 婉转声（最高）。
`enrich_pet_medals(pet)`：内嵌种群名录（890 条宠物名 → 种群分组）+ `_load_catalog_measurements()`
（catalog 测量数据）→ `refresh_pet_measurements(pet)` 算极值 → 挂 `size_medal_name` / `voice_medal_name`。
冲突消解：`resolve_size_medal_conflict(names, pet)`。
desktopSkillMedalData.json 提供 skills/medals 名称映射（desktop_catalog 加载）。

### 3.9 桌面壳三件套（已抄 ✅）

| 项 | 蛋神实现 | SpriteLens 实施 |
|---|---|---|
| WebView2 兜底 | GetAvailableBrowserVersionString + MessageBoxW 引导 + webview-startup.json | `system/webview_guard.py`：注册表 Evergreen 键 pv + env 覆盖 + 原生对话框（文案行为对齐） |
| 窗口几何 | 工作区 + GetDpiForSystem，常量 640×360~1440×810 | `system/window_geometry.py`：fit_window（默认 1280×720，clamp 工作区 90%，下限 640×360） |
| 关闭拦截 | WindowCloseIntent（comctl32 SetWindowSubclass 拦 SC_CLOSE） | 未抄（pywebview 自带关闭语义；如需"最小化到托盘"再实现） |
| DPI 感知 | SetProcessDpiAwarenessContext → shcore → SetProcessDPIAware 三级 | `web/run.py:_enable_dpi_awareness` 同款三级 |

## 4. 协议 opcode 映射（反汇编还原，业务域摘录）

> 完整规格（帧层 / IV 派生 / 断流恢复 / FlowState 37 字段 / 解码器字段级映射，46KB）
> 在反汇编研究产物 `.research/danshen-protocol.md`（临时目录，不入库；需要时按
> DANSHEN_ASSISTANT_ANALYSIS.md §11 的方法重新生成）。
> 说明：`.research/` 为竞品研究过程产物，按 `.gitignore` 不入库（参见本文档第 10 行的约定），读者需自行生成。

蛋神路由结构 = `_process_frame` 的 if/elif 显式分支（17 个）+ 全扫描解码器（12 个，
对每帧无条件尝试、结构校验通过即发事件）。与页面直接相关的：

| opcode | 方向 | 语义 | 喂给哪个页面 |
|---|---|---|---|
| 0x1344 | s2c | **蛋背包分页**（bagType==8；分页 1..total 凑齐才产出） | 蛋蛋仓库 |
| 0x030B / 0x030C | c2s/s2c | 砸蛋请求/响应（pending 对账，30s 窗口，防 ambiguous） | 蛋蛋仓库（数量扣减） |
| 0x0312 | s2c | 孵化槽 gids | 蛋蛋仓库（孵化中标记） |
| 0x0164 / 0x0300 | s2c | 蛋操作成功响应 | 蛋仓新鲜度标记 |
| 0x0137 / 0x0243 | c2s/s2c | 家园拾蛋请求/结果（pending 配对） | 我的家园 / 蛋仓 |
| 0x014A | s2c | **家园完整快照**（home_scene.decode_home_scene） | 我的家园 |
| 0x0413 / 0x0414 | s2c | 家园增量 | 我的家园 |
| 0x0152 / 0x015C | s2c | 家园资源响应（fields 3/12） | 我的家园 |
| 0x039D | s2c | 花信息（flower_seeds.handle_flower_message；258/338 也参与） | 炫彩花种 |
| 0x1883 / 0x1885 / 0x1891 | s2c | 盒子/背包业务响应 → box 快照 | 精灵背包（盒子视图） |
| 0x01C5 | s2c | 放生宠物（从 known/box 状态全部移除） | 宠物状态一致性 |
| 0x1324 | s2c | 战斗捕捉提示 → pet.capture | 捕获中心（远期） |
| 0x0102 | s2c | 登录档案 | 已有（identity） |

全扫描解码器（无 opcode 条件，结构校验准入）：box.snapshot、box.move、
handbook、egg.upsert、pet.snapshot、team.snapshot 等——这套"结构准入"思路
与 SpriteLens 现有的 schema 双路降级同型，可对照补缺。

**底层对照结论**（SpriteLens protocol/ 现状）：
- AES key 捕获：蛋神取 s2c 0x1002 帧 raw[23:39]——与 SpriteLens 0x1002 密钥链路一致 ✅
- CBC IV：蛋神**双模式并存**（legacy 链式：上帧密文尾块作下帧 IV、初始全零；
  exact：body 前 16 字节即本帧 IV）。SpriteLens 是固定 IV——**若后续遇到
  "解密成功但内容乱"的帧，优先怀疑 IV 模式差异**，这是协议层第一待验证点。
- 断流恢复：蛋神在 pending 非空且游标 3s 未前进时，把乱序段合并成连续 run →
  扫描 `b'3f'` 魔数找完整业务帧（len%16==0、32≤len≤16MiB-25）→ 用"body 前 16
  字节作 IV"试解密 + 业务记录校验 → 成功则跳游标、发 `capture.gap` 事件。
  SpriteLens 的 frames.py 已有假 magic 同步 + reassembly 已有 pending 重排，
  但没有"3 秒停滞触发的主动恢复"——列为协议层第二待验证点。
- 历史文档勘误：DANSHEN_ASSISTANT_ANALYSIS.md §3.2(7) 所述"活跃网卡智能排序
  （active_network_descriptions）"在 v1.1.6 中**不存在**——设备枚举仅用
  pcap_findalldevs，选择靠 config.json。SpriteLens 的 nic_rank.py 是自有增强（保留）。
- 工程参数：pcap_setbuff 32 MiB（SpriteLens 已对齐：`PCAP_BUFFER_BYTES`）、BPF `tcp port 8195`、
  PcapWriter 写标准小端 pcap（0xA1B2C3D4 / snaplen 65535 / link_type 首包锁定）。

## 5. 已实施清单（累计）

| 项 | 文件 | 说明 |
|---|---|---|
| UI 骨架 | `web/static/index.html` | 分组侧栏（14 页）+ modal 层 |
| 启动自恢复链 | `web/static/boot.js` + app.js | 资源加载错误捕获 + 15s 超时重试 + 内联启动面板 |
| 桌面壳三件套 | `system/webview_guard.py` / `window_geometry.py` / run.py | WebView2 预检、窗口几何 + DPI（见 §3.9） |
| 活跃网卡排序 | `capture/nic_rank.py` | Get-NetAdapter Status=Up 前置 |
| 静态目录 | `tools/import_*.py` + `data/static/` | 蛋目录 224 / 图鉴描述 601 / 色卡 44 / 花种等级表 / 奖牌表 |
| 蛋图鉴 / 蛋蛋仓库 | `domain/eggs.py` / `domain/egg_box.py` + `egg_store` | 蛋目录联查 + 蛋仓快照累积 → SQLite 持久化 + 孵化槽标记 |
| 种公阵列 / 种公母库 | payloads 种公矩阵 + app.js | 性格×蛋组覆盖矩阵、公母分库（可折叠） |
| 我的家园 | `domain/home.py` + `domain/home_breeding.py` + `home_repository` + `frontend/src/pages/HomePage.vue` | 0x014A：居民/物种/窝位/场景配对/场景蛋；0x0413/0x0414：居民/场景蛋增量；过期关系按巢穴范围推导候选 |
| 炫彩色卡 / 炫彩花种 | `domain/color_cards.py` / `domain/flowers.py` | glass→卡号矩阵；0x0375 花田 + 宠物名学习表 |
| 账号隔离 | `services/account_tracker.py` | 切号清空各域内存快照；同 uid 重复帧不误判 |
| 持久化底座 | `repositories/*` + `services/event_logger.py` | v1→v4 追加式迁移（事务化）、宠物/蛋仓 write-behind |
| 抓包健壮性 | `capture/npcap_source.py` + `services/monitor_service.py` | 32MiB 缓冲、流/会话回收、关闭事件保序、丢弃计数 |

## 6. 待实施清单（分批建议）

> 依赖顺序：协议 opcode 映射已在 §4 齐备（蛋仓 0x1344 / 家园 0x014A / 花 0x039D 等），
> 大部分页面的前置只剩"真实帧验证 + 字段映射落码"。

**第二批（有 opcode 映射，可直接开工）**：
1. 蛋蛋仓库 ✅ 已实装（0x1344 分页解析 + SQLite；"智能标注"UI 未做）
2. 种公阵列 ✅ 已实装（性格×蛋组矩阵；0x0312 孵化槽已在蛋仓页标记）
3. 体型/声音奖牌富化 ⬜（medals.json 静态表已导入，极值富化规则未做）
4. 协议层增强 🟡 部分：32MiB 缓冲 ✅；"3 秒停滞"断流恢复 ⬜、IV exact 模式兼容 ⬜

**第三批（需真实帧验证字段映射）**：
5. 我的家园 🟡 已有居民/窝位/场景配对/场景蛋解析和Vue展示；真实字段树已确认核心数据具备。场景归属、错误旧路径、增量过滤及参考页面交互待按 F04-U2-A 至 F 实施，游戏繁育效果仍待验证。
6. 智能配窝 ⬜ 待做（nest_egg_inference 推断引擎（§3.4）+ planner UI；页占位已挂）
7. 炫彩花种 ✅ 已实装（0x0375 快照 + 名字学习表）
8. 炫彩色卡 ✅ 已实装（glass→卡号→底色×混色矩阵）

**第四批（大工程）**：
9. 产线收集 ⬜ 待做（依赖蛋仓长期积累 + collection_accounts 本地部分；页占位已挂）
10. 证据链闭环 ⬜ 待做（egg_evidence 三级标注——纯本地只做前两级）
11. 3D 宠物模型 ⬜ 待做（蛋神用 Rust/WebGPU wasm 1.77MB + 云端模型 CDN——需评估本地化方案）

**明确不做**：交易市场、换蛋广场、赞赏、云账号、订阅、增量更新服务（分发服务）。
