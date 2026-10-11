# 蛋神助手本地功能规格（v1.1.6 解剖结论 · 实施对照）

> 本文是对标实施的**工作文档**：记录蛋神助手（电脑版 v1.1.6）本地功能的
> 模块结构、数据模型与算法要点，以及 SpriteLens 侧的实施状态。
> 云端 / 账号 / 订阅 / 交易市场 / 更新服务不在范围（项目定位纯本地）。
>
> 解剖方法：PyInstaller 解包 → Python 3.12 marshal 反汇编（pyc 无源码级
> 反编译工具，靠字节码 + 常量表还原）→ 前端 JS 通读。
> 解包产物：`C:\Users\chiqingsan\AppData\Local\Temp\ds\out\…exe_extracted\`。
> 研究过程产物（pyc 反汇编 dump 等）在 `.research/`（不入库）。
> 架构层结论见 [DANSHEN_ASSISTANT_ANALYSIS.md](DANSHEN_ASSISTANT_ANALYSIS.md)（历史文档，仍有效）。

## 1. 业务模块全景（PYZ 反汇编确认）

蛋神本地业务模块 → SpriteLens 实施对照：

| 蛋神模块 | 规模 | 职责 | SpriteLens 状态 |
|---|---:|---|---|
| `roco_collector` | 7,117 行 | 协议采集器（可独立 CLI） | 已有等价且更强（schema 双路降级） |
| `egg_types` | 小 | 蛋类型判定（普通/特殊/异色/神奇/炫彩 + 玻璃信息） | 📋 规格在 §3.1 |
| `egg_inventory` | 757 行 | 蛋仓快照解析 + 分页 + SQLite | ⬜ 待做（需协议帧） |
| `egg_evidence` | 小 | 孵蛋证据链（性格预测/声音/标注来源） | ⬜ 待做 |
| `nest_egg_inference` | 1,454 行 | **孵蛋推断引擎**（窝×父本→子代概率） | ⬜ 待做（算法在 §3.4） |
| `home_scene` | 737 行 | 家园场景解码（居民/家具/产蛋窝/场景蛋） | ⬜ 待做（结构在 §3.5） |
| `home_breeding_range` | 295 行 | 繁育范围（楼层×距离×蛋组兼容） | ⬜ 待做 |
| `color_cards` | 小 | 炫彩色卡（glass→卡号/粒子映射） | ⬜ 待做 |
| `flower_seeds` / `flower_state` | 小 | 炫彩花种（协议帧 + 按天合并） | ⬜ 待做 |
| `pet_medals` | 4,710 行 | 体型/声音奖牌富化（种群内极值 + 内嵌种群名录） | ⬜ 待做（含 890 条宠物名数据） |
| `desktop_catalog` | 小 | 静态目录加载（技能/勋章/特长/体型声音名） | 部分已有（static_data） |
| `desktop_preferences` | 小 | WebView2 leveldb 旧偏好迁移 | 不适用（无历史包袱） |
| `collection_accounts` | 小 | 产线收集的账号维度（本地 gameIds ≤100 / 云端 gating） | ⬜ 本地部分待做 |
| `webview_guard` / `window_geometry` / `window_close` | 小 | 桌面壳三件套 | ✅ 前两者已抄（见 §4） |
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
      └── pages：每页 section#page-*，workspace.split 三栏（筛选/内容/详情）
modal-layer + toast-layer
```

SpriteLens 已按此骨架重构（保留自有"概览/协议流/采集与设置"页）。
蛋神特有的交互资产，后续页面直接复用：

- **点阵背包 / 卡片背包双模式**（segmented 切换 + 悬浮预览开关）
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
- 蛋条目字段：`itemConfId`（→蛋目录 egg_conf_id）、`petConfId`、`category`（来源：trade/nest/boss/random/activity/special/unknown）、`preciousEggType`、`obtainedAtUnix`、`bagType`、`instanceId`、`quantity`
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
- 楼层：`_home_position` 的 signed x/y/z → 一楼/二楼/地下室（`home_floor`）
- 请求/响应配对：`pending_home_collection`（前端主动拉家园数据，带 gameId + requestedAt，响应 ambiguous 处理）
- 繁育范围：`in_range(a, b, home)`——两窝距离判定 + `compatible(a, b)`（性别不同 + 蛋组交集）
- opcode 线索（待协议层确认）：0x14A/0x152 附近 + 0x7532

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

