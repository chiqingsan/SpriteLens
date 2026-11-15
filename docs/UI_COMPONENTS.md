# 通用组件层（组件库雏形）

状态：已落地基础层，页面按需逐步迁移。读者：前端开发者、UI 维护者、AI 协作者。
维护边界：本文件描述 `spritelens/web/static/ui-components.css` 的组件契约；颜色/字号/圆角/阴影/动效的数值以 `themes.css` 与 `app.css` 的 token 为准，页面级布局仍在各页面 CSS / Vue `<style scoped>` 内。

## 1. 分层与加载顺序

`spritelens/web/static/index.html` 的样式加载顺序（后者可覆盖前者）：

1. `themes.css` — 设计 token：三主题色板、表面、文字、语义色、动效时长/缓动、阴影层级。
2. `ui-components.css` — 通用组件外观（本文件描述的 `ui-*` 类）。
3. `app.css` — 全局基础样式、浮动画布外壳、侧栏/顶栏，以及历史类名 → `ui-*` 的**同源别名**。
4. `ui.css` / `desktop-shell.css` / `backpack-layout.css` — 既有页面布局与桌面壳细节（按页面加载）。

规则：新页面/新组件只写「组件类 + 布局」，外观不要写进页面 CSS；历史页面继续用旧类名即可，视觉与 `ui-*` 一致（见 §4）。

## 2. Token 速查

| 类别 | Token |
| --- | --- |
| 字体 | `--font-ui`（Microsoft YaHei UI / PingFang SC / Segoe UI Variable 回退） |
| 字号 | `--fs-3xs` 13 / `--fs-2xs` 14 / `--fs-xs` 14 / `--fs-sm` 14 / `--fs-md` 15 / `--fs-lg` 16 / `--fs-xl` 20 / `--fs-2xl` 28；密集数据最低 13px（100% DPI 可读下限） |
| 间距 | `--space-0` 2 / `-1` 4 / `-2` 6 / `-3` 8 / `-4` 10 / `-5` 12 / `-6` 16 / `-7` 20 / `-8` 24（禁止 3/5/7/9 等散值） |
| 圆角 | `--radius-sm` 8 / `--radius-md` 10 / `--radius-lg` 16 / `--radius-xl` 20；胶囊写 999px、正圆 50% |
| 阴影 | `--shadow-1` 静置 / `--shadow-2` 悬停 / `--shadow-3`（=`--shadow-pop`）浮层 / `--shadow-canvas` 工作画布；全部为「低透明叠层小偏移 + inset 高光」，不使用单层重投影 |
| 描边 | `--hairline`（墨色 9%，卡片/分隔线）/ `--hairline-strong`（15%，悬停/强调）替代实色 `--line` 作为视觉边界；`--field-line`（26%）/ `--field-line-hover`（34%）专给**需要看清边界的输入控件**（搜索框、筛选 chip）——白底上 15% 只有 1.35:1 对比，看起来像没描边 |
| 输入 | `--field-bg`（内凹底色，= surface-1）/ `--field-inset`（内凹阴影），输入框统一使用，聚焦叠加 3px 焦点光环 |
| 动效 | `--motion-fast` 120ms / `--motion-base` 200ms / `--motion-slow` 300ms / `--motion-ease`（出）/ `--motion-spring`（弹性）/ `--motion-lift` |
| 颜色 | 表面 `--bg/[--canvas]/--panel/--surface-1..4`；描边 `--line/--line-soft/--hairline*`；文字 `--ink/--ink-soft/--muted/--muted-2`；主色 `--teal/--teal-dark/--teal-soft/--teal-bright`；语义 `--amber*/--danger*/--ok`；焦点 `--focus-ring/--focus-halo`；环境光 `--ambient-1/2` |
| 主题 | `data-theme="miaomiao"`（默认）、`"huohua"`、`"shuilanlan"`；组件不得写死主题色 |

## 3. 组件清单

