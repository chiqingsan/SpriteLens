# 蛋神助手 v1.1.6 解剖报告

> 历史文档：本报告写于项目仍名为 RocoPeek 时期，文中的「本项目/我们」
> 即现在的 SpriteLens；结论与实测数据保留原样，仅项目名已随迁移更新。

> 目的：回答"蛋神助手是什么架构、有什么值得学"。
> 方法：本机安装包静态解剖（PE 头解析 → PyInstaller CArchive 解包 → pyc 反汇编 → 前端源码通读）。
> 素材：`C:\Users\chiqingsan\Downloads\蛋神助手电脑版-v1.1.6-b49823778e99.exe`（45 MB）
> 解包产物：`C:\Users\chiqingsan\AppData\Local\Temp\ds\out\...exe_extracted\`（1898 文件 + 754 PYZ 模块）

---

## 1. 总体架构

**一句话**：Python 3.12 后端（PyInstaller 打包）+ pywebview/WebView2 原生壳 + 本地 aiohttp 服务 + 手写原生 JS 前端 + Npcap 抓包协议解析 + 云端账号/交易市场。

```
┌─────────────────────────────────────────────────────────────┐
│ 蛋神助手.exe  (PE32+, 45 MB, 单文件)                          │
│  ├── 外层壳 461 KB (C++ 引导 + .fptable 自定义节)             │
│  └── PyInstaller CArchive overlay 46 MB                      │
│       ├── python312.dll + CPython 标准库                      │
│       ├── PYZ 754 模块 (业务代码 ~1.07 MB / 约 4.3 万行)       │
│       ├── webui/ 8 MB   手写原生 JS 前端 (零框架)              │
│       └── assets/ 26 MB 静态数据 + 官方美术资源                │
└─────────────────────────────────────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
  Npcap 抓包            aiohttp 本地服务         api.danking.cn
  (ctypes→wpcap.dll)   127.0.0.1:随机端口        (账号/交易/同步)
  TCP 重组 + AES-CBC    token 鉴权 + WebSocket
       │
       ▼
  SQLite 本地库 (events / outbox / 宠物快照)
```

### 1.1 技术栈证据链

| 层 | 结论 | 证据 |
|---|---|---|
| 打包器 | PyInstaller（Python 3.12） | cookie `MEI\014\013\012\013\016`，`python312.dll`，pyver=312，1898 文件 |
| 外层壳 | 自研 C++ 引导（非 UPX） | 7 节区仅 461 KB，`.fptable` 自定义节；字符串含 `PyInstaller`/`pyi-` |
| 桌面壳 | **pywebview**（EdgeChromium/WebView2） | `webview` 包 553 KB；`webview.guilib.initialize`；`CoreWebView2Environment` |
| WebView 兜底 | 运行时检测 + 引导安装 | `webview_guard.py`：`GetAvailableBrowserVersionString`，缺失时 `MessageBoxW` + 打开下载页 |
| 本地服务 | **aiohttp**（`aiohttp.web.Application`） | `web_runtime.py` 导入 `aiohttp.web`；`client_max_size=4194304` |
| 前端 | **手写原生 JS，零框架** | 无 React/Vue/jQuery；DOM `createElement` + `fetch` 封装 |
| 前端实时 | WebSocket（`/ws`） | 路由表含 `/ws`；`app.js` 用 `new WebSocket` |
| 抓包 | **Npcap + ctypes 直调 wpcap.dll**（非 scapy） | `load_wpcap`/`list_devices`/`PcapIf`；`Npcap device is missing` |
| 解密 | **cryptography** AES-CBC | `decrypt_cbc_body`: `Cipher(algorithms.AES(key), modes.CBC(iv))` |
| 数据校验 | RFC 8785 (JCS) 规范化 + SHA-256 | `rfc8785` 库；`hashScheme: 'jcs-sha256-v1'` |
| 增量更新 | **bsdiff4 + bz2 + Ed25519 签名** | `delta_update.py`: `bsdiff4.core.apply_patch`；`remote_release.py`: `Ed25519PublicKey.verify` |
| 密钥保护 | **Windows DPAPI**（`CryptProtectData`） | `app.py` `_dpapi_protect` / `_dpapi_unprotect`，前缀 `_DPAPI_PREFIX` |
| 官方资源代理 | 服务端图片代理 + 缓存 | `official_assets.py` 2196 行；`/api/official-assets` 路由 |

### 1.2 关键常量

| 项 | 值 |
|---|---|
| 游戏端口 | `GAME_PORT = 8195` |
| TGCP 魔数 | `TGCP_MAGIC = b'3f'` |
| 最大帧 | `MAX_FRAME_SIZE = 16777216` (16 MB) |
| 零 ACK | `ZERO_ACK = b'\x00' * 6` |
| 采集器版本 | `COLLECTOR_VERSION = '3.1.3'` |
| 主 API | `https://api.danking.cn/miniapp/api/v3/desktop/sync` |
| 更新控制 | `https://api.idom.fun/desktop/windows/control.json` |
| 模型 CDN | `https://api.danking.cn/pet-models/`、`https://models.danking.cn/pet-models/` |

