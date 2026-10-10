"""录制文件全格式离线分析：布局分类、opcode 分布、宠物形状搜索。

用法:
    python tools/analyze_recording.py RECORDING.jsonl [--key HEX]

对录制做逐帧分析（覆盖全部四种实测内层布局），输出：
- 每条 TCP 流（会话×方向）的帧分类统计（解析成功/无密钥/拆分失败）
- 全部业务 opcode 分布
- 0x1345/0x1346 宠物分页请求-响应的出现位置与响应内容
密钥来源：录制内 0x1002 ACK 自动提取，缺失时回退 keys/latest.key。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spritelens.capture.key_store import KeyStore, parse_key_text
from spritelens.paths import keys_dir
from spritelens.protocol.crypto import extract_ack_key, iter_decrypt_variants
from spritelens.protocol.frames import FrameStream
from spritelens.protocol.records import Direction, split_record
from spritelens.recording.recorder import read_recording


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="SpriteLens 录制文件全格式分析")
    parser.add_argument("recording", help="录制文件（.jsonl）")
    parser.add_argument("--key", help="手动指定会话密钥（16 字节 ASCII 或 32 位 hex）")
    args = parser.parse_args(argv)

    path = Path(args.recording)
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 2
    chunks = read_recording(path)
    print(f"录制: {path.name}，{len(chunks)} 段")
    print("会话分布:", dict(Counter(c.session_id for c in chunks)))

    fallback = None
    if args.key:
        fallback = parse_key_text(args.key)
    else:
        fallback = KeyStore(keys_dir()).load_latest()

    streams: dict[tuple, FrameStream] = {}
    keys: dict[str, bytes] = {}
    frames: Counter = Counter()
    ops: Counter = Counter()
    pet_reqs: list[tuple[str, int]] = []
    pet_rsps: list[tuple[str, int, bytes]] = []
    fail_samples: list[tuple[str, bytes]] = []

    for ch in chunks:
        fk = (ch.session_id, str(ch.direction))
        fs = streams.setdefault(fk, FrameStream())
        for frame in fs.feed(ch.data):
            if frame.is_ack:
                k = extract_ack_key(frame.header_extra)
                if k:
                    keys[ch.session_id] = k
                    frames[fk + ("ack✓",)] += 1
                else:
                    frames[fk + ("ack✗",)] += 1
                continue
            if not frame.is_data:
                frames[fk + ("ctrl",)] += 1
                continue
            key = keys.get(ch.session_id) or fallback
            if not key:
                frames[fk + ("nokey",)] += 1
                continue
            rec = None
            for plain in iter_decrypt_variants(key, frame.body):
                rec = split_record(plain, ch.direction)
                if rec:
                    break
            if rec:
                frames[fk + ("ok",)] += 1
                ops[(fk[1][-3:], hex(rec.opcode))] += 1
                if rec.opcode == 0x1345:
                    pet_reqs.append((fk[0][-5:], fk[1][-3:]))
                if rec.opcode in (0x1346, 0x1348) and len(pet_rsps) < 3:
                    pet_rsps.append((fk[0][-5:], fk[1][-3:], rec.payload))
            else:
                frames[fk + ("parsefail",)] += 1
                if fk[1].endswith("s2c") and len(fail_samples) < 6:
                    plain = next(iter_decrypt_variants(key, frame.body), b"")
                    fail_samples.append((fk[0][-5:], plain[:40]))

    print("\n各流帧分类:")
    for fk, n in sorted(frames.items()):
        print(f"  {fk[0][-5:]} {fk[1][-3:]} {fk[2:]}: {n}")
    print(f"\n业务 opcode 分布:")
    for (d, op), n in ops.most_common(30):
        print(f"  {d:>3} {op:<10} x{n}")
    print(f"\n宠物分页请求 0x1345: {len(pet_reqs)} 次 {pet_reqs[:5]}")
    print(f"宠物分页响应 0x1346/0x134A: {len(pet_rsps)} 条")
    for sid, d, payload in pet_rsps:
        print(f"  [{sid} {d}] payload={len(payload)}B 前 100B:")
        print("   ", payload[:100].hex(" "))
    if fail_samples:
        print("\ns2c 拆分失败样本（供结构分析）:")
        for sid, head in fail_samples:
            print(f"  [{sid}] {head.hex(' ')}")
    print("\n提示: 宠物全量数据由服务器在登录进世界时主动推送（0x1346，多页连续帧）。")
    print("若本文件里 s2c 帧普遍 parsefail，多半是录制期间监听晚于连接建立（缺该会话")
    print("的 0x1002 密钥），用 --key 手动传入该会话密钥重试。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
