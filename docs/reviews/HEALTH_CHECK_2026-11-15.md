# 全项目健康检查与清理（2026-11-15）

状态：本轮健康检查快照。读者：维护者、实现者、架构复核者。
维护边界：本文只记录 2026-11-15 当次的度量、清理范围与验证证据；持续状态以 ROADMAP 为准，
未完成项不代表已修复，已清理项不表示相关功能已完成验收。

## 1. 范围与方法

覆盖仓库内全部可维护资源：`spritelens/`（Python 源码）、`tools/`、`tests/`、`frontend/src`、
`spritelens/web/static`（原生 JS/CSS 与图片资源）、`docs/`。
不含：`build/`、`output/`、`.guishot/`、`.research/` 等本地产物（见 §6.5），以及 `frontend/node_modules`。

执行的手段：

| 维度 | 手段 |
| --- | --- |
| Python 死代码 | `ruff --select F,E402`（F401/F811/F822/F841/F402 等真实缺陷类）、`vulture --min-confidence 80` |
| Python 结构 | 自建 AST 脚本：重复函数体（归一化 AST 哈希）、裸 except/静默 pass、分支数与函数长度热点、模块级未被引用定义 |
| 前端死代码 | 全仓引用扫描（组件/类型/样式类/图标符号）、`vue-tsc --noEmit` |
| 资源 | 统计文件/哈希去重、图片与图标符号引用比对、`.gitignore` 与实际产物核对 |
| 文档 | 相对链接可解析性、索引完整性、代码地图与源码一致性（路径解析 + 反向缺口） |
| 回归 | Python `unittest discover`（783）、Vitest（260）、`tools/frontend.py build`、`python -m spritelens --smoke-test` |

## 2. 基线度量

| 范围 | 文件数 | 行数 |
| --- | --- | --- |
| `spritelens/**.py` | 123 | 22 029 |
| `tests/*.py` | 73 | 16 183 |
| `tools/*.py` | 22 | 3 387 |
| `frontend/src/**/*.ts|vue` | 144 | 14 931 |
| `spritelens/web/static/*.js|css` | 25 | 5 136 |
| `docs/*.md` | 27 | 5 877 |
| `docs/reviews/*.md` | 23 | 2 328 |

测试基线（清理前后一致）：

- Python：`Ran 783 tests ... OK (skipped=2)`，约 93–98 秒。
- 前端：`Test Files 34 passed | 1 skipped`、`Tests 260 passed | 1 skipped`，约 8–9 秒。
- 类型检查：`vue-tsc --noEmit` 通过；`tools/frontend.py build` 产物校验通过。
- ruff F 类（死代码/未定义名）：起始 33 条，清理后 0 条。

规模红线（`DEVELOPMENT_GUIDE.md` §文件规模红线）现状：

| 阈值 | 数量 | 文件 |
| --- | --- | --- |
| > 1200 行 | 0 | — |
| > 800 行 | 4 | `web/server.py` 1058、`static/app.css` 957（清理后）、`web/payloads_catalog.py` 876、`static/app.js` 845 |
| > 500 行 | 12 | 上述 4 个 + `services/retention.py`、`static/ui-components.css`、`pages/NearbyPage.test.ts`、`services/scene_repository.py`、`components/SceneMap.vue`、`repositories/database.py`、`domain/home.py`、`pages/NearbyPage.vue` |

## 3. 已清理项（本轮改动）

### 3.1 Python 死代码与缺陷类告警

