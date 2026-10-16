"""验收用合成探针；只用内存库、临时目录和故障替身。"""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import logging
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.test_web_server import _make_context, _pet
from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore, SessionCheckpoint
from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pet_locations import Backpack, PetBox
from spritelens.recording.recorder import StreamRecorder
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.pet_store import PetStore
from spritelens.web.pet_media_cache import PetMediaCache
from spritelens.web.server import LocalServer
from spritelens.events import PacketEvent
from spritelens.view_models.events_vm import EventsViewModel

logging.disable(logging.CRITICAL)

def emit(probe, **values):
    print(json.dumps({"probe": probe, **values}, ensure_ascii=False), flush=True)

def sample(kind):
    return _pet(1, name="Synthetic", level=10) if kind == "pet" else EggBoxEntry(1, 1, 1, 10, *([0] * 12))

def batch_order(kind):
    from runpy import run_path
    gate_type = run_path(str(ROOT / "output/review-20261015-performance/probe_backend.py"))["Gate"]
    db = Database(":memory:")
    store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
    gate = gate_type()
    store._flush_lock = gate
    store.put(1, [sample(kind)])
    caller = threading.Thread(target=store.flush, name="audit-old")
    caller.start()
    try:
        assert gate.reached.wait(3)
        new = replace(sample(kind), **({"level": 20} if kind == "pet" else {"quantity": 20}))
        store.put(1, [new])
        store.flush()
    finally:
        gate.release.set()
        caller.join(3)
    sql = "SELECT level AS n FROM pets" if kind == "pet" else "SELECT quantity AS n FROM eggs"
    emit("batch_order", store=kind, expected=20, actual=db.query(sql)[0]["n"])
    store.close()
    db.close()

def lazy_event_detail():
    event = PacketEvent(ts=time.time(), session_id="synthetic", direction="s2c", opcode=1,
                        opcode_name="synthetic", payload_len=1,
                        decoded=[{"name": "field_1", "type": "int", "value": 1}])
    vm = EventsViewModel(monitor=SimpleNamespace(drain_events=lambda: [event] * 201))
    original = vm._format_detail
    calls = []
    def count(value):
        calls.append(value)
        return original(value)
    vm._format_detail = count
    vm.drain()
    after_drain = len(calls)
    one, two = vm.detail(200), vm.detail(200)
    emit("lazy_event_detail", format_calls_after_drain=after_drain,
         format_calls_after_two_reads=len(calls), same_detail=one == two,
         retained=len(vm._details) + len(vm._detail_events), evicted_text=vm.detail(0))

def concurrent_close(kind):
    db = Database(":memory:")
    store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
    original = db.execute_many
    entered, release = threading.Event(), threading.Event()
    errors = []
    def blocked(sql, rows):
        entered.set()
        assert release.wait(3)
        return original(sql, rows)
    db.execute_many = blocked
    store.put(1, [sample(kind)])
    def flush():
        try:
            store.flush()
        except Exception as cause:
            errors.append(type(cause).__name__)
    caller = threading.Thread(target=flush, name="acceptance-explicit-flush")
    caller.start()
    assert entered.wait(3)
    close_error = None
    try:
        store.close()
    except Exception as cause:
        close_error = type(cause).__name__
    alive_at_return = caller.is_alive()
    if close_error is None:
        db.close()
    release.set()
    caller.join(3)
    emit("close_while_explicit_flush_inflight", store=kind, close_error=close_error,
         flush_alive_at_close_return=alive_at_return, flush_errors=errors, pending=store.pending_count)
    if close_error is not None:
        store.close()
        db.close()

