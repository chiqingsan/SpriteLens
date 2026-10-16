# 竞品解剖报告（roco_helper 及同源工具）

> 历史文档：本报告写于项目仍名为 RocoPeek 时期，文中的「本项目/我们」
> 即现在的 SpriteLens；结论与实测数据保留原样，仅项目名已随迁移更新。

> 目的：回答"对标 roco_helper，它的架构/功能/UI 有什么值得学，我们能不能做得更好"。
> 方法：本机 roco_helper v3.9.0.exe 静态解剖（PE/字符串/SQLite 运行时残留）
> + 四个同源开源仓库源码通读。所有结论附证据。
>
> 素材位置（本机，可能被清理，可重新 clone）：
> - `本机下载的 roco_helper-v3.9.0.exe`（UPX 加壳发行版）
> - `本机解包目录`（已解包）
> - `用户数据目录的 roco_helper.sqlite`（真实运行时数据）
> - `AppData\Local\Temp\roco_research\`（roco-catcher / MITM-Server / Protocol-Parser / rocom-parse / 两个 rocom-helper）
> - `AppData\Local\Temp\rocom-helper-reference\`（innovationb1ue/rocom-helper，PvP 分析工具）

---

## 1. roco_helper v3.9.0 完整解剖

### 1.1 技术栈与形态（证据链）

| 层 | 结论 | 证据 |
|---|---|---|
| 桌面壳 | Qt（PyInstaller/Nuitka 类冻结，UPX 加壳） | 解包版 `QApplication`×18、`QWidget`×105、`qt.conf` |
| 主界面 | **本地 Web 服务**（浏览器访问） | 内嵌 `Content-Type`/`ETag`/`Cache-Control`/`text/html`/`gzip` |
| 实时推送 | **SSE**（Server-Sent Events） | `text/event-stream`、`EventSource`；roco-catcher 用 okhttp-sse 消费 |
| 持久化 | **SQLite**（单文件，按 uid 分表） | `AppData/Roaming/roco_helper/roco_helper.sqlite` 921KB |
| 抓包 | Npcap（Windows）/ BPF（mac、Docker） | README + 日志 `正在监听 \Device\NPF_{...}` |
| 跨平台 | Win 桌面 exe / mac app / Docker（amd64+arm64） | README 三方案表 |
| 版本 | v3.9.0，Company=Roco Helper | 文件版本资源 |

**架构一句话**：Qt 桌面壳（只做网卡选择/启停/端口配置）+ 内嵌 HTTP 服务器（静态前端 + REST API + SSE）
+ SQLite 持久化 + 被动抓包 TGCP 解析。桌面端只是"启动器"，主界面在浏览器。

### 1.2 抓包实现（日志实证）

```
[capture] TGCP SYN      flow=... head_ext=63 head_ext_hex=020300002710
[capture] TGCP ACK      ... encrypted=1 head_ext=27 body=16 key=ok   ← 从 ACK 取 AES key
[capture] TGCP AUTH_REQ / AUTH_RSP / BINGO
[capture] TGCP CSTOP    ... offset=5967 seq=543                      ← TCP 重组（offset/seq）
```

- 消息类型命名：SYN / ACK / AUTH_REQ / AUTH_RSP / BINGO / CSTOP —— 与我们协议层对应关系一致
  （0x1001 / 0x1002 / 0x2001 / 0x2002 / 0x6002 / 0x…STOP）。
- 有 TCP 重组（offset/seq 字段），支持 `ROCO_FILTER_HOST` 单 IP 过滤（解决单臂路由双份流量）。
- 支持 SOCKS5 方案（Docker 内 microsocks + Proxifier/Clash 把游戏连接转入），
  本质是**把"抓包点"从本机网卡挪到代理链路**，规避本机抓包封号风险。

### 1.3 数据模型（SQLite 实测，最有价值的部分）

**按 UID 分表**——每个账号一套业务表，自动建表：

| 表 | 行数(实测) | 内容 | 对应 spritelens 现状 |
|---|---|---|---|
| `pet_info_{uid}` | 107 | 宠物全量 JSON（conf_id/name/skill/attribute_info/…） | 会话内内存快照 |
| `bag_info_{uid}` | 296 | 背包道具（按 type 分组 17 类） | 无 |
| `handbook_{uid}` | 305 | 图鉴记录 | 无 |
| `box_{uid}` | 40 | 盒子（mark_type/vacancy_num/box_name/lock） | 无 |
| `pet_history_{uid}` | 0 | 捕捉/获取历史（含 catch_time） | 无 |
| `throw_history_{uid}` | 0 | 丢球历史（ball_id/throw_time） | 无 |
| `home_pet_{uid}` / `room_plane_{uid}` | 0 | 家园宠物/房间平面图 | 无 |
| `gather_spot` / `gather_collection` | 0 | 资源点 + 采集记录 | 无 |
| `map_paint` | 0 | 地图涂绘（用户标记） | 无 |

**跨账号表**：

| 表 | 内容 | 启示 |
|---|---|---|
| `users` | uid/name/avatar/flow_id/**aes_key**/last_seen | **多账号管理 + 密钥记忆**（换号免重新抓 key） |
| `web_storage` | key/value/updated_at，前端状态 | **前端状态回写后端**：主题(dark)、地图视角、筛选器配置全持久化 |
| `exchange_auth` / `special_feature_github_credential` / `machine_identity_secure` | 授权/许可/机器指纹 | 商业化痕迹（它是免费+Pro 模式？） |

**注意**：它给宠物保存的是**原始 protobuf JSON 全量**（`data` 列），不是裁剪过的行——
所以它的表格能展示六维、声音、体重、技能等全部字段，前端按需取。
我们在 wire 层同样能拿到这些字段，只是没有持久化和名字映射。

### 1.4 UI 设计（截图实证）

**桌面壳**（screenshots/img1）：极简三区
```
流量解析: [网卡下拉 ▾] [刷新]   [停止解析] 运行中
Web 服务: 绑定地址 [127.0.0.1]  端口 [4939] [应用]
          [        打开 Web 界面        ]
