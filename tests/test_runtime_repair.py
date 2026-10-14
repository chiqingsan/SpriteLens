"""E01–E06 回归：慢操作隔离、退出确认、超时所有权及错误事实。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from spritelens.capture.base import SourceError
from spritelens.capture.npcap_source import NpcapCaptureSource
from spritelens.recording.recorder import StreamRecorder
from spritelens.web.server import LocalServer
from tests.test_server_lifecycle import _port_serving
from tests.test_web_server import _http_post, _make_context


class RuntimeRepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.context = _make_context(Path(self.tmp.name))
        self.addCleanup(self.context.close)

    def server(self):
        server = LocalServer(self.context)
        server.start()
        self.addCleanup(server.stop)
        return server

    def test_slow_recording_save_does_not_block_http_or_ws(self):
        server = self.server()
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def persist(enabled):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("测试未释放保存")

        def command():
            try:
                self.context.capture_vm.set_recording_requested(True)
            except Exception as exc:
                errors.append(exc)

        self.context.capture_vm._service.set_recording_persist(persist)
        thread = threading.Thread(target=command)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            request = urllib.request.Request(
                f"http://{server.host}:{server.port}/api/capture",
                headers={"X-Local-Token": server.token},
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                self.assertTrue(json.loads(response.read())["recording_requested"])
            with urllib.request.urlopen(f"http://{server.host}:{server.port}/", timeout=1) as response:
                self.assertEqual(response.status, 200)
                response.read()

            async def receive():
                from aiohttp import ClientSession

                async with ClientSession() as session:
                    async with session.ws_connect(
                        f"http://{server.host}:{server.port}/ws",
                        headers={"X-Local-Token": server.token},
                    ) as ws:
                        message = await asyncio.wait_for(ws.receive_json(), 1)
                        self.assertIn("capture", message)
                await asyncio.sleep(0)  # ClientSession 的非 SSL transport 关闭回调

            asyncio.run(receive())
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_recorder_count_read_does_not_wait_for_file_io_lock(self):
        recorder = StreamRecorder()
        acquired = threading.Event()
        release = threading.Event()

        def slow_io():
            with recorder._lock:
                acquired.set()
                release.wait(5)

        thread = threading.Thread(target=slow_io)
        thread.start()
        try:
            self.assertTrue(acquired.wait(2))
            read = threading.Event()
            reader = threading.Thread(target=lambda: (recorder.chunk_count, read.set()))
            reader.start()
            self.assertTrue(read.wait(1))
        finally:
            release.set()
            thread.join(2)
            reader.join(2)

    def test_sniffer_false_running_before_thread_exit_blocks_restart(self):
        closing = threading.Event()
        release = threading.Event()

        class Sniffer:
            running = True

            def __init__(self):
                self.thread = threading.Thread(target=self.work)
                self.thread.start()

            def work(self):
                closing.wait(5)
                self.running = False  # scapy 在 socket close 之前更新该字段
                release.wait(5)

            def stop(self):
                closing.set()
                self.thread.join()

        sniffer = Sniffer()
        source = NpcapCaptureSource(8195, on_chunk=lambda chunk: None)
        source._sniffer = sniffer
        source._sniffer_stop_budget = 0.02
        try:
            source.stop()
            self.assertTrue(source.has_unfinished_sniffer())
            with self.assertRaises(SourceError):
                source.start()
            self.assertIsNone(source._worker)
        finally:
            release.set()
            closing.set()
            sniffer.thread.join(2)
            for helper in source._sniffer_stop_threads.values():
                helper.join(2)
        self.assertFalse(source.has_unfinished_sniffer())

    def test_sniffer_stop_error_keeps_handle_and_retry_stops_it(self):
        class Sniffer:
            running = True
            fail = True

            def stop(self):
                if self.fail:
                    raise OSError("control socket send failed")
                self.running = False

        source = NpcapCaptureSource(8195, on_chunk=lambda chunk: None)
        sniffer = Sniffer()
        source._sniffer = sniffer
        source.stop()
        self.assertTrue(source.has_unfinished_sniffer())
        self.assertIn(sniffer, source._stale_sniffers)
        with self.assertRaises(SourceError):
            source.start()
        sniffer.fail = False
        source.stop()
        self.assertFalse(source.has_unfinished_sniffer())

    def test_capture_stop_budget_retains_monitor_and_storage_until_retry(self):
        service = self.context.capture_vm._service
        monitor = self.context.monitor
        entered = threading.Event()
        release = threading.Event()
        source = NpcapCaptureSource(8195, on_chunk=service._tee_chunk)
        source._worker_join_timeout = 0.02
        source._running = True
        monitor.bind(source)
        service._source = source

        def callback():
            with monitor._lock:
                entered.set()
                release.wait(5)

        worker = threading.Thread(target=callback)
        source._worker = worker
        worker.start()
        store = mock.Mock()
        self.context.pet_store = store
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(TimeoutError):
                service.stop(timeout=0.08)
            stopping = service._stop_thread
            self.assertTrue(stopping.is_alive())
            with mock.patch.object(service, "stop", side_effect=TimeoutError("仍未退")):
                with self.assertRaises(TimeoutError):
                    self.context.close()
            store.close.assert_not_called()
            self.assertFalse(self.context._closed)
            service.start()  # 不等待旧停止命令锁，不建立新的 source
            self.assertIs(service._source, source)
            with self.assertRaises(TimeoutError):
                service.stop(timeout=0.02)
            self.assertIs(service._stop_thread, stopping)
        finally:
            release.set()
            worker.join(2)
            service.stop(timeout=2)
        self.context.close()
        store.close.assert_called_once()
        self.assertEqual(service.status().last_error, "")

    def test_server_stop_timeout_retains_owner_and_drains_tasks_on_release(self):
        server = self.server()
        entered = threading.Event()
        release = threading.Event()
        loop = server._loop
        thread = server._thread
        runner = server._runner
        port = server.port
        loop_errors = []
        loop.set_exception_handler(lambda loop, context: loop_errors.append(context))

        def blocked():
            entered.set()
            release.wait(5)

        loop.call_soon_threadsafe(blocked)
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(TimeoutError):
                server.stop(timeout=0.02)
            self.assertIs(server._thread, thread)
            self.assertIs(server._loop, loop)
            self.assertIs(server._runner, runner)
            future = server._stop_future
            with self.assertRaises(TimeoutError):
                server.stop(timeout=0.02)
            self.assertIs(server._stop_future, future)
        finally:
            release.set()
            server.stop(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(loop.is_closed())
        self.assertFalse(_port_serving(port))
        self.assertEqual(loop_errors, [])
        server.stop()

    def test_recording_http_distinguishes_start_stop_and_save_failure(self):
        server = self.server()
        service = self.context.capture_vm._service
        url = f"http://{server.host}:{server.port}/api/capture/recording"
        source = mock.Mock(is_running=True)
        self.context.monitor.bind(source)
        with mock.patch.object(service._recorder, "start", side_effect=OSError("open failed")):
            status, data = _http_post(url, server.token, {"enabled": True})
        self.assertEqual(status, 500)
        self.assertEqual(data["error_kind"], "start")
        self.assertFalse(data["recording"])
        self.assertFalse(data["saved"])
        service.set_recording(True)
        with mock.patch.object(service._recorder, "stop", side_effect=OSError("close failed")):
            status, data = _http_post(url, server.token, {"enabled": False})
        self.assertEqual(status, 500)
        self.assertEqual(data["error_kind"], "stop")
        self.assertTrue(data["recording"])
        self.assertFalse(data["requested"])
        with mock.patch.object(self.context.settings, "set_checked", side_effect=OSError("disk full")):
            status, data = _http_post(url, server.token, {"enabled": False})
        self.assertEqual(status, 500)
        self.assertEqual(data["error_kind"], "save")
        self.assertFalse(data["recording"])
        self.assertIn("保存失败", data["error"])
