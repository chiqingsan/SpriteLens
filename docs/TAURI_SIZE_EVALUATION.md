# Tauri 打包体积评估

> 历史文档：本报告写于项目仍名为 RocoPeek 时期，文中的「本项目/我们」
> 即现在的 SpriteLens；结论与实测数据保留原样，仅项目名已随迁移更新。

> 命题：若将来用 Tauri（Rust 后端 + Web UI）替换当前 PyQt6 单体，打包体积会不会变得巨大？
> 方法：官方文档 + 本机实测双验证。
> **结论：不会巨大（~30MB 量级）。但它对"体积"的优势被高估了——因为体积大头是我们的游戏静态数据
> （26MB），不是框架；而 PyQt6 裁剪后打包同样能到 ~30~35MB。**
> 体积不是当前该优化的问题——见 §5。

---

## 0. 一句话结论

**Tauri 应用体积 = Rust 二进制（8~15MB）+ 前端（1~3MB）+ 静态数据（26MB）+ 杂项，
装包约 30MB。WebView2 复用系统的，不打包进安装包。**

但关键实测发现：**这 30MB 里有 26MB 是我们自己带的游戏数据**，
不算框架开销。而当前 PyQt6 里有 **41MB 未使用模块可裁剪**，
**裁剪 + PyInstaller 打包后同样是 ~30~35MB**——也就是说，
**为了体积而选 Tauri，收益接近于零。**

---

## 1. Tauri 体积构成拆解

| 组成部分 | 体积 | 说明 |
|---|---|---|
| **系统 WebView2 运行时** | **0 MB 打包** | 复用系统自带，不进安装包（关键点） |
| Rust 编译产物（含协议层） | 8~15 MB | release + LTO + strip 后；`pcap`/`aes`/`serde` 等 |
| 前端（HTML/JS/CSS 打包） | 1~3 MB | 用系统 WebView2 的现成 V8，不打包浏览器 |
| **游戏静态数据** | **26 MB** | ← **真正的体积大头**，见 §3 |
| 图标/配置/其他 | <1 MB | |
| **合计（主程序）** | **~40 MB** | |
| **安装包（NSIS/LZMA）** | **~30 MB** | 静态数据 JSON 压缩率极高 |

### 1.1 为什么 WebView2 是 0 MB

Tauri 官方文档明确（已核实 `v2.tauri.app/distribute/windows-installer/`）：

- **默认模式 `downloadBootstrapper`：额外体积 0 MB**，运行时缺失才下载安装（需联网）。
- Windows 10（2018 年 4 月后版本）与 Windows 11 **系统自带 WebView2**。
- 本机实测确认：注册表 `HKLM\...\EdgeUpdate\Clients\{F3017226...}` 存在，
  版本 **154.0.4258.62**，位置 `系统 Edge WebView2 安装目录（默认路径）`。
  → **目标用户（Win10/11 玩家）几乎 100% 已预装，下 0 字节。**

其他模式的额外体积（仅当要支持无网/特殊环境时才用）：

| 模式 | 额外体积 | 何时需要 |
|---|---|---|
| `downloadBootstrapper`（默认） | **0 MB** | 正常情况 |
| `embedBootstrapper` | ~1.8 MB | Win7 支持 |
| `offlineInstaller` | ~127 MB | 离线环境 |
| `fixedVersion` | ~180 MB | 固定 WebView 版本 |

**只有选 `offlineInstaller`/`fixedVersion` 才会"巨大"**——那是为无网环境付出的代价，
不是默认行为。

---

## 2. 与 Electron 的对照（公平基线）

上一轮我用 ZCode 的 733MB 代表 Electron，这里做个更严谨的修正说明：

| 应用 | 总体积 | 其中应用代码 | **框架基线**（潜在不含应用内容） |
|---|---|---|---|
| VS Code | 1049 MB | ~300 MB（内置扩展） | ~750 MB |
| DeepSeek Harness | 1036 MB | — | ~1000 MB |
| ZCode | 733 MB | **312 MB**（app.asar） | **~420 MB** |
| @opencodedesktop | 684 MB | — | ~680 MB |

**公平结论**：Electron 的**框架基线约 400 MB 量级**（Chromium + Node + ICU + V8 快照，
压缩安装包后约 60~80MB）。即使把应用代码算成 0，也远大于 Tauri 的 ~40MB。

**但这不构成"选 Tauri"的理由**——体积是 Tauri 唯一优势，而它要付的代价
（重写 1022 行协议 + 785 行测试、牺牲协议迭代速度）远大于体积收益。
见 `docs/STACK_EVALUATION.md` §3 决策矩阵。

---

## 3. 体积大头其实是静态数据，不是框架

这是最值得注意的一点。游戏静态数据全集（innovationb1ue 的 `data/game/`）实测：

| 文件 | 体积 | 用途 |
|---|---|---|
| `monster_map.json` | 7.4 MB | 怪物兜底表（1.1 万条） |
| `pet_skill_map.json` | 3.5 MB | 881 条学习表 |
| `pet_map.json` | 3.5 MB | 6575 实例化谱系 |
| `proto_schema.json` | 2.4 MB | 消息 schema |
| `pb_message_index.json` | 1.9 MB | 9883 索引 |
| `pet_species.json` | 1.7 MB | 1015 物种（种族值/属性/特性） |
| `skill_map.json` | 1.4 MB | 1378 技能 |
| `buffbase_map.json` + `buff_map.json` | 2.1 MB | 3804 buff 效果定义 |
| `special_move_map.json` | 0.9 MB | 首领特殊招式 |
| 其余（evolution/nature/type_chart…） | ~0.5 MB | |
| **合计** | **26 MB** | |

