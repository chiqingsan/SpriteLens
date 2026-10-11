# UI 规范（web/static）

适用范围：`spritelens/web/static/` 下的全部界面工作。加新页面、改组件、调样式
之前先读这份；与 `DEVELOPMENT_GUIDE.md` 的前端约定配合使用（那边管架构与
安全转义，这边管视觉与组件）。

## 1. 参照系与设计立场

- **蛋神助手**（布局对标对象）：它的 `:root` 与我们同源，视觉密度为
  数据面板风格——字号 9~15px 为主、间距 6~14px、圆角聚集在 8px。
  最重要的观察：**它几乎不用阴影**（大量 `box-shadow: none`），质感来自
  1px 描边 + surface 分层底色。我们也照此执行：能靠描边和底色分层解决
  的，不加阴影。
- **Open Props**（分级节奏参照）：间距 4px 步进、少档圆角的 scale 思路。
- **shadcn/ui**（命名思想参照）：语义化变量命名（什么用途，而不是什么颜色）。
  我们的 `--surface-2`、`--ink-soft`、`--amber-ink` 都是这个思路。
- 约束不变：零框架零构建、不引入 Tailwind/React、不在线引用任何资源。

## 2. Token 速查（定义在 app.css 的 `:root`，禁止绕过）

**选值规则：先查这张表，表里没有的语义先加 token 再用；禁止在规则里写
hex/rgba 字面值。** 1px 属"贴紧"语义、`999px` 胶囊、`50%` 正圆，可直接
写字面值。

| 组 | Token | 用途 |
|---|---|---|
| 间距 | `--space-0..7` = 2/4/6/8/10/12/16/20px | margin/padding/gap 全部走它；禁止 3/5/7/9 等奇数散值 |
| 字号 | `--fs-3xs..2xl` = 9/10/11/12/13/15/20/26px | 密集角标 → 辅助标签 → 次要信息 → 正文 → 强调正文(基准) → 面板标题 → 页面标题 → 大数字 |
| 圆角 | `--radius-sm/md/lg` = 6/8/12px | 小徽章/chip/输入框 → 卡片/按钮/头像（默认） → 面板/弹层 |
| 阴影 | `--shadow` / `--shadow-hover` / `--shadow-pop` / `--shadow-inset` | 面板静置 → 卡片悬停（hb-card/pet-card/nav active 共用） → toast/浮层 → 头像内阴影 |
| 表面 | `--surface-1..4` | 工具条底 → 常用次级底（行悬停/chip/账号行） → 更深一档（轨道/占位头像/按钮静置底） → 按压最深档 |
| 线 | `--line` / `--line-soft` | 常规边框；表格内弱分隔用 soft |
| 文字 | `--ink` / `--ink-soft` / `--muted` / `--muted-2` | 标题 → 深青正文 → 次要说明 → 占位字/徽章淡字 |
| 品牌 | `--teal` 四阶 + `--teal-bright` + `--focus-ring` | 主色/悬停加深/深文字/浅底；渐变亮端与悬停描边用 bright |
| 琥珀 | `--amber` 六件套 | 处理中状态与提示条专用（`--on-amber` 是渐变底上的深字） |
| 危险 | `--danger` 四件套 + `--positive/--negative/--ok` | **红色只留真正破坏性操作**；数值升降用 positive/negative |
| 性别 | `--male/--female` + `--male-strong/--female-strong` + `--male-ink/--female-ink` | 卡片底色 / 环形标记 / 小字（对比度） |
| 侧栏深底 | `--deep-1/2` + `--deep-text(-dim/-faint)` + `--deep-line/--deep-hover` | 侧栏渐变与其上的文字/分隔/悬停 |
| 解码树 | `--code-*` 五色 | colorizeDecoded 白名单着色，与 tok-* 类名对应 |
| 图表 | `--chart-h/w/v` | 体型条三色，与 `.body-bar i` 类名对应 |

业务色（系别/天赋阶/glass 渐变）不属于 CSS token：由 `domain/display.py`
经 payloads 下发，前端不复制色表（见 DEVELOPMENT_GUIDE）。

## 3. 组件类清单（加页面先对表抄结构，不新造类）

