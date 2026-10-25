# SpriteLens 交接文档：数据库数据恢复与伙伴标记

状态：**已完成**（2026-10-24 收尾）。数据已恢复、迁移已落地并提交、点阵顺序已修正并验收；实际执行记录见 §十一，遗留事项见 §十。

日期：2026-10-24（Asia/Shanghai）

读者：本工作区的维护者、审查者和 AI 协作者。本文前半是事故与恢复的完整记录，后半是收尾结果。

## 一、先看结论

一次数据库结构变更触发了启动时的空库重建，用户数据被搬进 `.incompatible-*.sqlite` 后应用继续用空基线运行。2026-10-24 已完成收尾：

- 用户数据已恢复：主库现为 1 个账号、1389 个精灵、613 个蛋、1 条箱位快照，`PRAGMA integrity_check` 返回 `ok`。
- 恢复前现场留证：`spritelens.empty-before-recovery-20261024-183036.sqlite`（65536 字节的空基线，含当时的 `-wal`/`-shm`）。
- 三个 `.incompatible-*.sqlite` 备份全部保留，未删除、未改名。
- 启动时已按 `partner_mark` 完成原地加列；连续两次关闭重启后行数不变，没有产生新的 `.incompatible-*` 备份。
- 未知结构不再静默重建：库内已有数据时阻止启动并保留原文件（§六）。
- 伙伴标记顺序已修正为「性别 → 伙伴标记 → 已有标记 → 性格」，并在真实 6 列点阵上完成几何与目视验收（§十一.3）。
- 伙伴标记字段号已用真实游戏流量确认（`PetData` 78），并与洛克助手实现交叉验证；1,308 只展示宠物中 638 只的真实标记已回填本地库，真实数据渲染验收通过（§十一.6）。

口径提醒：数据库 `pets` 有 1389 行，但界面显示 1308 只——差的 81 只是按既有规则（`spritelens/services/pet_repository.py` 排除 `is_trial_pet` / `is_mirror_pet`）不计入展示，不是数据丢失。

## 二、用户真实需求与已拒绝方向

用户要求的是精灵背包点阵中的伙伴标记只读展示：

1. 伙伴标记显示在性别图标右侧。
2. 顺序应为：`性别图标 → 伙伴标记 → 已有标记 → 性格`。
3. 标记由游戏内设置，SpriteLens 只读取游戏数据并展示。
4. 软件内不能提供设置、编辑、保存或 POST 标记的入口。
5. 用户给出的左上角标记样式图仅用于视觉参考；游戏全标记列表图仅用于素材参考。

此前曾有一版错误实现增加软件内可编辑标记和 `pet_annotations` 表，之后代码层已撤回；但该表曾经写入过本地数据库结构。最新备份中的 `pet_annotations` 表行数为 0，仍应保留表或通过兼容逻辑忽略，不要无备份删除未知表。

## 三、数据事故证据

运行数据根目录是 `%LOCALAPPDATA%\SpriteLens`，除非设置了 `SPRITELENS_DATA_ROOT`。

### 3.1 当前主库

文件：`spritelens.sqlite`

当前检查结果：

| 项目 | 结果 |
|---|---:|
| `PRAGMA user_version` | 1 |
| accounts | 1 |
| pets | 0 |
| eggs | 0 |
| `PRAGMA integrity_check` | ok |
| `pets.partner_mark` | 存在 |

这是重建后的当前基线空库，不是用户原始数据。

### 3.2 最近一次重建前备份

文件：`spritelens.incompatible-1792836638.sqlite`

日志时间：2026-10-24 18:10:35 左右。

| 项目 | 结果 |
|---|---:|
| `PRAGMA user_version` | 1 |
| accounts | 1 |
| pets | 1389 |
| eggs | 613 |
| `pet_locations` | 1 |
| `pet_annotations` | 存在，0 行 |
| `pets.partner_mark` | 不存在 |
| `PRAGMA integrity_check` | ok |

这是默认恢复候选，因为它最接近用户最后一次重启前的状态。

### 3.3 更早备份

文件：`spritelens.incompatible-1792835416.sqlite`

日志时间：2026-10-24 17:50:11 左右。

| 项目 | 结果 |
|---|---:|
| `PRAGMA user_version` | 1 |
| accounts | 3 |
| pets | 4143 |
| eggs | 810 |
| `pet_annotations` | 不存在 |
| `pets.partner_mark` | 不存在 |
| `PRAGMA integrity_check` | ok |