```
就是一个"启动器"——所有数据展示都在浏览器。

**Web 主界面**（img2）——左筛选器面板 + 右表格：
```
┌─────────────┬────────────────────────────────────────────────┐
│ 筛选        │ 宠物 │位置│系别│蛋组│形态│性格│特长│奖牌│声音│体重│身高│六维 │
│ 等级 1-60   │ 🐱魔力猫 33 │1盒1行2列│草│动物组│-│踏实│亲密│-│0│113.83│1.76m│生命190↑速度50…│
│ 声音 0%-100%│ 🐦岚鸟 41   │-│翼│天空组│…│悠闲│无│星月交辉│30│32.31│2.04m│生命176 速度104…│
│ 体重 0-100% │ ...                                             │
│ 身高 0-100% │                                                 │
│ 异色/炫彩   │                                                 │
│ 性别 ALL ♂♀ │                                                 │
│ 捕捉时间范围│                                                 │
│ 系别 OR|AND │                      共 52 只  < 1 2 3 4 5 > 12条/页│
│ 性格/个体值 │                                                 │
│ 血脉/蛋组/球│                                                 │
│ 天赋阶/技能 │                                                 │
│ 奖牌/盒子…  │                                                 │
└─────────────┴────────────────────────────────────────────────┘
```

值得学的交互细节：
1. **行内信息密度极高**：头像+等级+名字+系别徽章+盒子位置+六维属性**全在表格一行内**，
   不用点开详情就能比较。六维带升/降箭头（性格加成方向）。
2. **滑块范围过滤**：等级/声音/体重/身高四组双端滑块 + 预设快捷（ALL/小不点/大块头）。
3. **游戏内不可见的隐藏属性直接可筛**：声音 0-100%（"粗嗓门/婉转声"）、体重/身高百分比。
4. **OR/AND 组合器**：系别、个体值支持多选 + OR/AND 切换（复杂筛选的表达力）。
5. **20+ 筛选维度**：血脉/蛋组/季节/球种/捕捉方式/盒子/天赋阶/技能/奖牌/伙伴标记/玻璃粒子…
6. **暗色主题**（默认 dark）。
7. **分页 + 排序**（12 条/页可调）。

**孵蛋管理器**（img3）——**性格×蛋组覆盖矩阵**（最有创意的 UI）：
```
        │巨灵组│两栖组│昆虫组│天空组│动物组│妖精组│植物组│拟人组│软体组│大地组│
 大胆   │  -   │  -   │  -   │  -   │  -   │  -   │🐦1   │  -   │  -   │  -   │
