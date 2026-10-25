# 文档索引

状态：当前文档总入口。读者：用户、维护者、开发者与 AI 协作者。
当前事实以代码与维护文档为准；路线图区分已落实范围与待办，带日期的核验/审查只代表当时证据。

[采集向导与健康诊断](CAPTURE_DIAGNOSTICS.md) — C01 当前操作、诊断语义和接口边界；任务状态见路线图。

[场景实体观察快照](SCENE_OBSERVATIONS.md) — C02 当前协议证据、接口与待验收边界。

[附近精灵列表](NEARBY_OBSERVATIONS.md) — C03 操作入口、解包适配来源、请求归属与观察版边界。

[DeepSeek 交接文档](HANDOFF_DEEPSEEK_2026-10-24.md) — 2026-10-24 数据库数据恢复事故记录、恢复后验证结果、伙伴标记实现与遗留事项。

[内存与性能修复交接](reviews/MEMORY_PERFORMANCE_HANDOFF_2026-10-24.md) — 进程内存采样、事件缓存隔离对照、PERF01–PERF07 修复方向与验收边界；持续状态见 ROADMAP，本报告不表示修复已完成。

阅读顺序：

1. `../README.md` — 安装与使用
2. [AI_CONTEXT.md](AI_CONTEXT.md) — 项目定位、重点风险与协作入口
3. `DEVELOPMENT_GUIDE.md` — 开发规范（改码前必读）
4. `ARCHITECTURE.md` — 当前分层、已知边界、接入设计与协议栈
5. [ROADMAP.md](ROADMAP.md) — 健壮性与可维护性演进顺序、验收条件
6. `CODEBASE_MAP.md` — 文件级代码地图
7. `PROTOCOL_NOTES.md` — 排障自查清单、未解事项、版本适配指引
8. `UI_GUIDE.md` — 前端视觉与组件规范（改 UI 前必读：token 速查/组件清单/反面清单）
9. [VUE3_MIGRATION.md](VUE3_MIGRATION.md) — 已确认的 Vue 3 技术方向、配套工程、接口/状态与逐页迁移边界（工程与蛋图鉴已落地）

- [FRONTEND_DEVELOPMENT.md](FRONTEND_DEVELOPMENT.md) — 前端安装/构建/验收、生成文件与临时桥所有权
- [HOME_IMPLEMENTATION_PLAN.md](HOME_IMPLEMENTATION_PLAN.md) — Luna6 家园编码交接：场景/账号归属修复、增量合并、资料预测、卡片交互、地图与桌面验收；持续任务状态见 ROADMAP 的 F04-U2
- [BREEDING_RULES.md](BREEDING_RULES.md) — 配种规则联网核对、玩家教程与跨种配种经验、来源等级及双牌／身高培养参考的区分
- [BREEDER_LIBRARY_SPEC.md](BREEDER_LIBRARY_SPEC.md) — 筛选配对的当前实现、蛋神功能对照、候选与预测边界；持续状态见 F04-U4
- [BREEDING_PLANNER_SPEC.md](BREEDING_PLANNER_SPEC.md) — 智能配窝完整设计：双入口、宽容双奖牌、合格/迭代候选区分、声体参考边界、联合摆位和账号存档；本地功能已实现，真实游戏/桌面验收状态见 F04-U5
- [reviews/EGG_INVENTORY_REPAIR_2026-10-15.md](reviews/EGG_INVENTORY_REPAIR_2026-10-15.md) — 蛋仓两类配置 ID 联查、试炼误识别清理与资源补齐证据
- [reviews/VUE_EGG_DEX_VERIFICATION_2026-10-13.md](reviews/VUE_EGG_DEX_VERIFICATION_2026-10-13.md) — F00/V01/V02 实施范围与本机验证，WebView2/exe 待验收
- [reviews/PET_SNAPSHOT_VERIFICATION_2026-10-13.md](reviews/PET_SNAPSHOT_VERIFICATION_2026-10-13.md) — F01 宠物响应/选项/身份同源、bootstrap 单次快照与离线归属
- [reviews/ACCOUNT_DOMAIN_VERIFICATION_2026-10-13.md](reviews/ACCOUNT_DOMAIN_VERIFICATION_2026-10-13.md) — F02 三域单次快照、跨域归属、历史恢复与原生账号页旧请求失效
- [reviews/VUE_PET_FILTERS_VERIFICATION_2026-10-13.md](reviews/VUE_PET_FILTERS_VERIFICATION_2026-10-13.md) — F03 基础筛选切片、单一状态/DOM 所有者、快捷恢复与防抖旧请求失效
- [reviews/F03_ACCEPTANCE_2026-10-13.md](reviews/F03_ACCEPTANCE_2026-10-13.md) — 完整宠物页交付范围、自动化证据与统一人工验收清单
- [reviews/PET_DETAIL_VERIFICATION_2026-10-14.md](reviews/PET_DETAIL_VERIFICATION_2026-10-14.md) — F03-U3精灵详情、共享区域与立绘占比/低清限幅、登录奖牌归属核验与增量限制
- [reviews/VUE_PET_INVENTORY_VERIFICATION_2026-10-13.md](reviews/VUE_PET_INVENTORY_VERIFICATION_2026-10-13.md) — F03 请求/三视图/分页/箱队迁移、账号失效、槽位语义与原生详情定位桥
- [reviews/ASSET_SIZE_AUDIT_2026-10-13.md](reviews/ASSET_SIZE_AUDIT_2026-10-13.md) — 素材体积/完全重复/运行引用与压缩副本实测；正式资源尚未修改
- [reviews/2026-10-24-nearby-review.md](reviews/2026-10-24-nearby-review.md) — 附近精灵/场景观测/雷达进度审阅：真实流量回放发现距离阈值量纲错误导致实机列表几乎恒空，附 P0/P1/P2 补全清单
- [reviews/2026-10-25-wiki-sync.md](reviews/2026-10-25-wiki-sync.md) — 图鉴与 B 站 wiki 同步核查：数据无可见变化不重导入、26 个物种 wiki 无条目、5 个缺图中 4 个同画别名补齐

