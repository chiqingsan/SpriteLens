# 协议观察笔记（排障与未解事项）

本文记录「已确认可用」之外的观察，供未来排障与版本变更时参考。
主协议结论见 `ARCHITECTURE.md`，此处只记边角信息与教训。

## 场景 actor 归属字段（2026-11-09 修订）

状态：已接入 `NavigationScene` 快照（`creator_id` 每行一个、`self_actor_id` 与 `player_actor_ids` 在顶层），Meow 侧据此排除非本人奇遇。

- 判据是 `npc_base.create_avatar_id`（field 19，uint64），值为创建者 avatar 的 `actor_id`；同一节点的 `create_avatar_name`（field 34）就是游戏界面上的「拥有者 XXX」。实测 `eventlog_20261109_p10` 中 actor `9230175863813782801`（cfg 29401、带 293015）的 `create_avatar_name` 为「持青伞」、`create_avatar_id` 为 `8079477309776592896`，与当时截图里的「拥有者 持青伞」一致。
- **`ActorInfo_Base.owner_id`（field 6）不能判归属**：同一批数据里它恒为当前账号自己的 `8077254359191126016`（127 条 actor 中 117 条，含上面那个别人创建的奇遇），语义更接近位面/场景归属。2026-11-08 曾按它做过滤，因此完全没有效果。
- 自身身份取 `self_info.avatar.base.actor_id`：`0x0152`（`ZoneEnterSceneRsp`，field 11）与 `0x015C`（`ZoneSceneTeleportNotify`，field 21）都携带。两者都是大包，ext 通道常被 `decoded_omitted` 清空，但 `ExtEventHub` 在校验前已把它交给 `NavigationScene`，所以快照可用。
- 自身身份未知时的兜底：快照的 `player_actor_ids` 列出场景里可见的其他玩家 avatar（`ActorInfo.no=12` 的 `actor_id`），若某奇遇的 `creator_id` 命中该集合，即可判定是别人的。
- 失败分支：`creator_id` 为 0 或缺失、自身身份未知且 `creator_id` 不在可见玩家集合、或两字段都缺失时都不作判断，退回原行为（走过去、到达后没有交互选项再拉黑）。

## 蛋仓来源字段（2026-10-28）

状态：已接入协议提取、账号内持久化与详情展示；字段位置依据当前 `PetEggBrief` schema，
合成数据链路已验证，真实游戏下发覆盖率和 `src` 枚举含义待核对。

| PetEggBrief 字段号 | 协议字段 | 当前用途 |
|---|---|---|
| 10 | `src` | 沿用内部 `category`，保存原始来源编号，不猜测获取方式 |
| 13 / 15 | `from_player_name` / `from_player_uin` | 来源玩家名字 / UID |
| 14 / 16 | `from_pet_name` / `from_pet_gid` | 来源精灵昵称 / 实例 ID，不作为物种编号 |

名字按 UTF-8 解码；两个 ID 在 schema 中均为 uint32，JSON 数值可精确表示。
四个来源字段写入现有 `eggs.detail_json`，不改表；旧记录缺失时读为空名与 0，页面“其他信息”只展示有值的来源字段。
已有 `0x0243` 家园拾蛋观测标记作为获取方式展示；手动小窝类型不改变这些游戏来源字段。
上述字段不包含地图、坐标或窝 ID，不能据此还原具体拾取地点，也不自动判定学院窝。

收蛋现场关联：同连接 `0x0137` 的目标 actor 能在当前快照里解析为场景蛋即为收蛋请求。
`option_id` 实测不固定（普通窝出现过 830000165/830000166/830000217，学院窝出现过
830000009），不作为判据。通过 `furniture_guid` 联查小窝、窝内唯一母本和服务器配对候选。
仅将 3 秒内的 `0x0243`、`reward_source=13`、`flow_reason=223` 单枚蛋奖励与之关联；
通用奖励本身不证明家园来源。奖励帧没有目标 ID，连续收蛋时按最近一次请求配对。
切场景/断连、历史或其他连接快照均不补猜关联。
关联作为 `detail_json.pickup` 保存，后续蛋仓更新保留原记录；手动窝型优先于自动标签。
配对有待同步时保留提示，候选不等于实际父本。学院窝必定继承母本性格（用户确认的游戏规则），
默认标签采用收取前同账号已采集的母本性格并持久保存；缺失时不推断，手动性格优先。

