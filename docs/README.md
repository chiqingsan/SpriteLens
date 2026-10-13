# 文档索引

状态：当前文档总入口。读者：用户、维护者、开发者与 AI 协作者。
当前事实以代码与维护文档为准；路线图区分已落实范围与待办，带日期的核验/审查只代表当时证据。

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
- [reviews/VUE_EGG_DEX_VERIFICATION_2026-10-13.md](reviews/VUE_EGG_DEX_VERIFICATION_2026-10-13.md) — F00/V01/V02 实施范围与本机验证，WebView2/exe 待验收
- [reviews/PET_SNAPSHOT_VERIFICATION_2026-10-13.md](reviews/PET_SNAPSHOT_VERIFICATION_2026-10-13.md) — F01 宠物响应/选项/身份同源、bootstrap 单次快照与离线归属
- [reviews/ACCOUNT_DOMAIN_VERIFICATION_2026-10-13.md](reviews/ACCOUNT_DOMAIN_VERIFICATION_2026-10-13.md) — F02 三域单次快照、跨域归属、历史恢复与原生账号页旧请求失效
- [reviews/VUE_PET_FILTERS_VERIFICATION_2026-10-13.md](reviews/VUE_PET_FILTERS_VERIFICATION_2026-10-13.md) — F03 基础筛选切片、单一状态/DOM 所有者、快捷恢复与防抖旧请求失效
- [reviews/F03_ACCEPTANCE_2026-10-13.md](reviews/F03_ACCEPTANCE_2026-10-13.md) — 完整宠物页交付范围、自动化证据与统一人工验收清单
- [reviews/VUE_PET_INVENTORY_VERIFICATION_2026-10-13.md](reviews/VUE_PET_INVENTORY_VERIFICATION_2026-10-13.md) — F03 请求/三视图/分页/箱队迁移、账号失效、槽位语义与原生详情定位桥
- [reviews/ASSET_SIZE_AUDIT_2026-10-13.md](reviews/ASSET_SIZE_AUDIT_2026-10-13.md) — 素材体积/完全重复/运行引用与压缩副本实测；正式资源尚未修改

方向与决策（按需查阅）：

- [reviews/PROJECT_REVIEW_2026-10-12.md](reviews/PROJECT_REVIEW_2026-10-12.md) — `114be08` 全项目初审快照；当前修复状态见路线图
- [reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md](reviews/ARCHITECTURE_FOLLOWUP_2026-10-13.md) — `240b94c` 改动复核：录制回归、生命周期/HTTP 缺口与完成范围校正
- [reviews/GLM_DELIVERY_REVIEW_2026-10-13.md](reviews/GLM_DELIVERY_REVIEW_2026-10-13.md) — `a106044` 交付复核：启动阻断、并发/停止/HTTP 返修证据与门禁边界
- [reviews/GLM_RECHECK_2026-10-13.md](reviews/GLM_RECHECK_2026-10-13.md) — `477bd75` 返修二次复核：启动已恢复，剩余 HTTP 阻塞、停止确认/所有权与失败分类
- [reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md](reviews/RUNTIME_REPAIR_VERIFICATION_2026-10-13.md) — E01–E06 实施复验：状态读取、停止重试/下游保护、错误分类与工程门禁

- `ARCHITECTURE_DECISION.md` — 架构决策：目标形态（pywebview + 本地服务 + Web UI）、
  Tauri 评估、阶段划分与量化判据
- `DANSHEN_FEATURE_SPEC.md` — 蛋神助手功能解剖与 SpriteLens 实施对照（工作文档）
- `FEATURE_MODULES.md` — 功能模块规划（M1–M16，本地/云端属性、优先级）
- `DANSHEN_ASSISTANT_ANALYSIS.md` / `COMPETITOR_ANALYSIS.md` — 竞品解剖（蛋神助手、roco_helper）
- `STACK_EVALUATION.md` / `TECH_EVALUATION.md` / `TAURI_SIZE_EVALUATION.md` — 技术栈与体积专项评估

本轮迭代记录与规格（2026-10-12）：

- 核验记录：`UI_UPGRADE_VERIFICATION.md`（三主题与资源）、
  `PET_PRESENTATION_VERIFICATION.md`（展示重构）、
  `BACKPACK_BOX_VERIFICATION.md` / `BACKPACK_UPGRADE_VERIFICATION.md`（真实箱位与背包操作）、
  `SESSION_RESUME_VERIFICATION.md`（会话接续）
- 规划与对照：`BACKPACK_PARITY_PLAN.md`（对标清单与迭代计划）、
  `BACKPACK_UI_COMPARISON.md`（蛋神对照差异）、`PET_CARD_LAYOUT_PLAN.md`（卡片布局细化）
- 下一轮规格（研究态）：`BREEDING_PLANNER_SPEC.md`（智能配窝）、`COLLECTION_LINES_SPEC.md`（产线收集）
- 资源台账：`RESOURCE_COVERAGE_REPORT.md`（覆盖/缺口/冲突）

维护约定：用户可见行为变更 → 更新 README；架构/分层变更 → ARCHITECTURE；
新增文件 → CODEBASE_MAP；协议观察与排障经验 → PROTOCOL_NOTES；
UI 视觉/组件规范 → UI_GUIDE；蛋神对标实施进度 → DANSHEN_FEATURE_SPEC；
每轮迭代验收记录与下轮规格 → 本轮组（验收命名 `*_VERIFICATION.md`）。
当前路线与验收顺序只维护在 `ROADMAP.md`，协作规则维护在 `DEVELOPMENT_GUIDE.md`；
历史评估中的架构、体积、测试数量与阶段状态须结合记录日期阅读。
文档用 LF、不写本机绝对路径。