这份数据量更大，可能是另一个更早的运行状态。恢复前应保留它，不要自动删除。

### 3.4 更老的旧 schema 备份

文件：`spritelens.incompatible-1792696919.sqlite`

它的 `user_version` 为 16，包含旧表 `pet_voice_overrides`，有 2 个账号、1711 个精灵、649 个蛋。除非前两份都不符合用户预期，否则不要优先恢复这份。

## 四、根因与时间线

### 根因

`spritelens/repositories/database.py` 的旧逻辑把 schema 1 当作“完整 DDL 基线”，启动时直接比较 `sqlite_master` 中的完整 SQL。只要结构不完全相等，就执行：

1. 把原库改名为 `.incompatible-时间戳.sqlite`；
2. 创建当前基线的新库；
3. 应用继续启动。

这套机制在开发期本意是“备份后重建”，但用户体验上就是“重启后数据没了”。它没有针对普通的新增字段做迁移。

本次同时发生了两个结构差异：

- 当前基线的 `pets` 表新增了 `partner_mark INTEGER NOT NULL DEFAULT 0`；旧库没有该列。
- 之前撤回的错误伙伴标记实现留下了 `pet_annotations` 表；当前基线不包含该表。

因此精确 DDL 比较失败，启动时自动重建空库。

### 日志证据

`logs/spritelens.log` 已记录：

```text
2026-10-24 17:50:16 WARNING ... 数据库结构不兼容，原库已备份到 ...spritelens.incompatible-1792835416.sqlite，已重建当前基线
2026-10-24 18:10:38 WARNING ... 数据库结构不兼容，原库已备份到 ...spritelens.incompatible-1792836638.sqlite，已重建当前基线
```

## 五、伙伴标记与迁移改动（已提交）

本轮伙伴标记和恢复修复相关的改动已拆成两个提交：

- `744c938 fix: migrate pets.partner_mark in place and stop silent database rebuilds`：数据层（`domain/pets.py`、`repositories/pet_store.py`、`repositories/database.py`、`tests/test_pets.py`、`tests/test_persistence.py`、`tests/test_partner_mark_migration.py`）。
- `f631481 feat: show the in-game partner mark on backpack pet cards`：展示层（`web/payloads.py`、`web/static/partner-marks/`、`web/static/ui.css`、`web/static/backpack-layout.css` 的伙伴标记规则、前端类型与组件、`tools/run_web_demo.py` 的极限数据集）。

工作区仍有大量账号、场景、雷达等其他未提交改动（见 §十一.5），禁止用 `git reset --hard`、`git checkout --` 或大范围清理覆盖它们。

### 5.1 伙伴标记数据链路

- `spritelens/domain/pets.py`
  - 从协议 `PetData` 字段号 78 读取 `partner_mark`。
  - 0 表示无标记。
  - 字段号由真实事件日志、洛克助手 C# 抓包服务、同族采集器与社区 schema 库四方交叉确认，证据见 `docs/PROTOCOL_NOTES.md` 的「伙伴标记字段确认（PetData 78）」。
- `spritelens/repositories/pet_store.py`
  - 将 `partner_mark` 写入和读出 `pets` 表。
- `spritelens/repositories/database.py`
  - 当前基线 `pets` 增加 `partner_mark` 列。
- `spritelens/web/payloads.py`
  - 将标记 ID 映射为只读 payload 和本地资源 URL。
  - 0 或未知 ID 返回 `null`，不伪造图标。
- `frontend/src/types/pets.ts`
  - 增加 `PartnerMark` 类型和 payload 校验。
- `frontend/src/components/PetPartnerMark.vue`
  - 只渲染图片，没有按钮、点击、编辑或提交逻辑。
- `spritelens/web/static/partner-marks/`
  - 已下载 frame 和 9 个标记素材。

参考的公开映射来源：`https://github.com/zxsos/rocom-go`。素材授权和长期来源仍应由接手者确认。

### 5.2 UI 顺序与尺寸（交接时的未完成问题，已解决）

`frontend/src/components/PetSlots.vue` 当前插入顺序是：

```text
伙伴标记 → 性别 → 已有标记 → 性格
```

这是错误的，用户已经明确指出目标是：

```text
性别 → 伙伴标记 → 已有标记 → 性格
```

下一位开发者必须把 `PetPartnerMark` 移到 `.pc-gender` 后面、`.point-markers` 前面，并重新按真实 6 列点阵检查，而不是使用孤立的合成卡片作为验收依据。

