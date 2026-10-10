# 文档索引

阅读顺序：

1. `../README.md` — 安装与使用
2. `DEVELOPMENT_GUIDE.md` — 开发规范（改码前必读）
3. `ARCHITECTURE.md` — 分层约束、接入层可插拔设计、协议栈
4. `CODEBASE_MAP.md` — 文件级代码地图
5. `PROTOCOL_NOTES.md` — 排障自查清单、未解事项、版本适配指引

方向与决策（按需查阅）：

- `ARCHITECTURE_DECISION.md` — 架构决策：目标形态（pywebview + 本地服务 + Web UI）、
  Tauri 评估、阶段划分与量化判据
- `FEATURE_MODULES.md` — 功能模块规划（M1–M16，本地/云端属性、优先级）
- `DANSHEN_ASSISTANT_ANALYSIS.md` / `COMPETITOR_ANALYSIS.md` — 竞品解剖（蛋神助手、roco_helper）
- `STACK_EVALUATION.md` / `TECH_EVALUATION.md` / `TAURI_SIZE_EVALUATION.md` — 技术栈与体积专项评估

维护约定：用户可见行为变更 → 更新 README；架构/分层变更 → ARCHITECTURE；
新增文件 → CODEBASE_MAP；协议观察与排障经验 → PROTOCOL_NOTES。
文档用 LF、不写本机绝对路径。