宠物帧 field87 = glass 外观参数 {field1: type, field4: value}（214/214 全量携带；
普通宠物实测 type=1/value=1，异色/炫彩时值变化）——色卡页数据随宠物帧全量
下发，无需专门"查看色卡"操作。

### 3.8 体型/声音奖牌（pet_medals）

四种奖牌 = 种群内极值：大块头（体型最大）/ 小不点（最小）/ 粗嗓门（声音最低）/ 婉转声（最高）。
`enrich_pet_medals(pet)`：内嵌种群名录（890 条宠物名 → 种群分组）+ `_load_catalog_measurements()`
（catalog 测量数据）→ `refresh_pet_measurements(pet)` 算极值 → 挂 `size_medal_name` / `voice_medal_name`。
冲突消解：`resolve_size_medal_conflict(names, pet)`。
desktopSkillMedalData.json 提供 skills/medals 名称映射（desktop_catalog 加载）。

### 3.8 桌面壳三件套（已抄 ✅）

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

蛋神路由结构 = `_process_frame` 的 if/elif 显式分支（17 个）+ 全扫描解码器（12 个，
对每帧无条件尝试、结构校验通过即发事件）。与待实施页面直接相关的：

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
- 工程参数：pcap_setbuff 32 MiB（SpriteLens 可对照调大抓包缓冲）、BPF `tcp port 8195`、
  PcapWriter 写标准小端 pcap（0xA1B2C3D4 / snaplen 65535 / link_type 首包锁定）。

## 5. 已实施清单（本轮）

| 项 | 文件 | 说明 |
|---|---|---|
| UI 骨架 | `web/static/index.html` | 分组侧栏 + 8 个待实现页占位 + modal 层 |
| 启动自恢复链 | `web/static/boot.js` + app.js | 资源加载错误捕获 + bootstrap 15s 超时重试 2 次 + 内联启动面板 |
| WebView2 预检 | `system/webview_guard.py` | 开壳前检测，缺失弹窗引导（测试：test_desktop_shell） |
| 窗口几何 + DPI | `system/window_geometry.py` + run.py | 工作区/DPI 适配初始尺寸 |
| 活跃网卡排序 | `capture/nic_rank.py` | Get-NetAdapter Status=Up 前置（server 接线，测试：test_nic_rank） |
| 蛋目录静态数据 | `tools/import_egg_data.py` + `data/static/eggs.json` | 224 种蛋（来源游戏客户端配置整理） |
| 蛋目录域 | `domain/eggs.py` | EggCatalog（egg_conf_id/base_id 联查，测试：test_eggs） |
| **蛋图鉴页** | payloads/server/app.js/index.html | `/api/eggs` + 筛选（蛋组/类型/孵化时长）+ 详情（倍速表/公母比环/身高体重/进化链） |

## 6. 待实施清单（分批建议）

> 依赖顺序：协议 opcode 映射已在 §4 齐备（蛋仓 0x1344 / 家园 0x014A / 花 0x039D 等），
> 大部分页面的前置只剩"真实帧验证 + 字段映射落码"。

**第二批（有 opcode 映射，可直接开工）**：
1. 蛋蛋仓库：0x1344 蛋背包分页解析（EggInventoryPages 等价物）→ SQLite → 页面 + "智能标注"UI
2. 种公阵列：性格×蛋组覆盖矩阵（纯本地数据即可做；0x0312 孵化槽加"在孵"标记）
3. 体型/声音奖牌富化：pet_medals 规则 + 种群名录静态数据
4. 协议层增强：抓包缓冲 32MiB 对照、"3 秒停滞"断流恢复、IV exact 模式兼容

**第三批（需真实帧验证字段映射）**：
5. 我的家园：0x014A/0x0413/0x0414 快照+增量 → 居民/家具/产蛋窝可视化
6. 智能配窝：nest_egg_inference 推断引擎（§3.4 算法）+ planner UI
7. 炫彩花种：0x039D/258/338 帧 + flowerLevels 静态表导入 + 按天合并
8. 炫彩色卡：glass 信息帧 → card_id（底色×混色）矩阵

**第四批（大工程）**：
9. 产线收集：跨会话孵化统计（依赖蛋仓长期积累 + collection_accounts 本地部分）
10. 证据链闭环：egg_evidence 三级标注（本地推断 > 手改 > 云标——纯本地只做前两级）
11. 3D 宠物模型（蛋神用 Rust/WebGPU wasm 1.77MB + 云端模型 CDN——需评估本地化方案）

**明确不做**：交易市场、换蛋广场、赞赏、云账号、订阅、增量更新服务（分发服务）。
