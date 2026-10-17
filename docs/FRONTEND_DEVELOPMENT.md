# Vue 前端开发与构建

状态：当前维护文档，2026-10-13 工程与蛋图鉴已落地。读者：前端开发者、打包维护者。
维护边界：本文维护命令、生成文件与迁移桥；任务状态只在 [ROADMAP](ROADMAP.md) 更新，
视觉遵循 [UI_GUIDE](UI_GUIDE.md)，设计依据见 [VUE3_MIGRATION](VUE3_MIGRATION.md)。

## 安装、构建、启动

已验证 Node 24.18.1 / npm 11.16.0，工程有 `.node-version`、engines 与 engine-strict。
Python 依赖仍按开发指南安装。首次源码启动、demo 和打包前必须构建：

```powershell
cd frontend
npm ci
cd ..
.venv/Scripts/python.exe -B tools/frontend.py build
.venv/Scripts/python.exe -B tools/run_web_demo.py --no-open --pets 40
```

在 demo 输出的本地 URL 打开页面。开发仍从 aiohttp 同源加载，不开第二个服务器、不改变鉴权/CORS。
修改源码后重新运行 `tools/frontend.py build` 并刷新浏览器。

构建已包含 vue-tsc 类型检查，日常不单独重复执行。交互行为变化时，按需选相关轻量回归：

```powershell
cd frontend
npm test -- src/composables/usePets.test.ts
```

