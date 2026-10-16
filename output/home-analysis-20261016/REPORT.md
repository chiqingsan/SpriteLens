# 蛋神家园实现与 SpriteLens 可行性分析

日期：2026-10-16。状态：只读分析，未修改生产代码或维护文档。
读者：项目维护者、家园功能实现者。维护边界：本报告是本次证据快照；后续实施状态仍归 docs/ROADMAP.md 的 F04-U2。

> 证据边界：本报告引用的原始反汇编与 REA 证据（`rea-webui.json`、`python-evidence.json`、`*.dis.txt`、`*.compact.txt`）未随仓库提交，可按本文方法重新采集；仓库内仅保留本报告与 `sample-summary.json`。

## 结论

SpriteLens 能通过自己的被动采集实现蛋神截图中的主要家园功能，不需要调用蛋神的家园 API。已有本机日志已经包含足够的家园成员、窝位和场景配对数据。

2026-10-16 的日志第 23、1955、5922 行是可解析的家园室内场景。当前工作树中的解析器对每份均提取出：

| 项目 | 数量 |
| --- | ---: |
| 房间等级 | 5 |
| 入住居民 | 11 |
| 家具（包含窝） | 81 |
| 普通窝 | 10 |
| 学院窝 | 1 |
| 母本配对记录 | 6 |
| 配对记录中的父本引用 | 14 |

这 11 个居民的 instance_id 全部能在同账号本地宠物库中匹配。因此居民身份、性格/声音等资料的主要关联数据已经具备。

之前将“1 个居民、0 个窝”归因为缺少接口数据或必须再次采集，没有证据支持。对同一份实际日志应用项目仍保留的旧解释路径，会得到“房间等级 10、1 个居民、1 件家具”，与错误截图一致。该路径把第一个场景 actor 当作房间，把 actor_detail_type=10 当作房间等级。当前工作树的新增嵌套解析可以读出真实数据，但运行中的旧进程是否加载了这些改动，本次没有核实。

## 证据与分析范围

- 项目基线：HEAD c327833，工作区已有家园协议、Vue 页面及文档等未提交改动；本轮保留原状。
- 目标：用户指定的 D:/code_resources/roco_resources/danshen-v1.2.0-extracted。
- JavaScript：REA 6.5.0 静态分析 feature-pages.js、home-breeding.js、home-interactions.js。Evidence ID：ev_64d3c9988866fb28dcbf0f495e05d788539d16ebc1ec1521cbc877f352294574。3 个选择文件全部解析成功，另 43 个库存文件未纳入该次语义分析，不能据此声称完整覆盖整个客户端。完整结果见 rea-webui.json。
- Python：使用版本匹配的 Python 3.12 marshal/dis 读取 pyc，未导入或执行目标模块。来源哈希及函数清单见 python-evidence.json；反汇编分别保存在 *.dis.txt、*.compact.txt。这些是普通本地静态分析证据，不冒称 REA Python 反编译结果。
- 实际样本：读取用户数据目录现有 eventlog_20261016.jsonl，调用项目当前纯解析函数检查已保存字段树；只保存聚合计数至 sample-summary.json，没有复制原始运行数据或密钥为测试样本。
- 宠物关联：SQLite 只读连接，限定同账号 gid 集合比对，11/11 匹配。
- 本轮未请求蛋神云端、未修改应用配置、未重启应用、未运行游戏操作。没有修改代码，因此未运行测试套件或前端构建。

日志的 bytes 字段序列化有损，不能把 JSONL 当作原始字节回放样本。这里确认的是仍保留的字段树及数字计数、ID 关联；不能由此确认每一种编码、所有增量或当前实时状态均正确。

## 蛋神如何采集和维护家园

### 1. 先识别场景与所属账号

home_scene.pyc 的 decode_home_scene（原源码行 218 起）接收同一游戏流上的 opcode 和 payload：