| 组件 | 类名 | 结构模板 |
|---|---|---|
| 面板 | `.panel` | `section.panel > .panel-head(h2+.muted) + 内容` |
| 分栏工作区 | `.workspace.split` | 左列表 + 右详情；**两栏页必须补 `#page-xxx .workspace.split { grid-template-columns: minmax(0,1fr) 340px }`**（默认三栏模板会让两栏页掉进窄列） |
| 内容面板 | `.content-panel` | `.panel-toolbar(工具条) + .table-wrap(滚动区) + .pager` |
| 详情栏 | `.detail-panel` | `.detail-title(h2) + .detail-sub + .detail-section(h3+内容)` |
| 筛选栏 | `.filter-rail` | `.filter-head + .field*`（sticky，窄窗自动取消） |
| 输入 | `.field` | `label span + input/select`；行内场景 `.inline-field` |
| chip 组 | `.chip-group > .chip(.active)` | 多选筛选；单值切换用 `.segmented` |
| 按钮 | `.primary-button` / `.ghost-button`（`.small` 变体） | 主操作每屏至多一个；`.danger-ghost` 只给破坏性操作 |
| 状态徽章 | `.status-pill(.ok/.warn/.bad)` | 顶栏与列表状态；文字要自明（"未启动"而非"灰"） |
| 计数徽章 | `.count-badge` | 工具条里的总数 |
| 表格 | `.pet-table/.event-table` | sticky 表头 + tabular-nums；行 hover/active 已内置 |
| 卡片网格 | `.hb-grid > .hb-card`（图鉴系）/ `.pet-grid > .pet-card`（背包系） | hover 抬升 + 边框变 teal，勿另造阴影 |
| 宠物小卡 | `.mm-pet` | chip 形态：头像+性别符+名(+Lv)；JS 用 `petChip(pet, withLevel)` |
| 宠物头像 | `.pc-avatar` | 首字回退 + 立绘覆盖；渐变底走 `glassStyle()` |
| 空状态 | `.empty-hint` | 每个列表区必备，说明"为什么空/怎么才有数据" |
| 占位页 | `.feature-placeholder` | 未实装页统一虚线框 |
| toast | `toast(msg, bad)` | 轻提示一律走它，不用 alert |
| 弹层 | `.modal-layer > .modal` | 模态容器 |

新页面 HTML 骨架、`switchPage` 分发、`/api/xxx` 路由四步流程见
`DEVELOPMENT_GUIDE.md`「加页面」。

## 4. JS 渲染约定

- 每页三件套：`loadXxx()` → `renderXxx()` → `bindXxxFilters()`；模板字符串
  拼 HTML，**所有后端文本过 `esc()`**。
- 可复用帮手：`esc / petAvatarHtml / eggAvatarHtml / glassStyle / petChip /
  flowerCard / levelColor / toast`。写第二个相同拼接之前先抽帮手——
  但不为单一使用方预抽象（如 `renderPetPager` 只服务背包页，保持页内）。
- 动态样式（系别色/进度条宽/glass 渐变）允许内联 `style=`，前提是值来自
  payload；静态样式一律进 app.css。

## 5. 反面清单（每条都真实踩过）

1. **中文标题不加 `letter-spacing`、不做 `text-transform: uppercase`**——
   英文排版习惯套在中文上是负资产（侧栏分组标题"压扁感"事故）。
2. **红色只给破坏性操作**。"停止采集"用主色+文字区分，不用红
   （用户明确反馈红色有警告意味、不协调）。
3. **两栏页必须补 split 列宽覆盖**，否则掉进三栏模板的 236px 窄列。
4. **改 app.css 后跑一次页面截图**；用脚本整表替换 CSS 曾留下孤立声明体
   导致整表失效白屏——手工 Edit + 花括号配平检查。
5. **WS 推送驱动的状态要同时挂 REST 响应路径**（采集按钮"点了没反应"
   事故）；CSS 类切换注意特异性（`.stop-button` 会被 `.primary-button`
   盖掉）。
6. **耗时操作按钮要有 disabled 中间态**（琥珀脉冲），失败回落上一状态。
7. 截图核对前先等 600~800ms——reload/切页后 CSS 重排期间截图可能整页
   空白，是截图陷阱不是代码 bug。
8. `payload` 新增参数要 grep 全部调用点（server.py 有 3 处调 pets_payload，
   只改 1 处字段静默为 null）。

## 6. 视觉验收

```
.venv/Scripts/python.exe tools/run_web_demo.py --no-open --pets 40
```

打印带 token 的 URL 到 stdout，浏览器打开核对；改动涉及布局时逐页截图，
关注：错位/重叠/压缩、中文方框、窄窗（<1280）行为、空状态是否给出解释。
改完跑 `.venv/Scripts/python.exe -m unittest discover -s tests`。