此前预览还存在这些视觉问题：

- 预览是单张测试卡，不代表真实背包点阵结构。
- 标记显示约为 20×20，用户目标位置的独立槽位明显更大。
- 预览没有还原目标图中已有标记和性格标签的完整排列。
- 不能仅凭“资源能加载”和“单卡不重叠”宣布 UI 完成。

**已解决（2026-10-24 收尾）**：`frontend/src/components/PetSlots.vue` 已把 `PetPartnerMark` 移到 `.pc-gender` 之后（`f631481`），顺序为「性别 → 伙伴标记 → 已有标记 → 性格」；验收不再用孤立的合成卡片，而是真实库快照与极限数据集在 1440/1280/960/864（最小支持窗）/760/640 宽度、DPR2 与字体回退下测量真实 6 列点阵几何并逐张目视（见 §11.3、§11.6）。尺寸与「灰色边框」问题随后由 `d9618a0`（图标 18×18、去掉素材里烘焙的投影）与 `f808957`（性别与标记间距 4px）解决，单卡 20×20 的旧口径作废（见 §12.1）。

## 六、数据库修复补丁的当前状态

`spritelens/repositories/database.py` 的迁移与保护逻辑（已复核，随 `744c938` 提交）：

- 只识别“当前 schema 1 除 `pets.partner_mark` 外完全相同”的已知旧结构。
- 创建新的完整 `pets` 表，将旧数据原样复制，`partner_mark` 默认填 0。
- 重建 `idx_pets_conf` 和 `idx_pets_level`。
- 保留额外旧表，例如空的 `pet_annotations`，不擅自删除未知数据。
- DDL 比较忽略空白和 SQLite 重命名产生的简单标识符引号——这一步是承重条件：`ALTER TABLE ... RENAME TO pets` 会把 DDL 改写成 `CREATE TABLE "pets" (...)`，下次启动全靠归一化才能与基线原文相等。
- 其余未知结构：库内没有任何业务数据时才备份后重建；库内已有数据时抛 `DatabaseSchemaError(rebuild_allowed=False)`，原文件逐字节不变，经 `web/run.py` 变成错误框 + 退出码 1，不再产生空库。
- 遗留风险：迁移只认这一种旧结构。pets 列顺序变化、缺索引、索引名不同等差异在有数据的库上都会安全失败并阻止启动，后续版本需要逐条补迁移函数。

四个待复核问题的结论（用例见 `tests/test_partner_mark_migration.py`，18 项）：

1. 迁移事务失败能完整回滚：迁移包在单个事务里、且在切 WAL 之前执行；authorizer 在 INSERT / DROP TABLE / 两个 CREATE INDEX / BEGIN+COMMIT 注入拒绝后，`sqlite_master` 逐条不变、无 `pets_partner_mark_migration` 残留、索引仍在，可再次成功迁移。忙锁抛错也不会被误判成损坏而重建。
2. 重启两次仍保留数据（幂等）：真实备份副本开关两次，结构与数据全等、无第二份 `.incompatible-*`。
3. WAL/SHM：只存在于 `-wal` 的已提交行在迁移后保留；备份清理期失败时原组字节不变，并留下完整的三成员备份组，不留半个备份。
4. 未知 schema 自动重建：已改为“库内有数据则阻止启动”（见上），不再静默产生空库。

## 七、恢复操作（已于 2026-10-24 执行，留作复现步骤）

实际执行与验证结果见 §11.1–§11.3；下面保留当初的操作口径，便于事故重演时复用。

### 7.1 前置条件

1. 完全退出 SpriteLens，确认没有两个 `pythonw main.py` 进程。
2. 不删除或移动任何 `.incompatible-*.sqlite` 文件。
3. 先复制当前空主库作为恢复前现场，例如：

```powershell
$root = Join-Path $env:LOCALAPPDATA 'SpriteLens'
Copy-Item -LiteralPath (Join-Path $root 'spritelens.sqlite') `
  -Destination (Join-Path $root 'spritelens.empty-before-recovery.sqlite')