| 文件 | 问题 | 处理 |
| --- | --- | --- |
| `web/payloads_catalog.py` | `__all__` 导出不存在的 `pet_row`/`pets_payload`（F822）；`from ... import *` 会直接 ImportError；`__all__` 前缺空行且置于最后一个函数之前 | 改为实际导出的 6 个符号并移到文件末尾；模块文档中"payloads.py 保留兼容重导出"的过期描述改为现状 |
| `main.py` | `_run_smoke_test` 的 6 个导入未被引用（F401）、两处无占位 f-string（F541） | 导入是 smoke 的检查对象，保留并标注 `# noqa: F401` 与说明；去掉多余 f 前缀 |
| `view_models/pet_vm.py` | 3 处循环变量 `field` 遮蔽 `dataclasses.field`（F402） | 循环变量改名 `metric`，输出键不变 |
| `build.py` | `import shutil` 未使用 | 删除 |
| `tests/test_desktop_shell.py`、`test_egg_box.py`、`test_monitor_service.py`、`test_pets.py`、`test_session_resume.py`、`test_wiki_chains.py`、`test_persistence.py` | 未用导入 8 处（含 F811 重复导入、重复的 `OpcodeCatalog` 局部导入） | 删除未用导入 |
| `tests/test_scene.py`、`test_server_lifecycle.py` | 未用局部变量 2 处（`before`、`release`） | 删除 |
| `tools/analyze_recording.py`、`tools/sync_wiki_chains.py` | 未用导入 2 处 | 删除 |
| `tools/frontend.py`、`tools/sync_catalog_resources.py` | `sys.path` 注入后的模块级导入（E402）是有意的 | 加 `# noqa: E402` 并注明原因 |

### 3.2 前端死组件与死样式

| 对象 | 证据 | 处理 |
| --- | --- | --- |
| `frontend/src/components/EggAvatar.vue` | 全仓无 import/模板引用，仅文档提及；图标渲染已由 `EggBoxArtwork`/`PetArtwork` 等承接 | 删除 |
| `frontend/src/components/PetDetailMedals.vue` | 全仓无引用；详情奖牌现由 `PetDetailHero` → `PetMarks` 渲染 | 删除（见 §6.3 功能入口缺口） |
| `frontend/src/components/WikiSkills.vue` | 全仓无引用；且模板使用 `UiSearch` 却未导入，挂载即报错，属废弃分支 | 删除（见 §6.3） |
| `static/app.css` 中 `.hb-grid/.hb-card/.hb-head/.hb-key/.hb-art/.hb-meta/.hb-sum/.hb-badge/.hb-evo/.hb-more` 整块（40 行）+ 两处选择器列表里的 `.hb-card/.hb-stat` | 全仓无该类名宿主（`HandbookPage.vue` 只用 `#hb-grid` 与 `dex-browser-grid`） | 删除 |
| `static/ui.css` 中 `.hb-card:focus-visible`、`.hb-head > div` | 同上 | 从选择器列表移除/删规则 |
| `static/ui.js` 的 `click` 委托分支（`#hb-grid .hb-card, #eb-grid .hb-card`） | 两个选择器在现 DOM 中都不存在，且 Vue 页已有 `[data-vue-page]` 早退 | 删除该监听器 |

### 3.2b 原生详情抽屉收敛（第二轮）

`ui.js` 的 `openDetail` 已无调用方（`app.js` 只调 `closeDetail`，而 `closeDetail` 在 `activePanel` 为空时直接返回），
详情抽屉的焦点陷阱、背景 `inert`、遮罩与返回焦点都已由 `PetDetailPanel.vue` 自管。本轮按"收敛"方案删除：

| 对象 | 处理 |
| --- | --- |
| `static/ui.js` 的 `openDetail / closeDetail / decorateDetail / syncDrawer / isModal`、`activePanel / returnTarget / narrow / backdrop / observer / inertNodes` 状态、Escape 与 Tab 焦点循环分支、遮罩点击与断点监听 | 删除；`ui.js` 从 130 行降到 25 行，只保留 `[role='button'][tabindex='0']` 的 Enter/Space 激活与精灵筛选面板开关 |
| `window.SpriteLensUI` | 连同导出一起删除（全仓已无调用方） |
| `index.html` 的 `<div id="detail-backdrop">` | 删除（唯一消费者是已删的 `ui.js` 监听器；Vue 页面各自渲染 `.detail-backdrop`） |
| `ui.css` 的 `.drawer-open .page.active` 规则 | 删除（唯一写入方是被删的 `syncDrawer`，从未生效） |
| `app.js` 两处 `window.SpriteLensUI.closeDetail(false, true)` | 删除（空操作） |
| 文档 | `CODEBASE_MAP` 的 `ui.js` 职责、`UI_GUIDE` §4 的详情约定改为"由 Vue `PetDetailPanel` 独占" |

