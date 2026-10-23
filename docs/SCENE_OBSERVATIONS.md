# C02 场景实体观察快照

状态：当前观察版规格，部分协议与现场生命周期待验收。读者：维护者与后续 C03 实现者。用途：维护输入证据、所有权、只读契约和失败边界；任务状态统一见 [路线图](ROADMAP.md)。

## 实现边界

独立 `domain/scene.py` 解析当前解码字段树，`SceneRepository` 单锁拥有账号、会话、场景和实体的内存状态。组合根接入现有 MonitorService；使用同一个实时/回放管线，不建立第二个抓包源，不落库，不新增附近页面，不计算米制距离或方向。

只收录带身高、体重或音量字段的 NPC 观察。其它 NPC 和玩家不当作野外精灵；目前不保证覆盖缺少这些字段的特殊形态。字段缺失使用 null，显式零值保留；actor ID 和 uid 在 JSON 中转字符串。缺失位置分量也保留 null，不拼出假坐标。快照由 frozen dataclass 和 tuple 组成，后续更新不会修改已经返回的快照。

## 协议证据与待验收项

- 本机 2026-10-22/23 的现有事件日志中，335 个场景 NPC 含身高字段；`0x014A.field7[].11.1` 是 NPC 基础字段，`.11.3` 是配置与测量字段。ID 为基础字段 2，等级为 11，位置为 8.1；配置 ID 为配置字段 1，身高/体重为 11/12，音量为 31，mutation 为 14，glass 为 30.1/2。测量字段的单位/奖牌语义不在本轮裁定。
- 当前日志确认 `0x0414.field1[]` 是动作包装；`0x0413` 要先进入顶层 field1，再取内部 field1[]，不能直接照抄外部工具统一分支。动作 1 的 field1[] 是进入实体，动作 2 的 field1 是离开 ID（支持普通 varint 与 packed bytes）。不支持的动作累计 `unresolved_updates`，不能报告已同步全部状态。
- `0x0152` 的场景/资源/实例为 2/3/4；非零返回码不改变现有观察。`0x015C` 的对应字段为 11/12/13，位置为 14.1；每次传送均开始新观察周期，即使场景编号不变。普通场景进入在场景、资源或实例变化时清空，不用单一地图编号判定归属。
- `0x0133 c2s` 的 field2 为移动目标坐标、field17 为场景；仅匹配当前场景时保存，来源明确为 `client_target`。传送位置来源为 `teleport`。客户端目标不等于服务器确认位置，坐标单位仍为 `unverified`。
- 外部 SceneTracker 提供的战斗进入 4886、结束 4908/4909 目前只作为保守失效信号：清空实体和位置，进入时标 `battle_unverified`，期间不收 AOI/移动观察；结束后等待新的场景观察。尚未验证 battleId 对应、所有战斗形态或结束后快照是否完整，不实现战斗复盘。

现有 33,667 条本机解码事件可顺序处理，观察到 905 次实体数量增加、786 次减少，最多 78 个实体。此为已解码事件核对，日志没有完整的流关闭事件。另对一份 2026-10-22 的本机字节录制运行直接管线和 ReplaySource：9,155 段流，成功解密 9,397 条事件（其中 5,083 条场景事件），最多 57 个实体；去除处理时刻后，逐事件业务观察序列一致，无缺密钥。该验证不等于现场交互验收。只提交统计与合成测试，不复制本机日志、账号、密钥或录制。

## 生命周期与失败分支

- 未识别本次身份或没有场景上下文时不收录实体，不借用背包离线身份。身份归属沿用 AccountTracker；切号或确认新会话时清空，旧会话的晚到身份/实体被拒绝。
- 最多记住 256 个退役会话，对齐管线会话上限。流关闭或新 SYN 释放相应隔离记录，允许同一个连接标识后续被新连接使用；活动会话失效后必须重新确认身份。
- 采集 start 在启动新 source 前清空观察；成功 stop 确认投递/嗅探退出后清空。停止失败/超时不冒充已停止，不让新一代 source 越过现有停止所有权。关闭/SYN/空闲回收/LRU 淘汰均通过只做内存操作的 session close listener 使活动观察失效。
- 历史账号选择只有在全部历史域读取并应用成功后才清空场景观察，保留所选 uid 并标 `historical_account`，没有历史附近缓存。历史读取失败不清当前观察；切号命令仍受采集命令锁保护。
- 最多保存 4096 个实体；满时拒收新 ID 并增加 `rejected_actors`，不静默淘汰。无法定位的测量实体和坏离开 ID 计入拒收/未知计数。未知增量不猜语义，也不把某次 AOI 当作完整世界仓库。

## 接口与验证

`GET /api/nearby` 沿用现有本机 token 鉴权和受控后台 runner，返回 uid/version/phase、scene_id/resource_id/instance_id、player_position/position_source、updated_at、actors、unresolved_updates/rejected_actors。所有快照固定 `complete=false`、`source=observed_partial`、`coordinate_unit=unverified`；不输出包含本机地址的会话字符串。未装配该域的测试/精简实例返回 503。

现有 WS `state.nearby` 只含 uid/version/phase，后续页面按版本拉取列表；不在 WS 复制整份实体数组。C03 需按响应 uid/version 和页面代次处理晚到请求。

79 项相关 Python 回归通过（其中 9 项 C02 回归）。命令：`python -B -m unittest tests.test_scene tests.test_monitor_service tests.test_recording tests.test_account_selection tests.test_runtime_repair tests.test_view_models tests.test_web_server -q`。

合成回归覆盖字段缺失/零值/负数、大 ID、进入/离开及不同包装、未知动作、实体数量上限、场景实例与同地图传送、切号与旧会话、方向过滤、战斗失效、断流与停止、真实组合根装配/关闭、接口鉴权，以及合成加密分段流录制/回放一致性。现场进出战斗、多账号抓包、丢包恢复及当前游戏距离单位仍需实际证据；这些缺口未完成前不启动 C03。
