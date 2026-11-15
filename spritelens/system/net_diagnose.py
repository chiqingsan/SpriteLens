"""网络诊断：按会话统计 TCP 流量分布（排障用）。

背景：全量业务数据（宠物/背包等）由服务器经 8195 连接在登录进世界时
主动推送，本工具不是获取数据的必要步骤。保留用于排障：当怀疑游戏启用
了新的连接/端口时，宽抓一段时间按会话统计双向字节，判断是否存在
8195 之外承载业务数据的连接。

用法：
    python main.py --diagnose-net [SECONDS]
    python main.py --diagnose-net 20

若确实发现 8195 之外活跃的业务连接，可将其加入配置 capture.ports
（逗号分隔，如 "8195,10012"）后重启生效。
"""

from __future__ import annotations

import time
from collections import defaultdict


def run_diagnose(seconds: float = 20.0) -> int:
    """宽抓全部 TCP 流量并按会话聚合统计；返回进程退出码。"""
    # 与采集入口一致，只注册以太网及 IPv4/IPv6 协议层。
    from scapy.layers import l2, inet, inet6  # noqa: F401
    from scapy.sendrecv import AsyncSniffer  # 延迟导入（缺 scapy 时给出可读错误）

    # 会话 → [上行字节, 下行字节, 包数]；会话键为 (local, remote) 归一化对
    flows: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])

    def bump(pkt) -> None:
        tcp = pkt.getlayer("TCP")
        ip = pkt.getlayer("IP") or pkt.getlayer("IPv6")
        if tcp is None or ip is None:
            return
        payload = len(bytes(tcp.payload))
        if not payload:
            return  # 只统计数据包，ACK 噪音剔除
        src, dst = (ip.src, tcp.sport), (ip.dst, tcp.dport)
        # 会话键：按 (ip, port) 字典序归一化，避免上下行记成两条
        a, b = sorted((src, dst))
        entry = flows[(a, b)]
        entry[0 if src == a else 1] += payload
        entry[2] += 1

    sn = AsyncSniffer(filter="tcp", prn=bump, store=False)
    sn.start()
    print(f"[diagnose] 宽抓全部 TCP 数据包 {seconds:.0f} 秒——请在此期间进行游戏内操作")
    try:
        time.sleep(seconds)
    finally:
        sn.stop()

    print(f"\n[diagnose] 共 {len(flows)} 条会话（按上行+下行字节排序，仅列数据包活跃的）：")
    ranked = sorted(flows.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True)
    for (a, b), (up, down, packets) in ranked[:20]:
        if up + down == 0:
            continue
        print(f"  {a[0]}:{a[1]} <-> {b[0]}:{b[1]}   上行 {up}B  下行 {down}B  ({packets} 包)")
    print(
        "\n[diagnose] 判读：8195 是承载全部业务数据的连接（登录推送即全量宠物/背包）。\n"
        "        若 8195 之外出现上下行都活跃的连接且确认属于游戏，可把端口写进\n"
        "        %LOCALAPPDATA%\\SpriteLens\\config.json 的 capture.ports（如 \"8195,10012\"），"
        "重启生效。"
    )
    return 0