---

## 2. 代码规模分布（反汇编 pyc 字节估算行数）

| 模块 | 字节 | ~行数 | 职责 |
|---|---:|---:|---|
| `desktop_ui` | 317,144 | 12,685 | **Tkinter 版旧 UI**（已被 Web 版取代，见 §5） |
| `app` | 198,581 | 7,943 | 本地状态库 LocalState + 云账号 + 市场 |
| `roco_collector` | 177,949 | 7,117 | 协议采集器（可独立运行 CLI） |
| `pet_medals` | 117,759 | 4,710 | 勋章数据/解析 |
| `official_assets` | 54,903 | 2,196 | 官方美术资源代理 |
| `nest_egg_inference` | 36,369 | 1,454 | 孵蛋推断 |
| `remote_release` | 21,371 | 854 | 远程版本控制 + 签名校验 |
| `egg_inventory` / `home_scene` / `home_breeding_range` | 18,933 / 18,442 / 7,387 | 757 / 737 / 295 | 蛋仓 / 家园场景 / 繁育范围 |
| `web_runtime` | （约 4300 行） | ~4,300 | Web 版主入口 + CollectorService + LocalWebServer |
| 其余 20+ 模块 | — | — | 见 PYZ 清单 |
| **业务合计** | **~1.07 MB** | **~4.3 万行** | |
| 第三方库合计 | 5.56 MB | — | aiohttp 0.93 / setuptools 1.43 / PIL 1.10 / cryptography 0.43 / webview 0.55 |

静态资源 26 MB：`official-resources` 7.3 M、`catalog` 4.9 M、`items` 4.8 M、`reference` 3.3 M、`trade-market` 1.1 M、`medals` 1.1 M。

前端 8 MB / 约 40 个 JS 文件，最大的几个：`trade-market-mini.js` 1.32 M、`planner-core.js` 755 K、`collection-model.js` 424 K、`app.js` 210 K、`skill-details.js` 162 K。

---

## 3. 协议采集器（`roco_collector.py`，最值得学的部分）

这个模块**可以脱离 GUI 独立以 CLI 运行**（`argparse` 支持 `--device` / `--duration` / `--jsonl` / `--key-hex` / `--state-db` / `--verbose`），同时支持**离线回放**本地 PCAP 和 **Hodor 文本日志**。

### 3.1 分层清晰

```
wpcap.dll (ctypes)
    ↓ list_devices / iter_live_packets
PcapIf / PcapPacketHeader / BpfProgram     ← 自己实现 pcap 读写，不依赖 scapy
    ↓
parse_tcp_packet                            ← 以太网/IP/TCP 解析
    ↓
TcpReassembler                              ← TCP 序号重组，处理乱序与 gap
    ↓
TgcpStreamParser                            ← TGCP 帧切分（魔数 3f / 16 MB 上限）
    ↓
decrypt_cbc_body                            ← AES-CBC 解密
    ↓
parse_tgcp_business_record                  ← protobuf 风格 varint 解析
    ↓
decode_* (30+ 个解码器)                      ← 业务语义层
    ↓
EventSink → LocalEventStore (SQLite) + NasUploader (gzip+token 上传)
```

