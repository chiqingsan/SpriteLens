# SpriteLens 代码与性能审查 / 6luna 执行交接

状态：2026-10-15 审查快照，尚未实施。读者：用户、6luna、复核者。
维护边界：本目录为一次性交接产物，不替代 `docs/ROADMAP.md` 的持续状态；执行者确认任务后再把状态同步到路线图。

审查基线：`de12fca3f940466de24df29cf6c2540ec24fc0fa` **加当前全部未提交改动**。现有 26 个已修改文件及未跟踪的 output、两组 wiki 素材均属于用户，本次未改动它们。新增内容只有本审查目录。结论针对当前工作区，不能只 checkout 该 commit 来复现新蛋仓问题。

交接文件：

- 本文：问题、证据、执行范围、优先级和验收。
- [probe_backend.py](probe_backend.py)：内存数据库、临时目录和故障替身的复现及性能基线。
- [probe_egg_save.cjs](probe_egg_save.cjs)：编译并运行当前 EggBoxDetail 的实际 setup，复现保存目标错位，不改组件源码。
- [backend-results.jsonl](backend-results.jsonl)、[egg-save-results.jsonl](egg-save-results.jsonl)：保存脚本复跑的原始输出。

运行位置为仓库根目录：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -B output/review-20261015-performance/probe_backend.py
node output/review-20261015-performance/probe_egg_save.cjs
```

脚本不启动 Npcap、不访问真实账号数据库、不向 CDN 发请求。它们打印当前行为，供修复前后比较；不是新增统一门禁。故障复现会出现预期的写失败日志。

## 结论与测量边界

当前性能压力主要来自：**HTTP 事件循环上做重计算/同步 IO、每次拉取全量精灵详情、采集投递路径同步落盘**。先修这些明确路径，无需更换技术栈或展开全项目重构。

同时发现三个应先处理的数据正确性问题：写回批次可能倒序、退出写失败不报告、蛋仓编辑保存可能转向另一枚蛋。优化线程和 IO 前，必须先锁住这些契约。

本机合成数据微基准，使用真实静态物种/蛋/色卡目录；精灵含六维，不含技能，图像映射预热后测量。构造与 JSON 分别取 3 次中位数，state 取 5 次中位数；数值不是 HTTP p95、GUI 帧率或真实登录实测。

| 场景 | 本轮观察 |
| --- | --- |
| 100 只精灵 | 载荷构造 10.28ms；JSON 3.58ms；UTF-8 JSON 322,712 字节 |
| 1107 只精灵 | 载荷构造 74.28ms；JSON 38.57ms；UTF-8 JSON 3,423,643 字节 |
| 2000 只精灵 | 载荷构造 178.92ms；JSON 76.74ms；UTF-8 JSON 6,208,669 字节 |
| state，100 / 1107 / 2000 只 | 0.10 / 1.59 / 2.55ms；不是当前最重热点 |
| 积压事件 100 / 500 / 2000 条，每条 1000 个解码字段 | drain 34.30 / 161.83 / 747.53ms；最后只保留最多 200 份详情 |
| 蛋仓查询注入 200ms 同步延迟 | 本应 10ms 完成的事件循环计时器在 200.58ms 后完成 |
| 录制 20 段，每次 flush 注入 20ms | append 总计 409.18ms，直接拖住串行投递 |
| 9 个并发请求同一张缺图 | 发起 9 次下载替身调用，负缓存未抑制已排队请求 |

2000 只的 cProfile 中，pet_row 累计约 285ms，六维条约 120ms，detail_payload 约 74ms；profile 自身有开销，不与上表无 profile 数字直接相加。这说明优先减少构造次数和载荷范围，比微调排序更有效。

保存脚本复跑时，1107 只的构造/编码为 97.05/46.32ms，2000 只为 238.62/82.65ms；2000 条事件为 770.74ms，state 最多约 5.27ms。原始输出见上述 JSONL。两轮存在调度与机器负载波动，报告不把单轮点值当作固定 SLA；主要结论和响应字节数一致。

## 已确认问题

### R01 / P1：写回批次可能倒序；flush 也不能保证等待在途写入

位置：`spritelens/repositories/pet_store.py:256-272,367-369`、`egg_store.py:102-116,247-252`。

两个 Store 都先在 `_lock` 内取走 pending，随后才获得 `_flush_lock`。线程 A 已取走旧批次、尚未拿提交锁时，线程 B 可以取走新批次并先提交，A 再覆盖新值。注释声称“按取出顺序提交”，实现并未保证。

受控复现：在旧线程进入提交锁之前暂停它，新线程写入并提交值 20，再放开旧线程；**宠物 level 和蛋 quantity 最终都为 10，预期 20**。现有并发测试的暂停点在 execute_many，此时旧线程已持提交锁，漏掉了窗口。

还有同源问题：worker 已取走 pending 但尚未提交时，另一线程 flush 见 pending 为空就返回。复现 `has_pet(1,1)==False`，虽然该宠物已被 put 受理。新加的手工保存接口可能误报 404；EggStore.load 也存在相同的在途读取窗口。

### R02 / P1：关闭遇到慢盘或最终写失败，可能卡住或静默丢待写数据

位置：`pet_store.py:418-427`、`egg_store.py:341-350`、`spritelens/app_context.py:70-108`。

worker.join 有 5 秒超时，但随后同步 flush 可能无限等提交锁或数据库 IO，实际停止没有统一预算。另一方面，数据库异常被 _commit_batch 捕获后仅回填 pending，close 仍正常返回，AppContext 已提前置 `_closed=True` 并继续关闭数据库。

复现：execute_many 抛 OperationalError，两类 Store.close 均不抛错，pending_count 仍为 1。后续组合根关库、进程退出，这条数据无法落盘；再次 context.close 也因已关闭标记直接返回。

### R03 / P1：蛋仓标注队列在切换选择后可能保存到另一枚蛋

位置：`frontend/src/components/EggBoxDetail.vue:81-102`、`frontend/src/pages/EggBoxPage.vue:125-144`。

保存循环的 revision 和 promise 属于同一组件实例，但每轮发送时读取的是变化中的 `props.egg.instance_id` 和当前表单。快速在蛋 1 连续改两次性格，在第一次保存未完成时切到蛋 2，第二轮会向未编辑的蛋 2 发送保存，蛋 1 第二次修改丢失。如果蛋 2 的服务端标注已发生新变化，这笔基于旧快照的无意保存还会覆盖它。

通过当前 SFC 的实际 setup 复现：用户仅编辑蛋 1，调用序列却为 `{id:1,nature_id:1}`、`{id:2,nature_id:0}`。不是仅凭推测提出。

同域另有静态确认的时序缺口：收藏完成后只按 instance_id 调用 setFavorite，没有核对发起时 uid/页面代次；旧账号请求晚到且新账号有同 id 时，会污染当前展示。标注保存完成无条件 model.load，也可能在离页/切号后触发额外加载。后两项尚未用真实页面操作复现。

### R04 / P1：事件页未打开，也逐条格式化全部详情，阻塞所有 HTTP/WS

位置：`spritelens/view_models/events_vm.py:39-69`、`spritelens/web/server.py:694-708`。

每 0.5 秒 push_loop 先 drain 全部事件。drain 对每条立即递归生成完整详情字符串，之后才淘汰至 200 条。即使用户一直停留在精灵页，也支付这些开销。合成积压场景已达 747.53ms，单次工作超过推送间隔。

### R05 / P1：异步 HTTP handler 内仍同步查询/提交 SQLite

位置：`spritelens/web/server.py:428-444,481-549,606-615`。

蛋仓 GET 同步 annotations 查询；手工声音/标注/收藏 POST 同步 flush、query、execute；bootstrap 通过 cached_accounts 查询本地库。Database 的全局锁也被后台批量写持有，因此无须磁盘完全卡死，正常查询也可能等待在途提交。新蛋仓保存放大了这个路径。

200ms 查询替身已确认事件循环会整体停顿 200ms。把函数声明成 async 不会消除这个问题；必须把完整的同步用例移出事件循环。

### R06 / P1：精灵列表和启动响应总是构造全库存的完整详情

位置：`spritelens/web/payloads.py:48-126,144-231`、`spritelens/web/pet_details.py:11-52`、`server.py:428-444,472-479`、`frontend/src/composables/usePets.ts:13-18,41-49`。

每次筛选、实时版本刷新都构造全部命中精灵的六维条、技能、测量范围、进化链、奖牌与详情，连静态选项也重复下发。前端一页只显示 30 只，却总取完整列表；bootstrap 在概览首屏也带全量 pets。1107 只约 113ms 服务端构造和编码、3.42MB；2000 只约 256ms、6.21MB，尚未计浏览器解析和响应式处理。

已有分页限制了 DOM 数量，无法消除服务端构造和全量传输成本。AbortController 只能阻止前端采用旧响应，当前同步服务器工作已经开始后仍会做完。

### R07 / P1（录制开启或 checkpoint 写入时）：旁路 IO 仍串行挡住解码

位置：`spritelens/services/capture_service.py:273-276`、`spritelens/recording/recorder.py:57-85`、`spritelens/services/monitor_service.py:158-178,204-230,299-308`、`capture/key_store.py:64-77`。

tee 先 append/flush 原始录制，再把 chunk 交给 monitor；录制慢盘直接阻塞整个投递线程。checkpoint 的目录/写临时文件/replace 也在 monitor 锁内执行；身份帧或握手时还可能连续保存，平时约每 5 秒一次。

录制慢盘替身已验证约 409ms/20 段。checkpoint 的锁内同步路径已静态确认，本轮没有做真实慢盘/抓包负载测试。不能通过增大队列或丢业务包来掩盖。

### R08 / P2：慢 WS 客户端挡住健康连接和后续状态计算

位置：`spritelens/web/server.py:694-718`。

broadcast 依次 await 每个 send_str，无发送预算。第一个连接背压时，后面健康连接无法收到；push_loop 也等 broadcast 完成才进入下一轮。这里阻塞的是推送链路，不是说 await 会冻结整个事件循环。

慢 socket 用 Event 挂住的替身复现：50ms 后健康连接仍没收到；释放慢连接后才收到。当前使用 set，实际谁先遇到是非确定的，但任一慢连接均可能拖后面的发送。

### R09 / P2：每条宠物事件重复完整提取两次

位置：`spritelens/services/pet_repository.py:61-63,113-115`、`spritelens/domain/pets.py:288-305`。

一次用于学习炫彩名字，一次用于聚合。两次都递归遍历 decoded、构造 Pet/属性/技能，不是两次便宜的字典查询；发生在 monitor 的串行处理锁内。

这是可直接消除的冗余。必须保留原有区别：炫彩学习排除试用/镜像；仓库仍接收 include_non_owned=True 的记录来纠正历史误收。不要为此引入通用事件总线或改变 opcode 兼容策略。

### R10 / P2：缺图并发的负缓存检查位置错误，失败请求会重复下载

位置：`spritelens/web/pet_media_cache.py:42-71`。

冷却检查在 Semaphore 外；已通过检查而排队的请求进入后只复查本地文件，不复查 misses/network_retry。不存在的图片不会产生本地文件，所有排队请求都会再次尝试。9 个相同缺图并发请求已复现 9 次下载替身调用。Semaphore 限并发为 3，不等于同资源请求合并。

### R11 / P2：打包会收入当前工作区的约 18.93MiB 候选素材

位置：`build_config.toml:73-77`、`build.py:142-149`。

resources 整目录被 include_data_dirs 收入，Nuitka 目录收集不受 Git 未跟踪状态保护。当前两个 wiki 候选目录共 234 个文件、18.93MiB；运行代码的资源引用为 app.ico，未找到这些目录的运行时调用。它们会增加发布输入与 onefile 解包负担，不能当作正式资源自动发布。

本轮只测了源码资源字节数；**没有构建 exe，不能声称包会精确增加 18.93MiB 或冷启动增加多少秒**。不删除候选素材，改发布收集范围即可。

## 给 6luna 的执行计划

一次只做下表的一项；每项独立提交、复核，再进入下一项。编号 CR15-* 是本审查切片编号，执行时映射/登记到已有 ROADMAP 的对应项，不展开整个 S/P/F 阶段。

| 顺序 / 任务 | 范围与最小实现 | 失败分支与验收 |
| --- | --- | --- |
| 1. CR15-01 / R01 / 持久化批次 | 两个 Store 的提交锁覆盖“取批次→提交/失败回填”，统一锁序，put 仍只持短状态锁；读前 flush 必须能等待更早的在途批次。不要新增万能 Store 基类。 | Event 暂停点放在旧批次取走后、获得提交锁前；新值不能被旧值覆盖。另测 pending 空但在途未完成时读取/手工保存不会误报不存在。保留写失败回填新值优先。复用 test_persistence/test_egg_box。 |
| 2. CR15-02 / R02 / S03b 关闭 | Store.close 明确报告最终写失败和未完成状态，AppContext 仅在相关 worker 确认退出、待写保存成功后释放 DB；失败/超时保留唯一清理所有权并允许重试。 | 写库持续失败、恢复后重试、worker 卡在 IO、重复 close。join 后不能再无界等 flush；未确认退出不能关其正在使用的 DB。不要静默丢 pending，也不要每次重试另起清理线程。 |
| 3. CR15-03 / R03 / F04-U1 编辑时序 | 标注保存按发起时 uid、instance_id、页面代次绑定不可变目标和对应草稿。连续编辑只合并同一目标；切换目标不能把未完成 revision 迁给新目标。收藏回包核对 uid/代次后再改展示；离页后不无条件重拉。状态由页面/composable 持有。 | 延迟第一笔保存→继续编辑→切蛋/切号/离页；旧目标编辑不得写新目标。保存失败保留该目标草稿并可重试。用 Vitest 的 deferred promise 覆盖这个数据风险，不补像素/DOM 镜像测试。 |
| 4. CR15-04 / R04 / P01 事件热点 | drain 只产生轻量行并保存有界的原始事件引用；detail(index) 首次访问时再格式化并缓存。先淘汰再重计算，保持现有文本/索引/淘汰语义。 | 用户不打开详情时，drain 不调用 render_decoded；打开同一详情结果一致；淘汰后仍显示原提示，内存有界。只为真实缓存/淘汰行为补必要回归。对照 2000×1000 字段基线，记录耗时与 loop lag。 |
| 5. CR15-05 / R05 / P01 HTTP IO | 把涉及 Store 的完整同步用例放到 asyncio.to_thread，保留 uid 输入与完整快照检查；新手工命令经明确 service/VM 边界执行，路由只解析/调用/序列化。不要仅 offload 最后一条 SQL。 | 注入慢查询/提交，另一 /api/state 请求与计时器保持可调度。持久化异常返回可读失败，UI 不显示保存成功；版本与归属回归仍成立。与 CR15-02 协调服务器停止时在途操作的所有权，不能提前关 DB。 |
| 6. CR15-06 / R06 / P01 列表载荷 | 先列出卡片、筛选、箱队与详情实际字段。列表只构造必要摘要，选中精灵再取详情，详情应带 uid/gid/version；bootstrap 返回首屏所需摘要，宠物页激活后再加载。若精简后仍超预算，再决定服务端分页，不同时引入多个方案。 | 对照 100/1107/2000 只，分别记录构造、编码、字节、浏览器解析/首个可交互时间；不丢箱位 matched/filtered/missing/unknown、选项全库存语义。乱序详情/切号旧响应拒绝提交；保留旧页面连续性与详情定位。同步 TS 运行校验、调用方，Vue 变更运行构建。 |
| 7. CR15-07 / R07 / P01 采集旁路 | 录制改有界队列+单写者批量 IO，状态读取不等 IO；checkpoint 用单一写者按版本合并。保持流顺序，身份失效/SYN/ACK 不能被旧保存任务覆盖。两个子改动可分别提交，均需明确停止与保存失败。 | 20ms/段慢盘时 monitor 收包不等录制 flush；队列过载丢录制旁路并计数，不能阻塞或丢业务采集。最终 flush、停止超时和重试遵守 CR15-02；会话接续/失效原回归保留。不得只加 buffer、增大 queue 就宣告完成。 |
| 8. CR15-08 / R08 / P04 WS | 每连接发送有预算，发送相互隔离；明确超时后的断开/移除。可用受控并发发送，不创建无界后台任务或发送积压。状态允许合并为最新快照。 | 一个 send_str 挂住时健康连接仍收到下一版；慢连接被移除且清理完成；关闭无遗留任务。保留唯一 WS 所有者及重连逻辑。 |
| 9. CR15-09 / R09 / P01 重复提取 | extract_pets(include_non_owned=True) 一次；同一结果用于合并，学习表另外按已知归属标记过滤。 | 试用、镜像、炫彩学习、简略更新保留字段的既有测试；代表性大页 profile 显示每事件只做一次完整提取。只局部改 PetRepository。 |
| 10. CR15-10 / R10 / P01 缺图 | 进入 Semaphore 后复查本地文件和两种冷却；若仍需同名请求合并，再增加最小的按名称在途任务表，完成即清理。 | 9 个相同 404 请求实际尝试应合并/抑制；网络全局冷却对已排队请求也生效；过期可重试，正常/异色回退保持。用下载替身，不依赖真实 CDN。 |
| 11. CR15-11 / R11 / A03 发布 | 明确列出运行所需 resources 文件，将候选图与 source/研究素材排除出发布清单；保留原始候选文件。 | dry-run/暂存清单无两组 wiki 目录，app.ico 和正式媒体仍可用。最终发布再测 onefile 总启动/解包后启动，记录两种口径。不要为了减少包体删未裁定素材。 |

每项交付统一写：基线与保留的用户改动、状态所有者、修改文件、失败分支、验证证据、未验证范围、回退条件。持续状态只回写 ROADMAP；数据正确性验收不以“测试总数增加”代替。

性能验收先记录本机对照值，再定产品阈值，不把本报告的微基准写成跨机器的硬门禁。至少区分：纯 Python 构造/编码、事件循环延迟、HTTP 端到端、WebView2 操作卡顿、驱动队列丢弃、退出耗时。

## 次要观察，暂不单独展开

- state 内容未变不推送，但仍每轮排序/复制库存、聚合；两轮中大库存约 1–6ms，排在上述热点之后。确有持续 CPU 问题再考虑 uid/version 对应的聚合复用，不能建立会过期的平行状态。
- `server.py:416` 对所有静态资源强制 no-store，包括哈希 Vue 文件和图片。它放弃浏览器跨导航缓存；本轮未量化真实 WebView2 重复解码/请求成本，暂不按已测瓶颈处理。后续可按 index/非哈希入口与哈希资源分别制定缓存策略。
- 蛋仓已使用 @tanstack/vue-virtual，精灵列表已有 30 项分页；不要再次为这些页面引入虚拟列表库。
- 原始回放 read_text + splitlines + 全部 StreamChunk 常驻，长文件峰值内存会随文件增长；队列主要按条数有界，流重组主要按单流有界，仍缺整体字节预算。归 P02，须用长合成回放测 RSS/日志增长后再排实施范围。
- `server.py`、`payloads_catalog.py`、原生 app.js 职责集中仍存在，但应随上述用例局部抽取，不能把机械拆文件列为性能修复。
- 文档存在漂移：架构仍写持久化 v11，而当前工作区迁移到 v14；开发指南有“仅蛋图鉴迁 Vue”的旧描述，当前蛋仓也已 Vue。执行对应功能切片时同步维护，不因这些旧描述回退现有实现。

## 已执行与未执行验证

已执行六个相关模块：

```powershell
.venv/Scripts/python.exe -B -m unittest tests.test_persistence tests.test_egg_box tests.test_view_models tests.test_session_resume tests.test_recording tests.test_web_server -q
```

结果：**104 tests，OK**。这些通过不否定本报告的受控反例，特别是 R01 的现有测试暂停位置不同。

另执行合成微基准、两类 Store 批次倒序/写失败、在途读取、同步查询 loop lag、慢 WS、缺图并发、录制慢盘替身，以及当前 Vue SFC 实际 setup 的保存错目标复现。所有探针只使用合成数据。

未执行：全套测试、前端发布构建（未改业务代码）、真实 Npcap 登录高负载、真实慢盘、可见 WebView2 帧率/输入延迟、真实多账号操作、长会话 RSS、exe/onefile 构建与启动。没有宣称这些已通过。
