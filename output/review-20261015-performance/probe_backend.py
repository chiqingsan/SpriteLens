"""一次性审查探针：仅合成数据/内存库/临时目录，不是项目测试门禁。"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.test_web_server import _make_context, _pet
from spritelens.capture.base import StreamChunk
from spritelens.domain.color_cards import ColorCatalog
from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.static_data import load_static_data
from spritelens.events import PacketEvent
from spritelens.paths import static_dir
from spritelens.protocol.records import Direction
from spritelens.recording.recorder import StreamRecorder
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.pet_store import PetStore
from spritelens.view_models.pet_vm import PetViewModel
from spritelens.web.payloads import pets_payload
from spritelens.web.pet_media_cache import PetMediaCache
from spritelens.web.server import LocalServer


def emit(**values):
    print(json.dumps(values, ensure_ascii=False))


def sample(kind):
    return (_pet(1, name="Synthetic", level=10) if kind == "pet"
            else EggBoxEntry(1, 1, 1, 10, *([0] * 12)))


class Gate:
    """在旧线程取得提交锁之前控制调度，显式暴露取批次/提交的窗口。"""
    def __init__(self):
        self.lock = threading.Lock()
        self.reached = threading.Event()
        self.release = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "audit-old":
            self.reached.set()
            assert self.release.wait(3), "old thread was not released"
        self.lock.acquire()

    def __exit__(self, *args):
        self.lock.release()


def store_probes():
    for kind in ("pet", "egg"):
        db = Database(":memory:")
        store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
        old = sample(kind)
        new = replace(old, **({"level": 20} if kind == "pet" else {"quantity": 20}))
        gate = Gate()
        store._flush_lock = gate
        store.put(1, [old])
        worker = threading.Thread(target=store.flush, name="audit-old")
        worker.start()
        try:
            assert gate.reached.wait(3)
            store.put(1, [new])
            store.flush()
        finally:
            gate.release.set()
            worker.join(3)
        assert not worker.is_alive()
        sql = "SELECT level AS value FROM pets" if kind == "pet" else "SELECT quantity AS value FROM eggs"
        emit(probe="batch_inversion", store=kind, expected=20, actual=db.query(sql)[0]["value"])
        store.close()
        db.close()

    for kind in ("pet", "egg"):
        db = Database(":memory:")
        store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
        original = db.execute_many

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic disk failure")

        db.execute_many = fail
        store.put(1, [sample(kind)])
        raised = None
        try:
            store.close()
        except Exception as exc:
            raised = type(exc).__name__
        emit(probe="close_with_write_failure", store=kind, exception=raised, pending=store.pending_count)
        db.execute_many = original
        store.flush()
        db.close()

    db = Database(":memory:")
    store = PetStore(db, flush_interval=60)
    original = db.execute_many
    entered, release = threading.Event(), threading.Event()

    def blocked(sql, rows):
        entered.set()
        assert release.wait(3)
        return original(sql, rows)

    db.execute_many = blocked
    store.put(1, [sample("pet")])
    worker = threading.Thread(target=store.flush)
    worker.start()
    assert entered.wait(3)
    result = []
    reader = threading.Thread(target=lambda: result.append(store.has_pet(1, 1)))
    try:
        reader.start()
        reader.join(.05)
    finally:
        release.set()
        worker.join(3)
        reader.join(3)
        assert not reader.is_alive()
        emit(probe="read_during_inflight_flush", expected=True, actual=result[0])
        db.execute_many = original
        store.close()
        db.close()


def benchmark():
    static = load_static_data(static_dir())
    eggs, colors = EggCatalog(static_dir()), ColorCatalog(static_dir())
    ids = [int(key) for key, _ in static.species_items()]

    def measure(function, count=3):
        times = []
        for _ in range(count):
            start = time.perf_counter()
            result = function()
            times.append((time.perf_counter() - start) * 1000)
        return round(statistics.median(times), 2), result

    with tempfile.TemporaryDirectory() as tmp:
        ctx = _make_context(Path(tmp))
        ctx.static_data, ctx.egg_catalog, ctx.color_catalog = static, eggs, colors
        ctx.pet_vm = PetViewModel(ctx.pet_repository, static)
        server = LocalServer(ctx)
        try:
            for count in (100, 1107, 2000):
                ctx.pet_repository._pets = {
                    i: replace(_pet(i, name="Synthetic", level=30, base_conf=ids[i % len(ids)]), voice=30)
                    for i in range(1, count + 1)
                }
                state_ms, _ = measure(server._state_payload, 5)
                payload_ms, payload = measure(lambda: pets_payload(
                    ctx.pet_vm.view_with(ctx.pet_vm.filters), static, colors, eggs))
                json_ms, encoded = measure(lambda: json.dumps(payload, ensure_ascii=False))
                emit(probe="inventory", pets=count, state_ms=state_ms, payload_ms=payload_ms,
                     json_ms=json_ms, utf8_bytes=len(encoded.encode("utf-8")))
            fields = [{"name": f"field_{i}", "type": "int", "value": i} for i in range(1000)]
            event = PacketEvent(ts=time.time(), session_id="synth", direction="s2c", opcode=1,
                                opcode_name="synth", payload_len=3000, decoded=fields)
            for count in (100, 500, 2000):
                ctx.monitor._events.extend([event] * count)
                start = time.perf_counter()
                ctx.events_vm.drain()
                emit(probe="event_drain", events=count, fields_per_event=1000,
                     elapsed_ms=round((time.perf_counter() - start) * 1000, 2))
        finally:
            ctx.close()


async def async_probes():
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _make_context(Path(tmp))
        ctx.egg_store = SimpleNamespace(annotations=lambda uid: (time.sleep(.2) or {}), close=lambda: None)
        server = LocalServer(ctx)
        start = time.perf_counter()
        tick = asyncio.create_task(asyncio.sleep(.01))
        await asyncio.sleep(0)
        await server._api_egg_box(None)
        await tick
        emit(probe="event_loop_sync_db", timer_due_ms=10, injected_delay_ms=200,
             completed_ms=round((time.perf_counter() - start) * 1000, 2))
        gate, seen = asyncio.Event(), []

        class Socket:
            closed = False

            def __init__(self, slow):
                self.slow = slow

            async def send_str(self, value):
                if self.slow:
                    await gate.wait()
                else:
                    seen.append(value)

        server._sockets = [Socket(True), Socket(False)]
        pending = asyncio.create_task(server._broadcast("state"))
        await asyncio.sleep(.05)
        emit(probe="slow_ws", healthy_received_before_slow_release=bool(seen))
        gate.set()
        await pending
        ctx.close()

        cache = PetMediaCache(Path(tmp) / "packaged", Path(tmp) / "cache")
        attempts = []

        def miss(*args):
            attempts.append(args)
            time.sleep(.02)
            return None, 21600

        cache._download = miss
        await asyncio.gather(*(cache.resolve("123-normal-artwork.webp") for _ in range(9)))
        emit(probe="same_missing_media", requests=9, download_attempts=len(attempts))


def recorder_probe():
    class SlowFile:
        def write(self, line):
            pass

        def flush(self):
            time.sleep(.02)

        def close(self):
            pass

    recorder = StreamRecorder()
    recorder._file = SlowFile()
    chunk = StreamChunk("synth", Direction.S2C, b"x" * 100, 0)
    start = time.perf_counter()
    for _ in range(20):
        recorder.append(chunk)
    emit(probe="recorder_slow_flush", chunks=20, flush_delay_ms=20,
         append_total_ms=round((time.perf_counter() - start) * 1000, 2))
    recorder.stop()


if __name__ == "__main__":
    store_probes()
    benchmark()
    asyncio.run(async_probes())
    recorder_probe()