```

如果主库有 `-wal` 或 `-shm`，也要一并保留现场；不要在应用仍运行时复制或覆盖主库。

### 7.2 默认恢复候选

最近备份是：

```text
%LOCALAPPDATA%\SpriteLens\spritelens.incompatible-1792836638.sqlite
```

关闭应用并保留当前空库副本后，可将该备份复制回 `spritelens.sqlite`，再由当前代码启动时执行 `partner_mark` 原地迁移。

### 7.3 恢复后必须验证

至少执行：

```powershell
$env:SPRITELENS_DATA_ROOT = Join-Path $env:LOCALAPPDATA 'SpriteLens'
.venv\Scripts\python.exe -c @'
import os, sqlite3
from pathlib import Path
root = Path(os.environ['SPRITELENS_DATA_ROOT'])
path = root / 'spritelens.sqlite'
con = sqlite3.connect(path)
print('integrity:', con.execute('PRAGMA integrity_check').fetchone()[0])
print('accounts:', con.execute('SELECT COUNT(*) FROM accounts').fetchone()[0])
print('pets:', con.execute('SELECT COUNT(*) FROM pets').fetchone()[0])
print('eggs:', con.execute('SELECT COUNT(*) FROM eggs').fetchone()[0])
print('partner_mark:', any(row[1] == 'partner_mark' for row in con.execute('PRAGMA table_info(pets)')))
con.close()
'@
```

然后连续关闭并重新启动应用至少两次，确认数量没有回到 0。第一次启动后应确认 `partner_mark` 列存在、旧精灵数量仍为 1389，且未知旧表没有导致重建。

## 八、已执行验证

数据库修复补丁加入后的最近一次定向 Python 测试：

```text
.venv\Scripts\python.exe -m unittest tests.test_persistence tests.test_pets tests.test_pet_presentation
Ran 67 tests ... OK
```

已验证的临时副本迁移结果：

- 复制最近备份到临时路径后，`Database` 能完成迁移。
- 迁移后 `pets` 仍为 1389 行。
- `partner_mark` 列存在，默认值为 0。
- `pet_annotations` 仍存在且没有被删除。
- `PRAGMA integrity_check` 为 `ok`。

此前前端相关验证：

- `PetPartnerMark.vue` 测试 2 项通过。
- `usePets` + 伙伴标记组件测试共 11 项通过。
- TypeScript typecheck 通过。
- 前端构建和 `tools/frontend.py check` 通过。
- `git diff --check` 通过。

这些结果不能替代真实恢复后的桌面重启验收；前端构建需要在修正标记顺序后重新执行。

## 九、交接时禁止做的事

- 不要删除 `.incompatible-*.sqlite` 备份。
- 不要直接运行 `git reset --hard` 或 `git checkout -- .`。
- 不要在应用运行时替换 SQLite 主库。
- 不要恢复软件内设置伙伴标记的按钮、接口或 `POST` 路由。
- 不要把未知 `partner_mark` ID 映射成猜测图标。
- 不要用单卡截图或构建成功代替真实点阵布局验收。
- 不要声称用户数据已恢复，除非恢复后连续重启验证通过。

## 十、下一步与遗留事项

交接时的 8 步已全部完成，实际执行记录见 §十一、§十二。以下按「仍需验证」「需要决策」「工作区账目」列出剩余事项。

### 10.1 仍未验证（需要真实环境或真实对局）

1. 真实 WebView2/pywebview 桌面窗口内的渲染：全部证据来自 headless Edge + 真实 LocalServer + 真实发布产物；Windows 系统级 125%/150% 缩放也未实测（只做了 CSS DPR2 与字体回退模拟）。
2. “筛掉”筛选空态截图：箱 2 无已采集精灵时产生不了 filtered 态；应在箱 1 上输入搜索词后重跑。
3. 伙伴标记的实时跟随：游戏内更换/摘除标记后本软件是否实时更新（按逻辑每次 `PetData` 观测都会更新，但未在真实对局中专门验证）；8 号标记未在当前账号流量中出现。
4. 记录数据上限的真实路径：跨天/切分片触发的清理（需要长时间运行）、Windows 文件占用导致删除失败的真实告警（目前只有单测注入 `OSError`）。`storage.*` 按用户决定不暴露 UI 设置页，只能手改 `config.json`。
5. 数据库迁移的长期覆盖：当前只认 `pets.partner_mark` 一种旧结构。之后改表需要按 `_migrate_partner_mark_column_locked` 的形式逐条补迁移，否则有数据的库会安全失败并阻止启动（这是有意的安全行为，但升级路径需要规划）。

### 10.2 已决事项（2026-10-24 第四轮，用户确认）

1. 伙伴标记素材授权与长期来源：**决定保持现状**（继续用 `https://github.com/zxsos/rocom-go` 的公开映射，不补来源说明、不动 `img_biaoji_wu_png.webp` 等未引用素材）。
2. 交接文档入库：**决定不入库**（继续作为工作区未跟踪文件维护内容，不 `git add`）。