保留未动：`.detail-panel` / `.detail-open` / `.detail-closed` / `.detail-collapsed` / `.detail-close` 的 CSS 规则——
它们与 `EggBoxPage.vue` 等页面共用 `.detail-panel` 选择器（窄屏媒体查询里会隐藏该面板），
删除会改变窄屏布局；其"原生产者已消失"的状态记在 §6.3。验证：`node --check` 通过、
`tools/frontend.py build` 通过（8 个产物）、`test_build / test_frontend_contract / test_ui_upgrade / test_web_server` 57 项通过。

### 3.3 死资源与仓库卫生

| 对象 | 证据 | 处理 |
| --- | --- | --- |
| `nuitka-crash-report.xml`（仓库根，1.9 MB） | 已列入 `.gitignore` 的构建崩溃产物，`build.py`/`build_config.toml`/工具均不读取 | 删除 |
| 14 个 `__pycache__/` 目录 | 字节码缓存（含 `tests/`、`tools/`） | 删除 |

复核后**保留**：`static/type-icons/sprites.css`、`static/type-icons/sprite-0.webp` 虽然运行时不引用
（页面只用 `type-{n}.webp`），但 `tools/import_assets.py` 把它们当作母版、按 `sprites.css` 里的
雪碧图坐标裁剪出 `type-{n}.webp`。删除会切断属性图标的复现链路，本轮撤回删除并保持原样。

### 3.4 文档

| 文件 | 问题 | 处理 |
| --- | --- | --- |
| `docs/CODEBASE_MAP.md` | 两处指向已删组件；缺近期 20+ 个模块（`navigation_scene`、`pet_partner_marks`、`retention`、`home_store`、`scene_checkpoint_store`、`ext_api`、`debug_preview`、`nearby`、`process_watch`、引导/设置壳脚本等） | 修正组件行（注明替代渲染链路与删除原因）；新增「2026-11-15 健康检查补齐的模块」表，职责取模块文档字符串 |
| `docs/UI_GUIDE.md` | §4 帮手表仍列 `petAvatarHtml / eggAvatarHtml / glassStyle / petChip`，这些函数已随原生卡片迁移删除 | 更新为现存 `esc / toast / copyText / levelColor / setPill`，并注明变更来源 |
| `docs/README.md` | `PET_PRESENTATION_VERIFICATION.md` 未被索引；本文未入索引 | 补两条索引 |

### 3.5 三份维护文档的逐段事实核对（第三轮）

范围：`ROADMAP.md`（481 行）、`UI_GUIDE.md`（382 行）、`BREEDING_PLANNER_SPEC.md`（526 行）。
方法：先做路径/命令可解析性脚本，再按四类断言逐条用代码证据核对——命令与路径、字段与 DTO 契约、
行为声明、状态口径（"已实现/待验收/已删"）。核对结论只认代码与测试，不认文档自我引用。

| 文档 | 核对条目 | 过期 | 不一致 | 需补注 | 未验证 |
| --- | --- | --- | --- | --- | --- |
| `UI_GUIDE.md` | 44 | 11 | 10 | 9 | 1 |
| `BREEDING_PLANNER_SPEC.md` | 35 | 3 | 11 | 5 | 1 |
| `ROADMAP.md` | 路径 31 / 命令 2 + 状态句 72 | 1 类 | 3 类 | 2 类 | — |

代表性修正（均为可直接改变实现行为的错误）：