### 3.2 亮点设计

**（1）解码器函数命名即文档**。`decode_pet_records`、`decode_box_snapshots_detailed`、`decode_handbook_glass`、`decode_egg_hatch_slots`、`decode_goods_change_inventory_updates`、`decode_known_pet_updates`、`decode_team_snapshot`、`decode_pet_free_response`、`decode_login_profile`、`decode_player_profiles`…… 一眼能看出游戏业务域划分。

**（2）流级状态容器 `FlowState`**，一个 TCP 流内聚了全部上下文：
```python
@dataclass
class FlowState:
    c2s_tcp / s2c_tcp: TcpReassembler
    c2s_tgcp / s2c_tgcp: TgcpStreamParser
    business_frames: list
    aes_key: bytes
    c2s_cbc_iv / s2c_cbc_iv: bytes
    game_id: str
    player_profile_hash: dict
    pet_hashes / box_hashes: dict
    box_slots: dict
```
上下行**各自独立**的重组器与解析器，IV 也分开存 —— 这点比自己实现的半双工更严谨。

**（3）断流恢复 `_recover_stream_gap`**。TCP 丢包后不放弃，而是：从 pending 缓冲重排 → 扫描 `TGCP_MAGIC` 重新对齐 → 重新解密 → 继续解析。这是长连接被动观测的核心健壮性设计。

**（4）密钥可热注入 `_seed_flow_state`**。通过 `state_provider` 回调按 `game_id` 拉取密钥，并缓存 `seeded_game_id` 避免重复拉取。密钥来源可以是 CLI `--key-hex` 或外部状态库 —— **官方游戏换 key 时无需重新打包**。

**（5）本地事件库用 outbox 模式**（`LocalEventStore`）：
```sql
INSERT OR IGNORE INTO events (event_id, event_type, game_id, occurred_at, payload, created_at)
-- 独立 outbox 表
UPDATE outbox SET attempts=attempts+1, last_error=?, next_attempt_at=? WHERE event_id=?
SELECT event_id,payload,attempts FROM outbox WHERE next_attempt_at<=? ORDER BY rowid LIMIT ?
```
事件先落库，上传失败进 outbox 退避重试（`attempts` + `next_attempt_at`）—— 这是**标准的事务性发件箱**，保证"采到的数据一定不丢"。

**（6）PCAP 旁路存档**。`PcapWriter` 可同时写原始 pcap（`data/pcap` 目录），便于事后复现问题。诊断模式支持 `--key-hex` 续采。

**（7）设备排序智能**：`active_network_descriptions()` 调 `subprocess` 查当前活跃网卡，`network_device_rank` 给它们排优先级，默认选中活跃网卡而非第一个。

---

## 4. Web 架构（最值得借鉴的部分）

### 4.1 本地服务：随机端口 + 单次 token

```python
def bind_browser_socket():
    for _ in range(N):
        try:
            s = socket.socket(AF_INET, SOCK_STREAM)
            s.bind(('127.0.0.1', 0))   # 端口 0 = 系统分配
            s.listen()
            return s
        except OSError:
            s.close()
```

- **随机端口**：避免固定端口冲突与外部扫描
- **`secrets.token_urlsafe()` 生成 token**，通过 URL fragment 传给 WebView：`http://127.0.0.1:PORT/#token=...`
- 服务端用 `secrets.compare_digest` 做**常量时间比较**，防时序攻击
- 前端把 token 存 `sessionStorage`，每次请求带 `X-Local-Token` 头
- 只在 `127.0.0.1` 监听

这套组合（随机端口 + 每次启动换 token + 常量时间比较 + 仅回环）比 roco_helper 的固定端口方案更严谨。

### 4.2 启动容错链（`desktop-boot.js`）