### 10.3 工作区账目（2026-10-24 收尾后）

- 本线仍未提交的文档修正（同一文件夹带雷达/附近工作线内容，需按 hunk 拆分）：`AI_CONTEXT.md`（数据库结构策略段）、`ARCHITECTURE.md`（同段）、`CODEBASE_MAP.md`（`repositories/database.py` 行与本文档条目）、`DEVELOPMENT_GUIDE.md`（持久化约定段）、`PROTOCOL_NOTES.md`（伙伴标记 78 段）、`README.md`（索引行）。`UI_GUIDE.md` 的伙伴标记规则行已随 `d9618a0` 提交。
- 未入库的新文档/工具：`docs/HANDOFF_DEEPSEEK_2026-10-24.md`、`docs/NEARBY_OBSERVATIONS.md`（雷达线）、`tools/import_scene_catalog.py`（雷达线）。
- 其余为雷达/附近精灵/账号/场景/采集诊断工作线（60 余个文件），不属于本文范围。
- 临时脚本（`tools/_tmp_*.py`、`tools/_layout_preview/`、`_preview/`、`.tmp-*`）已删除；验收截图与 metrics 保留在 `/output/layout-preview/`、`output/partner-marks-real/`、`output/badge-v2/`、`output/badge-v3/`（均在 gitignore 的 `/output/` 下）。重跑方式：`.venv\Scripts\python.exe tools\frontend.py build` → `.venv\Scripts\python.exe tools\run_web_demo.py --scenario extreme --no-open` → 用 CDP 无头浏览器测量 `.point-top` 子元素几何（真实库验收则先用 `sqlite3` backup API 取快照并设 `SPRITELENS_DATA_ROOT`）。

## 十一、2026-10-24 收尾记录（实际执行）

### 11.1 前置检查

- 没有 `pythonw main.py` / `python main.py` 进程持有主库（Win32_Process 命令行无匹配；ctypes `CreateFileW` 独占打开成功）。
- 三个 `.incompatible-*` 备份齐全；主库为 65536 字节空基线（1 账号 / 0 精灵 / 0 蛋 / 已有 `partner_mark` 列）。

### 11.2 恢复动作

1. 把主库组（`spritelens.sqlite` + 当时的 `-wal`/`-shm`）复制为 `spritelens.empty-before-recovery-20261024-183036.sqlite*` 留证。
2. 校验候选 `spritelens.incompatible-1792836638.sqlite`：`integrity_check=ok`、`user_version=1`、账号 1 / pets 1389 / eggs 613 / pet_locations 1 / `pet_annotations` 0 行、`pets` 无 `partner_mark`。
3. 候选先复制到 `*.restore-staging` 复验，再替换主库，并**删除主库旧的 `-wal`/`-shm`**——旧空基线的 WAL 帧若套到新库会损坏数据。
4. 用真实装配路径 `build_app_context(autostart=False)` 启动两次，完成 `partner_mark` 原地迁移与幂等验证。

主库现值：11210752 字节、`user_version=1`、`integrity_check=ok`，tables = accounts / egg_annotations / egg_hatch_slots / eggs / home_snapshots / pet_annotations / pet_locations / pets。

### 11.3 验证结果