历史补录（`tools/backfill_egg_origins.py`）：按 ts 归并 `eventlog/` 分片后回放同一套关联规则，
只把缺失的 `detail_json.pickup` 合并进已有蛋记录，已有来源不覆盖、其他字段不动。
日志里缺少 `0x0137` 请求帧（请求未被采集或奖励超出 3 秒窗口）的蛋无法补录，
工具会统计“收蛋奖励未匹配到请求帧”的次数。写库前需退出应用，避免在线整仓写回覆盖补录。

## 蛋仓声音遗传（2026-10-28）

状态：已按用户提供的游戏规则实现服务端推算与前端展示；奖牌阈值沿用 `domain/pet_marks.py`
的实测规则，未独立反编译核对。

- 蛋的声音 = 母本与父本声音取平均并向下取整（Python `//`，负奇数向 −∞ 取整）。
- 奖牌判定复用 `voice_mark`：`−100..−96` 为粗嗓门、`96..100` 为婉转声；另 `100` 记满分、
  `−100` 记底分。父母（母本 + 那个父本）都命中同一组标签才自动打标。
- 父本可能只有一个也可能是一批候选：逐个候选算出的蛋声音或标签不一致时，只展示声音区间
  （最小值 ~ 最大值），不自动打任何声音标签，也不臆测实际父本；人工声音标签始终优先。

蛋仓载荷新增字段：`pickup.mother`、`pickup.fathers[]` 各带 `icon_url`（物种头像，
`/static/pet-media/...`，未知物种为空串），行级 `voice_prediction` 为
`{mother_voice, voice_db|null, range[[min, max]], tags[], unanimous, father_voices[{instance_id, voice}]}`；
无收取来源或亲代声音缺失时整段为 `null`。声音 dB 只来自宠物快照，不写回数据库。

## 伙伴标记字段确认（PetData 78，2026-10-24）

`PetData` 的伙伴标记是字段 78（`partner_mark`，无符号整数，0=无标记），由四条独立证据交叉确认：

1. 本机真实事件日志 `%LOCALAPPDATA%\SpriteLens\eventlog\eventlog_2026*.jsonl`（10-10 至 10-24 十个会话）：`partner_mark` 节点出现在 2,097 条消息、27,044 条 `PetData` 记录、4,268 个 gid 上，取值只有 `0/1/3/4/5/6/7/14/15`，是有限枚举而不是任意数值。
2. 洛克助手（小洛克精灵工具箱 1.0.0）的 .NET 抓包服务反编译 `roco_capture_service.cs`：`Put(dictionary, "partner_mark", Proto.UInt32(fields, 78));`，与 `wear_medal_conf_id`(73)、`medal_complete_cnt`(74)、`speciality_id`(82) 在同一解码块。
3. 同族工具的采集器 `roco_collector.py`（本地解包目录 `<ROCO_RESOURCES>`）：`78: 'partner_mark'`；`archive\dumps\d_mod.txt`：`const[139] = 'partner_mark'`；协议逆向笔记：`| 78 | partner_mark | 82 | speciality_id |`。
4. 社区 schema 库 `data/schemas/messages/all.json`：`"78": {"name": "partner_mark", "type": "enum"}`。

易混字段：94 `activity_partner_pet_data`（活动搭档子消息，不是标记 ID）、80 `custom_medal_conf_id`、73/74 奖牌相关。