def read_barrier(kind):
    db = Database(":memory:")
    store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
    original = db.execute_many
    entered, release = threading.Event(), threading.Event()
    result = []
    def blocked(sql, rows):
        entered.set()
        assert release.wait(3)
        return original(sql, rows)
    db.execute_many = blocked
    store.put(1, [sample(kind)])
    writer = threading.Thread(target=store.flush)
    writer.start()
    assert entered.wait(3)
    reader = threading.Thread(target=lambda: result.append(store.has_pet(1, 1) if kind == "pet" else bool(store.load(1))))
    reader.start()
    reader.join(.03)
    blocked_until_commit = reader.is_alive()
    release.set()
    writer.join(3)
    reader.join(3)
    emit("read_waits_inflight_flush", store=kind, blocked_until_commit=blocked_until_commit, found=result)
    store.close()
    db.close()

def close_retry(kind):
    db = Database(":memory:")
    store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=.05)
    original = db.execute_many
    def fail(*args):
        raise sqlite3.OperationalError("synthetic disk error")
    db.execute_many = fail
    store.put(1, [sample(kind)])
    original_worker = store._worker
    start = time.perf_counter()
    cause = None
    try:
        store.close()
    except Exception as error:
        cause = type(error).__name__
    elapsed = (time.perf_counter() - start) * 1000
    retained = store.pending_count
    db.execute_many = original
    store.close()
    count = db.query("SELECT COUNT(*) AS n FROM " + ("pets" if kind == "pet" else "eggs"))[0]["n"]
    emit("store_failed_close_retry", store=kind, error=cause, elapsed_ms=round(elapsed, 2),
         pending_before_recovery=retained, rows_after_retry=count,
         same_worker=original_worker is store._worker, worker_alive=store._worker.is_alive())
    db.close()

async def asynchronous_paths():
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _make_context(Path(tmp))
        ctx.egg_store = SimpleNamespace(annotations=lambda uid: (time.sleep(.2) or {}), close=lambda: None)
        server = LocalServer(ctx)
        start = time.perf_counter()
        async def timer():
            await asyncio.sleep(.01)
            return (time.perf_counter() - start) * 1000
        tick = asyncio.create_task(timer())
        await server._api_egg_box(None)
        emit("slow_db_loop_timer", injected_db_delay_ms=200, timer_due_ms=10,
             timer_actual_ms=round(await tick, 2))
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            assert release.wait(3)
        handler = asyncio.create_task(server._run_blocking(blocked))
        while not entered.is_set():
            await asyncio.sleep(.001)
        handler.cancel()
        try:
            await handler
        except asyncio.CancelledError:
            pass
        shutdown = asyncio.create_task(server._shutdown())
        await asyncio.sleep(.02)
        waiting = not shutdown.done()
        release.set()
        await shutdown
        emit("shutdown_waits_cancelled_http_thread", shutdown_waited_for_thread=waiting,
             remaining_tracked_tasks=len(server._blocking_tasks))
        seen = []
        class Socket:
            closed = False
            def __init__(self, slow): self.slow = slow
            async def send_str(self, text):
                if self.slow: await asyncio.Event().wait()
                else: seen.append(text)
            async def close(self, **kwargs): self.closed = True
        slow, healthy = Socket(True), Socket(False)
        server._sockets = {slow, healthy}
        send = asyncio.create_task(server._broadcast("synthetic-state"))
        await asyncio.sleep(.03)
        healthy_seen = bool(seen)
        await send
        emit("slow_ws", healthy_received_at_30ms=healthy_seen,
             slow_removed=slow not in server._sockets, slow_closed=slow.closed)
        cache = PetMediaCache(Path(tmp) / "packaged", Path(tmp) / "cache")
        attempts = []
        def miss(*args):
            attempts.append(args)
            time.sleep(.02)
            return None, 21600
        cache._download = miss
        await asyncio.gather(*(cache.resolve("123-normal-artwork.webp") for _ in range(9)))
        emit("missing_media", requests=9, download_attempts=len(attempts), inflight=len(cache._inflight))
        ctx.close()