- **UI_GUIDE**：token 表把 `--radius` 写成 `sm/md/lg=6/8/12`（实际 `xs/sm/md/lg=6/8/10/12`，缺 `--space-8=24px`、
  `--radius-xl/pill`）；图表变量 `--chart-h/w/v` 与 `.body-bar` 已不存在（只剩 `--chart-v` 兜底）；
  组件表把已删的 `.hb-card/.pet-card/.pager/.mm-pet/.pc-avatar`、`petChip()/glassStyle()` 当现行结构；
  工具条规则按"窗口 − 230px 侧栏"算面板（背包页侧栏实际 64px，`ui.css:454-455`）；
  "数据更新不得造成 UI 闪动"整节仍按**缺陷现状**描述，而 `useNearby.ts` 已改成 `autoLoadSoon` 合并、
  `NearbyPage.vue` 已用局部 `refreshing`、虚拟列表已做锚点补偿——已改写为"现行机制 + 历史根因"。
- **BREEDING_PLANNER_SPEC**：目标字段写成 camelCase（`goalId/eggKey/...`），实际 DTO 全 snake_case；
  `primaryGoalId`/`supportMotherCount`/`primaryMotherCount`/`schemaVersion`/`geometryRuleVersion`
  均不是现有字段名；"拖动按 0.5 格吸附"实为 1 格（半格只在接口校验层允许）；"可平移、缩放"实际只有自动适配；
  "分支限界＋交换改进"实为束宽 2 的确定性束搜索；"择优参与"的排序项只有 3 项；
  草稿"点击保存才持久化"已改为 150ms 自动落盘；"未取蛋/取蛋后继续"在代码中不存在，已标"未实现"。
- **ROADMAP**：测试文件规模数字过期（1136/600/527 → 1327/802/806）；F03-U3 声称交付的"横向获得奖牌"条
  已无渲染入口（组件删除，见 §3.2）；§8 七项待办里 4 项代码已有入口（随游戏启动/随游戏开启采集/首次引导/
  双牌悬浮监控），2 项无代码，1 项部分；另有一处散落的字面 `\n` 残留。

未验证项（保持原样并已标注）：`UI_GUIDE` 的工具栏 51/93/135px 是否来自实测（CSS 无硬编码高度规则）、
`BREEDING_PLANNER_SPEC` 的 2,000 只合成仓库 2.45 秒性能样本（本次未复跑）。

不在本轮范围：`UI_COMPONENTS.md`、`NEARBY_OBSERVATIONS.md`、`PROTOCOL_NOTES.md`、`ARCHITECTURE.md` 等其余文档
只做了链接与路径级校验，未逐段核对内容。

## 4. 验证证据

| 项 | 命令 | 结果 |
| --- | --- | --- |
| Python 全量 | `.venv\Scripts\python.exe -B -m unittest discover -s tests -q` | `Ran 783 tests ... OK (skipped=2)`（97.7 s） |
| Python 定向 | `unittest tests.test_pet_vm tests.test_persistence tests.test_scene tests.test_monitor_service tests.test_session_resume tests.test_wiki_chains tests.test_desktop_shell tests.test_egg_box tests.test_pets tests.test_server_lifecycle tests.test_view_models tests.test_web_server` | 通过 |
| 自检 | `python -m spritelens --smoke-test` | 通过（协议/服务/配置/网卡/静态目录） |
| Python 静态 | `ruff check spritelens tools tests build.py main.py --select F` | `All checks passed` |
| 前端类型 | `npm run typecheck` | exit 0 |
| 前端测试 | `npm test` | 260 passed / 1 skipped（既有 smoke 跳过） |
| 前端产物 | `python -B tools/frontend.py build` | 构建 + 产物哈希校验通过 |
| 文档链接 | 相对链接批量解析 | 全部可解析 |
| 静态引用 | `index.html`/`radar.html` 的 `/static/*` 目标存在性 | 0 缺失 |
| 前端 JS 语法 | `node --check spritelens/web/static/ui.js` | 通过 |

工具版本：`ruff 0.17.5`、`vulture 2.16`（2026-11-15 装入当前 venv，已写入 `requirements-dev.txt`，
标注为"仅用于清点、不构成门禁"）。

未覆盖：真实 WebView2 窗口、真实游戏流量、打包态 exe 与本次改动无关，未重复验收。

## 5. 复杂度热点（未改，按 ROADMAP 推进）

统计口径：分支节点（if/for/while/try/with/BoolOp/IfExp）≥ 14 或函数体 ≥ 90 行，共 78 个函数。
建议优先顺序（按调用热度 × 现有复杂度）：