```js
// 1. token 优先从 hash 取，失败退回 sessionStorage
let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
try { if (token) sessionStorage.setItem('danking.localToken', token);
      else token = sessionStorage.getItem('danking.localToken') || ''; } catch {}

// 2. 全局捕获资源加载错误（script/link 标签）
window.addEventListener('error', event => {
  if (event.target !== window && !['SCRIPT','LINK'].includes(event.target?.tagName)) return;
  if (!complete) failed(..., () => location.reload(), false);
}, true);

// 3. 所有请求 15s 超时 + AbortController
async function json(url, options = {}, timeout = 15000) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
  ...
}
```

- **启动面板 `#startup-panel`**：纯 HTML 内联，不依赖任何 JS 模块，保证"JS 全挂也能显示错误"
- **自动重试 2 次**（间隔 2s），失败后显示"重新加载"按钮
- 关键注释：`Startup recovery must not depend on browser storage or application modules.`

这是**桌面壳 + Web 前端**场景下非常实用的自恢复设计。

### 4.3 前端工程化克制

- **零框架**：40 个 JS 文件全部手写，没有 React/Vue
- **按功能域拆文件**：`trade-market.js` / `planner-core.js` / `collection-model.js` / `flowers.js` / `home-breeding.js`
- **CSS 按模块拆**：`app.css` + `motion.css` + `planner.css` + `flowers.css` + `readability.css` + `responsive.css` + `collection-lines.css`
- `desktop-storage.js` 封装 `localStorage` 读写（带命名前缀 `danking.`）
- `official-image-fallback.js` 专门处理图片 404 降级

### 4.4 前后端接口约定

- `GET /api/bootstrap` —— **一次性返回**前端初始化所需的全部数据（宠物目录、蛋目录、成就、性格枚举、UI 偏好），减少往返
- `GET /api/state?revision=N` —— **基于 revision 的增量轮询**，配合 WebSocket 推送
- `POST /api/ui/preferences` —— UI 偏好持久化
- 业务接口按域分组：`/api/capture/*`、`/api/devices/*`、`/api/cloud-account/*`、`/api/market/*`、`/api/color/*`、`/api/subscription/*`、`/api/planner/*`、`/api/eggs/*`、`/api/profile/*`
- 统一 `req` 封装：自动加 token 头 + JSON 解析 + 错误处理

---

## 5. 一次真实的 UI 迁移（重要发现）

打包里**同时存在两套 UI**：

| | `desktop_ui.py`（旧） | `web_runtime.py` + `webui/`（新） |
|---|---|---|
| 技术 | Tkinter（`tk.Tk`、`ttk.Combobox`、`Canvas` 手绘雷达图） | pywebview + aiohttp + 原生 JS |
| 规模 | 12,685 行 | ~4,300 行 Python + 8 MB JS |
| 入口 | `app.py` 的 `if __name__ == '__main__': CollectorApp().mainloop()` | `web_runtime.py` 的 `main()` |
| 状态 | **仅被自身引用**，无人调用 | 实际入口 |

证据：
- `app.py` 顶部 `import desktop_ui` 和 `import tkinter`，`CollectorApp(tk.Tk)` 定义在 2360 行，`mainloop` 在 3268 行
- 但 `web_runtime.py` 的入口链是 `main()` → `LocalWebServer` + `CollectorService`，完全不引用 `desktop_ui`
- `desktop_ui.pyc` 317 KB 里没有任何模块反向引用它（只有 `app.pyc` 和它自己）

**结论**：这个产品**从 Tkinter 迁移到了 Web 前端**，旧代码作为死代码留在包里（`desktop_ui` + `_tkinter.pyd` + `_tcl_data` + `_tk_data` 都是迁移残留）。这直接印证了 spritelens 现有技术评估里"PyQt 壳 + 内嵌 FastAPI 渐进 Web 化"的方向 —— 同赛道的头部产品已经走完了这条路。

### 5.1 迁移没做干净（代价确证）