| 组件 | 类名 | 说明 |
| --- | --- | --- |
| 布局 | `ui-stack` / `ui-cluster` / `ui-split` / `ui-grid-auto` | 纵向堆叠 / 横向换行 / 两端对齐 / 自适应卡片网格 |
| 表面 | `ui-surface` / `ui-panel`(`__head`/`__body`/`__foot`) / `ui-inset` | 轻表面 / 垂直布局面板（头部-内容-底部）/ 虚线内嵌区 |
| 卡片 | `ui-card`；`ui-card--interactive`；`.is-selected` / `[aria-pressed="true"]` | 可交互卡片悬停抬升 2px、选中描边加深 |
| 文本 | `ui-title` / `ui-subtitle` / `ui-label` / `ui-value` / `ui-muted` / `ui-numeric` | 标题/副标题/标签/数值（等宽数字）/弱化/数字对齐 |
| 按钮 | `ui-btn` + `--primary` / `--ghost` / `--quiet` / `--danger` / `--sm` / `--lg`；`ui-icon-btn` | 主操作 / 次级 / 弱动作 / 危险；纯图标按钮 |
| 分段 | `ui-segmented > button`，当前项加 `.is-active` 或 `aria-pressed="true"` | 工具栏单选组（白色药丸滑块） |
| 徽章 | `ui-chip` + `--accent/--warn/--danger/--muted/--pill`；`ui-dot--ok/warn/bad`；`ui-status` + `--ok/--warn/--bad` | 标签 / 状态点 / 带点状态胶囊 |
| 表单 | `ui-field` / `ui-label` / `ui-help` / `ui-input` / `ui-textarea` / `ui-check` / `ui-switch` | 输入、选择、勾选、开关（`:has(input:checked)`） |
| 搜索框 | `ui-search`（`--compact`）/ `__icon` / `__input` / `__clear`；Vue 组件 `<UiSearch>`（`frontend/src/components/UiSearch.vue`） | 34px 高、10px 圆角；描边/底色/焦点光晕都由**外层容器**承载，内部 `input` 复位 `appearance`（WebView2 会自绘原生 searchfield 白框，形成双边框）；清空按钮常驻占位只切 `visibility`，宽度不跳动 |
| 多选框 | 原生 `input[type="checkbox"]`（全局统一外观） | 18px 圆角方块；勾选 = 品牌色实底 + 白色对勾；悬停描边加深、聚焦 2px 光环、禁用半透明；页面内紧凑场景可局部设 `16px` |
| 下拉框 | `ui-picker`（`--xs` / `--sm`；`.is-empty` 为占位态）/ `__trigger` / `__panel` / `__list` / `__option`（`.is-selected`、右侧 `circle-check`）；Vue 组件 `<UiSelect>`（`frontend/src/components/UiSelect.vue`） | 自制下拉，页面里不再有原生 `<select>`。三档尺寸 34/30/28px、10px 圆角；面板 `position: fixed` + Teleport（`document.body`，在 `<dialog>` 内则挂到 dialog，避开 top layer），空间不足自动向上翻并夹取到视口内；触发器支持 ↑↓/Home/End/Enter/Esc/Tab 与 `aria-activedescendant`，`role="combobox"` + `aria-haspopup="listbox"` + `aria-expanded`；面板 120ms 淡入位移，列表滚动条墨色 18% 不压住勾选图标。静态页历史样式 `select` / `.ui-select`（含 `::picker(select)` 渐进增强）保留未删 |
| 工具栏 | `ui-toolbar`(`--flush`/`__spacer`) / `ui-section-head` / `ui-kpi` | 面板工具条 / 分区标题 / 指标块 |
| 空态 | `ui-empty` + `__icon` / `__title` / `__desc` / `__actions` | 图标 + 标题 + 说明 + 一个主操作（禁止只用一行文字当空态） |
| 提示条 | `ui-banner` + `--info/--warn/--danger` / `__actions` | 页面内提示，错误用 `role="alert"` |
| 列表 | `ui-list` / `ui-row`（`.is-selected`）/ `ui-row__main|__title|__meta` / `ui-divider` | 行列表与分隔线 |
| 标签页 | `ui-tabs` / `ui-tab`（`.is-active` 或 `aria-selected="true"`） | 底部 2px 主色指示条 |
| 表格 | `ui-table`（`ui-table--dense`） | 粘性表头、行悬停、细描边 |
| 对话框 | `ui-dialog[open]` + `__head/__body/__foot` | 原生 `<dialog>`，入场动画 + 背景模糊；需自行 `showModal()` |
| 滚动/骨架 | `ui-scroll` / `ui-skeleton` | 细滚动条容器 / 加载闪光条（`prefers-reduced-motion` 下停止） |
| 详情面板（Vue） | `<PageInspector>`（`frontend/src/components/PageInspector.vue`，根类名 `ui-inspector`） | 右侧详情统一外壳：标题 + 副标题 + 操作区 + 关闭；左缘拖拽调宽、双击复位、宽度按 `storage-key` 记忆；窄屏自动切换为抽屉 |
| 页面骨架（Vue） | `<PageShell>`（`frontend/src/components/PageShell.vue`，根类名 `ui-page`） | 统一页面骨架：`#toolbar` 槽 = 页头/工具行（`ui-page-toolbar`），默认槽 = 页面主体；`:busy` 标记加载中 |
| 分页（Vue） | `<PagePager>`（`frontend/src/components/PagePager.vue`，类名 `ui-pager`） | 统一分页条：页码条 + 上/下页 + 总数说明；`:page` + `@update:page`；横向滚轮翻页，选中页自动滚入视野 |