+物攻-物防
 固执   │  -   │  -   │  -   │  -   │🐦1   │  -   │  -   │  -   │  -   │  -   │
+物攻-魔攻
 勇敢   │  -   │  -   │  -   │  -   │🐦1 ♀1│  -   │  -   │  -   │      │      │
…
```
- 行=性格（含加成说明），列=蛋组，格子=该组合下拥有的宠物图标+性别+数量徽章。
- 直接回答"我想孵出 X 性格、该找哪个蛋组的宠"——**二维矩阵代替列表，一眼定位缺口**。
- 侧栏还有"高亮 OFF/♂/♀/炫彩"过滤 + 性格多选（只控制行显示，不影响筛范围）。

### 1.5 API 生态（让 99★ 变成生态位的关键）

roco-catcher（Android 应用，第三方开发）消费的接口：

```
GET /api/users           → [{uid, name, avatar}]
GET /api/events?uid=...  → SSE 事件流（event: pet_info.catch / throw_ball）
```

- 助手只负责"解析+存储+广播"，**第三方可以基于 API 长出手机端/小程序/机器人**。
- roco-catcher 在此之上做了：捕获统计、实时速率（近 1 分钟滑动窗口 + 平均）、
  30 分钟速率折线图、按任务目标的多阶段告警（预热 60s→确认 30s→提醒）、
  前台服务 + 3 通知渠道 + 状态持久化可恢复。
- README 还挂了 ROCO Wiki、洛克图鉴等友链——**开放的 API 把工具变成了平台**。

---

## 2. 其他同源竞品的架构参照点

### 2.1 innovationb1ue/rocom-helper（38★，PvP 实时战斗分析，Python FastAPI + React）

**对战分析的最强工程参照**（我们规划中的 M4/M5 直接对标）：

- **分层 + 架构测试锁死依赖**：`capture → protocol → analysis → api → web` 单向；
  `pytest tests/test_architecture.py` + `scripts/check_architecture.py` 强制无循环/无反向依赖。
- **纯同步核心 + 三入口共用**：`BattleProcessor` 纯同步，实时 / 无头回放 / API 回放三条路径
  共用同一处理管线，杜绝双份解析语义漂移。
- **状态投影器**（`state_projector.py`）：战斗结算包到达时，先投影"buff/能量/换宠已生效
  但 HP 未扣"的中间态，再算伤害预测——**时序正确性**的工程解法。
- **四阶段伤害 hook 管线**（pre_power → post_base → pre_final → post_calc）+
  独立生命周期 hooks（`hook_registry`：7 个触发时机、priority/expires_round、
  建议信号回灌战术评分，如 `avoid_skill` 使高耗技能 ×0.5）。
- **预测可解释性全链路**：每条伤害预测带 min/max/expected + accuracy_flags +
  confidence + missing_reasons，一直传到 UI 的 Tooltip；回放对账脚本反哺
  `damage_calibration.json`。
- **对手信息兜底链**：protocol → used → pool → `popular_skills.json`（社区预设，前端可编辑），
  解决 PvP 对手数据不对称。
- **静态数据管线**：游戏 pak 解包 → `scripts/decode_bin.py` → `import_bin_data.py` →
  `data/game/*.json`（pet_species 1015 物种 / skill_map 1378 技能 / type_chart 克制矩阵 /
  buff_map 1925 效果定义 / proto_schema 等），带 `data_manifest.json` 版本标记。
- **回放系统**：抓包即落盘一包一文件；`replay_service`（推 WS 带 delay）/ `replay_runner`（无头
  CLI 产出逐回合快照）/ `replay_messages`（共用消息构造）。**实时与回放 WS 消息契约一致**。
- **UI（React + antd + Zustand）**：单页决策面板按"当下要做什么"排序（连接→回合→双方阵容→
  战术推荐→我方技能伤害→对手技能→特性→建议→hook 分析→总结→事件日志）；
  战术面板 = 候选行动排序 + 评分进度条 + 分类 tag + 置信度/风险 + "对手最可能行动+概率%"；
  事件上限 500 条防内存膨胀；历史页**可行动空态**（诊断条告诉用户缺哪一步）。

### 2.2 whoisnian/rocom-parse + rocom-capture（Go）

- **pak 解包工具链**：CUE4Parse 全量导出 json/png/lua/bin →
  `gen.sh` 生成名称表/图标 webp/Go 结构体/进化链 `chains.json`，
  **生成物不进仓库**，消费方构建时生成。这是"静态数据从哪来"的标准答案。
- 协议层包化：`gcp`（分帧/密钥/AES）、`capture`（TCP 重组 + pcap 回放）、`pbdesc`（运行时反射）——
  与我们 protocol/capture 分层思路一致，互相印证。
- rocom-capture 提供实时地图 + 宠物列表 + 捕获事件（46★）。

### 2.3 Roco-Kingdom-MITM-Server（Python + WinDivert）

- 定位：**在链路内**的 MITM 代理 + Web 控制台（可注入/改写，风险等级不同）。
- WinDivert 按 PID 重定向游戏出向 8195 到本地代理；`SessionState` 收拢
  cipher / seq 偏移 / 按 opcode 的 counter 基线（注入必需）。
- 架构亮点：`web/event_bus.py`（ring buffer 历史回放 + 订阅队列丢老保新背压）；
  `codec/opcode_registry.py` **多源优先级加载 + mtime 热重载**（1626 opcode）；
  过滤器 DSL（`dir=/opcode=/key~val`）+ 本地 MCP 工具接口。
- 对我们：`CaptureSource` 的 MITM 实现可直接复用其分层（Cipher / Frame / InternalHeader /
  wire_builder 各司其职；socket 直读天然有序、免 TCP 重组）——印证了我们把重组放在接入层的设计。

### 2.4 Roco-Kingdom-Protocol-Parser（62★，Python）

- **装饰器注册表**：`@_register_opcode(0x1324, "action_resolve")` 把
  opcode→提取函数→kind→文本格式化器分层注册，新增协议支持零散改动。
- **语义状态机 + 叙事输出**：ProtocolPhase（等待对位→等待名单→进行中），
  输出"首发对位建立: A vs B""玩家选择动作: …"这类人话句子——UI 可直接消费结构化 summary。
- 数据打包：`rkpp_data.sqlite`（msgpack blob，entity 4.2 万行）替代散 JSON。
- 人类可读文本 + CSV/NDJSON 双轨输出；离线 pcap 回放让解析逻辑可测试。

---

## 3. 我们（spritelens）的对照现状

| 维度 | roco_helper | spritelens 现状 | 差距 |
|---|---|---|---|
| 协议层 | TGCP 帧解析（自研） | GCP 21B 头 + 双加密变体自适应 + schema 双路降级 + 1627 opcode | **我们更强**（覆盖广、有降级） |
| 架构 | 未公开（单体） | 单向分层 + 纯函数协议层 + 可插拔接入层 + 录制回放 | **我们更干净** |
| 持久化 | SQLite 分表，重启不丢，多账号 | 内存快照，重启即失 | **重大差距** |
| 静态数据 | 内建（名称/技能/图鉴/蛋组表） | 无（wire 层只有字段号） | **重大差距** |
| 功能覆盖 | 宠物(极深)+图鉴+孵蛋+盒子+资源点 | 宠物(基础列表/搜索) | 单模块深度差距大 |
| UI | Web（筛选器矩阵+高密度表格），可远程/手机 | PyQt6 三页（监听/事件流/宠物表） | 表达力差距 |
| 对外 API | REST + SSE，已有 Android 客户端生态 | 无 | 生态位差距 |
| 部署 | Win/mac/Docker/SOCKS5 | Win 本机 Npcap | 场景覆盖差距 |
| 差异化机会 | 不做 PVP/战斗/全业务 | 全业务数据面 + 对战解包（规划中） | **主战场** |

---

## 4. 值得学习清单（按优先级）

### 架构层

1. **持久化 + 多账号**：`{domain}_{uid}` 分表思路可用，但建议**统一 schema + uid 列**
   （避免 N 账号 × M 业务 = 表爆炸）；`users` 表存 aes_key 实现换号免抓 key。
2. **前端状态回写**（web_storage 模式）：筛选器/主题/视角持久化，用户体验"回来还在"。
3. **对外 API（REST + SSE）**：开放 `/api/users`、`/api/events` 级别的接口，
   第三方可长出手机端/机器人；SSE 比 WebSocket 更简单（单向广播够用）。
4. **静态数据生成管线**：pak 解包（CUE4Parse）→ gen_* → 结构化 JSON，
   生成物不进仓库；短期可先用社区 JSON（innovationb1ue 的 `data/game/*.json` 可直接引用）。
5. **架构测试**：仿 `test_architecture.py` 用测试锁死我们的分层（ui → services → domain/protocol/capture）。
6. **MITM 接入层**：复用 RKMS 的分层，实现 `CaptureSource` 第二实现（风险等级需用户评估）。
7. **战斗分析工程化**（若做 M4/M5）：四阶段 hook 管线 + 状态投影器 + 预测可解释性 +
   回放对账；这是从"能看"到"可信"的关键。

### 功能层

| 功能 | 来源 | 我们的可行性 |
|---|---|---|
| **孵蛋覆盖矩阵**（性格×蛋组） | roco_helper img3 | 高（数据都有，纯 UI） |
| **全维度筛选**（20+ 维、OR/AND、滑块） | roco_helper img2 | 高（需静态名字映射） |
| **六维属性行内展示 + 升降箭头** | roco_helper | 高（attribute_info 已在 wire 层） |
| **盒子可视化**（位置/命名/空位/锁） | roco_helper | 高 |
| **捕捉/丢球历史** | roco_helper pet_history/throw_history | 高（事件流已有） |
| **资源点采集追踪** | roco_helper gather_spot | 中（需地图静态数据） |
| **实时捕获概率**（catch_prob） | 我们的 M6 规划 | 高（schema 有字段） |
| **战斗实时分析**（伤害预测/建议） | innovationb1ue | 中（最高价值，需一次性完整录制验证） |
| **回放验证体系** | innovationb1ue / RKPP | 高（我们已有 recording/replay 基础） |
| **捕获统计 + 速率监控 + 告警** | roco-catcher | 高（纯事件流消费） |
| **数据导出/分享** | 空白区 | 高（差异化） |

### UI 层

1. **左筛选器 + 右高密度表格**的分栏范式（筛选器可折叠分组）。
2. **二维矩阵视图**（矩阵回答二维问题，比列表直观一个数量级）。
3. **决策导向的卡片排序**（战斗页按"当下要做什么"排，而非按数据来源堆）。
4. **可行动空态**：告诉用户"缺哪一步"而不是空白表（我们已有类似排障文案，可产品化）。
5. **暗色主题**。
6. **桌面壳极简**：控制面板只做启停/配置，数据展示分流到浏览器（可远程访问）。

---

## 5. "能不能做得更好"——结论与建议路径

**结论：能，但主战场不在复刻它的宠物深度，而在三个它没有的东西**：
① 全业务数据面（背包/任务/邮件/商店/社交——竞品全空白）；
② 对战复盘与分析（innovationb1ue 证明了价值，但只有 PVP 辅助且无持久化生态）；
③ 数据资产化（持久化+导出+分享+API，让它从"工具"变成"平台"）。

**但要先补齐三个短板，否则功能越多越像 Demo**：

| 优先级 | 动作 | 理由 |
|---|---|---|
| **P0** | 宠物仓库升级 **SQLite 持久化**（全字段 JSON 存储 + 多账号 uid） | "越用越有价值"的前提；捕捉历史/战报/统计全靠它 |
| **P0** | **静态数据导入**（先引社区 JSON：名称/技能/图鉴/蛋组/克制表） | 没有名字映射，筛选器/矩阵/战斗分析都无法显示人话 |
| **P0** | 宠物页 **全字段展示**（六维/性格名/系别/蛋组/体重/身高/声音） | 我们 wire 层已有数据，只差映射与表格列 |
| **P1** | **对外 API（REST + SSE）** + 宠物筛选器升级 | 生态位杠杆（roco-catcher 已证明第三方会因为 API 而来） |
| **P1** | **孵蛋覆盖矩阵** | 复刻它的亮点 UI，成本低、辨识度高 |
| **P1** | 一次性**完整业务录制**（登录→开面板→PVE→抓宠→PVP） | 解锁 V1.5→V2 的全部事件域功能（见 FEATURE_MODULES.md） |
| **P2** | 对战观测/战报复盘（M4/M5） | 最大差异化，参照 innovationb1ue 的工程化深度 |
| **P2** | Docker/SOCKS5 部署形态 | 覆盖软路由/NAS/手机场景，规避本机抓包风险 |

**一个需要决策的战略分叉：UI 技术栈**
- 竞品（roco_helper / rocom-capture / innovationb1ue）**全部是 Web UI**——因为筛选器矩阵、
  滑块、图表、分页表格用 Web 生态做起来快一个数量级，且天然可远程/手机访问、天然有 API。
- 我们现为 PyQt6：优点是单进程、无端口、离线安全；缺点是复杂交互组件成本高。
- 折中路线：**保留 PyQt 桌面壳（监听控制/系统页）+ 内嵌 FastAPI + pywebview（系统 WebView2）
  承载数据页**——兼得两者，且 API 与 UI 同一套服务。此项建议用户决策后再动工。
  （2026-10-10 修正：此处原写"浏览器/QWebEngineView"；QWebEngineView 自带 Chromium、
  wheel 实测 **132.4 MB**，应改用 pywebview——详见 `docs/ARCHITECTURE_DECISION.md` §3。）

---

## 附：证据索引

| 结论 | 证据位置 |
|---|---|
| roco_helper 是 Qt 壳 + Web UI | 解包版字符串 `QApplication`/`QWidget`/`qt.conf`；内嵌 HTTP 头；img1/img2 截图 |
| SSE + REST API 生态 | 解包版 `text/event-stream`/`EventSource`；roco-catcher `data/HelperApi.kt`、`HelperHttp.kt` |
| SQLite 数据模型 | `AppData/Roaming/roco_helper/roco_helper.sqlite` 表结构（见 1.3） |
| 抓包消息类型与重组 | `AppData/Roaming/roco_helper/roco_helper.log` |
| 部署形态 | h3110w0r1d-y/rocom-helper README + docker-compose*.yml |
| 战斗分析工程化 | innovationb1ue/rocom-helper：`docs/architecture.md`、`src/analysis/*`、`web/src/components/*` |
| pak 解包 → 静态数据 | whoisnian/rocom-parse README + `scripts/gen.sh` 说明 |
| MITM 分层与 SessionState | Roco-Kingdom-MITM-Server：`src/roco_mitm/proxy/*`、`web/event_bus.py` |
| opcode 注册表 + 叙事输出 | Roco-Kingdom-Protocol-Parser：`rkpp_proto_battle.py`、`rkpp_reporter.py` |