本机库 `pets.partner_mark` 在 2026-10-24 之前全为 0，是「该字段此前未实现、加列时默认填 0」的结果，**不能反推游戏里没有标记**。按上述流量以 gid 取最新值回填后：1,308 只展示宠物中 638 只有标记（分布 `0:670、1:479、3:2、4:34、5:8、6:12、7:2、14:4、15:97`）；另有 81 个 `is_trial_pet`/`is_mirror_pet` 行不在流量里，保持 0 且本就不参与展示。

口径：同一 gid 在不同时刻出现过 `0 → X` 或 `X → 0` 共 15 例（游戏内可更换/摘除标记），按最新观测值处理，不跨会话合并；8 号标记在当前账号流量里未出现，但资源与映射保留，未列出的 ID 一律不渲染。

### 伙伴标记实时更新（2026-10-29）

游戏内改标记不会下发完整 `PetData`，只有一条专用回执，因此此前界面要等重开宠物背包（`0x1346`）才刷新：

```
c2s 0x0402 ZoneUpdatePetCollectTagReq
    collection_info{3: partner_mark, 1: pet_gid}, 2: 1
s2c 0x0403 ZoneUpdatePetCollectTagRsp（34 字节）
    ret_info{1: ret_code, 4: goods_change_info{1: changes{...}, 2: pet_data_vesion, 3: bag_data_vesion}}
        changes 展平后：{1: type=39, 2: op=2, 3: num=新标记值, 5: id=0, 14: gid, 15: coro_id}
```

实测样本（`eventlog_20261029*.jsonl`，17:24–17:25 三次）：`partner_mark=4` 对应 `type=39, num=4, gid=100781 / 100592 / 100769`；回放该日全部 76,992 条事件后三个 gid 的标记均变为 4（修复前一直是 0）。`type=39` 是伙伴标记资源类型，`num` 即标记 ID，与 c2s 请求值一致。

实现：[pet_partner_marks.py](../spritelens/domain/pet_partner_marks.py) 的 `extract_partner_marks` 按字段号取值，兼容展平与嵌套容器两种 repeated 形状；`PetRepository.handle_packet` 把新值合并到已观测宠物，`_version += 1` 并落库，界面靠既有 `pets_version` 推送自动刷新。未观测到的 gid 不凭空插入（缺少 `conf_id`，等分页包补齐）。

未取证部分：摘除标记（`partner_mark=0`）的真实回执结构未采集，当前按「`num` 缺失视为 0」处理；`op` 字段语义未确认，不据此判断增删。

## 双开重启续解（M01，2026-10-24）

现场两条连接均有原始流，旧版重启后只剩其中一条可解析。旧装配将 latest.key 作为全局预置，而两条连接实际使用不同密钥。
只读扫描已有录制恢复两条 ACK 密钥后，在临时目录按连接保存并重放出问题的那段录制：两条连接分别成功解析 239/240 与 25/26 帧，缺密钥均为 0；各余 1 帧拆分失败，不能据此宣称全部协议已覆盖。
新装配只恢复对应连接的密钥，身份未确认不路由业务事件。修复不自动补齐旧版漏存的密钥，不自动修改历史数据库中可能已混入的数据；完整现场双开、重启及单边重连验收仍待用户方便时进行。

## 附近场景观察（C02，2026-10-23）

当前有原始场景观察快照与 C03 不完整观察列表，不宣称全量附近精灵支持。现有本机事件已核对 NPC 基础/测量字段和实体进入/离开：`0x0413` 比 `0x0414` 多一层包装，必须分开提取动作。客户端移动目标坐标不能当作服务器确认位置，单位不预设为厘米；未知字段保留 null，未知增量计数，不猜完整性。战斗信号仅作保守失效，现场恢复语义仍待验证。字段路径、证据范围、接口与剩余项维护在 [C02 场景观察规格](SCENE_OBSERVATIONS.md)。