| 位置 | 分支 | 行数 | 备注 |
| --- | --- | --- | --- |
| `services/scene_repository.py:338 handle_packet` | 89 | 211 | 附近观察主链路，`CODEBASE_MAP` 已标关注区 |
| `domain/breeding_solver.py:100 solve` | 83 | 169 | 有预算搜索，纯函数，可先补边界用例再拆 |
| `domain/breeding_planner.py:145 evaluate` | 74 | 149 | 同上，规则与展示耦合 |
| `web/payloads_catalog.py:613 egg_box_payload` | 67 | 158 | 载荷层，可拆行/详情/筛选三段 |
| `web/payloads_catalog.py:462 home_payload` | 60 | 150 | 同上 |
| `domain/static_data.py:140 _load` | 58 | 111 | 启动期一次性解析，风险低于前五项 |

其余热点集中在 `pet_locations.update_backpack`、`navigation_scene.submit`、`pet_repository.handle_packet`、
`ui_preferences.validate_shortcuts`、`payloads.pet_row`、`pet_vm._apply_filters_with`。
本轮不做机械拆段（`DEVELOPMENT_GUIDE` 明确禁止为行数而拆），只在文档侧登记。

## 6. 发现但本轮未处理

### 6.1 风格类告警（低价值 diff）

`ruff` 在 `E501`（超长行）、`SIM*`、`C4*`、`B*`、`E731`（测试内 lambda 助手）等规则上仍有 300+ 命中。
这些不是死代码，统一格式化会产生大面积无关 diff，按 `DEVELOPMENT_GUIDE` 不纳入日常清理；
如需长期收敛，建议单独一轮"仅格式化"提交并冻结其余改动。

### 6.2 依赖与并发

- 前端测试环境开销**已处理**：原 `Environment jsdom was created 35 times · 74.09 s total`；
  `frontend/vite.config.ts` 改用 `pool: 'vmThreads'` 后 jsdom 按 worker 建一次，全量耗时
  8–9 s → **5.26 / 4.52 / 4.60 s**（连跑三次，260 用例全过），文件级隔离保留，构建产物不受影响。
  口径与命令见 `DEVELOPMENT_GUIDE.md#验证命令`。
- 推送循环已具备 PERF07 优化（无订阅时只推进插值、JSON 未变则不广播），未见新的整份重算热点。

### 6.3 功能入口缺口（需产品决策，不建议静默删除数据）

- 详情页"全部奖牌"横条（`pet.detail.awarded_medals` 全量）当前无挂载入口：`PetDetailHero` 只渲染
  `PetMarks` 的奖牌标记。数据仍随详情 DTO 下发。若产品要保留该视图，应在 `PetDetail.vue` 显式挂载并补视觉验收。
- 图鉴技能列表：`wiki.skills` 仍由 `domain/wiki_reference.py` 生成、`types/wikiReference.ts` 仍做运行校验，
  但页面不渲染（原 `WikiSkills.vue` 已删）。若要裁剪载荷需同步改后端、DTO 与 `test_wiki_reference.py`。
- `pet.skills` 同理：`types/pets.ts` 校验但无渲染点。
- `~window.SpriteLensUI~` 与原生详情抽屉已在第二轮删除，见 §3.2b；CSS 侧的 `.detail-open/.detail-closed/
  .detail-collapsed/.detail-close` 仍无生产者，因与 `EggBoxPage.vue` 共用 `.detail-panel` 选择器未动，
  后续如果要清，需要先补一次窄屏目视验收。

### 6.4 文档继续漂移的风险