这不是"干净的迁移"，而是**新入口反向依赖旧模块**，导致旧 UI 无法真正摘除：

```
web_runtime.py
  └── from app import (APP_NAME, APP_VERSION, ..., CollectorApp, EventSink, LocalState, RocoDecoder, ...)
                      ↑ 注意 CollectorApp —— Tkinter 窗口类
       └── app.py
             ├── 第 23/24 行  import tkinter as tk; from tkinter import filedialog, messagebox, ttk   ← 模块级无条件
             ├── 第 28 行     import desktop_ui                                                       ← 模块级无条件
             └── 第 2360 行   class CollectorApp(tk.Tk): ...                                          ← 12,685 行 UI
```

`web_runtime.py` 的导入清单里同时出现 `CollectorApp`（Tkinter 主窗口类），说明 Web 版复用了旧 `CollectorApp` 上的某些静态方法（如 `_build_cloud_snapshot` 调用的 `CollectorApp._cloud_snapshot`）—— 为了一个静态方法，把整个 Tkinter UI 拖进了运行时依赖。

**代价**：`_tkinter.pyd` + `_tcl_data` + `_tk_data` + `desktop_ui.pyc`（317 KB）随发行包一起分发，tcl/tk 数据目录通常 8–10 MB，属于纯浪费；更麻烦的是 Web 版启动时仍会初始化 Tkinter 相关模块。

**对 spritelens 的启示**：UI 迁移时要把"复用旧代码"限定在不引入旧 UI 依赖的范围内（把可复用的纯逻辑下沉到无 UI 依赖的模块），否则新架构会被旧架构的 import 图绑住。

---

## 6. 增量更新链（工程化最完整的一环）

```
remote_release.py
  ├── 拉 control.json (api.idom.fun)
  ├── verify_control()  → Ed25519 验签（公钥硬编码 PUBLIC_KEY）
  ├── select_patch()    → 按当前 exe 的 sha256(base_hash) 选补丁
  ├── fetch_artifact()  → URL 校验（scheme/host/port/path 全部白名单 + 路径穿越防护）
  ├── delta_update.apply_patch() → bsdiff4 打补丁 + bz2 解压 + sha256 校验 + 大小上限
  ├── place_update()    → 原子替换（copyfileobj → unlink → replace）
  └── register_launch_target() → 写 launch.json 记录

update_launcher.py
  └── 生成 PowerShell 脚本：等原进程退出(2min超时) → 校验 size/hash → 移动文件 → 重启
```

安全设计要点：
- **Ed25519 签名**控制通道，防止中间人下发恶意更新
- **base_hash 定补丁**：只对已知版本的 exe 打补丁，防止补丁错配
- **多重重校验**：下载后 sha256、place 阶段再 sha256、Windows 启动脚本里第三次校验
- **URL 白名单**：`fetch_artifact` 校验 scheme/hostname/port/username/password，只允许特定 host，`unquote` 后检查路径不越界
- **大小上限** `MAX_PACKAGE`，防 zip bomb
- **原子替换** + 失败回滚（`.previous-` 后缀）

---

## 7. 其他值得注意的细节

| 项 | 实现 | 价值 |
|---|---|---|
| 单实例 | 未发现显式单实例锁 | 可能依赖 WebView2 行为 |
| DPI 感知 | `_enable_windows_dpi_awareness`：`SetProcessDpiAwarenessContext` → `shcore.SetProcessDpiAwareness` → `SetProcessDPIAware` 三级降级 | Windows 高分屏正确渲染 |
| 窗口适配 | `window_geometry.initial_window_size` 读 `SystemParametersInfoW` 工作区 + `GetDpiForSystem`，按 DPI 缩放 | 小屏笔记本不溢出 |
| WebView2 兜底 | `webview_guard.py`：启动前检测 WebView2 运行时版本，缺失时弹原生 MessageBox + 引导下载 | 用户环境兼容 |
| 界面崩溃日志 | `web_runtime.py` 顶层 try 包 `main()`，异常写 `startup-error.log` | 无控制台也能排查 |
| 配置外置 | `DANKING_CAPTURE_UPLOAD_TOKEN` 等环境变量可覆盖内置 token | 便于内部测试 |
| 本地状态库 | preference 用 `_PROTECTED_PREFERENCE_KEYS` + DPAPI 加密存储 | 敏感项不落明文 |
| 抓包参数调优 | `pcap_setbuff` 设置抓包缓冲 | 高流量下不丢包 |
| 3D 模型运行时 | `rocom_pets_bg.wasm` 1.77 MB（Rust/WebGPU），从独立工程 `s4-glassy-20260910/runtime/wasm` 构建 | 宠物 3D 预览 |
| 社区/交易 | `/api/market/*`、`/api/trade-market`、摊位、鉴定报告、社区配色 | 已超出"仓库工具"，形成生态 |
| 商业模式 | `/api/subscription/status`、`/api/subscription/redeem` | 订阅制 + 兑换码 |