- 迁移后计数：accounts 1、pets 1389、eggs 613、pet_locations 1、pet_annotations 0（表保留）。
- `pets.partner_mark` 存在；恢复当时 1389 行全为 0，这是「该字段此前未实现、加列默认填 0」的结果，**不能**反推游戏里没有标记（§十一.6 已用真实流量回填 638 只）。
- 连续两次真实启动：行数、`user_version`、表集合完全不变，**没有产生新的 `.incompatible-*`**。
- Python：`tests.test_persistence` / `test_pets` / `test_pet_presentation` / `test_desktop_startup` 共 74 项通过；全仓库 57 个测试模块 549 项通过；新增 `tests/test_partner_mark_migration.py` 18 项通过。
- 前端：`npm test` 141 通过 / 1 skipped；`tools/frontend.py build`（含 `vue-tsc --noEmit`）通过并发布 4 个文件；`tools/frontend.py check` 通过。
- 点阵几何验收（真实发布产物 + `run_web_demo.py --scenario extreme`，24 张极限卡片 + 6 空格 + 12 只队伍精灵）：1440×900 / 1280×800 / 960×720 / 864×672（最小） / 760×720 / 640×720 / 864×672@DPR2 / 字体回退共 8 个有效场景，顶行几何顺序恒为 性别(w14) → 伙伴标记(w24) → 居中标记组(w40) → 性格(w40)，x 严格递增、两两无重叠、`.point-top` 无横向溢出、四个子元素完整落在顶行内、卡片无横纵裁切、页面无横向溢出（只有网格容器内部横滚，符合 UI_GUIDE）。伙伴标记恒 24×24；渲染出的标记数 17 与数据集内“已知非零标记”数精确一致，`partner_mark=0` 与未知 ID(2) 都不渲染。（**此处为第一轮验收口径**；第二轮按用户反馈改为 18×18 并修掉素材投影，见 §12.1。）
- 目视：1440×900 正常数据、864×672 最小窗与 3× 卡片特写、640×720 极窄、864×672 四种箱位空态逐张核对；长名称按既有 ellipsis 截断、性格胶囊从不截断。
- 提交：`744c938`（数据层）与 `f631481`（展示层），两个提交分别在独立 worktree 中跑通相关测试。

### 11.4 未验证项

- 真实 WebView2/pywebview 桌面窗口内的渲染（全部证据来自 headless Edge）。
- Windows 系统级 125%/150% 缩放（只模拟了 CSS DPR2 与字体回退）。
- 真实游戏内的伙伴标记分布：已用 2026-10-24 的真实事件日志确认并回填（§十一.6）；仍未验证的是「游戏内变更标记后本软件是否实时跟随」。
- “筛掉”筛选空态截图。

### 11.5 工作区剩余未提交内容

雷达/附近精灵（`SceneRadar`、`useNearby`、`NearbyPage`、`FloatingRadar`、`radar_window.py`、`scene_checkpoint_store.py`、`account_sessions.py` 等）、capture diagnostics、账号与场景相关改动，以及夹带这些内容的 4 个文档。本次只提交了伙伴标记与数据库迁移链路。

### 11.6 伙伴标记字段复核与真实数据回填（第二轮）

**纠正**：11.3 曾写「现有 1389 行全为 0，说明历史数据里没有该字段值」，这是错误推断——字段此前根本没有实现，加列时默认填 0，不能用来判断游戏里有没有标记。用户要求改用真实流量确认字段号，并参考洛克助手实现。

**字段确认**（完整证据见 `docs/PROTOCOL_NOTES.md`「伙伴标记字段确认（PetData 78）」）：

- 本机 `eventlog_2026*.jsonl`（10-10 至 10-24）：2,097 条消息、27,044 条 `PetData`、4,268 个 gid 带 `partner_mark`，取值只有 `0/1/3/4/5/6/7/14/15`。
- 洛克助手（小洛克精灵工具箱 1.0.0，.NET 抓包服务反编译 `roco_capture_service.cs`）：`Put(dictionary, "partner_mark", Proto.UInt32(fields, 78));`；同族 `roco_collector.py`：`78: 'partner_mark'`；社区 schema 库 `all.json`：字段 78 `partner_mark`。

**与本地库核对**：交集 1,308 个 gid（缺的 81 个是 `is_trial_pet`/`is_mirror_pet` 行，本就不参与展示）；其中 638 只非 0。15 个 gid 在不同时刻出现过 `0↔X`，按最新观测取值。

**回填动作**：桌面应用当时正在运行（两个 `pythonw main.py`），因此没有替换主库文件，而是走 SQLite WAL 的行级 `UPDATE`（638 行）；回填前把主库组备份到工作区 `.tmp-partner-backfill/`。回填后 `quick_check=ok`、与流量不一致 0 行，分布 `0:751、1:479、3:2、4:34、5:8、6:12、7:2、14:4、15:97`（含 81 个 trial/mirror 行仍为 0）。

**真实数据渲染验证**：用 `sqlite3` 备份 API 取真实库一致性快照到临时数据根，`build_app_context(autostart=False)` + `LocalServer` 起真实服务，headless Edge 截图：箱 1 共 30 张卡（24 箱位 + 6 队伍）渲染出 28 个伙伴标记、破图 0，图标均为 `/static/partner-marks/img_biaoji*_webp`；3× 特写目视确认顺序为 性别 → 伙伴标记 → 已有标记 → 性格。截图在 `output/partner-marks-real/`。