用法示例：

```html
<button class="ui-btn ui-btn--primary"><svg class="ui-icon"><use href="/static/icons/sprite.svg#search"></use></svg>开始扫描</button>
<div class="ui-empty">
  <span class="ui-empty__icon"><svg class="ui-icon"><use href="/static/icons/sprite.svg#search"></use></svg></span>
  <h2 class="ui-empty__title">还没有数据</h2>
  <p class="ui-empty__desc">开始采集并在游戏中浏览背包后，这里会自动出现结果。</p>
  <div class="ui-empty__actions"><button class="ui-btn ui-btn--ghost">刷新</button></div>
</div>
```

### 页面级共享组件（Vue）

图鉴、蛋图鉴、蛋仓、精灵背包四个右侧详情面板统一使用 `PageInspector`；宽度、关闭、焦点与窄屏抽屉行为由组件负责，页面只提供内容与操作：

```vue
<PageInspector ref="inspector" title="精灵详情" :meta="`#${item.handbook_no}`"
  :modal="modal && mobileDetail" storage-key="handbook" :default-width="360" @close="close()">
  <template #actions>
    <button class="ghost-button small" aria-label="上一枚" @click="moveSelection(-1)">…</button>
  </template>
  <HandbookDetail :item="item" />
</PageInspector>
```

- 宽度记忆键：`sn.inspector.<storage-key>`；默认 360、范围 280–560，拖拽手柄键盘方向键可调，`Home` 复位。
- 内容区是唯一滚动容器（`.ui-inspector-body`），需要滚动到顶部时调用 `inspector.value?.body?.scrollTo(0, 0)`；打开窄屏抽屉后调用 `inspector.value?.focusClose()` 聚焦关闭按钮。
- 背包详情 `PetDetailPanel` 已迁移到 `PageInspector`（`storage-key="pets"`，定位按钮通过 `#actions` 插槽传入）；`#pet-detail` 上的内容样式保持，`.workspace.has-detail` 继续由页面切换网格列宽。

## 4. 历史类名 = 同源别名

为兼容既有页面，以下旧类名已在 `app.css` 中与 `ui-*` **共用同一条规则**（不是复制一份），视觉完全一致，迁移时无需担心细节差异：

| 历史类名 | 等价组件 |
| --- | --- |
| `primary-button` | `ui-btn--primary` |
| `ghost-button` | `ui-btn--ghost` |
| `icon-button` | `ui-icon-btn` |
| `status-pill`（`.ok/.warn/.bad`） | `ui-status`（`--ok/--warn/--bad`） |
| `chip`（`.active`） | `ui-chip`（`.is-active`） |
| `segmented` | `ui-segmented` |
| `panel` | `ui-panel` |
| `empty-hint` | `ui-empty` |
| `field` | `ui-field` |

约定：旧类只保留既有用法，不再派生新变体；新代码写 `ui-*`。迁移一个页面时，把模板中的旧类替换成对应 `ui-*` 并同步更新本表即可，CSS 不需要额外删除（别名规则保留）。