- 0x0152 从 field3 记录场景资源 ID，0x015C 从 field12 记录目标场景资源 ID；切场景时清空流内活动家园状态和待关联拾蛋请求。
- 0x014A 是通用进场景应答，不能仅凭 opcode 就认定是自己的家园。
- 从顶层 field22 取得 home_info，field2 取得主人 UID；主人必须与当前游戏 UID 相同。
- 排除场景资源 30002。实际日志中该场景带同一份家园布局和配对元数据，但没有这 11 个室内居民；直接接受会将居民列表替换为空。该资源的具体游戏场景名称未在本次静态代码中确认。

证据：home_scene.compact.txt 的 decode_home_scene，原源码行 221–231；本机日志的场景序列见 sample-summary.json。

### 2. 从专门字段读取居民、家具和配对

- 家园居民来自重复的顶层 field7 场景 actor，经 npc.field22.field1 找 home pet 信息；其中 instanceId、baseId 和 furnitureGuid 必须存在。不是看到一个带名字的 NPC 就认作入住居民。
- instanceId 用于关联宠物个体；baseId 用于关联物种；actorId 用于场景配对和离开事件；furnitureGuid 用于关联窝。四种键各有用途。
- 家具从 home_info 的房间 → 平面 → 家具列表读取；保留 GUID、配置 ID、位置、房间等。家具原始坐标除以 100 转为游戏世界坐标。
- 普通窝配置 1001071，学院窝配置 1001072。
- home_info.field22 给出 layEggCouples：一个 femaleActorId 对应多个 maleActorIds。核心配对关系由游戏场景直接提供。
- 场景蛋经 NPC 类型及窝附件识别，关联至家具 GUID。

证据：home_scene.compact.txt 的 _home_actor、_home_furniture、_home_egg、decode_home_scene。

### 3. 增量维护与缓存

- 0x0413/0x0414 更新居民和场景蛋，按 actorId 处理离开；居民变化时将已有配对标记 couplesStale，等待下一份场景快照确认。
- 解码器发出 home.snapshot 事件。LocalState.handle_decoder_event 校验 gameId，将结果按 home-capture:<gameId> 保存，并交给 nest_inference。
- 离开家园时流内活动状态失效；界面仍可读取按账号保存的上一份家园缓存。
- 0x0137/0x0243 的 pending_home_collection 是拾蛋请求/响应关联，用于关联拾取的蛋与窝；不能把它当作前端主动查询家园成员的请求机制。

证据：roco_collector.compact.txt 原源码行 1054–1062、1188–1193、1201–1204；app-home.compact.txt 原源码行 1112–1118。

## /api/home/info 的真实作用

本地页面 → LocalWebServer._home_info → CollectorService.home_info。

| 条件 | 蛋神实际行为 |
| --- | --- |
| 正在采集 | 直接返回 cached_home_info；缓存仅选 home-capture:<gameId>，不调用在线家园查询 |
| 未采集 | 可选本地 capture 或 remote 缓存中时间较新的记录 |
| 未采集，且账号、会话和订阅条件满足 | 调用云端 /desktop/home/info，按 syncTask 轮询 |
| 云端返回完成结果 | 写入 home-remote:<gameId>；错误通过 warning 返回 |

cached_home_info 会以居民 instanceId/gid 查询同账号 pets 表，合并个体资料，再 decorate_home。它把结果放在名为 remote 的字段中，即使来源完全是本地 capture。因此 frontend 中看到 info.remote.residents，不能推出这组居民必须来自云端。

云端请求的 provider 字段明确写作“洛克魔法书”；客户端代码未包含上游服务端实现，本次没有验证其具体采集方式。在线更新是一条独立的可选能力，单靠客户端解包不能复原其服务端实现。

证据：web_runtime.compact.txt 的 CollectorService.cached_home_info（原源码 1479–1504）、home_info（1506–1536）、_desktop_account_request（1193–1228）、LocalWebServer._home_info（4000–4009）；feature-pages.js:136 的轮询调用。

## 蛋神如何利用这些数据

### 个体卡片与详情

