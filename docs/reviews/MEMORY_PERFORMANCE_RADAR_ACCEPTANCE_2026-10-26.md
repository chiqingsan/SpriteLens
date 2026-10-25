# 悬浮雷达原生窗口验收（PERF02，2026-10-26）

## 结论

PERF02 剩余的「原生雷达窗口」验收在真实 WebView2 + 真实 pywebview 窗口完成，通过。验证链路是生产代码本身：`radar.html` → `radar.js`（排队/交接/`dataset.ready`）→ `/static/vue/radar-entry.js`（PERF04 双入口产物）→ `FloatingRadar.vue` + `SceneRadar`；宿主侧走真实 `RadarWindow.open_radar()` 与 `pywebview.api`。

覆盖并通过：挂载后实时渲染（数量与单牌/双牌徽章）、同观察周期版本递增原位更新、新观察周期清空旧数据、`stale` 保留实体并标注过期、`error` 清空数据并显示原因、错误后恢复、主窗口消失后的心跳失效与清空、`set_radar_opacity` 合法/非法入参、`close_radar` 关闭回调。

仍未验收：真实游戏流量下的帧序列与频率、冻结 EXE 部署、长时间运行，以及 PERF02 条目里的「整机内存对比」。

## 方法

- 隔离数据根：`SPRITELENS_DATA_ROOT` 指向临时目录，只读拷贝真实 `keys/`（`latest.key`、`session.json`）；`build_app_context(autostart=False)` + `LocalServer(ctx, port=0)`，不启动采集，不写真实数据目录。
- 窗口：主窗口加载 `server.url`，雷达窗口加载 `server.url.replace('/#','/static/radar.html#')`（与 `spritelens/web/run.py` 生产路径一致），360×460。
- 注入：在主窗口内 `new BroadcastChannel('spritelens-nearby-<token>')` 发送 `summary`/`snapshot`/`stale`/`error` 帧；帧内容按 `frontend/src/types/nearby.ts` 的 `parseNearbySummary`/`parseNearby` 校验规则构造。
- 观测：轮询雷达窗 `#radar-root` 的 `dataset.ready`、`.floating-drag span` 数量文本、`.floating-attention-chip` 数量、`.floating-error` 文本与容器节点数；宿主侧用 `pywebview.api` Promise 结果落到 `window.__apiResult` 后轮询（`evaluate_js` 不等待 Promise）。
- 环境：WebView2 `Edg/155.0.0.0`，Windows 11，Python 3.12 `.venv`。

### 验收期间的临时静音（重要限制）

主窗口壳自带的附近桥（`spritelens/web/static/nearby-page.js`）在没有观察数据时会广播 `{kind:'error', message:'当前没有可用的附近观察数据'}`，并每 1 s 广播 `{kind:'ping'}`。前者会覆盖注入帧，使验收无法区分「雷达丢弃」与「宿主覆盖」。

因此验收期间在主窗口内临时替换 `BroadcastChannel.prototype.postMessage`，过滤 `summary`/`snapshot`/`stale`/`error` 四个结构化 kind（本次 `window.__blocked = 5`），只保留开启前捕获的原方法用于注入；雷达窗口、宿主 `RadarWindow` 与页面脚本全部为生产代码，未做任何修改。主窗口附近桥到雷达的生产广播链路本次未启用，属未覆盖项。

心跳失效不靠静音 `ping` 模拟：直接销毁主窗口，使附近桥的 1 s `ping` 真正消失，雷达窗按 3 s 超时进入失效态，属真实断链场景。

## 结果

| 步骤 | 观测 | 结果 |
| --- | --- | --- |
| 挂载 | `dataset.ready=""`、容器节点 33、0 只 | 通过 |
| 实时渲染 | 注入 3 个 actor（双牌 1、单牌 1）→ `3 只`、2 个关注徽章、节点 63 | 通过 |
| 同周期更新 | 版本 4、2 个 actor → `2 只`、2 徽章，内容原位更新 | 通过 |
| 新观察周期 | `summary` observation 2 + 快照 1 actor → `1 只`、0 徽章，旧数据清空 | 通过 |
| `stale` | 保留 `1 只`，错误区显示「刷新失败，显示的是稍早的结果：网络超时」 | 通过 |
| `error` | 清空为 `0 只`，显示「采集已断开」 | 通过 |
| 恢复 | 新快照 `1 只`、1 徽章，错误区清空 | 通过 |
| 宿主窗口 | `RadarWindow.open_radar()` 打开真实悬浮窗并挂载 | 通过 |
| 不透明度 | `set_radar_opacity(70)` 成功；`set_radar_opacity(20)` 抛「不透明度必须是35到90的整数」 | 通过 |
| 关闭 | `close_radar()` 触发 `on_closed` | 通过 |
| 心跳失效 | 销毁主窗口后 3 s 内显示「数据已失效（采集连接断开或主窗口未响应）」并清空为 `0 只`，雷达窗进程仍存活 | 通过 |

`set_radar_opacity(20)` 的异常由 pywebview 记录到 stderr（`[pywebview] Traceback ... ValueError: 不透明度必须是35到90的整数`），属预期失败路径，同时验证了参数校验与错误可观测性。

## 未覆盖与后续

- 真实游戏流量：本次帧为按类型契约构造的最小合法载荷，未验证真实采集频率下的连续刷新与图片加载重试。
- 挂载前排队队列：雷达页较轻易于挂载，本次原生窗口未命中「监听器已挂载、Vue 未挂载」窗口；该路径由 `radar.js` 代码审查与此前合成浏览器验收覆盖，原生浏览器下未复现。
- 主窗附近桥（`nearby-page.js`）到雷达的真实广播未启用（无观察数据，按上文静音）。
- 冻结 EXE、长期运行、整机内存对比未做。
- 脚本为临时探针，未入库；关键参数、注入帧与断言已记录在本文件。