---

## 8. 对 spritelens 的可借鉴清单

按"投入产出比"排序：

### 立刻可借鉴（低成本高收益）

1. **本地服务安全组合**：随机端口 + 每次启动随机 token + `compare_digest` 常量时间比较 + 仅 `127.0.0.1`。
   比"固定端口 + 无鉴权"安全得多，代码量不到 30 行。

2. **启动面板 + 自恢复链**：内联 `#startup-panel` HTML，全局捕获 script/link 加载错误，自动重试 2 次，所有请求带超时。
   直接解决"白屏且用户不知道为什么"的问题。

3. **`bootstrap` 单次聚合接口**：前端初始化只需一次请求，把目录/枚举/偏好一次给全。spritelens 目前是多次拉取。

4. **revision 增量轮询 + WebSocket**：`/api/state?revision=N` 只在数据变化时返回新内容，避免全量重传。spritelens 的 `ui_revisions` 思路已经接近，可以进一步做成 HTTP 轮询接口。

5. **活跃网卡智能排序**：默认选中真正在用的网卡，而不是列表第一个。这是抓包工具最常见的使用痛点。

### 中期可借鉴（需要设计）

6. **事务性发件箱（outbox）**：事件先落 SQLite，上传失败进 outbox 按退避策略重试。
   spritelens 如果要做云端同步，这是防丢数据的标准解法。

7. **`FlowState` 流级上下文容器**：把上下行重组器、解析器、密钥、IV、game_id、各类 hash 全部内聚到一个 dataclass。
   比散落的字典/实例变量清晰，也让"一包多流"的处理更安全。

8. **`_recover_stream_gap` 式断流恢复**：TCP 丢包后不重置流，而是从 pending 缓冲重排 + 魔数重扫 + 继续解密。
   这对"被动观测、无法要求重传"的场景是刚需。

9. **密钥可热注入（`state_provider` 回调）**：密钥不硬编码在二进制里，通过回调按 `game_id` 动态获取并缓存。
   游戏换 key 时无需重新打包。spritelens 目前密钥处理方式值得对照。

10. **CLI 独立运行 + PCAP 离线回放**：`roco_collector` 可脱离 GUI 跑，支持 `--jsonl` 输出和本地 pcap 回放。
    开发调试、问题复现、自动化测试全都受益。spritelens 可以给协议层加同样能力。

### 长期参考（大工程）

11. **Ed25519 签名的增量更新链**：如果 spritelens 要发布给外部用户，这套（签名控制通道 + bsdiff 补丁 + 三次校验 + 原子替换 + PowerShell 守护脚本）是完整可抄的模板。

12. **UI 迁移路径已验证**：同类产品从 Tkinter 走到了 pywebview + 原生 JS。spritelens 的"渐进 Web 化"方向正确，且**前端零框架**这条路线被证明可行（40 个文件、8 MB、可维护）。

13. **死代码迁移残留**：注意蛋神助手把 12,685 行 Tkinter 代码留在了包里（+ `_tkinter.pyd` + tcl/tk 数据），这部分纯属体积浪费。spritelens 迁移时应当清理。