feature-pages.js:63–104 筛选 resident/isHomeResident，排除守护宠物，按实例 ID 合并本地宠物和物种目录。性格、蛋组、声音、体型百分位、奖牌和图片主要来自这些关联数据。卡片、地图上的居民都可以打开详情。

### 配对与后代预测

feature-pages.js:163 的 homePairingModel 将场景配对按 actorId 关联居民，再构建配对连通组，分组着色。家园主界面的 analyzeAcademyBreeding 调用没有开启 allowRangeInference；关系过期时不会直接把距离候选当成已确认配对。

home-breeding.js 提供另一套范围判断：同楼层、窝边缘间距不超过 10 格、每格 40 世界单位、窝占 4×4 格，再检查性别和蛋组。该算法还用于学院窝参与标识。它计算的是候选关系，不能替代游戏给出的有效配对。

性格预测的静态实现：普通窝母本 30%、父本 30%、随机 40%；单方学院窝按该方性格 100%；双方学院窝性格不一致时记未知；多父本按等概率分摊。随机部分也可能得到已列出的性格，不能把图中的 30% 理解为最终得到该性格的完整概率。

声音取父母均值并向零取整，多父本可显示最小至最大值；母本物种/进化链关联蛋目录显示蛋种；体重百分位均值用于展示奖牌预测。以上是解包客户端采用的工具规则，不代表本次独立验证了游戏繁育概率。

### 地图与本地交互

feature-pages.js:106–133 按家具坐标和楼层映射至家园底图，提供楼层切换、缩放、空窝及居民标点。范围计算采用窝的家具位置，避免可走动的宠物坐标导致误判。

home-interactions.js 的长按拖动只保存卡片显示顺序；配对模式只组织展示分组。这些操作不改变游戏内摆放或配对。

## SpriteLens 已具备什么、还缺什么

| 能力 | 当前工作树 | 实现判断 |
| --- | --- | --- |
| 家园居民、窝、游戏配对 | home.py 新增嵌套路径已可从真实字段树提取 11/11/6 | 数据已具备，先修场景生命周期 |
| 个体性格、蛋组、声音、图片 | home_payload 按同账号 instance_id 联查；样本 11/11 命中本地库 | 可本地实现 |
| 性格与每个父本的声音预测 | home_payload 已有规则；home_breeding.py 已有范围候选 | 可本地实现，需要资料缺失语义与规则验收 |
| 蛋神式完整卡片 | 当前是概览卡片；缺百分位、奖牌、母本蛋种及图形概率 | 可复用现有宠物、蛋目录和图片能力 |
| 配对颜色分组、显示排序、详情 | 当前列表和侧栏独立，缺相应交互 | 只需本地状态和已有详情入口 |
| 家园地图 | 当前只显示坐标；缺地图、楼层和缩放 | 家具坐标已具备，需底图与映射 |
| 退出后仍看上次家园 | HomeRepository 仅内存；没有家园快照持久化 | 如要求跨重启查看，需要按账号保存并标历史 |
| 不启动游戏的在线更新 | 当前无对应上游服务 | 与本地家园功能分开评估，不能从客户端推定可用服务 |

## 当前实际问题

### P0：旧路径把场景 actor 当房间

位置：spritelens/domain/home.py:369、:380。

_entities_of 只取第一个 field7，读取其 field1 当 roomLevel，再把 field11 当房间实体；实际 schema 中 field7 是重复 other_actors，首个 actor 的 field1 是 actor_detail_type=10。对已有真实样本，旧路径得到 1 个居民、房间等级 10；正确 home_info 路径得到 11 个居民、房间等级 5。

新增嵌套路径能纠正带 home_info 的场景，但旧分支仍对没有 home_info 的普通场景返回一个 HomeSnapshot，继续产生伪家园。没有证据支持把这种误读保留为“旧版兼容布局”。

### P0：缺场景和主人检查，非目标场景覆盖家园

位置：spritelens/services/home_repository.py:45；spritelens/domain/home.py:303。