## 5. 编写规则

- 只用 token：不写死 hex/rgb、圆角、阴影、动效曲线；页面 CSS 只负责布局（grid/flex/间距/断点）。
- 动效只服务交互反馈与页面进入（`page-enter`、卡片悬停、弹层、抽屉）；**禁止**给后台数据更新加入场动画，避免闪动（见 `AGENTS.md`、`UI_GUIDE.md`）。
- `prefers-reduced-motion: reduce` 已在全局和组件层兜底，新增动画不需要重复判断，但不能依赖动画表达信息。
- 图标统一 `UiIcon` + `/static/icons/sprite.svg`；不得用 Unicode 符号/emoji 充当图标。缺失图标先查 `sources.json`，需要新增时在 `tools/sync_ui_icons.py` 的 `ICONS`（Tabler）或 `EXTRAS`（项目保留图形）登记后重新生成。
- 极限布局与数据更新稳定性按 `AGENTS.md` 验收：最长名称、多行、空态/加载/错误态、最小窗口、三主题、150% DPI 都要过一遍，不得用 `overflow: hidden` 掩盖布局问题。

## 6. 维护与迁移状态

- 当前状态：全局外壳、导航、按钮/徽章/分段/面板/空态已统一到 token + 组件层；图鉴、蛋仓/家园、配窝/筛选配对/双牌产线、色卡/附近精灵/雷达/采集诊断各自完成页面级现代化，页面 CSS 中的硬编码颜色已清零（游戏资源色与属性色按 `themes.css` 保留）。页面骨架与右侧详情已统一（`PageShell` / `PageInspector`），图鉴与蛋图鉴使用同一套分页条和显示偏好。
- 迁移顺序建议：先小页面（设置/采集诊断）后大页面（背包/图鉴）；每次迁移只动一个页面的类名，改完用 `output/ui_shot.py` 做 1440/1280/960/760/640 三主题截图对比。
- 新增组件流程：先在 `ui-components.css` 加 `ui-*` 与变体 → 同步本文件 §3 表格 → 页面里替换使用 → 截图验收。

## 7. 壳层扩展：折叠侧栏

壳层扩展脚本 `web/static/shell-ui.js`，折叠态样式在 `app.css`。

- 入口：侧栏底栏右侧按钮 `#btn-rail-toggle`，快捷键 `Ctrl+B` / `⌘B`；状态写入 `localStorage["spritelens.sidebarRail"]`，刷新后保持。
- 折叠态：`#app.sidebar-rail` 把 `--sidebar` 置 64px；隐藏账号文案/分组标题/设置按钮文字，导航只留图标（悬停/聚焦用 `title` 提示），账号头像仍可点击打开账号浮层；导航滑块在宽度过渡结束后重新测量。
- 与既有窄窗规则的关系：`#app.sidebar-rail` 的 id 选择器优先级高于 `:root` 断点与 `body:has(#page-pets.active)` 图标模式，因此任意窗口宽度下都能手动折叠；不覆盖背包 ≤760 的自动图标模式（那是默认行为，折叠是用户选择）。
- 无障碍：按钮 `aria-pressed` + `aria-label` 随状态切换；折叠不影响键盘 Tab 顺序。
- 视觉：折叠态设置按钮去底色，仅悬停/选中出底；图标条宽度过渡 200ms，`prefers-reduced-motion` 下瞬时。

> 说明：曾实现的 `Ctrl/⌘+K` 命令面板已按用户要求移除（顶栏按钮、快捷键、`ui-command*` 样式、`shell-ui.js` 内的面板逻辑均删除）；相关图标 `layout-sidebar-left-*` 保留给折叠侧栏，`command` / `corner-down-left` 留在图标源中备用，未再引用。

## 8. 页面骨架与显示偏好

页面骨架统一为 `PageShell`：`#toolbar` 槽放页头与工具行，默认槽放页面主体；`ui-page` 负责占满可用高度、`ui-page-toolbar` 负责单行工具区的换行与间距。