### 需要警惕的差异

- 蛋神助手有**云端账号体系**（`api.danking.cn`）和**订阅付费**，spritelens 当前是纯本地工具 —— 不必照搬，但说明"本地工具 + 云同步 + 市场"是已验证的商业路径。
- 它的协议解析继承了 roco_helper 的资源（`assets/reference/roco-helper-v3.8.1/TypeIcon/sprites.css`），说明生态内有共享资源习惯。
- `desktop_ui.py` 里的 Tkinter 代码仍被 `app.py` import（模块级 `import desktop_ui`），意味着**即使走 Web 入口，Tkinter 模块仍会被加载**（除非 PyInstaller 做了延迟导入优化）。迁移时要注意入口与 import 图的彻底清理。

---

## 10. 运行时验证（与静态结论互相印证）

用 accessibility 接口读取运行中的窗口（pid 85396，本机实测），拿到三条独立于字节码的硬证据：

| 观察 | 证据 | 印证了 |
|---|---|---|
| 内嵌浏览器地址栏的值 | `http://127.0.0.1:60545/#token=IgXczno17sD_j5IJJ9mHxzzVk--zgx…`（element 77） | §4.1 的**随机端口 + URL fragment token**；端口 60545 确为系统动态分配（非硬编码） |
| 无障碍树根节点 | `pane "Chrome Legacy Window"`（element 76） | **WebView2/Chromium** 渲染，坐实 pywebview 路线 |
| 窗口结构 | 顶层 `window 蛋神助手 v1.1.6` → titlebar（原生最小化/最大化/关闭）→ `pane 蛋神助手 - Web 内容` | 原生窗口壳 + Web 内容区混合形态 |

界面功能与后端路由表**逐项对应**，验证了路由清单的真实性：

- 侧栏：`我的家园` / `种公阵列` / `种公母库` / `智能配窝` / `产线收集` / `交易市场` / `精灵图鉴` / `蛋图鉴` / `炫彩色卡` / `炫彩花种` / `换蛋广场` / `赞赏作者`
- 顶部：`开始采集` / `采集设置` / `上传数据` / `拉取数据` / `本地模式` / `当前角色/UID` / `登录助手账号`
- 采集状态实时显示：`采集：正在停止`、`握手：已结束`
- 蛋图鉴页：`收录 224 种精灵蛋 · 浏览完整图鉴`，含孵化时间倍率表（原始/5倍/6倍/30倍）、公母比例环形图、身高体重区间条

值得注意的产品细节：
- **前端零框架的代价与收益都体现在无障碍树里**：399 个元素中大量 `group` 无名称 —— 手写 DOM 没有语义标注习惯（React/Vue 项目通常也不会更好，但这是可访问性上的短板）。
- **"本地模式"与"云端同步"是并列的第一等状态**，未登录也能完整使用（`拉取数据` 按钮 disabled）—— 印证了它不强制云端账号。
- 侧栏底部有 `赞赏作者`，配合 `/api/subscription/*`，说明是"免费本地功能 + 增值订阅"的混合模式。

---

## 11. 复现方法


```bash
# 1. 解包
pip install pyinstxtractor-ng
python -m pyinstxtractor_ng "蛋神助手电脑版-v1.1.6-b49823778e99.exe"

# 2. 反汇编（需要 Python 3.12，pyc magic = 3531）
# 环境已有：C:\Users\chiqingsan\AppData\Local\Python\pythoncore-3.12-64\python.exe
python -c "
import marshal, dis
code = marshal.loads(open('app.pyc','rb').read()[16:])   # 跳过 16 字节头
dis.dis(code, depth=0)
"
```

- pyc 头 16 字节：`magic(4) + flags(4) + mtime(4) + size(4)`
- 反编译成源码：Python 3.12 无成熟工具（decompyle3/uncompyle6 不支持 3.12），推荐用 `dis`（字节码本身信息量已足够）+ `xdis`。若需源码级，可用 `pycdc`（C++ 实现，对 3.12 支持仍在完善）。