附近载荷的 `colorful`（2026-10-28）：场景配置字段 14 的 `mutation` 第 4 位（`& 8`）是游戏内炫彩外观，与背包 `is_colorful`、`breeder_library` 同口径；现场样本为 16:38:55 一只乖乖鹄 `mutation=8`、同时刻 7 只同类为 0，场景与大地图数据一致。`nearby.py` 据此下发 `colorful`，前端在雷达/地图/列表三处只做独立标识，不参与 `attention`（本地参考线推的奖牌潜力）判定，也不把大地图条目与场景实体按 ID 直接关联（两者 ID 不同、坐标差约 12.5 米，需按物种/拥有者/变异/外观值匹配）。

## 家园场景复核（2026-10-16）

- `0x014A` 是通用场景进入应答；重复 `field7` 是 `other_actors`，不是房间。首个 actor 的 `field1=actor_detail_type=10` 不能解释成“房间等级10”。家园元数据是顶层 `field22`，主人 UID 为其 `field2`，房间等级为其 `field5`。
- 蛋神经 `0x0152.field3`、`0x015C.field12` 记录场景资源，校验主人 UID 并排除30002。既有日志中30002虽带家园布局/配对，却没有室内的11居民；10003没有home_info。二者均不能覆盖本账号室内家园缓存。
- 当前正确嵌套解析对本机三份字段树读出房间等级5、11居民、81家具（含10普通窝、1学院窝）、6条母本配对；11居民的实例均匹配同账号宠物库。这是样本观察，不能成为固定数量断言或完整性声明。
- `0x0413/0x0414` 同样用于普通场景，只有活动家园中的相关变化才能更新家园。`0x0137/0x0243` 用于拾蛋请求/响应关联，不能解释为拉取入住成员。
- 本地JSONL的bytes字段有损，字段树核对不能替代原始字节回放；实际增量变体和游戏繁育概率仍待验证。修复规格见 [家园开发计划](HOME_IMPLEMENTATION_PLAN.md)，当前状态见 ROADMAP 的 F04-U2。

## 已确认（2026-10-09 端到端验证）

- 全部业务数据（宠物/背包/图鉴等）由服务器在**登录进世界时经 8195 主动推送**；
  实测单会话 s2c 280 帧解码、160 只宠物提取成功。0x1345 分页请求已废弃。
- 宠物响应固定 3 帧（约 46KB / 43KB / 6KB），对应 `ZoneGetPetInfoByPageRsp` 多页连续推送；
  帧结构与页面数在相邻版本间稳定（10-07 与 10-09 两次实测 payload 尺寸一致）。
- **玩家身份（账号 uid）**：两条已核验路径，登录响应 `ZoneLoginRsp`(0x0102) 的
  `player_info.brief_info`（`uin` / `name` / `role_level`，早于进场景），以及
  `ZoneEnterSceneRsp`(0x0152) 的 `self_info.avatar.base.logic_id`
  （实测 101384922，与外部工具记录的账号一致），同节点含 `name`（角色名）与
  `lv`（等级）。
  - 账号卡片使用游戏名片头像：`player_info.brief_info.additional_data.card_brief_info.card_icon_selected`。
    本机 2026-10-20 登录包实测值为 `1001017`（游戏配置名「初心·喵喵」），对应专用资源
    `img_1022`，与精灵图鉴喵喵 `3001/icon.png` 不同。头像按原始 ID 映射到
    `/static/account-avatars/{id}.png`，由本地服务按 ID 从映射中的云端来源按需获取，并原样缓存到
    用户数据目录 `account-avatar-cache/`；仓库只保留来源、配置版本和资源 ID 映射在同目录
    `manifest.json`，通过 `tools/import_account_avatars.py` 同步。缓存原图保留透明区域，不裁剪转码。
    `plat_avatar_url`（字段 9，bytes）是 QQ/平台头像，不能作为游戏头像；没有已知游戏头像映射
    时显示应用 Logo。schema 1 保存最终的游戏头像 URL，缺头像的同账号场景/接续身份保留
    已观察值，切号不复用。
  - **必须走已核验路径**：`ZoneSceneClientEnterSceneFinishNtyAck` 的
    `other_actors[*].npc.base.logic_id` 是 NPC 编号（实测「护主犬」
    435444924297510922），误取会串数据；不能递归搜索所有玩家结构。
  - 时序：身份包先于宠物推送到达（同一会话行号 853 vs 933），
    因此「先认身份、后归属宠物」是安全的（见 `domain/identity.py`）。