**代码与测试**：`spritelens/domain/pets.py` 字段注释与 `spritelens/web/payloads.py` 映射注释补上证据指针；新增 `tests/test_partner_mark_assets.py`（运行时观察到的标记 ID 必须有素材、未知 ID 不伪造图标、映射表素材齐全）。本轮提交只含这两处注释与该测试；`docs/PROTOCOL_NOTES.md` 与本文档因同文件夹带雷达/附近工作线内容仍留在工作区。

**仍未验证**：游戏内更换/摘除标记后本软件是否实时跟随（当前按每次 `PetData` 观测更新，逻辑上会跟随，但没有在真实对局中专门验证）；8 号标记未在当前账号流量中出现。

## 十二、2026-10-24 第三轮：图标边框、尺寸与记录数据上限

### 12.1 伙伴标记的「灰色边框」根因与修复

用户反馈标记「有 rgb(204, 191, 194) 色的边框」。根因不在 CSS：`spritelens/web/static/partner-marks/frame.webp` 原为 50×48，除橙色贴纸外还在边缘烘焙了半透明纯黑投影（440+ 个近黑低 alpha 像素铺满 alpha bbox）。`(0,0,0,52)` 叠在卡片浅色底 `rgb(255,240,244)` 上正好合成 `rgb(203~204,191,194)`，与截图取样一致。

修复：清除近黑低 alpha 像素（442 px）、按 alpha bbox 裁到内容，`frame.webp` 变为 44×42；`ui.css` 中 `.pet-partner-mark` 20px → 18px、内图标 58% → 62%（约 11.2px），与性别图标 14、稀有标记 16、色卡 20 的光学尺寸协调；`backpack-layout.css` 删除 24px 覆盖规则，尺寸单由 `ui.css` 决定，`.point-top-left` 的 gap 由 2px 调到 4px（用户反馈性别与标记贴得太近；最小窗左簇 14+4+18=36px，仍留约 5px 净空）。`docs/UI_GUIDE.md` 增补「不得在图标素材里烘焙半透明黑色投影」的规则与公式。

验收：真实库快照（1,308 只/可见标记 28 个）与极限数据集（36 只/24 卡/17 个已知标记）在 1440×900、1280×800、960×720、864×672（最小支持窗）、760/640 窄窗、DPR2、字体回退下均为 18×18，卡片重叠 0、卡片内溢出 0、页面横向滚动 0；截图在 `output/badge-v2/`。

### 12.2 记录数据上限设计（最终口径：近 3 天 / 合计 300MB）

`%LOCALAPPDATA%\SpriteLens` 原先只增不减：eventlog 2,037MB/10 天、recordings 290MB/422 个、根目录还留着 3 个 `.incompatible-*.sqlite` 恢复候选。用户在第三轮之后把口径收敛为「只保留近 3 天、合计最大 300MB；超过 300MB 立刻清最旧、超过 3 天清旧记录」，实现按此定稿：

- `spritelens/services/retention.py`：`eventlog/` 与 `recordings/` 合并成一个记录池，先按年龄（默认 3 天）删过期文件，再按 mtime 从旧到新删到合计 ≤ 300MB；**单个文件本身就超过上限时（升级前留下的大分片）从头部按行边界截断、保留最近尾部**，避免整份删除丢掉最近记录；正在写的文件（当天 eventlog 当前分片、录制中的 capture）永不删但计入总量；单文件删除/截断失败只 warning，`resolve()+is_relative_to` 防目录穿越、跳过符号链接。
- 默认值（`config.json` 可改，缺键/越界 clamp）：`storage.records_max_age_days=3`、`storage.records_max_mb=300`、`storage.backups_max_age_days=30`。备份是恢复手段，只按年龄清理、不参与记录池总量。主库 `spritelens.sqlite`（含 `-wal/-shm`）、`keys/`、`config.json` 永不清理。
- `spritelens/services/event_logger.py`：单个分片写满 64MB 切下一个分片（`eventlog_YYYYMMDD_pNN.jsonl`），每次切换触发 `on_rollover` 回调清理一次——这是「总量超过上限立刻清最旧」在当天生效的机制，不依赖重启或跨天；新的一天从主分片名 `eventlog_YYYYMMDD.jsonl` 重新开始，上次运行留下的大分片不会被继续追加。
- 启动清理默认不把当天分片当 `keep`：正常启动顺序下写入器还没打开文件，超限时直接截断，**重启即收敛回 300MB**（提交 `de6f1c0`）；写入器已打开（或另一实例在写）时由 `app_context` 的 `eventlog_active` 传当前分片，该文件只计入总量、不被改动。
- `spritelens/app_context.py`：装配时传 `max_part_bytes` 与 `on_rollover` 回调，启动时再跑一轮 `apply_storage_retention(..., eventlog_active=lambda: event_log.current_path)`（异常只 warning，不阻断启动）。
- `tools/cleanup_data_root.py`：默认 dry-run，`--apply` 才执行（孤儿 sidecar → 恢复用旧库移入 `backups/database-recovery-YYYYMMDD/` → 按 3 天/300MB 清理记录池 → Before/After 汇总）；面向「应用已退出」的一次性回收，不保护当天文件。
- `storage.*` **不暴露 UI 设置页**（用户明确「内部写规则就行」），只能改 `config.json`。

