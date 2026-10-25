# 打包耗时研究与缩短方案（2026-10-25）

状态：一次性研究快照；本轮未修改任何构建脚本、配置或业务代码（仅临时改一个模块做缓存命中实验，已用 `git checkout` 还原并确认工作区干净）。
读者：构建/发布维护者、后续实施加速任务的实现者。
维护边界：本文只记录 2026-10-25 本机实测数据、阶段拆解、方案排序与风险；真正改 `build.bat` / `build.py` / `build_config.toml` 需另立任务，按 [开发指南](../DEVELOPMENT_GUIDE.md#资源与打包兼容) 与 [架构决策](../ARCHITECTURE_DECISION.md) §8 的踩坑清单验证。

## 1. 结论（先看这三行）

1. **耗时的绝对大头是 C 编译（564 个生成文件，占冷构建 70.4%）**；Nuitka 4.3 没有增量编译，所以每次构建都会重新生成 C，唯一能跨构建复用的是 Nuitka 自带的 ccache。
2. **过去每次构建都 100% ccache 未命中**（累计 2420 次 miss / 1 次 hit），等于每次都从头编译；把缓存键固定住之后，**同参数第二次构建实测 25m31s → 6m57s（−73%，实验脚本复刻）/ 7m28s 与 9m07s（真实 `build.bat`→`build.py` 入口连续两次复验，448s / 547s，均 564 命中）**，改一个模块后重建实测 **8m16s**。这一条不需要改任何代码，只要不破坏缓存前提；另外实测确认了**环境里带相对路径的 `CCACHE_DIR` 会让 ccache 100% 未命中**（见 §5.1），这是"之前每次都慢"可复现的原因之一。
3. 还想再快，就只剩两类改动：**开发档不产 onefile（预计再省 ~3 分钟，热缓存下约 5 分钟）**，以及**缩减 C 生成量**（scapy 占生成 C 的 58.6%，估冷构建可省 ~9.5 分钟，但要动 scapy 导入面，风险高，需单独立项）。

## 2. 测量口径

- 机器：Windows 11，i7-13700H（14C/20T），32GB，NVMe SSD；Python 3.12.10（`.venv`），Nuitka 4.3，Nuitka 自带 MinGW gcc 15.2.0 + ccache 4.12.3。
- 构建入口：`build.bat` → `build.py`（配置 `build_config.toml`）→ `python -m nuitka`；发布配置为 `--standalone --onefile --windows-uac-admin --remove-output --mingw64`，gcc 参数 `-O3 -mno-gfni`，scons 并发 20（=逻辑核数）。
- 前端 Vite 构建（`build_frontend.bat` / `tools/frontend.py build`）**不属于打包耗时**；`build.py` 打包前只做前端产物哈希校验（`tools/frontend.py check`），不重新构建前端。
- 实验方法：用一次性脚本（`build/_bench/bench_build.py`，位于 gitignore 的 `build/` 下，不入库）复刻 `build.py` 生成的**完全相同**命令行与 Nuitka 环境变量（`NUITKA_CACHE_DIR` 等），给每行输出加时间戳，记录总耗时与 ccache 前后统计；目标均为 `--output-filename=bench_SpriteLens`，不覆盖正式产物。
- 基线产物：`build/optimized-build.log` / `build/optimized-timing.json`（2026-10-25 15:42:08→16:07:39，exit 0，25m31s，产出 55.3MB exe）。C 编译的时间边界由 ccache 结果文件 mtime 还原（Nuitka 只打印 ≥360s 的单文件耗时，见 `nuitka/build/SconsSpawn.py` 的 `min_report_time`）。

## 3. 冷构建 25m31s 的构成

| 阶段 | 实测耗时 | 占比 | 关键事实 |
|---|---|---|---|
| 预处理：PASS1/PASS2 优化 + C 代码生成 + 插件/依赖 | ~208s | 13.6% | 单线程；1045 个模块；scapy 占其中 87.09s（39.8%） |
| C 编译 564 个文件（scons 20 并发） | 1078s | 70.4% | 生成 C 共 527.70 MiB；scapy 309.44 MiB（58.6%）；4 个 >360s 文件全是 scapy（ms_srvs 446.10s、ms_nrpc 482.40s、bluetooth 368.10s、kerberos 360.47s） |
| 链接 + dist 装配 + onefile 压缩/装配 + 图标 + 清理 | ~245s | 16.0% | onefile payload 147,699,180→57,701,152 B（39.07%），zstd level 22 |

补充：payload 140.86 MiB = 数据 35.91（其中 pet-media 静态图 26.08）+ DLL 14.91 + C 扩展 7.16 + 其余（main.dll 代码/常量）约 82.88。静态资源目录逐个核对过引用，**没有发现死资源目录**，压缩包体积不是本轮目标。

## 4. 实测：缓存热起来之后的三种场景

| 场景 | 实测总耗时 | ccache 结果 | 说明 |
|---|---|---|---|
| 冷（15:42 基线，全部 miss） | 25m31s | 564 miss | 旧 main.build 被删除、缓存键不匹配 |
| 同参数再构建一次（仍全 miss） | 27m08s | 564 miss | 当时机器同时在跑分析任务，比基线慢约 6% |
| 再构建一次（缓存全命中） | **6m57s** | **564 hit** | 关键词：`result 'cache hit': 564` |
| 改 1 个模块后重建 | **8m16s** | 563 hit / 1 miss | 只有被改模块的 C 重编；总时长波动来自 zstd 压缩耗时（100.3s→119.3s）等机器噪声 |
| 真实入口 `build.bat`→`build.py`（干净环境，第 1 次） | **7m28s（448s）** | **564 hit** | 2026-10-25 18:15 用与用户完全相同的命令 `.venv/Scripts/python.exe -B build.py` 复验，产出 `build/小洛探探_SpriteLens_1.0.0_3296.exe`（55.3 MB）；仅 onefile 引导文件 1 miss（正常） |
| 真实入口第 2 次（间隔 24 分钟） | **9m07s（547s）** | **564 hit + 1 引导 hit** | 产出 `build/小洛探探_SpriteLens_1.0.0_5438.exe`（55.3 MB）；本次 ccache 统计 **+565 命中 / +0 miss**。与第 1 次的 100s 差异主要来自 onefile 压缩与机器负载（两次间隔期间有其它进程活动），命中行为稳定可复现 |

缓存全命中时的阶段耗时（6m57s 那次）：Python 优化 148.8s → C 生成 52.6s → 编译+链接 21.4s → 图标/dist 装配 23.5s → **onefile 压缩 100.3s** → onefile 引导编译+链接 ~20.8s → 最终 exe 装配 37.7s → 清理 ~11s。

**也就是说：热缓存构建仍然有约 4 分钟"固定成本"（Python 优化 + C 生成 + 链接），onefile 管线另外占约 3 分钟。**

## 5. 关键机制（决定方案取舍）

### 5.1 ccache 是唯一跨构建复用手段

- Nuitka 把自带 ccache 注入到**全部 564 个模块编译**上（`nuitka/build/SconsCaching.py:103-198`），缓存目录默认在 `NUITKA_CACHE_DIR/ccache/<abi>`，即 `build/nuitka-cache/ccache/3.12`（由 `build.py` 的 `build_environment()` 指定的 `build/nuitka-cache`）。当前占用 0.2 GiB / 上限 5.0 GiB，**没有淘汰风险**。
- 缓存键 = 编译器 + 命令行 + 工作目录（`hash_dir=true`）+ 编译器 mtime；因此 **换 Nuitka 版本、换 gcc、改 CFLAGS、移动仓库路径都会让全部缓存失效**。
- 生成 C 的内容是可复现的：两次构建抽样比对 `module.*.c` 逐字节相同，所以"同参数 → 同键 → 命中"在机制上成立，实测也已确认。
- 历史 0% 命中的直接原因无法完全复盘（15:42 那次构建写入的键与后来同命令的键不同；推测是此前几轮实验改过环境/参数）。**落地时以实测为准：连续两次同参数构建，第二次日志必须出现 `cache hit: 564`，否则缓存前提被破坏，需要排查再继续。**
- **已定位一条可复现的"全 miss"机制：环境里带相对路径的 `CCACHE_DIR`。** `nuitka/build/SconsCaching.py:216-222` 只在 `CCACHE_DIR` **不存在**时把它设成绝对路径；若外部环境已导出 `CCACHE_DIR=build/nuitka-cache/ccache/3.12`（相对路径），Nuitka 不再覆盖，ccache 会按每次编译的工作目录（`build/main.build`）解析，缓存落到 `build/main.build/build/nuitka-cache/...` 的私有目录，随后被 `--remove-output` 连同 `main.build` 一起删除 → 每次构建都 100% miss。2026-10-25 18:0x 的 `real1` 实验就是这样被污染的（ccache 日志 `Config: (environment) cache_dir = build\nuitka-cache\ccache\3.12`，且 `build/main.build/build` 长到 93 MB，564 次全 miss）。清掉该变量后同一条命令重跑：`cache_dir = D:\code\SpriteLens\build\nuitka-cache\ccache\3.12`、564 hit、448s。**规则：不要 `export CCACHE_DIR`（或只给绝对路径）；构建脚本会自动用 `NUITKA_CACHE_DIR/ccache/<abi>` 的绝对路径。** 排查时看日志头这一行：绝对路径才对。

### 5.2 Nuitka 4.3 没有增量编译，保留 build 目录没有收益

- 每次构建都无条件执行 `cleanSconsDirectory()`，删掉全部 `.c/.o/.obj/.lib/.res/.const`，再重新生成所有 C（`nuitka/MainControl.py:285-291`、`nuitka/build/SconsInterface.py:671-723`、`nuitka/tree/SourceHandling.py:340-345`）。
- `--remove-output` 只是结束时删除 `main.build`/`main.dist`（`nuitka/MainControl.py:1350-1396`、`nuitka/freezer/Onefile.py:330-341`），**对耗时中性，也不影响 ccache**。所以"去掉 --remove-output 让下次增量"是无效期待。

### 5.3 scapy 为什么被全量编译

- `.venv/Lib/site-packages/nuitka/plugins/standard/standard.nuitka-package.config.yml` 里 `scapy.all` 配置了 `implicit-imports: depends: scapy.layers.*`；只要静态引用到 `scapy.all`，Nuitka 就会把 bluetooth/kerberos/msrpce/dcerpc/smb2/dot11/x509/tls 等全部收进来（编译报告里 `usage="plugin:implicit-imports"` 可查）。
- 项目只在 3 处引用 scapy：`spritelens/capture/npcap_source.py:113`、`:461`、`spritelens/system/net_diagnose.py:24`，且都只需要 `AsyncSniffer` / `conf` 和 TCP/IP 解析。
- 因此 scapy 生成 C 占 58.6%、Python 侧优化占 39.8%，是"冷构建"最大杠杆；但 `build_config.toml` 里明确记录了排除 scapy 子模块曾导致网卡枚举失效（`as_resolvers` 被排掉），**不能盲加 `--nofollow-import-to=scapy.*`**，需要改导入面 + 分阶段协议回归，属于独立任务。

### 5.4 已确认的无效项 / 坑

- `--lto=no`：无效——编译模块 >250 时自动 LTO 已经关闭（564 远超阈值）。
- `NUITKA_RESOURCE_MODE=coff_obj`：已经是 Win32 非 ClangCL 的默认值。
- `--jobs`：默认就是 20（=逻辑核数），不需要调；调低只会变慢。
- `--zig`：会禁用 ccache；`--clang`：Windows 上需要可用的 Visual Studio；`--low-memory`：会把并发降到 1，灾难性。
- 删除 `build/`：会连带删掉 `build/nuitka-cache`（ccache + MinGW 下载 + 依赖扫描缓存），下次全量重来。
- 升级 Nuitka 4.3.1/4.3.2：没有可查到的编译提速，**反而会让 ccache 全部失效**。
- `--onefile-no-compression` 只省压缩那 100~120s，产物变成 ~147MB，适合开发档不适合发布。

## 6. 方案排序（按收益/风险）

### 方案 A：把"缓存热"固定下来（不改代码，立刻可用）

- 做法：日常构建保持与发布构建完全一致的参数（同 `build_config.toml`、同 Nuitka/gcc 版本、同仓库路径）；**不要删 `build/`**；不要同时跑两个构建；构建完在日志里确认 `Cached C files (using ccache) with result 'cache hit': 564`。
- 预期：冷构建 25m31s → 热缓存 **6m57s**（实测），改一个模块后 **8m16s**（实测）。
- 风险：低。唯一代价是"改任何 Nuitka 参数/版本/路径后，下一次构建回到 ~25 分钟"；这种一次性冷构建可以接受，也可以在想避免时挑空闲时间跑。
- 验证：连续两次同参数构建，第二次出现 564 hit；再改一个模块重建，应为 `hit: 563 / miss: 1`。

### 方案 B：加一个"开发档"（不动发布配置）

- 做法：新增开发用构建方式（新配置档或 `build_config.toml` 增加 profile 概念，由 `build.py` 读取），与发布档的差异只有两项：**去掉 `--onefile`**（只产 `dist/` 目录），可选再加 **`--onefile-no-compression`** 仅当仍要单文件时用。
- 预期（从实测扣减）：热缓存下 onefile 管线约 195.6s（压缩 100~120s + 引导编译链接 ~21s + 最终装配 ~38~53s + 图标），
  - 仅去 onefile：**约 5 分钟**（496−195.6≈300s，估算，需一次实测确认）；
  - 保留 onefile 但关压缩：**约 6 分钟**，产物 ~147MB。
- 风险：低（发布路径完全不变；开发档产物形态不同，不能当发布验收）。
- 验证：开发档构建一次记录耗时；`dist/` 下直接启动 GUI 检查；发布档仍走原配置并保留 `--smoke-test` + 实机启动三项验收。

### 方案 C：只在"冷构建"场景投入（按需，不急于本轮）

1. **gcc `-O1`**：Nuitka 自己追加 `-O3`，但环境变量 `CFLAGS` 在它之后追加（`nuitka/build/SconsCompilerSettings.py:1756-1765`、`:2150-2153`），所以 `CFLAGS="-mno-gfni -O1"` 能覆盖。估算冷构建的 1078s 编译可降到 ~430~650s（冷构建估 15~18 分钟），但缓存键改变 → 首次仍全冷，且运行性能略降。**只用于开发档，不用于发布。**
2. **缩减 scapy**：估冷构建省 ~9.5 分钟 + Python 侧省 ~87s，但要改导入面（例如从 `scapy.sendrecv` / `scapy.config` 导入）+ 分阶段抓包回归，风险高，单独立项。
3. **bottle / PIL 插件裁剪**：bottle 是单个 10.25 MiB C 文件（pywebview 自带 http server 未被使用，应用走自己的 aiohttp），估省 ~21s；PIL 只用到 Image+WebP/PNG/JPEG，裁插件估省 20~30s。都是低收益中风险，优先级最低。
4. **MSVC（`--msvc=latest`）**：cl.exe 在巨型 TU 上可能比 gcc -O3 快，但需要装 VS Build Tools、全量重测，且 ccache 路径会换成 clcache；本轮未验证，不建议现在投入。

## 7. 建议落地顺序

1. （零改动）日常构建固定为"同参数、保留缓存、不 export `CCACHE_DIR`"，构建后确认命中（已实测两次连续真实构建 448s/7m28s、547s/9m07s，均 564 命中，把 25 分钟降到 8~9 分钟）：
   - 构建前：`echo "$CCACHE_DIR"` 应为空，或至少是**绝对路径**（相对路径会 100% miss，见 §5.1）；
   - 构建后：日志出现 `Cached C files (using ccache) with result 'cache hit': 564`；若全量 miss，先查 `CCACHE_DIR` 与 ccache 日志头 `cache_dir`；
   - 保持 `build/nuitka-cache` 不被清理、不换编译器/参数；改版本号、改代码只让相关模块 miss，其余仍命中（实测改 1 模块 563 hit / 8m16s）。
2. 若 7 分钟仍嫌慢：做方案 B 的开发档（预计 5 分钟），发布仍用现配置。
3. 冷构建（清缓存/换机器/升级工具链）频率低，按需再评估方案 C 的 `-O1`；scapy 裁剪另立任务，不并入"加速打包"。
4. 任何构建配置改动后：打卡时日志确认 hit/miss 数、记录一次实测耗时；发布前按开发指南做 `--smoke-test` + 实机启动验收。

## 8. 未验证 / 不确定项

- 15:42 那次构建写入的缓存键为何与后来同命令不同，未复现出根因（当时没有留下 ccache 日志）；本轮已定位一条足以造成同样现象的机制（相对 `CCACHE_DIR`，见 §5.1），但不能确认 15:42 就是该原因。
- 方案 B 的 5 分钟是扣减估算，未实测；onefile 相关耗时受机器负载影响明显（warm2 417s / warm3 496s / 真实入口 448s 与 547s，最长相差 22%），热构建可在 7.5~9 分钟间波动。
- 2026-10-25 18:22 与 18:59 产出的 `build/小洛探探_SpriteLens_1.0.0_{3296,5438}.exe` 只验证了体积与可生成性；`--smoke-test` 需要 UAC 提升（发布配置 `uac_admin=true`），本轮无法在无人值守下执行，发布前仍需按开发指南做 `--smoke-test` + 实机启动验收。
- `-O1` 的编译提速、MSVC 对比、scapy 导入面改造后的抓包行为均未实测。
- 实验脚本与日志在 `build/_bench/`（gitignore，不入库）；需要复现时按本文 §2 的口径重建即可。

## 9. 数据来源

- `build/optimized-timing.json`、`build/optimized-build.log`：25m31s 冷构建基线与阶段标记。
- `build/scapy-report.xml`：模块优化/代码生成耗时、模块种类与插件 `implicit-imports` 证据。
- `build/probe/main.build/*.c`：生成 C 体积分布（562 文件 / 527.70 MiB）。
- `build/_bench/{warm1,warm2,warm3}.log|json`：三次实验的时间戳日志与总耗时。
- `build/_bench/real1.log`（被 `CCACHE_DIR` 污染的全 miss 样本）、`build/_bench/realclean1.log`（干净环境 448s、564 hit 的真实入口第 1 次复验）与 `build/_bench/realclean2.log`（第 2 次，547s、564 hit）。
- `build/nuitka-cache/ccache/3.12`：ccache 配置与命中统计（`ccache -s`）。