- **箱位协议**：登录响应/进场景的 `player_info.pet_info`（或增量
  `ret_info.goods_change_info.changes`）内含 `PetBox`（字段 1=箱号、
  字段 3=30 槽位 gid 列表、字段 5=箱名，0 为空格、gid 唯一）与
  `PetTeamInfo`（字段 4==1 为普通队伍列表、字段 1=当前队下标、每队 6 格；
  字段 6==1 或成员超 6 的非普通队伍跳过）。`PetBoxPetChange`（字段 1=gid、
  2=去向、3=箱号、4=槽位）是移动增量；实测「1 队 1 格 / 2 队 4 格 /
  3 队 2 格」的行序证伪了列表顺序假设。

- **会话接续的序号语义**：重启接续时旧的 `server_sequence` 只是「上次见到的
  位置」，不能当作接头依据——新连接的 s2c 序号会重置，用旧值比较会误判。
  实现取「首次 s2c 帧序号必须严格大于旧检查点」判定接续；SYN/ACK 到达即
  失效旧身份。这是本机行为约定，不是协议字段语义（详见
  `docs/archive/SESSION_RESUME_VERIFICATION.md`）。

## 未解事项（已知存在、暂不影响主功能）

### 精灵获得奖牌集合（2026-10-14）

登录ZoneLoginRsp.CliPetMedalInfo.collection按PetMedalRecord→buckets→detail_list读取奖牌配置ID与obtain_pet_gid；wear_pet_gid仅表示佩戴者，不改变获得归属。两批本机录制核验见[详情记录](reviews/PET_DETAIL_VERIFICATION_2026-10-14.md)，包含多奖牌个体和获得者/佩戴者不同的记录。PetRepository保存每个体的已确认集合，SQLite v10区分NULL未知与[]已确认空集合。

PetMedal增量尚无真实样本，收到时失效涉及集合等待登录重采；不猜op删除/转移语义。PetData.free_medal_conf_ids等候选字段未在本轮录制出现，不作为完整集合。体型与声音阈值只能作参考标记。

### 获取方式与日期（2026-10-14 接入）

PetData字段67=`catch_way`，字段32=`add_time`（Unix秒）。蛋神1.2.0的
`web_runtime._pet`映射为1捕捉、2互访捕捉、3孵化、4花种、5传说、6守护地；
`pet_timestamps.game_acquired_at`读取游戏add_time/catch_time，不使用本机落库日期。
本项目接入已存在的字段32，日期条件为近1/3/7天的滚动时间窗；仍显示“捕获日期”，
其数据语义为游戏获得时间，含孵化等获得方式。未知时间0不满足日期条件，未知获取ID
以“方式 #ID”显示。全局AND/OR统一组合这些条件；OR下可由其他已选条件命中。
SQLite v9追加两列，旧行保留并默认为未知；须再次收到游戏宠物数据才能补齐。
简略更新缺少获得信息时保留已采集值，切号仍清除账号快照；首次落库时间不作回填。
当前 schema 1 直接包含获得方式和时间字段；回归覆盖字段读写、简略更新保留已知信息及未知日期。

### 特性名称映射（2026-10-13 静态核对）

界面“特性”对应当前解析的 `Pet.speciality_id`（协议字段82）。蛋神助手1.2.0的
`desktop_catalog.speciality()` 按 `speciality_id` / `specialityId` 查询独立的
`SPECIALITIES` 常量表：101=奇袭、402=同乘、1001=爱分享；104/105/106均为灵巧。
`assets/catalog/petFeatures.json` 是按物种索引的战斗特征，不作为此字段的名称表。
已裁剪13个ID和名称至 `data/static/specialities.json`，来源哈希在 `_specialities_meta.json`。
筛选仍按原始ID精确匹配，完整已知目录可选，观测到的未知ID以“特性 #ID”展示；
同名ID不合并为另一个协议值。这是静态来源核对与合成查询验证，未新增真实捕获样本验收。

