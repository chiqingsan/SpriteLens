"""重启接续须由同一连接、密钥与连续服务端帧确认，缓存不能冒充登录。"""
import tempfile
import unittest
from pathlib import Path

from spritelens.capture.base import StreamChunk
from spritelens.capture.key_store import KeyStore
from spritelens.domain.identity import PlayerIdentity
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from tests._synth import SYNTH_KEY, encode_frame, make_ack_frame, make_data_frame, make_protobuf_payload
from tests.test_pet_locations import integer, message

SESSION = "10.0.0.5:51000"
ROOT = Path(__file__).resolve().parent.parent


class SessionResumeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = KeyStore(self.directory)
        self.addCleanup(self.store.close)
        load_library(ROOT / "data/schemas")

    def checkpoint(self):
        self.store.flush()
        return self.store.load_session()

    def monitor(self):
        monitor = MonitorService(
            catalog=OpcodeCatalog.load(ROOT / "data/schemas/opcodes.json"),
            key_store=self.store,
            # 用例通过 drain_events() 校验事件历史，需显式开启。
            keep_event_history=True,
        )
        repo = PetRepository()
        monitor.add_packet_listener(repo.handle_packet)
        return monitor, repo

    def feed(self, monitor, data, *, flow=SESSION, direction="s2c"):
        monitor.on_chunk(StreamChunk(flow, direction, data, 1))

    def login(self, monitor, *, uid=123, name="测试角色", key=SYNTH_KEY, sequence=10):
        brief = integer(1, uid) + message(3, name.encode()) + integer(5, 55)
        payload = message(2, message(1, brief))
        self.feed(monitor, make_data_frame(key, 0x0102, payload, sequence=sequence))

    def seed(self):
        monitor, repo = self.monitor()
        self.feed(monitor, make_ack_frame(SYNTH_KEY))
        self.assertIsNone(self.checkpoint().identity)
        self.login(monitor)
        self.assertEqual(repo.identity, PlayerIdentity(123, "测试角色", 55))
        monitor.stop()
        self.store.flush()

    def test_restart_resumes_from_server_data_without_relogin(self):
        self.seed()
        monitor, repo = self.monitor()
        self.assertIsNone(repo.identity)
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x013D, b"", sequence=11, direction="c2s"), direction="c2s")
        self.assertIsNone(repo.identity)
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x013D, b"", sequence=11))
        self.assertEqual(repo.identity, PlayerIdentity(123, "测试角色", 55))
        self.assertEqual(monitor.drain_events()[-1].resumed_identity, (123, "测试角色", 55))
        self.assertEqual(self.checkpoint().server_sequence, 11)

    def test_other_flow_wrong_key_and_sequence_reset_do_not_restore_old_role(self):
        self.seed()
        monitor, repo = self.monitor()
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=11), flow="10.0.0.5:52000")
        self.assertIsNone(repo.identity)
        self.feed(monitor, make_data_frame(b"fedcba9876543210", 0x1AA, make_protobuf_payload(), sequence=11))
        self.assertIsNone(repo.identity)
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=2))
        self.assertIsNone(repo.identity)
        self.assertIsNone(self.checkpoint().identity)
        again, repo = self.monitor()
        self.feed(again, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=100))
        self.assertIsNone(repo.identity)

    def test_new_handshake_and_connection_close_invalidate_cached_role(self):
        for key in (SYNTH_KEY, b"fedcba9876543210"):
            self.seed()
            monitor, repo = self.monitor()
            self.feed(monitor, make_ack_frame(key))
            self.feed(monitor, make_data_frame(key, 0x1AA, make_protobuf_payload(), sequence=11))
            self.assertIsNone(repo.identity)
            self.assertIsNone(self.checkpoint().identity)
            self.login(monitor, uid=456, name="新角色", key=key, sequence=12)
            self.assertEqual(repo.identity.uid, 456)
            self.assertEqual(self.checkpoint().identity[0], 456)
            monitor.close_session(SESSION)
            self.assertIsNone(self.checkpoint().identity)

    def test_new_syn_invalidates_cache_even_before_key_arrives(self):
        self.seed()
        monitor, repo = self.monitor()
        self.feed(monitor, encode_frame(0x1001, 0, 1, b"", b""), direction="c2s")
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=11))
        self.assertIsNone(repo.identity)
        self.assertIsNone(self.checkpoint().identity)

    def test_new_identity_overrides_cache_and_stop_saves_latest_sequence(self):
        self.seed()
        monitor, repo = self.monitor()
        self.login(monitor, uid=456, name="另一角色", sequence=11)
        self.assertEqual(repo.identity.uid, 456)
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=12))
        monitor.stop()
        checkpoint = self.checkpoint()
        self.assertEqual(checkpoint.identity, (456, "另一角色", 55))
        self.assertEqual(checkpoint.server_sequence, 12)

    def test_corrupt_cache_and_old_key_only_are_not_role_evidence(self):
        self.store.save_latest(SYNTH_KEY, SESSION)
        self.assertIsNone(self.checkpoint())
        monitor, repo = self.monitor()
        monitor.set_preset_key(self.store.load_latest())
        self.feed(monitor, make_data_frame(SYNTH_KEY, 0x1AA, make_protobuf_payload(), sequence=11))
        self.assertIsNone(repo.identity)
        for text in ('{', '[]', '{"version":1,"key_hex":"00","flow_id":"s","server_sequence":2}',
                     '{"version":1,"key_hex":"0123456789abcdef0123456789abcdef","flow_id":"s","server_sequence":2,"identity":[0,"x",2]}'):
            (self.directory / "session.json").write_text(text, encoding="utf-8")
            self.assertIsNone(self.checkpoint())