当前规格、历史 review 与方向（按需查阅）：

- [reviews/PROJECT_REVIEW_2026-10-12.md](reviews/PROJECT_REVIEW_2026-10-12.md) — `114be08` 全项目初审快照；当前修复状态见路线图
- [reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md](reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md) — `240b94c` 改动复核：录制回归、生命周期/HTTP 缺口与完成范围校正
- [reviews/GLM_DELIVERY_REVIEW_2026-10-13.md](reviews/GLM_DELIVERY_REVIEW_2026-10-13.md) — `a106044` 交付复核：启动阻断、并发/停止/HTTP 返修证据与门禁边界
- [reviews/GLM_RECHECK_2026-10-13.md](reviews/GLM_RECHECK_2026-10-13.md) — `477bd75` 返修二次复核：启动已恢复，剩余 HTTP 阻塞、停止确认/所有权与失败分类
- [reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md](reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md) — E01–E06 实施复验：状态读取、停止重试/下游保护、错误分类与工程门禁

- `ARCHITECTURE_DECISION.md` — 架构决策：目标形态（pywebview + 本地服务 + Web UI）、
  Tauri 评估、阶段划分与量化判据
- `DANSHEN_FEATURE_SPEC.md` — 蛋神助手功能解剖与 SpriteLens 实施对照（工作文档）
- `COLLECTION_LINES_SPEC.md` — 双牌产线当前实现、参考规则及待验收边界（F04-U3）
- `BREEDING_PLANNER_SPEC.md` — 智能配窝当前规格、规则边界与待验收范围（F04-U5）

历史依据与验收快照（已移入 `archive/`）：

- 早期架构／竞品／技术评估：`archive/FEATURE_MODULES.md`、
  `archive/DANSHEN_ASSISTANT_ANALYSIS.md`、`archive/COMPETITOR_ANALYSIS.md`、
  `archive/STACK_EVALUATION.md`、`archive/TECH_EVALUATION.md`、`archive/TAURI_SIZE_EVALUATION.md`
- 早期核验记录：`archive/UI_UPGRADE_VERIFICATION.md`、
  `archive/BACKPACK_BOX_VERIFICATION.md` / `archive/BACKPACK_UPGRADE_VERIFICATION.md`（真实箱位与背包操作）、
  `archive/SESSION_RESUME_VERIFICATION.md`（会话接续）
- [ROCO 资源解包报告功能分析](archive/ROCO_RESOURCES_ANALYSIS.md) — 外部解包报告的参考路径、功能适配清单和附近精灵实施顺序；不代表当前已实现
- 早期规划／对照：`archive/BACKPACK_PARITY_PLAN.md`、`archive/BACKPACK_UI_COMPARISON.md`、
  `archive/PET_CARD_LAYOUT_PLAN.md`、`archive/UI_THEME_PROPOSAL.md`
- 资源台账：`archive/RESOURCE_COVERAGE_REPORT.md`（覆盖／缺口／冲突）

维护约定：用户可见行为变更 → 更新 README；架构/分层变更 → ARCHITECTURE；
新增文件 → CODEBASE_MAP；协议观察与排障经验 → PROTOCOL_NOTES；
UI 视觉/组件规范 → UI_GUIDE；蛋神对标实施进度 → DANSHEN_FEATURE_SPEC；
每轮迭代验收记录与下轮规格 → 本轮组（验收命名 `*_VERIFICATION.md`）。
当前路线与验收顺序只维护在 `ROADMAP.md`，协作规则维护在 `DEVELOPMENT_GUIDE.md`；
历史评估中的架构、体积、测试数量与阶段状态须结合记录日期阅读。
文档用 LF、不写本机绝对路径。

- [本地 Wiki 补充资料](WIKI_REFERENCE.md)：当前维护说明；来源、离线导入、身份核对与运行边界。
- [历史文档归档](archive/README.md)：早期分析、计划、快照和验收记录，仅供追溯。
- [图鉴原型](prototypes/handbook/README.md)：已确认的蛋蛋图鉴清稿与布局验收边界；其他图鉴方案仍在评审。