```vue
<PageShell class="catalog-dex" :busy="loading">
  <template #toolbar>
    <div class="ui-page-heading"><h2 class="page-heading">精灵图鉴</h2></div>
    <div class="ui-page-actions"><input class="field" placeholder="搜索" /></div>
  </template>
  <div class="dex-browser-layout">…</div>
</PageShell>
```

- 已迁移：图鉴、蛋图鉴、蛋仓、筛选配对、双牌产线、智能配窝、附近精灵、我的家园；背包为原生页面，保留既有 `#page-pets .workspace.split` 结构（工具行与筛选栏由 `backpack-layout.css` 负责），后续如迁移需同步处理 `#pet-detail-root` 的网格列。
- 分页统一用 `PagePager`；不再在页面内自行实现页码条。图鉴/蛋图鉴只保留网格视图，不提供网格/列表切换与舒适/紧凑密度选择（对应样式与状态已在界面重构中移除）。
- 工具行内的分组用 `ui-page-heading`（标题/说明/状态）与 `ui-page-actions`（按钮组）排布；需要两行时让 `ui-page-toolbar` 自然换行，不要固定高度。
- 迁移页面时不要再用 `.page > .xxx-page` 的旧包装器规则（`height:100%` / `overflow:hidden` 已由 `ui-page` 承担），否则会出现双滚动容器。

## 9. 常用组合（可直接照抄的页面骨架）

### 9.1 列表页：工具行 + 网格 + 分页 + 详情

```vue
<PageShell class="catalog-dex" :busy="loading">
  <template #toolbar>
    <div class="ui-page-heading">
      <p class="ui-page-meta">资料条目 {{ total }} 条</p>
    </div>
    <div class="ui-page-actions">
      <input class="field" placeholder="搜索名称 / 编号" />
      <button class="segmented">属性</button>
      <button class="segmented">蛋组</button>
      <PagePager :page="page" :pages="pages.length" :page-size="30" unit="只"
        label="精灵图鉴页码" @update:page="goPage" />
    </div>
  </template>
  <div class="dex-browser-layout">
    <section class="dex-results">…</section>
    <PageInspector v-if="detail" storage-key="handbook" title="精灵详情" @close="closeDetail()">
      <HandbookDetail :item="detail" />
    </PageInspector>
  </div>
</PageShell>
```

要点：分页只接 `PagePager`；详情只接 `PageInspector`；图鉴卡片固定网格视图，不再有视图/密度切换。

### 9.2 设置页两栏

```html
<div class="settings-page">
  <aside class="settings-nav" aria-label="设置分区">
    <a href="#settings-appearance" aria-current="page">外观</a>
    <a href="#settings-capture">采集与连接</a>
    …
  </aside>
  <div class="settings-main">
    <header class="settings-header">…</header>
    <section id="settings-appearance" class="settings-group">…</section>
  </div>
</div>
```

滚动高亮与平滑定位由 `settings-nav.js` 负责；新增分区只需加锚点与 `id`，脚本会自动纳入滚动监听。

### 9.3 统计概览条

```html
<section class="home-overview" aria-label="家园概览">
  <div class="home-stat"><span>房间等级</span><strong>10</strong></div>
  …
  <p class="home-overview-note">快照已同步</p>
</section>
```

样式在页面 CSS（如 `home.css`）里用 `.home-stat` 组合 `--hairline` / `--radius-lg` / `--fs-xl` 实现，不新建全局类；卡片数量 3–6 个、数值等宽。

## 10. 反模式（代码审查时优先拦下）

- 页面 CSS 里出现 hex/rgb 颜色、圆角/阴影/字号散值 → 应改用 token。
- 为「后台数据更新」加入场动画或过渡整块骨架 → 违反数据更新稳定性要求，见 `docs/UI_GUIDE.md`。
- 用 `overflow: hidden` 掩盖布局溢出、用固定高度裁切长名称 → 极限布局测试必须过。
- 双滚动容器：外层页面 + 内层面板同时 `overflow: auto`。
- 用 Unicode 字符当图标；新增图标未登记 `tools/sync_ui_icons.py` 直接手改 sprite。
- 在页面里复制分页/详情/空态结构而不是用 `PagePager` / `PageInspector` / `ui-empty`。
