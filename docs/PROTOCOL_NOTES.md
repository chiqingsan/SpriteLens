# 协议观察笔记（排障与未解事项）

本文记录「已确认可用」之外的观察，供未来排障与版本变更时参考。
主协议结论见 `ARCHITECTURE.md`，此处只记边角信息与教训。

## 附近场景观察（C02，2026-10-23）

当前仅实现原始场景观察快照，不宣称全量附近精灵支持。现有本机事件已核对 NPC 基础/测量字段和实体进入/离开：`0x0413` 比 `0x0414` 多一层包装，必须分开提取动作。客户端移动目标坐标不能当作服务器确认位置，单位不预设为厘米；未知字段保留 null，未知增量计数，不猜完整性。战斗信号仅作保守失效，现场恢复语义仍待验证。字段路径、证据范围、接口与剩余项维护在 [C02 场景观察规格](SCENE_OBSERVATIONS.md)。

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
