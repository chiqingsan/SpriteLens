# 文档索引

状态：当前文档总入口。读者：用户、维护者、开发者与 AI 协作者。
当前事实以代码与维护文档为准；路线图中的方案是待实施任务，带日期的核验/审查只代表当时证据。

阅读顺序：

1. `../README.md` — 安装与使用
2. [AI_CONTEXT.md](AI_CONTEXT.md) — 项目定位、重点风险与协作入口
3. `DEVELOPMENT_GUIDE.md` — 开发规范（改码前必读）
4. `ARCHITECTURE.md` — 当前分层、已知边界、接入设计与协议栈
5. [ROADMAP.md](ROADMAP.md) — 健壮性与可维护性演进顺序、验收条件
6. `CODEBASE_MAP.md` — 文件级代码地图
7. `PROTOCOL_NOTES.md` — 排障自查清单、未解事项、版本适配指引
8. `UI_GUIDE.md` — 前端视觉与组件规范（改 UI 前必读：token 速查/组件清单/反面清单）

方向与决策（按需查阅）：

- [reviews/PROJECT_REVIEW_2026-10-12.md](reviews/PROJECT_REVIEW_2026-10-12.md) — 全项目审查快照：基线、可复现缺陷、代码/资源/文档风险；缺陷尚未修复

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
