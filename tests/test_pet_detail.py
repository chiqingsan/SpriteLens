"""详情数据、真实奖牌归属及其未知/空集合持久化契约。"""
from __future__ import annotations
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from spritelens.events import PacketEvent
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pet_medals import extract_medals
from spritelens.domain.pets import Pet, PetAttribute
from spritelens.domain.static_data import load_static_data
from spritelens.repositories.database import Database
from spritelens.repositories.pet_store import PetStore
from spritelens.services.pet_repository import PetRepository
from spritelens.web.payloads import pet_row
from tests.test_pets import _named_pet_node


def field(no, raw=None, children=None, kind=''):
    value = {'no': no, 'raw': raw, 'type': kind}
    if children is not None:
        value['children'] = children
    return value


def event(nodes, name='ZoneLoginRsp'):
    return PacketEvent(1, 'synthetic', 's2c', 1, name, 0, nodes)


def collection(records):
    return field(1, children=[field(1, children=[field(1, medal), field(3, children=[field(2, children=[field(6, gid), field(8, wearer)])])])
                              for medal, gid, wearer in records], kind='CliPetMedalInfo')


class PetDetailTest(unittest.TestCase):
    def setUp(self):
        self.pet = Pet(1, 2000001, '合成护主犬', 1, 0, 1, 1, 0, 2, False, base_conf_id=3070)

    def test_collection_uses_obtainer_not_wearer_and_empty_is_known(self):
        update = extract_medals(event([collection([(1010, 1, 2), (1001, 1, 1), (1010, 1, 2)])]))
        self.assertEqual(update.collection, {1: (1001, 1010)})
        self.assertEqual(extract_medals(event([collection([])])).collection, {})
        self.assertIsNone(extract_medals(event([])))
        self.assertIsNone(extract_medals(replace(event([collection([])]), direction='c2s')))

    def test_snapshot_merge_replacement_account_isolation_and_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'data.sqlite')
            store = PetStore(db, flush_interval=100)
            repo = PetRepository(store)
            try:
                repo._account.observe(PlayerIdentity(101, '合成账号', 1))
                repo.handle_packet(event([collection([(1010, 1, 1), (1001, 1, 1)])]))
                repo.handle_packet(event([_named_pet_node(1, 2000001, b'pet', 1)], 'PetBriefUpdate'))
                self.assertEqual(repo.snapshot()[0].awarded_medal_ids, (1001, 1010))
                store.flush()
                self.assertEqual(store.load(101)[0].awarded_medal_ids, (1001, 1010))
                repo.handle_packet(event([collection([])]))
                store.flush()
                self.assertEqual(store.load(101)[0].awarded_medal_ids, ())
                change = field(16, children=[field(1, 1001), field(3, children=[field(6, 1)])], kind='PetMedal')
                repo.handle_packet(event([change], 'MedalChange'))
                store.flush()
                self.assertIsNone(store.load(101)[0].awarded_medal_ids)
                repo.handle_packet(replace(event([_named_pet_node(1, 2000001, b'other', 1)], 'PetBriefUpdate'), resumed_identity=(202, '合成B', 1)))
                self.assertIsNone(repo.snapshot()[0].awarded_medal_ids)
                store.flush()
                self.assertIsNone(store.load(202)[0].awarded_medal_ids)
                db.execute("UPDATE pets SET awarded_medals_json = '{}' WHERE uid=202")
                with self.assertLogs('spritelens.pet_store', level='ERROR'):
                    self.assertEqual(store.load(202), ())
                store.put(202, [replace(self.pet, awarded_medal_ids=(1030,))]); store.flush()
                self.assertEqual(store.load(202)[0].awarded_medal_ids, (1030,))
                self.assertIsNone(store.load(101)[0].awarded_medal_ids)
            finally:
                store.close(); db.close()

    def test_v9_migration_preserves_unknown_and_round_trip(self):
        from spritelens.repositories.database import _MIGRATIONS
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite'
            conn = sqlite3.connect(path)
            for version, statements in _MIGRATIONS:
                if version > 9: break
                for statement in statements: conn.execute(statement)
                conn.execute('PRAGMA user_version=' + str(version))
            conn.execute("INSERT INTO pets (uid, gid, name, first_seen, updated_at) VALUES (101, 3, '旧记录', 0, 0)")
            conn.commit(); conn.close()
            db = Database(path); store = PetStore(db, flush_interval=100)
            try:
                store.put(101, [self.pet, replace(self.pet, gid=2, awarded_medal_ids=())]); store.flush()
                self.assertEqual([pet.awarded_medal_ids for pet in store.load(101)], [None, (), None])
            finally:
                store.close(); db.close()
            db = Database(path); store = PetStore(db, flush_interval=100)
            try:
                self.assertEqual([pet.awarded_medal_ids for pet in store.load(101)], [None, (), None])
            finally:
                store.close(); db.close()

    def test_payload_bonus_measurements_and_branch_edges(self):
        static = load_static_data(Path('data/static'))
        pet = replace(self.pet, attributes=(PetAttribute(base_value=40, talent_add=9, effort_add=3),),
                      height=88, weight=16931, voice=-96, awarded_medal_ids=(1010, 1001, 1010))
        row = pet_row(pet, static, 1, 1)
        self.assertEqual(row['stats'][0]['value'], 52)
        self.assertEqual(row['stats'][0]['talent_add'], 9)
        self.assertEqual(row['detail']['measurements']['voice']['ratio'], .02)
        self.assertEqual([medal['id'] for medal in row['detail']['awarded_medals']], [1001, 1010])
        self.assertIsNone(pet_row(self.pet, static, 1, 1)['detail']['measurements']['voice']['value'])
        branch = pet_row(replace(self.pet, base_conf_id=3060), static, 1, 1)['detail']['evolution']['edges']
        self.assertIn([3060, 3061], branch)
        self.assertIn([3060, 3481], branch)