- **0701 协议通道**（服务器 120.233.252.215 等，端口 80/10012 漂移）：
  帧格式为 `[4B 总长][07 01][4B seq][4B 帧号][4B 载荷长][加密载荷]`，
  有独立密钥、连接建立时无握手帧（密钥在别处协商，未破解）。
  当前确认它不是宠物数据通道，真实用途未定。排障时可用
  `capture.ports` 收录样本，不要据此怀疑主链路。
- **游戏进程 UDP**：仅少量打点包（端口 52056+ 等），无业务流量。
- **游戏 443 端口中的一条明文私有协议**（非 TLS，含账号串与时间戳）：
  疑似状态推送，未深入。

## 排障教训（同类问题自查清单）

1. **收不到 s2c 数据**：先查 debug 日志有无「重传冲突」。
   服务器在大批下行前会先发 6 字节全零段、随后同 seq 发真实数据；
   重组器必须支持该形态的回滚重收（`reassembly.py` 已处理，见其模块注释）。
2. **抓包线程**：嗅探回调内绝不做重活（解密/解码/IO）。登录推送秒级数百 KB，
   同步处理会导致 libpcap 缓冲溢出、整批丢包（`npcap_source.py` 已改为
   轻量回调 + 队列 + worker 线程）。连接关闭事件（FIN/RST/空闲淘汰）同样经
   该队列**保序**投递：先处理残余数据、再释放协议层会话——顺序颠倒会先清掉
   密钥，让残余 DATA 全部丢解（实测复现过 key_miss 并重建出已关闭会话）。
3. **判定解密正确性**：用结构锚点（明文尾部 `tsf4g`、内层 `55aa`）或跨帧一致，
   不要用熵/可打印率等弱指标（会产生大量假阳性）。
4. **离线分析 raw 字节**：必须按 TCP seq 排序重组后再切帧，乱序字节流会造成
   「全部解不开」的假象。
5. **scapy 兼容**：`AsyncSniffer(buffer_size=...)` 在部分版本抛 TypeError，
   且异常发生在嗅探后台线程（构造期 try/except 捕不到）；需在探活期识别降级。
   （`npcap_source.py` 已处理）
6. **mihomo/Clash 等代理环境**：代理转发的流量在物理网卡抓包中完整可见
   （已实测 1.3MB 下载逐字节吻合），不是丢数据原因；但游戏进程会以
   虚拟网卡地址连接（如 198.18.0.1），断言会话归属时注意。

## 版本适配指引

蛋仓 2026-10-15 核对：BagItem.field2 是道具 ID，field15.conf_id 是蛋配置 ID，二者不能共用索引。PetEggBrief 的 field11/is_precious、field17/random_egg_conf、field18/mutation_type、field19/glass_info、field21/precious_egg_type 分开处理。草系试炼 `0x1959` 也有 field14=8 和两字段外观子消息，不能只以这些弱特征收为蛋。形状识别要求 BagItem 关键标量唯一且 PetEggBrief 身高、体重、孵化时长同时存在；真实录制保留 530 条分页与两类各 5 条更新，拒收 24 条试炼节点。缓存清理与资源证据见 [蛋仓修复记录](reviews/EGG_INVENTORY_REPAIR_2026-10-15.md)。

游戏更新后若解不出数据，按以下顺序排查：
1. 密钥仍从 0x1002 ACK 取？`extract_ack_key` 偏移 [2:18] 是否仍成立。
2. 0x4013 双变体是否覆盖新流量？先用 `analyze_recording.py --key` 手动解录制的
   首帧，观察明文头部结构。
3. 内层布局是否变化？对照 `records.py` 三种拆分分支的判据。
4. 字段改名/新增：换 `data/schemas/messages/`（外挂数据，不改代码）。