`CODEBASE_MAP` 本轮补齐了源码侧缺口，`ROADMAP` / `UI_GUIDE` / `BREEDING_PLANNER_SPEC` 三份已逐段核对（见 §3.5）。
仍未覆盖的：`UI_COMPONENTS.md`、`NEARBY_OBSERVATIONS.md`、`PROTOCOL_NOTES.md`、`ARCHITECTURE.md`、
`CAPTURE_DIAGNOSTICS.md`、`HOME_IMPLEMENTATION_PLAN.md` 等只做了链接/路径级校验。
另：`docs/*.md` 仍有 5 份只在自身标题出现的文档（`EXT_API.md` 已在索引、`PET_PRESENTATION_VERIFICATION.md`
本轮补索引；`archive/` 下 3 份只被归档索引点名）。
建议在新增模块时同步追加 `CODEBASE_MAP` 行，并沿用 §3.5 的四类断言做增量核对，避免再次累积 20+ 条缺口。

### 6.5 本地产物（未删除，仅登记）

| 目录 | 文件数 | 体积 | 性质 |
| --- | --- | --- | --- |
| `build/` | 20 963 | 2 367.6 MB | Nuitka 打包缓存，删除后需冷构建（约 25 分钟，见 BUILD_TIME_RESEARCH） |
| `output/` | 8 784 | 998.8 MB | 历史验收/预览产物（含 CDP profile） |
| `.guishot/` | 4 951 | 519.8 MB | GUI 截图校验的浏览器 profile |
| `.research/` | 698 | 107.2 MB | 竞品解剖临时产物 |

四者均在 `.gitignore` 内、不入库，可随时回收约 3.99 GB；本轮不删除，避免丢失验收证据与重建成本。

### 6.6 工作区状态

本轮开始时工作区已有 80+ 个未提交改动（含 `frontend/src/composables/useDexDisplay.ts` 删除与多个新文件），
本次清理叠加在其上，按文件级最小改动执行，未回滚或覆盖任何既有改动。

### 6.7 行尾统一（已处理）

`.gitattributes` 约定 `* text=auto eol=lf`（仅 `*.bat` / `*.ps1` 保留 CRLF），但工作区有 28 个受版本控制的
文本文件仍是 CRLF：`data/static/*.json`、`data/schemas/opcodes.json`、`docs/ARCHITECTURE_DECISION.md`、
`docs/DANSHEN_FEATURE_SPEC.md`、若干 `frontend/src/**`、`tests/*.py`、`spritelens/**/*.py`、
`resources/*.csv|json`。全部按字节把 CRLF 换成 LF（`.bat/.ps1` 与二进制未动）。

- 该操作**不改内容**：索引里这些文件的 blob 本就是 LF，转换后工作区字节与 blob 一致。
  用临时索引实测 `git add` 后 `git diff --cached --numstat` 对这些文件为空，不会产生"整文件重写"的提交噪音。
- `git status` 可能对这些文件显示 ` M`，那是索引 stat 缓存未刷新，`git diff`/`git diff --cached` 均为空；
  下次 `git add` 或重新检出即消失。
- 受影响的测试模块复验：`tests.test_scene_coverage_store`、`test_web_server`、`test_home`、`test_radar_window`、
  `test_wiki_reference` 共 73 用例通过。
- 与本节无关但同源的噪音：`git add` 时的 `CRLF will be replaced by LF` 警告应不再出现。

## 7. 建议的下一步（按投入产出排序）

1. 处理 §6.3 的两个入口缺口（奖牌横条、技能列表）：确认保留或裁剪，二者都要改 DTO/测试，越早定口径越省。
2. ~~前端测试环境改 `pool: 'vmThreads'`~~ 已随第二轮处理，见 §6.2；后续只需在新测试文件增多时复测耗时。
3. 按 ROADMAP 单编号推进 §5 前两项（`scene_repository.handle_packet`、`breeding_solver.solve`），
   每次只拆一段并保留原异常路径回归。**本轮按用户要求未动。**
4. 若磁盘紧张，先清 `output/` 与 `.guishot/`（1.5 GB，可再生），再考虑 `build/`。
5. 新增模块时同步 `CODEBASE_MAP` 与 `docs/README.md` 索引，并沿用 §3.5 的四类断言做增量核对。
6. 其余文档（§6.4 列出）仍待逐段核对；`UI_GUIDE` 的 51/93/135px 与配窝 2.45 秒样本两个"未验证"项，
   需要真实窗口测量/复跑样本才能定论。