当前不处理 0x0152/0x015C，也没有校验 home_info.home_owner_id。真实日志中两份 10003 场景没有 home_info，却被旧分支解析为“房间等级 6、0 居民、1 家具”；两份 30002 场景带家园布局但无室内居民，会把家园居民替换为空。

应维护当前流/账号是否位于目标家园的状态，只有符合归属和场景条件的数据才更新家园。离开后保留上一份家园缓存，并标明它是历史观察。

### P1：通用场景增量污染家园状态

位置：spritelens/services/home_repository.py:58；spritelens/domain/home.py:425。

0x0413/0x0414 是通用场景行为通知，当前无活动家园过滤；任意不能合并的此类帧都会增加 pending_deltas。不能把这个计数等同于“收到这么多条家园变化”。

apply_home_delta 还会因批次中一个无法识别的 actor 直接返回 None，丢弃已在同批计算出的可识别居民变化。需区分无关 NPC、有效居民变更和真正无法判定的相关数据，保持活动场景边界。

### P1：展示仍未达到参考页面，且多父本 key 不唯一

HomePage.vue:192 以母本 actor ID 加父本名称作 key，:197 以 father_name 作 key；多个父本同名时会重复。应保留 actor ID 到声音预测项并按 ID 渲染。

当前页面缺地图、详情、配对分组、母本蛋种与图形化预测；这些是本地展示工作，不是 API 阻塞。

另需核对声音来源：当前家园直接使用 pet.voice，并以 0 作缺失判断；项目又支持手动分贝覆盖。后续应按现有有效值来源明确未知与合法零值，而不能只改一个前端条件。

完整性状态也应区分“本次目标家园快照成功解析”“来自历史缓存”“相关数据待刷新”。不能因为读到了 11/11/6 就宣称游戏全部数据已完整，也不能始终用一条固定的未确认提示掩盖解析是否成功。

## 建议实施顺序（继续 F04-U2）

1. **先完成场景识别和快照维护。** 去掉无依据旧路径；校验主人 UID，跟踪 0x0152/0x015C 的场景及会话；过滤非家园增量；正确保留上次家园观察。验收：目标家园提取 11/11/6，离开到 10003 或切到 30002 不抹掉室内居民；访问他人家园不污染当前账号；切号后不混用缓存。必要的协议回归使用最小合成结构，不把用户日志提交为夹具。
2. **接通资料与参考页面。** 同账号 instance ID 联查已有宠物资料和有效声音来源；复用物种体型百分位、奖牌、蛋目录及现有详情；补配对颜色/分组、母本预测卡、搜索性格和蛋组，使用稳定 ID。协议和预测计算仍归 domain/service，Vue 只展示。验收：11 个居民资料能对上，6 组配对亲本稳定，同名父本不发生重复 key。
3. **补位置视图和需要的本地交互。** 用家具位置实现楼层、窝位和空窝；显示排序按账号保存。跨重启历史查看如纳入本切片，再按已有持久化规范保存家园；不因做地图而扩展在线服务。Vue 改动构建并目视验收，场景/账号行为复用相关测试。

本轮已经回答：核心数据来源、本地与云端关系、场景筛选、个体关联、配对/预测/地图及本地可行性。尚未确认：运行进程是否加载当前改动、真实增量字节的全部变体、游戏实际繁育概率、云端服务端实现及完整桌面交互。此次没有实施修复。

## 可复核文件索引

- sample-summary.json：既有日志的数字汇总、场景序列、旧路径对照、同账号宠物匹配数。
- python-evidence.json：Python 目标文件身份和已反汇编函数清单。
- web_runtime.compact.txt：缓存读取、在线分支、本地路由。
- home_scene.compact.txt：场景过滤、居民/家具/蛋/配对解析、增量维护。
- roco_collector.compact.txt：采集解码到 home.snapshot/拾蛋事件。
- app-home.compact.txt：按账号保存 home-capture 缓存。
- rea-webui.json：三个指定前端文件的完整 REA 静态证据。
- *.dis.txt：保留完整指令和偏移的常规反汇编输出。