def recorder_and_checkpoint():
    class SlowFile:
        def writelines(self, lines): pass
        def flush(self): time.sleep(.02)
        def close(self): pass
    with tempfile.TemporaryDirectory() as tmp:
        recorder = StreamRecorder()
        with patch.object(Path, "open", return_value=SlowFile()):
            recorder.start(Path(tmp) / "recording.jsonl")
        chunk = StreamChunk("synthetic", "s2c", b"x" * 100, 0)
        start = time.perf_counter()
        for _ in range(20): recorder.append(chunk)
        elapsed = (time.perf_counter() - start) * 1000
        recorder.stop()
        emit("recorder_slow_disk", append_total_ms=round(elapsed, 2),
             chunks=recorder.chunk_count, dropped=recorder.dropped_count)
        store = KeyStore(Path(tmp) / "keys")
        entered, release = threading.Event(), threading.Event()
        writes = []
        def blocked_write(revision, checkpoint):
            if not writes:
                entered.set()
                assert release.wait(3)
            writes.append(checkpoint.server_sequence)
        store._write_session = blocked_write
        store.save_session(SessionCheckpoint("synthetic", b"x" * 16, (1, "A", 1), 10))
        assert entered.wait(3)
        store.save_session(SessionCheckpoint("synthetic", b"x" * 16, None, 11))
        store.save_session(SessionCheckpoint("synthetic", b"x" * 16, (2, "B", 1), 12))
        release.set()
        store.close()
        emit("checkpoint_coalesces_versions", written_sequences=writes, writer_alive=store._writer.is_alive())

def replay_writer_lifecycle():
    from spritelens.recording.replay import run_replay
    from tests._synth import SYNTH_KEY, make_ack_frame
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        store = KeyStore(directory / "keys")
        entered, release = threading.Event(), threading.Event()
        def delayed(revision, checkpoint):
            entered.set()
            assert release.wait(3)
        store._write_session = delayed
        recording = directory / "recording.jsonl"
        recording.write_text(json.dumps({"session": "synthetic", "direction": "s2c", "seq": 0,
                                        "data": make_ack_frame(SYNTH_KEY).hex()}) + "\n", encoding="utf-8")
        try:
            with patch("spritelens.recording.replay.KeyStore", return_value=store), \
                    patch("spritelens.recording.replay.keys_dir", return_value=directory / "keys"), \
                    redirect_stdout(io.StringIO()):
                result = run_replay(str(recording), logger=logging.getLogger("acceptance"))
            assert entered.wait(3)
            emit("replay_writer_lifecycle", exit_code=result, writer_alive_at_return=store._writer.is_alive(),
                 close_requested=store._closing)
        finally:
            release.set()
            store.close()

def export_contract():
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _make_context(Path(tmp), tuple(_pet(i, name="Synthetic", level=10) for i in (1, 2)))
        ctx.pet_repository._account.observe(PlayerIdentity(101, "Synthetic", 10))
        ctx.pet_repository._version = 10
        server = LocalServer(ctx)
        try:
            for filename, backpack in (
                ("backend-contract.json", Backpack()),
                ("backend-contract-known.json", Backpack({}, (PetBox(1, (1, 2, 0, 0, 0, 0)),), 1)),
            ):
                ctx.pet_repository._backpack = backpack
                payload = {
                    "summary": server._pets_payload_for_query({}),
                    "details": [server._pet_detail_payload(101, 10, gid)[1] for gid in (1, 2)],
                    "wrong_uid_status": server._pet_detail_payload(202, 10, 1)[0],
                }
                Path(__file__).with_name(filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        finally:
            ctx.close()
    emit("export_source_contract", synthetic_pets=2, unknown_and_known_backpack=True)

if __name__ == "__main__":
    benchmark = runpy.run_path(str(ROOT / "output/review-20261015-performance/probe_backend.py"))
    benchmark["benchmark"]()
    for kind in ("pet", "egg"):
        batch_order(kind)
        read_barrier(kind)
        concurrent_close(kind)
        close_retry(kind)
    asyncio.run(asynchronous_paths())
    lazy_event_detail()
    recorder_and_checkpoint()
    replay_writer_lifecycle()
    export_contract()