### 12.3 实际清理结果（已执行 `--apply`，第四轮口径）

第一轮（旧口径）：2,390.01 MB / 486 个文件 → 2,058.62 MB / 478 个文件；8 个恢复用旧库移入 `backups/database-recovery-20261024/`。

第二轮（3 天/300MB 定稿后）：Before 2,058.66 MB / 481 个文件 → After **363.19 MB / 57 个文件**，共清理 1,695.47 MB。记录池收敛到恰好 300.00 MB：`eventlog/` 只剩 `eventlog_20261024.jsonl` 300.00 MB（由 1,117.80 MB 从头部截断，首末行均为完整 JSON），`recordings/` 只剩 1 个空文件；10-20/22/23 的 eventlog 与 424 个旧录制按年龄/总量删除。主库 `integrity_check=ok`、1 账号 / 1,389 精灵 / 613 蛋 / 638 个非零伙伴标记不变；`backups/` 下两个目录保留。

### 12.4 验证与未验证（最终）

`python -m unittest tests.test_retention` → 33 项 OK（含截断、dry-run、截断失败、freed_sink 计量、启动时截断超限当天分片）；`tests/test_event_logger.py` 新增 3 项（提交 `7bc72bf`）：分片写满后切到 `_p02`/`_p03` 且旧分片不再追加、上次运行留下的超大当天分片不会被追加、清理回调异常只 warning 不影响写入。在 `de6f1c0` 的干净 worktree 里跑 `tests.test_retention + test_event_logger + test_desktop_startup + test_persistence` → 93 项 OK；`tools/cleanup_data_root.py` 先 dry-run 后实跑，dry-run 预计释放量与实跑一致（1,695.47 MB）。

真实进程观察（20:30 启动的桌面实例）：它加载的是 `9c14a2c` 之前的代码，日志仍打印「年龄>7天 / 总量>1024MB」。记录池当前 314,568,892 字节（= 300 MiB 上限内，未超出；旧代码在该实例未采集时没有继续增长）。**需要重启应用**才会启用 3 天/300MB 与 64MB 分片：重启时启动清理按上限检查（超出才截断，`de6f1c0`），随后当天主分片已 ≥64 MiB，新数据写入 `eventlog_20261024_p02.jsonl`。端到端验证：把真实 300 MiB 分片追加到 315,623,892 字节后运行 `tools/cleanup_data_root.py --apply`，文件被截断为 314,572,361 字节（300 MiB 以内，首末行仍是完整 JSON）。未验证：跨天/切分片在真实长跑进程中的清理时序、Windows 文件占用导致删除失败告警的真实路径（仅有单测注入 `OSError`）。

### 12.5 工作区状态（本轮结束时）

新增 `spritelens/services/retention.py`、`tests/test_retention.py`、`tools/cleanup_data_root.py`；修改 `spritelens/services/event_logger.py`、`spritelens/app_context.py`（同文件还有雷达/附近工作线未提交改动，本轮只暂存了保留策略相关 hunk）、`docs/DEVELOPMENT_GUIDE.md`、`docs/UI_GUIDE.md`、`spritelens/web/static/ui.css`、`spritelens/web/static/backpack-layout.css`、`spritelens/web/static/partner-marks/frame.webp`。提交：`2e38c5c`（初版上限）、`9c14a2c`（3 天/300MB + 64MB 分片 + 截断）、`7bc72bf`（分片轮转测试）、`de6f1c0`（启动即收敛：截断超限当天分片）。雷达/附近精灵与采集诊断工作线仍未提交，本轮未触碰其文件内容。