而当前 spritelens 自带的 schema 只有 **922 KB**（`data/schemas/`）。

**推论**：
1. 真正的体积增长来自**业务数据**（静态表 + 玩家的宠物/战报历史），不是框架选择。
2. 我们**不需要全量打包这 26MB**——按需裁剪（当前阶段只需 pet_species/skill_map/
   type_chart/nature_map/evolution_map ≈ 4 MB）或运行时按需下载。
3. 玩家数据（SQLite）会随时间增长，这才是长期体积主因——**这与选什么 UI 框架无关**。

---

## 4. 三种形态的体积对照（结论表）

**PyQt6 可裁剪性实测**（本机 `>2MB` 文件核算）：

| 类别 | 体积 | 明细 |
|---|---|---|
| **未使用模块**（可删） | **41.3 MB** | `opengl32sw.dll` 19.7、`avcodec-61` 13.4、`Qt6Quick` 6.3、`Qt6Qml` 5.1、`Qt6Designer` 5.0、`Qt6Pdf` 4.4、Quick3D 7.8 … |
| **核心模块**（必需） | **34.8 MB** | `Qt6Core` 9.9、`Qt6Gui` 9.1、`Qt6Widgets` 6.2、`QtWidgets.pyd` 4.8、`QtCore.pyd` 2.5 … |
| PyQt6 全量 | 207 MB | 差额多为 QML/Quick 插件、翻译、样式资源 |

**体积测算**（基于实测）：

| 形态 | 主程序 | 安装包 | 说明 |
|---|---|---|---|
| 当前 PyQt6（venv） | 248 MB | —（未打包） | PyQt6 占 207MB（含大量未用模块） |
| **PyQt6 + PyInstaller（裁剪后）** | **~70 MB** | **~30~35 MB** | 核心 35 + Python 运行时 ~18 + scapy 16 + 代码/数据 1 |
| **Tauri + Rust（带全量静态数据）** | **~40 MB** | **~30 MB** | Rust 8~15 + 静态数据 26 |
| Tauri（裁剪静态数据后） | ~15 MB | ~10 MB | 只带当前需要的 4MB 数据 |
| Electron | ~420 MB 框架基线 | ~60~80 MB | 不含应用代码 |

**关键洞察（实测修正）**：**Tauri 的体积优势没有想象中大。**
- Tauri 主程序 ~40MB 里，**26MB 是我们自己的游戏静态数据**，不是框架开销。
- PyQt6 经裁剪 + PyInstaller 打包后 **~30~35MB 安装包**，
  与 Tauri 的 ~30MB **几乎持平**——因为 PyQt6 那 41MB 未用模块可以全部剔除。
- 换句话说：**体积这一项，继续用 Python 也能拿到 95% 的收益，且零重写。**

**Tauri 的真实优势是"冷启动更快 + 内存更省"**（没有 248MB venv 常驻、
WebView2 按需加载），这两点对体验有实际价值——但仍远不足以抵消
重写 1022 行协议层 + 785 行测试的成本（见 `docs/STACK_EVALUATION.md` §3）。

---

## 5. 所以：体积该现在优化吗？

**不该。** 理由：

1. **当前还没打包**，用户（目前主要就是你）用的是 `.venv` 直跑，
   体积不是痛点；竞品 15.6MB 是它的**最终发行形态**，我们还没到那一步。
2. **先打包，后优化**。要发行时第一步应是 PyInstaller + 裁剪 Qt 未用模块
   （成本 1~2 天，248MB → ~30~35MB），这一步做完体积就已与 Tauri 持平。
3. **体积的大头（静态数据 26MB + 玩家历史）与框架选择无关**，
   优化它靠"数据按需加载/裁剪"，不靠换栈。

### 正确的体积优化顺序

```
现在：             不优化（未发行，体积非痛点）
要发行了：         ① PyInstaller 打包 + 裁剪 Qt 未用模块（1~2 天，248MB → ~30~35MB）
                   ② 静态数据按需裁剪/下载（~35MB → ~25MB）
                   ③ UPX 压缩主程序
若仍嫌大（协议已稳定）：④ 才考虑 Tauri 重写（→ ~30MB，成本最高，收益有限）
```

**注意 ④ 基本没有体积收益**——① 做完就已经到 ~30~35MB，与 Tauri 持平。
Tauri 真正的收益在**冷启动与内存**，不在体积。

---

## 6. 附：本次核实的实测事实

| 事实 | 数据 | 来源 |
|---|---|---|
| Tauri 默认 WebView 模式额外体积 | **0 MB** | 官方 `v2.tauri.app/distribute/windows-installer/` |
| WebView2 系统预装条件 | Win10 2018-04+ / Win11 | 同上 |
| 本机 WebView2 状态 | 已装 **154.0.4258.62**（系统级） | 注册表查询 |
| 本机最接近"纯框架"的 Electron 应用 | @opencodedesktop 684 MB | `du -sm` |
| Electron 框架基线（推算） | ~420 MB | ZCode 733MB − app.asar 312MB |
| 游戏静态数据全集 | **26 MB** | `du -sh data/game/` |
| 当前 spritelens 自带 schema | 922 KB | `du -sh data/schemas/` |
| 当前 PyQt6 venv | 248 MB（PyQt6 207MB） | `du -sh .venv` |
| **PyQt6 未使用模块（可裁剪）** | **41.3 MB** | `>2MB` 文件核算：Quick/Qml/Designer/Pdf/opengl32sw/avcodec |
| PyQt6 核心模块 | 34.8 MB | Qt6Core+Gui+Widgets+QtWidgets.pyd |
