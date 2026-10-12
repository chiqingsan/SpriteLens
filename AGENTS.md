# 协作规则

## 工作原则

- 编码前先明确假设、目标和验证方式；有多种合理解释时说明差异，有合理默认时说明后继续。
- 修改前先运行 `git status --short`，保留用户已有改动；不得擅自覆盖、回滚或删除。
- 只修改任务必要代码，保持现有风格、命名、架构和测试习惯，不顺手重构或加未要求功能。
- 修改后必须验证：优先相关测试；无法运行时说明原因和替代检查。每个改动应能追溯到请求。

## 项目入口

- 先读 `docs/AI_CONTEXT.md`、`docs/DEVELOPMENT_GUIDE.md`；涉及边界读 `docs/ARCHITECTURE.md`，后续演进读 `docs/ROADMAP.md`。
- 当前事实以代码和维护文档为准；`docs/reviews/` 是带日期的审查快照，历史方案不自动代表已实现。
- 默认沿用 Python + aiohttp + pywebview + 原生 JS；新增能力沿用现有层次，抽象应有可验证收益。
- `web/static/app.js`、`web/server.py`、`web/payloads.py` 是复杂度关注区；新增页面先确定模块归属，不继续吸收整页职责。
- 账号、快照、线程、持久化、协议和资源导入修改必须写明失败分支及验证。运行数据、密钥、录制和本机临时路径不得作为可提交测试样本。
- Python 使用 unittest，完整入口为 `.venv\Scripts\python.exe -B tools\run_build_tests.py`；按开发指南选择相关测试、源码 smoke、JS/资源与GUI验收。
- 文档使用 UTF-8/LF，新增文档同步索引并说明状态、读者和维护边界。
