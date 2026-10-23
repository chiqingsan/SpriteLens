"""采集向导纯判断；累计观察不代表当前连接或业务快照完整。"""
from __future__ import annotations

from spritelens.system.environment import NpcapReport
from spritelens.view_models.capture_vm import CaptureSnapshot


def capture_diagnostics(
    snapshot: CaptureSnapshot, environment: NpcapReport, *, port: int,
    extra_ports: tuple[int, ...], environment_error: str, environment_checking: bool = False,
) -> list[dict[str, str | list[str]]]:
    totals = snapshot.totals
    checks: list[dict[str, str | list[str]]] = []
    env_status = "ok" if environment.installed else "error"
    actions = ["recheck"]
    if not environment.installed:
        actions.append("install")
    elif environment.rsc_enabled:
        env_status = "warning"
        actions.append("rsc")
    env_message = environment.message
    if environment_error:
        env_status = "error"
        env_message = f"刷新失败：{environment_error}；以下为上次检测结果：{env_message}"
    if environment_checking:
        env_status = "waiting"
        env_message = f"正在检测环境；以下为上次检测结果：{env_message}"
    checks.append(dict(id="environment", title="环境检查", status=env_status,
                       message=env_message, actions=actions))
    ports = "、".join(str(p) for p in (port, *extra_ports))
    checks.append(dict(id="network", title="网卡与端口", status="info",
                       message=f"下次启动使用：{snapshot.iface or '默认路由网卡'}；采集端口：{ports}。选择网卡后下次启动生效。",
                       actions=["ifaces"]))
    if snapshot.last_error:
        status, message = "error", snapshot.last_error
    elif not snapshot.running:
        status, message = "idle", "采集未启动。请先开始采集，再进入游戏。"
    elif not totals.raw_chunks:
        status, message = "waiting", "采集已启动，尚未观察到数据。请检查网卡，并在采集启动后重新登录游戏；暂不能判定网卡或端口错误。"
    else:
        status, message = "ok", f"已启动采集；累计观察到原始流 {totals.raw_chunks} 段 / {totals.raw_bytes} 字节，不代表当前连接持续有数据。"
    checks.append(dict(id="capture", title="采集检查", status=status, message=message,
                       actions=["stop"] if snapshot.running else ["start"]))
    if totals.decrypt_ok:
        status, message = "ok", f"累计成功解密 {totals.decrypt_ok} 帧，仅代表已观察到成功数据，不代表当前连接健康或业务数据完整。"
    elif snapshot.any_key:
        status, message = "waiting", "已有密钥，尚未观察到成功解密。请进入游戏并产生数据。"
    else:
        status, message = "waiting", "等待密钥。请在采集启动后重新登录游戏；必要时使用高级诊断。"
    checks.append(dict(id="decrypt", title="解密检查", status=status, message=message,
                       actions=["advanced"]))
    warnings = []
    for name, count in (("解密失败", totals.decrypt_fail), ("解析失败", totals.parse_fail),
                        ("缺密钥", totals.key_miss), ("采集队列丢弃", snapshot.dropped_chunks),
                        ("重组丢弃", snapshot.dropped_segments), ("日志丢弃", snapshot.event_log_dropped)):
        if count:
            warnings.append(f"{name} {count}")
    if snapshot.event_log_error:
        warnings.append(f"事件日志写入失败：{snapshot.event_log_error}")
    if warnings:
        checks.append(dict(id="warnings", title="累计观察警告", status="warning",
                           message="；".join(warnings), actions=["advanced"]))
    return checks
