"""受控慢 IO 验收：仅使用内存 SQLite、临时目录与合成 ACK。"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from spritelens.capture.key_store import KeyStore, SessionCheckpoint
from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.pets import Pet
from spritelens.repositories.database import Database
from spritelens.repositories.egg_store import EggStore
from spritelens.repositories.pet_store import PetStore
from spritelens.recording.replay import run_replay
from tests._synth import make_ack_frame, SYNTH_KEY

logging.disable(logging.CRITICAL)

def emit(probe, **values):
    print(json.dumps(dict(probe=probe, **values)), flush=True)

def external_flush_close(kind):
    db = Database(":memory:")
    store = (PetStore if kind == "pet" else EggStore)(db, flush_interval=60)
    value = (Pet(gid=1, conf_id=1, name="synthetic", level=1, exp=0, nature=0,
                 gender=0, blood_id=0, talent_rank=0, is_first_catch=False)
             if kind == "pet" else EggBoxEntry(1, 1, 1, 1, *([0] * 12)))
    entered, release = threading.Event(), threading.Event()
    original = db.execute_many
    errors = []
    def blocked(sql, rows):
        entered.set()
        if not release.wait(15):
            raise TimeoutError("probe gate not released")
        return original(sql, rows)
    def flush():
        try:
            store.flush()
        except Exception as exc:
            errors.append(type(exc).__name__)
    db.execute_many = blocked
    store.put(1, [value])
    caller = threading.Thread(target=flush)
    caller.start()
    assert entered.wait(3)
    started = time.perf_counter()
    cause = None
    try:
        store.close()
    except Exception as exc:
        cause = type(exc).__name__
    elapsed = time.perf_counter() - started
    db_open = bool(db.query("SELECT 1"))
    release.set()
    caller.join(3)
    db.execute_many = original
    store.close()
    count = db.query("SELECT COUNT(*) AS n FROM " + ("pets" if kind == "pet" else "eggs"))[0]["n"]
    emit("external_flush_close_timeout_retry", store=kind, close_error=cause,
         elapsed_seconds=round(elapsed, 2), database_retained=db_open,
         flush_errors=errors, rows_after_retry=count, worker_alive=store._worker.is_alive())
    db.close()

def checkpoint_barriers():
    with tempfile.TemporaryDirectory() as tmp:
        store = KeyStore(Path(tmp))
        entered, release = threading.Event(), threading.Event()
        original = store._write_session
        def blocked(revision, checkpoint):
            entered.set()
            assert release.wait(3)
            original(revision, checkpoint)
        store._write_session = blocked
        store.save_session(SessionCheckpoint("synthetic", SYNTH_KEY, (42, "synthetic", 1), 10))
        assert entered.wait(3)
        errors = []
        for action in (lambda: store.flush(timeout=.05), lambda: store.close(timeout=.05)):
            try:
                action()
            except Exception as exc:
                errors.append(type(exc).__name__)
        retained_writer = store._writer
        release.set()
        store.close()
        emit("checkpoint_flush_close_barriers", timeout_errors=errors,
             same_writer=retained_writer is store._writer, writer_alive=store._writer.is_alive(),
             persisted_sequence=store.load_session().server_sequence)

def replay_waits_writer():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        store = KeyStore(directory / "keys")
        original = store._write_session
        entered, release = threading.Event(), threading.Event()
        def blocked(revision, checkpoint):
            entered.set()
            assert release.wait(3)
            original(revision, checkpoint)
        store._write_session = blocked
        recording = directory / "ack.jsonl"
        recording.write_text(json.dumps(dict(session="synthetic", direction="s2c", seq=0,
                                             data=make_ack_frame(SYNTH_KEY).hex())) + "\n", encoding="utf-8")
        results = []
        def replay():
            with patch("spritelens.recording.replay.KeyStore", return_value=store), \
                    patch("spritelens.recording.replay.keys_dir", return_value=directory / "keys"), \
                    contextlib.redirect_stdout(io.StringIO()):
                results.append(run_replay(str(recording), logger=logging.getLogger("probe")))
        caller = threading.Thread(target=replay)
        caller.start()
        assert entered.wait(3)
        caller.join(.05)
        waited = caller.is_alive()
        release.set()
        caller.join(3)
        emit("replay_waits_writer", blocked_until_write_finished=waited, results=results,
             writer_alive=store._writer.is_alive(), closed=store._closed)

if __name__ == "__main__":
    for kind in ("pet", "egg"):
        external_flush_close(kind)
    checkpoint_barriers()
    replay_waits_writer()