仅保留请求失效、账号/DTO 契约、筛选状态联动、卸载清理与保存失败回归。
已取消统一门禁、ESLint 和 Playwright；布局用必要目视检查，不维护固定 DOM/像素值断言。
前端测试与合成数据不参与生产源码指纹，修改测试不会要求重建运行页面；生产类型检查也不包含测试文件。
构建与打包仍检查运行产物；`tools/frontend.py check` 用于需要单独检查现有产物的场景，不在刚成功构建后重复运行。
具体取舍见 [开发指南](DEVELOPMENT_GUIDE.md#测试取舍)；实际 WebView2/exe 验收留在受影响的启动改动或发布时进行。

## 生成文件所有权与失败语义

`frontend/src/`、配置、测试、package-lock 是源文件；`node_modules/`、`dist/` 与
`spritelens/web/static/vue/` 是忽略的生成文件。新 checkout 通过 npm ci + build 重建，不提交 bundle。
工程没有 public 媒体副本；继续引用 `/static/pet-media/`、`egg-icons/`、`icons/sprite.svg`。

构建只清空 `frontend/dist`，通过 [Vite manifest](https://vite.dev/guide/backend-integration.html)
列出入口、chunk、CSS、媒体引用，再写源指纹与逐文件 SHA256 清单。
构建/校验失败保留现有运行产物；复制到 `static/vue-pending` 完成后才替换专用 `static/vue`。
目录替换失败恢复 `vue-previous`；残留 pending/previous 时显式失败，维护者检查后处理，工具不猜测删除。
普通构建不会清空 `static` 或现有图片。打包只附带运行静态资源，不包含 Node、node_modules、源码 map。

`frontend.py check` 与 `build.py` 拒绝源不匹配、引用缺失、产物损坏；smoke 与 HTTP 首页也检查运行产物。
冻结包无需 Node，仅检查产物。源码/demo 缺构建时首页返回可读 500，不显示半成品。

## 页面与迁移桥

蛋图鉴与精灵蛋仓由旧 `app.js` 在导航时动态 import `vue/entry.js` 并挂载；
蛋图鉴传入根节点和启动 token，蛋仓只接收应用壳提供的账号请求/取消/版本回调。
桥的代次阻止离页后完成的 import 挂载。Vue mount 返回 pause/resume/unmount，离页取消请求，窗口关闭时卸载。
Vue Router 使用 memory history，Pinia 已安装；本页无共享业务状态，不创建空 store。
唯一 WS、bootstrap、主题偏好仍由旧壳持有，F04 迁完整壳时删除桥。

蛋图鉴根带 `data-vue-page`，ui.js 与 icons.js 跳过该子树。Vue 负责模板、图标、详情、
焦点和窄窗 inert，卸载解除 inert 与事件监听。主题继承根 CSS 变量，不复制主题状态。
蛋图鉴筛选、选择、错误与请求状态归页面/composable；离页取消请求和 debounce、关闭详情并解除 inert，保留挂载、筛选与滚动位置。返回复用同筛选目录，失败或未完成的筛选重新加载；首批显示 40 张卡片，滚近底部追加。
同页筛选使用 AbortController + 请求代次；输入立即废弃旧响应，不能等 debounce 才作废。
加载、无数据、筛选空态、可重试错误分别展示；移除旧蛋图鉴脚本与 HTML。

蛋图鉴是静态目录，不伪造 uid/version。精灵蛋仓复用 `accountRequests` 的 UID、域版本、账号代次和取消语义；
蛋仓 DTO 运行校验包含目录蛋组、数值测量范围、快照来源和可编辑标签；标签保存通过本地鉴权 POST，数据按 uid 与蛋/精灵实例持久化。分类使用后端 `egg_kind`，协议 `category` 仍表示获取来源，不作为蛋类型筛选。
蛋仓数据、筛选、选中项及详情由 `EggBoxPage.vue` 独占；账号切换清空页面数据，离页暂停并取消请求。
背包和蛋仓返回时复用同账号、同版本的有效快照；背包还核对筛选条件，错误或保存后未同步状态重新加载。手动标注、收藏和声音修正成功保存后由仓库推进版本，使 WS 和返回页缓存失效；失败不推进版本。概览使用 bootstrap/WS 统计，不为总数重复拉取宠物列表。
蛋性格/蛋窝与手动绑定归蛋注释表；宠物详情的手动分贝单独覆盖协议读数，蛋的声音标签只读取绑定精灵的手动分贝。
后端按精确配置、Wiki 物品变体与协议 `mutation_type` / `precious_egg_type` 分类；随机配置 ID 不等于特殊蛋。
图片只使用蛋图，随机蛋的物种/蛋组显示为孵化前未确定，缺范围不借用普通蛋范围。
账号页迁移仍依赖 F01/F02 的快照与失效语义。
宠物基础筛选在 bootstrap 时通过 mountPetFilters 挂载；控件与基础状态归 Vue。
查询/恢复/清理接口连接应用壳与矩阵跳转；usePetAdvancedFilters 独占蛋组、绝对范围与位置筛选。
Vue 使用 Teleport 独占搜索/排序和天赋占位子树，挂载容器用 display:contents 保持旧布局。
输入立即使旧 pets 请求失效，随后防抖重载；离页暂停、切号清派生选项，关闭卸载清定时器。
基础筛选 DTO 检查消费的 options；列表 DTO 校验 uid/version、消费的行字段、箱/队槽形状和匹配一致性。
PetInventory 与 usePets 独占请求/数据/加载错误、三视图、分页、箱队与选择；PetDetailPanel 管理详情显示、键盘、焦点与窄屏 inert。
请求复用统一 API 客户端；每次取旧壳唯一 petContext（uid/version/generation），不建立平行账号 store。
bootstrap 先核对载荷与账号上下文；后续请求校验序号、代次、uid 和最新版本，离页/切号/新条件取消并失效。
列表错误可直接重试；显示完整数据、过滤空态、未采集箱表和未知槽位仍分别处理。表格只在选中该视图时构建行。
纯资源展示用 Vue 模板，原生脚本不再写宠物页节点；详情定位和滚动恢复由 Vue 执行。
PetShortcuts 管理命名、应用与删除；appearance.js 仍是偏好持久化的唯一所有者，返回保存 Promise。
保存失败保留编辑与错误提示，重试使用保存前列表快照，避免乐观预览造成重复项。
已删除 pet-filters.js 与 backpack-controls.js；旧壳仅桥接账号、导航与偏好。
REST DTO 只定义页面所用字段并运行时检查；本页不消费 WS，不提前定义未使用的 WS DTO。
API 客户端集中 token、取消和 error/message 归一，不增加通用网络框架。

筛选配对由 `BreederLibraryPage`／`useBreederLibrary` 独占筛选、选择、分页和请求；壳只桥接当前账号上下文、取消、版本通知与背包详情跳转。`tools/frontend.py`发布入口导出`mountBreederLibrary`。筛选输入立即失效旧请求，再防抖查询；离页取消、同版本返回复用、切号清空。DTO校验亲本与预测字段，亲本gid使用字符串；旧公母矩阵截断列表已退出此入口。

家园 `actor_id` 在 Python 载荷边界转十进制字符串；旧页仅转义展示，无需数值比较。
家具 guid 原本是字符串，宠物 gid 有 `PetBriefInfo.json` uint32 证据，目录 ID 继续为 number。
其它未确认标识符在相关页面迁移时核对协议，不全局转换数字。
孵化筛选沿用后端 `hatch_min_hours`（至少），文案修正为 ≥，避免原先 ≤ 与接口相反。

运行依赖 Vue、Vue Router、Pinia 均 MIT；它们解决 SFC 页面、memory 导航与后续共享状态，
F03 完整页面构建的生产 JS 为 160.73 kB / gzip 57.87 kB（Vite 输出），尚无桌面冷启动测量。

### 智能配窝（F04-U5）

`mountBreedingPlanner`由独立迁移桥惰性挂载，原壳只提供账号版本、可取消鉴权请求与背包跳转。页面持有两入口独立草稿与修订号；相同账号版本返回复用页面，背包更新保留布局并标待评。Python负责求解与重评；SVG固定展示20×20格，已有窝群仅在视图中居中，不更改草稿坐标；窝内保留序号、性别和头像，姓名在相邻索引，点选后突出相关亲本与连线。点击亲本查看或替换，窝可直接拖到空白位置或与另一窝交换，手动坐标限于0～18，旧草稿越界时提示重新规划。目标蛋用搜索后的蛋图列表点选，并显示当前观察记录中对应的母本数量。选择器分页24只，画布最多11窝，不为长列表累积DOM。草稿保存失败保留本地编辑，恢复不自动重选亲本。布局工具条提供撤销/重做（拖动与方向键移动都可撤销，上限40步）；有未保存修改时「保存草稿」可用并标注原因，保存失败可就地重试，恢复草稿失败显示服务端原因而不静默。迭代卡在缺失奖牌位置显示空位与「待培养」，不画成已获完整奖牌。接口与维护范围见BREEDING_PLANNER_SPEC。
